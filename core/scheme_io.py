# -*- coding: utf-8 -*-
"""Сохранение и загрузка схемы, вставка из файла.

Методы этого миксина подключаются к ``main.CircuitEditor`` и отвечают за
сериализацию чертежа: запись элементов, связей и служебных списков в JSON
(``_write_scheme``), чтение схемы обратно (``load_json``, ``_build_*``),
вставку фрагмента из другого файла с перенумерацией обозначений
(``insert_from_json``) и отметку изменений в заголовке окна
(``_mark_modified``, ``_mark_saved``, ``_confirm_unsaved``).

Формат файла описан в STRUCTURE.md; логика перенесена из ``main.py``
без изменений.
"""

from __future__ import annotations

import copy
import json
import os
import uuid

import cabs
import komplekts
import library
import logic_library
from element_info import APP_TITLE, PREFIX_BY_TYPE

try:
    from tkinter import filedialog, messagebox
except ImportError:                                # pragma: no cover
    filedialog = messagebox = None


class SchemeIOMixin:
    # ================= СОХРАНЕНИЕ / ЗАГРУЗКА =================
    # Заголовок окна показывает имя чертежа; звёздочка — есть несохранённые
    # изменения. При закрытии программы и при загрузке другой схемы
    # программа спрашивает, сохранить ли изменения.

    def _drawing_name(self):
        """Имя чертежа для заголовка окна и сообщений."""
        if self.current_path:
            return os.path.basename(self.current_path)
        return "Без имени"

    def _update_title(self):
        """Заголовок окна: имя чертежа, звёздочка изменений, имя программы."""
        mark = "*" if self.is_modified else ""
        self.root.title("{}{} — {}".format(self._drawing_name(), mark,
                                           APP_TITLE))

    def _mark_modified(self):
        """Помечает схему как изменённую (ставит «*» в заголовке)."""
        if self.is_modified:
            return
        self.is_modified = True
        self._update_title()

    def _mark_saved(self, path=None):
        """Снимает отметку изменений после сохранения или загрузки."""
        if path:
            self.current_path = path
        self.is_modified = False
        self._update_title()

    def _confirm_unsaved(self, question):
        """Спрашивает о несохранённых изменениях.

        True — можно продолжать: изменений нет, пользователь отказался
        сохранять или сохранение прошло успешно.
        """
        if not self.is_modified:
            return True
        answer = messagebox.askyesnocancel(
            "Несохранённые изменения",
            "Схема «{}» изменена.\nСохранить изменения {}?".format(
                self._drawing_name(), question))
        if answer is None:      # «Отмена»
            return False
        if not answer:          # «Нет» — продолжить без сохранения
            return True
        return bool(self.save_json())   # «Да» — сохранить

    def on_close(self):
        """Закрытие окна: при несохранённых изменениях спросить о сохранении."""
        if not self._confirm_unsaved("перед закрытием"):
            return
        self.root.destroy()

    def save_json(self, event=None):
        """Сохранить: в текущий файл, а если его нет — спросить путь."""
        return self._write_scheme(save_as=False)

    def save_json_as(self, event=None):
        """Сохранить как: всегда спрашивать новый путь к файлу."""
        return self._write_scheme(save_as=True)

    def _write_scheme(self, save_as=False):
        data = {"elements": [], "connections": []}

        for el in self.elements.values():
            item = {
                "id": el.id,
                "type": el.type,
                "name": el.name,
                "x": el.x,
                "y": el.y
            }
            if el.type == "bus":
                item["length"] = el.length
            if hasattr(el, "rotation"):
                item["rotation"] = el.rotation
            if el.type == "corner":
                item["orientation"] = el.orientation
            offset = getattr(el, "label_offset", (0.0, 0.0))
            if offset and (offset[0] or offset[1]):
                item["label"] = [round(offset[0], 2), round(offset[1], 2)]
            if el.type == "cabinet":
                item["cabinet"] = {
                    "key": getattr(el, "cabinet_key", ""),
                    "title": getattr(el, "title", "Шкаф РЗА"),
                    "info": dict(getattr(el, "info", {})),
                    "komplets": copy.deepcopy(
                        getattr(el, "komplets", [])),
                }
            if el.type == "container":
                item["container"] = {
                    "key": getattr(el, "container_key", ""),
                    "code": getattr(el, "code", "КЭТ"),
                    "title": getattr(el, "title", "КЭТ"),
                    "size": getattr(el, "size", "20dc"),
                    "slots": el.slot_count(),
                    "info": dict(getattr(el, "info", {})),
                    "cabinets": list(getattr(el, "cabinets", [])),
                    "slot_labels": list(getattr(el, "slot_labels", [])),
                    "link_points": [
                        self._clean_points(points)
                        for points in getattr(el, "link_points",
                                             [[] for _ in range(el.slot_count())])
                    ],
                }
            if logic_library.is_logic_type(el.type):
                item["logic"] = logic_library.element_payload(el)
            data["elements"].append(item)

        for c in self.connections:
            el1 = self.elements.get(c.get("from"))
            el2 = self.elements.get(c.get("to"))
            if not el1 or not el2:
                continue
            p1 = el1.ports.get(c.get("port_from"))
            p2 = el2.ports.get(c.get("port_to"))
            if not p1 or not p2:
                continue
            record = {
                "node_from": p1["node_id"],
                "node_to": p2["node_id"],
                "port_from": c["port_from"],
                "port_to": c["port_to"],
                "element_from": el1.id,
                "element_to": el2.id
            }
            points = self._clean_points(c.get("points"))
            if points:
                record["points"] = points
            data["connections"].append(record)

        # Ссылка на подложку: по ней схема открывается вместе с чертежом
        if self.underlay:
            data["underlay"] = {
                "path": os.path.abspath(self.underlay["path"]),
                "scale": self.underlay_scale,
                "visible": bool(self.show_underlay),
            }
        if self.protection_links:
            data["protection_links"] = [self._protection_record(link)
                                       for link in self.protection_links]
        if self.analog_links:
            data["analog_links"] = [self._analog_record(link)
                                    for link in self.analog_links]
        if self.logic_links:
            data["logic_links"] = [self._logic_link_record(link)
                                   for link in self.logic_links]
        # Комментарии к чертежу: точка привязки, вид и текст
        if self.comments:
            data["comments"] = [
                {"id": comment.get("id", ""),
                 "x": round(float(comment.get("x", 0.0)), 1),
                 "y": round(float(comment.get("y", 0.0)), 1),
                 "text": comment.get("text", ""),
                 "style": comment.get("style", "note")}
                for comment in self.comments
            ]
        data["view"] = {
            "zoom": round(self.zoom, 4),
            "offset_x": round(self.offset_x, 2),
            "offset_y": round(self.offset_y, 2),
        }

        filepath = None if save_as else self.current_path
        if not filepath:
            filepath = filedialog.asksaveasfilename(
                title="Сохранить как" if save_as else "Сохранить схему",
                defaultextension=".json",
                initialfile=os.path.basename(self.current_path or "схема.json"),
                filetypes=[("JSON files", "*.json")])
            if not filepath:
                return False

        # путь к подложке храним относительно файла схемы, чтобы папку можно было переносить
        if "underlay" in data:
            try:
                base = os.path.dirname(os.path.abspath(filepath))
                data["underlay"]["path"] = os.path.relpath(
                    data["underlay"]["path"], base)
            except ValueError:
                pass
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except OSError as e:
            messagebox.showerror("Ошибка",
                                 f"Не удалось сохранить файл:\n{e}")
            return False

        self._mark_saved(filepath)
        messagebox.showinfo("Сохранение",
                            "Схема сохранена:\n{}".format(filepath))
        return True

    def load_json(self):
        if not self._confirm_unsaved("перед загрузкой другой схемы"):
            return
        filepath = filedialog.askopenfilename(
            title="Открыть схему", filetypes=[("JSON files", "*.json")])
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")
            return

        # Схема собирается отдельно: при ошибке текущая схема остаётся нетронутой
        # (раньше файл сначала стирал полотно диалогом clear_all).
        try:
            elements = self._build_elements(data)
            connections = self._build_connections(data, elements)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить схему:\n{e}")
            return

        self._push_undo()
        self.elements = elements
        self.connections = connections
        self.protection_links = self._build_protection_links(
            data.get("protection_links", []))
        self.analog_links = self._build_analog_links(
            data.get("analog_links", []))
        self.logic_links = self._build_logic_links(
            data.get("logic_links", []))
        self.comments = self._build_comments(data.get("comments", []))
        self.selected_comment = None
        self._reset_transient()

        underlay_info = data.get("underlay")
        if isinstance(underlay_info, dict):
            self._restore_underlay(
                underlay_info, os.path.dirname(os.path.abspath(filepath)))

        view_info = data.get("view")
        if isinstance(view_info, dict):
            try:
                self.zoom = float(view_info.get("zoom", self.zoom))
                self.offset_x = float(view_info.get("offset_x", self.offset_x))
                self.offset_y = float(view_info.get("offset_y", self.offset_y))
            except (TypeError, ValueError):
                pass

        self.redraw_all()
        if hasattr(self, "zoom_label"):
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")
        self._refresh_search()
        self._mark_saved(filepath)
        messagebox.showinfo("Загрузка", "Схема загружена:\n{}".format(
            filepath))

    @staticmethod
    def _cabinet_payload_meta(payload):
        """Данные шкафа из JSON схемы — для вида комплектов и ссылки на шкаф."""
        info = payload.get("info") or {}
        key = payload.get("key") or ""
        standard_key = "1" if (info.get("standard") or
                               info.get("standard_title")) else ""
        source = {}
        if not standard_key and key:
            source = cabs.find_cabinet(key) or {}
            standard_key = source.get("standard_key") or ""
        return {
            "key": key,
            "code": info.get("code") or source.get("code") or "",
            "name": info.get("name") or source.get("name") or "",
            "group": info.get("group") or source.get("group") or "",
            "standard_key": standard_key,
        }

    def _restore_cabinet(self, el, payload):
        """Восстанавливает шкаф из JSON схемы (поля каталога и комплекты)."""
        el.cabinet_key = payload.get("key", "")
        el.title = payload.get("title", el.title)
        el.info = dict(payload.get("info") or {})
        komplets = payload.get("komplets")
        if not isinstance(komplets, list):
            komplets = library.komplets_from_ieds(payload.get("ieds", []))
        meta = self._cabinet_payload_meta(payload)
        el.komplets = library.normalize_komplets(
            komplets, komplekts.cabinet_kit_kind(meta), meta)

    def _build_elements(self, data):
        """Создаёт элементы схемы из разобранного JSON, не трогая текущее полотно."""
        elements = {}
        for item in data.get("elements", []):
            el = library.create_component(item["type"], item["id"],
                                          item.get("x", 0), item.get("y", 0), self.grid_size)
            el.name = item.get("name", item["id"])

            if hasattr(el, "rotation") and item.get("rotation") is not None:
                el.rotation = item["rotation"]
            if el.type == "corner" and item.get("orientation"):
                el.orientation = item["orientation"]
            if el.type == "bus" and item.get("length"):
                el.length = item["length"]
            label = item.get("label")
            if isinstance(label, (list, tuple)) and len(label) == 2:
                el.label_offset = [float(label[0]), float(label[1])]
            if el.type == "cabinet":
                self._restore_cabinet(el, item.get("cabinet") or {})
            if el.type == "container":
                self._restore_container(el, item.get("container") or {})
            if logic_library.is_logic_type(el.type):
                logic_library.restore_element(el, item.get("logic") or {})

            el.generate_ports()
            elements[item["id"]] = el

        # Подписи слотов — после того, как собраны все элементы
        self._sync_containers(elements)
        return elements

    def _restore_container(self, el, payload):
        """Восстанавливает контейнер из JSON (поля каталога и привязку шкафов)."""
        el.container_key = payload.get("key", "")
        el.code = payload.get("code") or el.code
        el.title = payload.get("title") or el.title
        el.size = payload.get("size", el.size)
        try:
            el.set_slots(payload.get("slots") or el.slots)
        except (TypeError, ValueError):
            pass
        cabinets = payload.get("cabinets") or []
        el.cabinets = [str(cabinet_id) for cabinet_id in cabinets
                       if cabinet_id][:el.slot_count()]
        while len(el.cabinets) < el.slot_count():
            el.cabinets.append("")
        el.slot_labels = [""] * el.slot_count()
        raw_labels = payload.get("slot_labels") or []
        if raw_labels and len(raw_labels) == el.slot_count():
            el.slot_labels = [str(label) for label in raw_labels]
        raw_points = payload.get("link_points") or []
        el.link_points = [self._clean_points(p) if p else []
                          for p in raw_points[:el.slot_count()]]
        while len(el.link_points) < el.slot_count():
            el.link_points.append([])
        el.info = dict(payload.get("info") or {})

    def _build_protection_links(self, links, id_mapping=None):
        """Проверяет и (при вставке) переназначает защитные связи."""
        result = []
        for link in links or []:
            if not isinstance(link, dict):
                continue
            ied_ref = link.get("komplekt") or link.get("ied") or ""
            element_id = link.get("element") or ""
            cabinet_id, sep, index = ied_ref.partition("#")
            if not sep:
                continue
            if id_mapping is not None:
                cabinet_id = id_mapping.get(cabinet_id, "")
                element_id = id_mapping.get(element_id, "")
            cabinet = self.elements.get(cabinet_id)
            element = self.elements.get(element_id)
            if not cabinet or cabinet.type != "cabinet":
                continue
            if not element or not (
                    f"komplekt{index}" in cabinet.ports
                    or f"ied{index}" in cabinet.ports):
                continue
            entry = {"komplekt": f"{cabinet_id}#{index}",
                     "element": element_id,
                     "points": self._clean_points(link.get("points"))}
            note = (link.get("note") or "").strip()
            if note:
                entry["note"] = note
            result.append(entry)
        return result

    def _build_connections(self, data, elements):
        connections = []
        for c in data.get("connections", []):
            el1 = elements.get(c.get("element_from"))
            el2 = elements.get(c.get("element_to"))
            if not el1 or not el2:
                continue

            port1 = self._resolve_port(el1, c.get("port_from"), c.get("node_from"))
            port2 = self._resolve_port(el2, c.get("port_to"), c.get("node_to"))
            if port1 and port2:
                entry = {
                    "from": el1.id, "to": el2.id,
                    "port_from": port1, "port_to": port2,
                    "canvas_id": None
                }
                points = self._clean_points(c.get("points"))
                if points:
                    entry["points"] = points
                connections.append(entry)
        return connections

    @staticmethod
    def _resolve_port(el, port_name, node_id):
        """Имя порта: прямое совпадение, затем поиск по node_id (совместимость со старыми файлами)."""
        if port_name in el.ports:
            return port_name
        if node_id:
            for p_name, p_data in el.ports.items():
                if p_data.get("node_id") == node_id:
                    return p_name
        return None

    def insert_from_json(self, event=None):
        """Вставляет схему из JSON-файла на текущее полотно"""
        filepath = filedialog.askopenfilename(
            title="Выберите файл схемы для вставки",
            filetypes=[("JSON files", "*.json")]
        )
        if not filepath:
            return
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if "elements" not in data or "connections" not in data:
                messagebox.showerror("Ошибка", "Неверный формат файла.")
                return

            if not data["elements"]:
                return

            # Состояние сохраняем ДО вставки, иначе Undo возвращал уже вставленную схему
            self._push_undo()

            # 1. Вычисляем смещение
            xs = [el["x"] for el in data["elements"]]
            ys = [el["y"] for el in data["elements"]]
            src_cx = sum(xs) / len(xs)
            src_cy = sum(ys) / len(ys)

            w = self.canvas.winfo_width() or 800
            h = self.canvas.winfo_height() or 700
            dst_cx, dst_cy = self.screen_to_world(w/2, h/2)
            
            offset_x = dst_cx - src_cx
            offset_y = dst_cy - src_cy
            
            if self.snap_to_grid:
                offset_x = round(offset_x / self.grid_size) * self.grid_size
                offset_y = round(offset_y / self.grid_size) * self.grid_size

            id_mapping = {}
            new_selected = []
            inserted_containers = []

            # 2. Вставляем элементы
            for item in data["elements"]:
                old_id = item["id"]
                new_id = f"{item['type'][:2].upper()}{str(uuid.uuid4())[:4]}"
                
                new_el = library.create_component(
                    item["type"], new_id, 
                    item["x"] + offset_x, 
                    item["y"] + offset_y, 
                    self.grid_size
                )
                
                new_el.name = self.get_next_name(
                    PREFIX_BY_TYPE.get(item["type"], "EL"),
                    item["type"]
                )
                
                if item.get("length") and hasattr(new_el, "length"):
                    new_el.length = item["length"]
                if item.get("rotation") is not None and hasattr(new_el, "rotation"):
                    new_el.rotation = item["rotation"]
                if item.get("orientation") and hasattr(new_el, "orientation"):
                    new_el.orientation = item["orientation"]
                label = item.get("label")
                if isinstance(label, (list, tuple)) and len(label) == 2:
                    new_el.label_offset = [float(label[0]), float(label[1])]
                if new_el.type == "cabinet":
                    self._restore_cabinet(new_el, item.get("cabinet") or {})
                if new_el.type == "container":
                    self._restore_container(new_el, item.get("container") or {})
                    inserted_containers.append(new_el)
                if logic_library.is_logic_type(new_el.type):
                    logic_library.restore_element(
                        new_el, item.get("logic") or {})

                new_el.generate_ports()
                self.elements[new_id] = new_el
                id_mapping[old_id] = new_id
                new_selected.append(new_id)

            # 3. Восстанавливаем связи
            for conn in data["connections"]:
                old_from = conn.get("element_from")
                old_to = conn.get("element_to")
                
                if old_from in id_mapping and old_to in id_mapping:
                    new_from = id_mapping[old_from]
                    new_to = id_mapping[old_to]

                    # id пересоздан, поэтому node_id не совпадёт — ищем по имени порта
                    port_from = self._resolve_port(self.elements[new_from],
                                                   conn.get("port_from"), conn.get("node_from"))
                    port_to = self._resolve_port(self.elements[new_to],
                                                 conn.get("port_to"), conn.get("node_to"))

                    if port_from and port_to:
                        created = self.create_connection(
                            new_from, new_to, port_from, port_to)
                        if created is not None and conn.get("points"):
                            created["points"] = [
                                [round(point[0] + offset_x, 1),
                                 round(point[1] + offset_y, 1)]
                                for point in self._clean_points(conn["points"])]

            # 3-бис. Привязка шкафов внутри вставленных контейнеров
            for container in inserted_containers:
                container.cabinets = [id_mapping.get(cabinet_id, "")
                                      for cabinet_id in container.cabinets]
                while len(container.cabinets) < container.slot_count():
                    container.cabinets.append("")
                # изломы линий привязки не переносятся — оставляем прямыми
                container.link_points = [[] for _ in range(container.slot_count())]
            self._sync_containers()

            # 3-бис. Аналоговые цепи внутри вставленного фрагмента
            inserted_analog = self._build_analog_links(
                data.get("analog_links", []), id_mapping)
            for link in inserted_analog:
                if link.get("points"):
                    link["points"] = [
                        [round(point[0] + offset_x, 1),
                         round(point[1] + offset_y, 1)]
                        for point in link["points"]]
            existing_analog = {(link["from"], link["to"])
                               for link in self.analog_links}
            for link in inserted_analog:
                key = (link["from"], link["to"])
                if key not in existing_analog:
                    self.analog_links.append(link)
                    existing_analog.add(key)

            # 3-бис. Связи ФЛС внутри вставленного фрагмента
            inserted_logic = self._build_logic_links(
                data.get("logic_links", []), id_mapping)
            for link in inserted_logic:
                if link.get("points"):
                    link["points"] = [
                        [round(point[0] + offset_x, 1),
                         round(point[1] + offset_y, 1)]
                        for point in link["points"]]
            existing_logic = {(link["from"], link["to"])
                              for link in self.logic_links}
            for link in inserted_logic:
                key = (link["from"], link["to"])
                if key not in existing_logic:
                    self.logic_links.append(link)
                    existing_logic.add(key)

            # 3a. Защитные связи внутри вставленного фрагмента
            inserted_links = self._build_protection_links(
                data.get("protection_links", []), id_mapping)
            existing = {(self._link_ref(link), link["element"])
                        for link in self.protection_links}
            for link in inserted_links:
                key = (self._link_ref(link), link["element"])
                if key not in existing:
                    if link.get("points"):
                        link["points"] = [
                            [round(point[0] + offset_x, 1),
                             round(point[1] + offset_y, 1)]
                            for point in self._clean_points(link["points"])]
                    self.protection_links.append(link)
                    existing.add(key)

            # 3б. Комментарии к вставленному фрагменту — со сдвигом на место вставки
            for comment in self._build_comments(data.get("comments", [])):
                self.comments.append({
                    "id": "C" + str(uuid.uuid4())[:6],
                    "x": round(comment["x"] + offset_x, 1),
                    "y": round(comment["y"] + offset_y, 1),
                    "text": comment["text"],
                    "style": comment["style"],
                })

            # 4. Выделяем вставленное
            self.selected_elements = new_selected
            self.redraw_all()
            self._refresh_search()
            messagebox.showinfo("Успех", f"Вставлено {len(new_selected)} элементов.")
            
        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Файл поврежден или не является корректным JSON.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось вставить файл:\n{e}")

