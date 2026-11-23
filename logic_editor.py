# -*- coding: utf-8 -*-
"""Редактор функционально-логических схем (ФЛС) устройства.

Методы этого миксина подключаются к ``main.CircuitEditor`` и добавляют
вкладку «Логика»: элементы ФЛС, цветные связи с номером и наименованием
сигнала, свойства функциональных блоков и вставку логических узлов.

Схема хранится в том же JSON, что и первичная: элементы получают поле
``logic``, связи — отдельный список ``logic_links``.
"""

from __future__ import annotations

import math

import tkinter as tk
from tkinter import messagebox, ttk

import logic_library as ll
import ui_theme


def _format_coord(value):
    """Координата поля для таблицы: без лишних нулей."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    text = ("%.1f" % number).rstrip("0").rstrip(".")
    return text or "0"


def _parse_coord(value):
    """Ввод координаты: запятая как десятичный разделитель."""
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


# ==========================================================================
# Иконки ленты (запасной вариант без Pillow)
# ==========================================================================
def _ri_logic_bus(canvas):
    canvas.create_line(16, 3, 16, 29, width=4, fill="#00acc1")
    for y in (9, 16, 23):
        canvas.create_line(10, y, 22, y, width=1, fill="#00838f")


def _ri_logic_key(canvas):
    canvas.create_rectangle(3, 8, 29, 24, outline="black", width=1)
    canvas.create_line(7, 12, 7, 20, width=1, fill="black")
    canvas.create_line(11, 12, 11, 20, width=1, fill="black")
    canvas.create_line(6, 21, 13, 11, width=1, fill="black")
    canvas.create_polygon(18, 12, 18, 20, 23, 16, fill="white",
                          outline="black")
    canvas.create_line(23, 12, 23, 20, width=1, fill="black")


def _ri_logic_led(canvas):
    canvas.create_rectangle(4, 9, 28, 23, outline="black", width=1)
    canvas.create_polygon(10, 12, 10, 20, 17, 16, fill="white",
                          outline="black")
    canvas.create_line(17, 12, 17, 20, width=1, fill="black")
    canvas.create_line(7, 16, 10, 16, width=1)
    canvas.create_line(17, 16, 22, 16, width=1)


def _ri_logic_block(canvas):
    canvas.create_rectangle(3, 4, 29, 28, outline="black", width=1)
    canvas.create_line(3, 10, 29, 10, width=1)
    for y in (15, 20, 25):
        canvas.create_line(8, y, 24, y, width=1, fill="#9e9e9e")
    canvas.create_line(3, 15, 0, 15, width=1)
    canvas.create_line(3, 20, 0, 20, width=1)


def _ri_logic_function(canvas):
    canvas.create_rectangle(8, 6, 24, 26, outline="black", width=1)
    canvas.create_text(16, 16, text="&", font=("Arial", 9, "bold"))
    canvas.create_line(2, 11, 8, 11, width=1)
    canvas.create_line(2, 21, 8, 21, width=1)
    canvas.create_line(24, 16, 30, 16, width=1)


def _ri_logic_port_in(canvas):
    canvas.create_rectangle(3, 9, 19, 23, outline="black", width=1)
    canvas.create_polygon(17, 12, 17, 20, 10, 16, fill="black")
    canvas.create_line(19, 16, 26, 16, width=1)
    canvas.create_polygon(30, 16, 24, 12, 24, 20, fill="black")


def _ri_logic_port_out(canvas):
    canvas.create_line(2, 16, 8, 16, width=1)
    canvas.create_polygon(10, 16, 4, 12, 4, 20, fill="black")
    canvas.create_rectangle(13, 9, 29, 23, outline="black", width=1)
    canvas.create_polygon(24, 12, 24, 20, 17, 16, fill="black")


def _ri_logic_refresh(canvas):
    canvas.create_line(6, 8, 24, 8, width=2, fill="#1f4e79")
    canvas.create_polygon(24, 8, 20, 5, 20, 11, fill="#1f4e79")
    canvas.create_line(24, 24, 6, 24, width=2, fill="#1f4e79")
    canvas.create_polygon(6, 24, 10, 21, 10, 27, fill="#1f4e79")
    canvas.create_text(16, 16, text="=", font=("Arial", 8, "bold"),
                       fill="#1f4e79")


def _ri_logic_link(canvas):
    canvas.create_line(3, 24, 20, 8, width=2, fill="#2e7d32")
    canvas.create_line(20, 8, 29, 8, width=2, fill="#2e7d32")
    canvas.create_polygon(29, 8, 24, 5, 24, 11, fill="#2e7d32")


def _ri_logic_link_kind(kind):
    """Иконка типа связи: цвет и штрих совпадают с линией на схеме."""
    style = ll.link_style(kind)
    color = style["color"]
    dash = style["dash"]

    def draw(canvas):
        canvas.create_line(3, 24, 19, 9, width=2, fill=color, dash=dash)
        canvas.create_line(19, 9, 28, 9, width=2, fill=color, dash=dash)
        canvas.create_polygon(29, 9, 24, 6, 24, 12, fill=color)

    return draw


def _ri_logic_legend(canvas):
    """Иконка «Легенда связей»: три цветных штриха."""
    for index, kind in enumerate(("analog", "discrete", "internal")):
        style = ll.link_style(kind)
        y = 8 + index * 8
        canvas.create_line(3, y, 20, y, width=2, fill=style["color"],
                           dash=style["dash"])
        canvas.create_rectangle(23, y - 2, 29, y + 2,
                                fill=style["color"], outline="")


class LogicEditorMixin:
    """Вкладка «Логика» и работа с элементами/связями ФЛС."""

    # ================= ИНИЦИАЛИЗАЦИЯ =================
    def _init_logic(self):
        self.logic_links = []
        self.selected_logic = None
        self._logic_start = None
        self._logic_label_boxes = []
        self.logic_link_kind = "discrete"
        self.show_logic = True
        self.show_logic_legend = False
        self._logic_legend_var = tk.BooleanVar(master=self.root, value=False)
        self._logic_kind_cells = {}
        self.clipboard_logic = []

    # ================= ЛЕНТА =================
    def _build_ribbon_logic(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")

        def build_elements(row):
            for title, etype, icon in (
                    ("Шина", "logic_bus", _ri_logic_bus),
                    ("Клавиша", "logic_key", _ri_logic_key),
                    ("Светодиод", "logic_led", _ri_logic_led),
                    ("Блок", "logic_block", _ri_logic_block),
                    ("Функция", "logic_function", _ri_logic_function),
                    ("Вход. порт", "logic_port_in", _ri_logic_port_in),
                    ("Вых. порт", "logic_port_out", _ri_logic_port_out)):
                self._register_tool(self._ribbon_button(
                    row, title, lambda t=etype: self.set_tool(t),
                    icon, 64), etype).pack(side=tk.LEFT)

        self._ribbon_group(page, "Элементы ФЛС", build_elements)

        def build_links(row):
            for kind in ll.LOGIC_LINK_ORDER:
                style = ll.link_style(kind)
                cell = self._ribbon_button(
                    row, style["title"],
                    lambda k=kind: self.set_logic_link_kind(k),
                    _ri_logic_link_kind(kind), 84)
                cell._label.config(fg=style["color"])
                self._logic_kind_cells[kind] = cell
                # Штатная подсветка кнопки меняет цвет подписи на общий;
                # возвращаем цвет типа связи после наведения/ухода.
                for widget in (cell, cell._canvas, cell._label):
                    widget.bind("<Enter>",
                                lambda e: self._paint_logic_kind_cells(),
                                add="+")
                    widget.bind("<Leave>",
                                lambda e: self._paint_logic_kind_cells(),
                                add="+")
                cell.pack(side=tk.LEFT)
            legend = self._ribbon_button(
                row, "Легенда связей", self._toggle_logic_legend,
                _ri_logic_legend, 92)
            self._logic_legend_cell = legend
            for widget in (legend, legend._canvas, legend._label):
                widget.bind("<Leave>",
                            lambda e: self._paint_logic_kind_cells(),
                            add="+")
            legend.pack(side=tk.LEFT)

        self._ribbon_group(page, "Связи", build_links)

        self._ribbon_group(page, "Свойства", lambda row: [
            self._ribbon_button(row, "Свойства связи",
                                self.edit_selected_logic, _ri_logic_link,
                                96).pack(side=tk.LEFT),
            self._ribbon_button(row, "Свойства блока",
                                self.edit_selected_logic_block,
                                _ri_logic_block, 96).pack(side=tk.LEFT),
            self._ribbon_button(row, "Структура функции",
                                self.edit_selected_logic_function_structure,
                                _ri_logic_function, 104).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Нумерация", lambda row: [
            self._ribbon_button(row, "Присвоить номер",
                                self.assign_selected_logic_number,
                                _ri_logic_link, 104).pack(side=tk.LEFT),
            self._ribbon_button(row, "Перенумеровать",
                                self.renumber_logic_links,
                                _ri_logic_link, 104).pack(side=tk.LEFT),
            self._ribbon_button(row, "Обновить связи",
                                self.update_logic_links,
                                _ri_logic_refresh, 104).pack(side=tk.LEFT),
        ])
        return page

    def _toggle_logic_legend(self):
        """Показать/скрыть условные обозначения типов связей на полотне."""
        self.show_logic_legend = not self.show_logic_legend
        if hasattr(self, "_logic_legend_var"):
            self._logic_legend_var.set(self.show_logic_legend)
        self._paint_logic_kind_cells()
        self.redraw_all()

    def set_logic_link_kind(self, kind, switch_tool=True):
        """Тип новой связи; у выбранной связи тип меняется сразу же.

        ``switch_tool=False`` — запомнить тип связи, не переключая
        инструмент: выбор элемента принципиальной схемы включает её цепь
        по умолчанию, но инструментом остаётся сам элемент, иначе клик
        по полотну начинал бы связь вместо размещения элемента.
        """
        if kind not in ll.LOGIC_LINK_KINDS:
            kind = "discrete"
        self.logic_link_kind = kind
        link = self.selected_logic
        if link is not None and link in self.logic_links:
            if link.get("kind") != kind:
                self._push_undo()
                link["kind"] = kind
                self._mark_modified()
            self._paint_logic_kind_cells()
            self.redraw_all()
            return
        if switch_tool:
            self.set_tool("logic_link")
        self._paint_logic_kind_cells()

    def _paint_logic_kind_cells(self):
        for kind, cell in getattr(self, "_logic_kind_cells", {}).items():
            style = ll.link_style(kind)
            active = (self.current_tool == "logic_link"
                      and kind == self.logic_link_kind)
            cell._active = active
            cell._label.config(fg=style["color"])
            bg = ui_theme.TOOL_ACTIVE if active else ui_theme.RIBBON
            cell.config(bg=bg)
            cell._label.config(bg=bg)
            cell._canvas.config(bg=bg)
        legend = getattr(self, "_logic_legend_cell", None)
        if legend is not None:
            active = bool(self.show_logic_legend)
            legend._active = active
            bg = ui_theme.TOOL_ACTIVE if active else ui_theme.RIBBON
            legend.config(bg=bg)
            legend._label.config(bg=bg)
            legend._canvas.config(bg=bg)
            legend._label.config(fg=ui_theme.ACCENT if active
                                 else ui_theme.TEXT)

    # ================= ГЕОМЕТРИЯ СВЯЗЕЙ =================
    @staticmethod
    def _logic_split_ref(ref):
        element_id, sep, port = str(ref or "").partition("#")
        return element_id, (port if sep else "")

    def _logic_ref_point(self, ref):
        element_id, port_name = self._logic_split_ref(ref)
        element = self.elements.get(element_id)
        if element is None:
            return None
        port = element.ports.get(port_name)
        if port:
            return (port["x"], port["y"])
        return (element.x, element.y)

    def _logic_ref_valid(self, ref):
        element_id, port_name = self._logic_split_ref(ref)
        element = self.elements.get(element_id)
        return element is not None and port_name in element.ports

    def _prune_logic_links(self):
        """Убирает связи, выводы которых исчезли после правки элемента."""
        self.logic_links = [
            link for link in self.logic_links
            if self._logic_ref_valid(link.get("from"))
            and self._logic_ref_valid(link.get("to"))]

    def _rebind_logic_bus_links(self, element, old_ports):
        """Перепривязка связей к отводам шины после изменения её длины.

        Отводы шины нумеруются от верхнего края, поэтому при изменении
        длины все точки подключения уезжают по вертикали, а при
        уменьшении длины часть отводов исчезает вместе со связями.
        Связь, привязанная к отводу, перепривязывается к ближайшему
        новому отводу — к тому, который оказался на прежнем месте
        подключения. Служебные выводы (верх, низ, середина) не меняются.
        """
        taps = [name for name in element.ports if name.startswith("p")]
        if not taps:
            # Отводов не осталось — подключаем к ближайшему выводу шины.
            taps = list(element.ports)
        if not taps:
            return
        points = [(name, element.ports[name]["x"], element.ports[name]["y"])
                  for name in taps]
        for link in self.logic_links:
            for end in ("from", "to"):
                element_id, port_name = self._logic_split_ref(link.get(end))
                if element_id != element.id \
                        or not port_name.startswith("p") \
                        or port_name not in old_ports:
                    continue
                old_x, old_y = old_ports[port_name]
                best = min(points, key=lambda item: math.hypot(
                    item[1] - old_x, item[2] - old_y))[0]
                link[end] = "{}#{}".format(element.id, best)

    def _logic_route(self, link):
        start = self._logic_ref_point((link or {}).get("from"))
        end = self._logic_ref_point((link or {}).get("to"))
        if start is None or end is None:
            return []
        route = [tuple(start)]
        route.extend((float(point[0]), float(point[1]))
                     for point in self._clean_points(link.get("points")))
        route.append(tuple(end))
        return route

    def _logic_ports(self):
        for element in self.elements.values():
            if not ll.is_logic_type(getattr(element, "type", "")):
                continue
            for name, port in element.ports.items():
                yield element, name, port

    def _logic_port_at(self, sx, sy):
        tolerance = max(8.0, 12.0 * self.zoom)
        best, best_dist = None, tolerance
        for element, name, port in self._logic_ports():
            px, py = self.world_to_screen(port["x"], port["y"])
            distance = math.hypot(sx - px, sy - py)
            if distance <= best_dist:
                best, best_dist = (element.id, name), distance
        return best

    def _logic_link_at(self, sx, sy):
        if not getattr(self, "show_logic", True):
            return None
        tolerance = max(6.0, 7.0 * self.zoom)
        best, best_distance = None, None
        for link in self.logic_links:
            route = self._logic_route(link)
            for index in range(len(route) - 1):
                x1, y1 = self.world_to_screen(*route[index])
                x2, y2 = self.world_to_screen(*route[index + 1])
                distance = self._point_segment_distance(sx, sy, x1, y1, x2, y2)
                if distance <= tolerance and (best_distance is None
                                              or distance < best_distance):
                    best, best_distance = link, distance
        return best

    def _logic_segment_at(self, sx, sy):
        tolerance = max(4.0, 6.0 * self.zoom)
        best, best_distance = None, tolerance
        for link in self.logic_links:
            route = self._logic_route(link)
            for index in range(len(route) - 1):
                x1, y1 = self.world_to_screen(*route[index])
                x2, y2 = self.world_to_screen(*route[index + 1])
                distance = self._point_segment_distance(sx, sy, x1, y1, x2, y2)
                if distance <= best_distance:
                    best, best_distance = (link, index), distance
        return best

    def _logic_label_at(self, sx, sy):
        for entry in self._logic_label_boxes:
            link, _part, box = entry
            if box and box[0] - 2 <= sx <= box[2] + 2 \
                    and box[1] - 2 <= sy <= box[3] + 2:
                return link
        return None

    def _logic_annotation_at(self, sx, sy):
        """Номер или наименование связи под курсором: (связь, часть).

        Часть — «start»/«end» для номера у конца линии, «label» для
        наименования вдоль линии; служит для перетаскивания мышкой.
        """
        for link, part, box in self._logic_label_boxes:
            if box and box[0] - 2 <= sx <= box[2] + 2 \
                    and box[1] - 2 <= sy <= box[3] + 2:
                return link, part
        return None

    def _logic_point_at(self, sx, sy):
        """Маркер излома связи ФЛС под курсором.

        Точки выделенной связи проверяются первыми; заодно находятся
        точки любой другой связи — захват точки выбирает эту связь,
        поэтому излом можно перетащить без предварительного выделения.
        """
        radius = max(5.0, 6.0 * self.zoom)
        best, best_distance = None, None
        links = list(self.logic_links)
        selected = self.selected_logic
        if selected in links:
            # Выделенная связь — первой: её точки приоритетны.
            links.remove(selected)
            links.insert(0, selected)
        for link in links:
            for index, point in enumerate(link.get("points") or []):
                px, py = self.world_to_screen(point[0], point[1])
                distance = math.hypot(sx - px, sy - py)
                if distance <= radius and (best_distance is None
                                           or distance < best_distance):
                    best, best_distance = ("link", link, index), distance
        return best

    def _logic_element_at(self, sx, sy):
        element_id = self._element_at(sx, sy)
        element = self.elements.get(element_id) if element_id else None
        if element is not None and ll.is_logic_type(element.type):
            return element
        return None

    # ================= КЛИКИ И НАВЕДЕНИЕ =================
    def _on_logic_click(self, event):
        if not getattr(self, "show_logic", True):
            messagebox.showinfo("Логика", "Слой ФЛС скрыт.")
            return
        port = self._logic_port_at(event.x, event.y)
        if self._logic_start is None:
            link = self._logic_link_at(event.x, event.y)
            if link is not None and port is None:
                if self._ctrl_click(event):
                    self._push_undo()
                    self.logic_links.remove(link)
                    if self.selected_logic is link:
                        self.selected_logic = None
                else:
                    self.selected_logic = link
                    self.selected_elements = []
                    self.selected_analog = None
                    self.selected_protection = None
                    self.selected_container_link = None
                self.redraw_all()
                return
            if port is not None:
                self._logic_start = port
            else:
                element = self._logic_element_at(event.x, event.y)
                if element is not None:
                    messagebox.showinfo(
                        "Логика",
                        "Связь ФЛС подключается к выводу элемента: "
                        "краю клавиши/светодиода, входу или выходу блока, "
                        "логического узла, отводу шины или другой шине.")
            self.redraw_all()
            return

        if port is None:
            self._logic_start = None
            if self._logic_element_at(event.x, event.y) is not None:
                messagebox.showinfo(
                    "Логика",
                    "Второй конец связи — вывод элемента ФЛС.")
            self.redraw_all()
            return
        if port == self._logic_start:
            self._logic_start = None
            self.redraw_all()
            return
        created = self._add_logic_link(self._logic_start, port)
        self._logic_start = None
        self.redraw_all()
        if created is not None:
            self.edit_logic_link(created)

    def _hover_logic(self, event):
        if not getattr(self, "show_logic", True):
            return
        radius = max(4.0, 6.0 * self.zoom)
        port = self._logic_port_at(event.x, event.y)
        if port is not None:
            point = self._logic_ref_point("{}#{}".format(*port))
            if point is not None:
                px, py = self.world_to_screen(*point)
                self.canvas.create_oval(
                    px - radius, py - radius, px + radius, py + radius,
                    outline="#1f4e79", width=2, tags="logic_hover")
        if self._logic_start is None:
            return
        point = self._logic_ref_point(
            "{}#{}".format(*self._logic_start))
        if point is None:
            return
        sx, sy = self.world_to_screen(*point)
        style = ll.link_style(self.logic_link_kind)
        self.canvas.create_line(sx, sy, event.x, event.y,
                                fill=style["color"], dash=style["dash"],
                                width=max(1, int(1.2 * self.zoom)),
                                tags="logic_preview")

    def _add_logic_link(self, first, second):
        first_ref = "{}#{}".format(*first)
        second_ref = "{}#{}".format(*second)
        if first_ref == second_ref:
            return None
        start_el = self.elements.get(first[0])
        end_el = self.elements.get(second[0])
        if start_el is None or end_el is None:
            return None
        start_port = start_el.ports.get(first[1]) or {}
        end_port = end_el.ports.get(second[1]) or {}
        # Соединяются выход со входом или вывод с шиной; два входа или два
        # выхода напрямую не соединяются — объединение идёт через шину.
        if (start_port.get("direction") == end_port.get("direction")
                and start_port.get("direction") in ("in", "out")):
            return None
        self._push_undo()
        source = (start_port if start_port.get("direction") == "out"
                  else end_port if end_port.get("direction") == "out" else {})
        link = {
            "from": first_ref,
            "to": second_ref,
            "kind": self.logic_link_kind,
            "id": ll.next_link_id(self.logic_links),
            "number": ll.next_logic_number(self.logic_links),
            "ru": source.get("slot_name") or "",
            "iec": source.get("slot_iec") or "",
            # Стрелка по умолчанию отключена: включается в свойствах связи.
            "arrow": False,
        }
        self.logic_links.append(link)
        return link

    def _logic_continuation(self, link):
        """Связь до шины, продолжением которой является данная связь."""
        reference = str((link or {}).get("continuation") or "").strip()
        if not reference:
            return {}
        for other in self.logic_links:
            if other is link:
                continue
            if str(other.get("id") or "").strip() == reference:
                return other
        return {}

    def _logic_link_label_text(self, link):
        """Подпись сигнала на линии; не дублирует подпись клавиши/светодиода."""
        text, signal = ll.link_full_label(
            self.elements, link, self._logic_split_ref)
        if not text:
            return ""
        link_ru = (link.get("ru") or "").strip()
        link_iec = (link.get("iec") or "").strip()
        for ref in (link.get("from"), link.get("to")):
            element_id, _port = self._logic_split_ref(ref)
            element = self.elements.get(element_id)
            if element is None:
                continue
            if element.type in ("logic_key", "logic_led", "logic_function",
                                "logic_port_in", "logic_port_out",
                                "logic_bus"):
                own_ru = (getattr(element, "signal_ru", "") or "").strip()
                own_iec = (getattr(element, "signal_iec", "") or "").strip()
                if own_ru and link_ru == own_ru \
                        and (not link_iec or link_iec == own_iec):
                    return ""
                own = ll.signal_text(own_ru, own_iec)
                if own and own == signal:
                    return ""
        return text

    def _logic_link_number(self, link):
        """Номер на линии; не повторяет маркировку подключённого элемента."""
        number = (link.get("number") or "").strip()
        if not number:
            number = (self._logic_continuation(link).get("number") or "").strip()
        if not number:
            return ""
        for ref in (link.get("from"), link.get("to")):
            element_id, _port = self._logic_split_ref(ref)
            element = self.elements.get(element_id)
            if element is not None \
                    and (getattr(element, "signal_no", "") or "").strip() == number:
                return ""
        return number

    # ---------- размещение подписей без наложений ----------
    _LOGIC_LABEL_FRACTIONS = (0.5, 0.38, 0.62, 0.28, 0.72, 0.2, 0.8, 0.14, 0.86)

    @staticmethod
    def _logic_text_box(x, y, text, size=6.0):
        width = max(14.0, len(text) * size * 0.55)
        height = max(9.0, size * 1.4)
        return (x - width / 2.0, y - height / 2.0,
                x + width / 2.0, y + height / 2.0)

    @staticmethod
    def _logic_box_busy(box, occupied, pad=2.0):
        x1, y1, x2, y2 = box
        for ox1, oy1, ox2, oy2 in occupied:
            if x1 - pad < ox2 and ox1 - pad < x2 \
                    and y1 - pad < oy2 and oy1 - pad < y2:
                return True
        return False

    @staticmethod
    def _logic_path_point(points, fraction):
        """Точка на заданной доле длины ломаной: (x, y, ux, uy) или None."""
        segments = []
        total = 0.0
        for start, end in zip(points, points[1:]):
            length = math.hypot(end[0] - start[0], end[1] - start[1])
            segments.append((start, end, length))
            total += length
        if total < 1e-6:
            return None
        target = total * fraction
        passed = 0.0
        for start, end, length in segments:
            if length < 1e-9:
                continue
            if passed + length >= target:
                t = (target - passed) / length
                return (start[0] + (end[0] - start[0]) * t,
                        start[1] + (end[1] - start[1]) * t,
                        (end[0] - start[0]) / length,
                        (end[1] - start[1]) / length)
            passed += length
        return None

    def _logic_number_anchor(self, route, number, occupied):
        """Позиция номера у начала линии с обходом занятых мест."""
        x1, y1 = route[0]
        x2, y2 = route[1]
        distance = math.hypot(x2 - x1, y2 - y1)
        if distance < 1e-6:
            return None
        ux, uy = (x2 - x1) / distance, (y2 - y1) / distance
        fallback = None
        for fraction, side in ((0.35, 1.0), (0.55, 1.0),
                               (0.55, -1.0), (0.25, -1.0)):
            shift = min(distance * fraction, 90.0)
            nx = x1 + ux * shift - uy * 9.0 * side
            ny = y1 + uy * shift + ux * 9.0 * side
            box = self._logic_text_box(nx, ny, number)
            if fallback is None:
                fallback = (nx, ny, box)
            if not self._logic_box_busy(box, occupied):
                return nx, ny, box
        return fallback

    def _logic_end_number_anchor(self, route, number, occupied):
        """Позиция маркировки у второго конца линии."""
        x1, y1 = route[-2]
        x2, y2 = route[-1]
        distance = math.hypot(x2 - x1, y2 - y1)
        if distance < 1e-6:
            return None
        ux, uy = (x2 - x1) / distance, (y2 - y1) / distance
        fallback = None
        for fraction, side in ((0.35, 1.0), (0.55, 1.0),
                               (0.55, -1.0), (0.25, -1.0)):
            shift = min(distance * fraction, 90.0)
            nx = x2 - ux * shift - uy * 9.0 * side
            ny = y2 - uy * shift + ux * 9.0 * side
            box = self._logic_text_box(nx, ny, number)
            if fallback is None:
                fallback = (nx, ny, box)
            if not self._logic_box_busy(box, occupied):
                return nx, ny, box
        return fallback

    def _logic_label_anchor(self, route, text, occupied, offset=12.0):
        """Позиция подписи сигнала вдоль линии с обходом занятых мест."""
        fallback = None
        for fraction in self._LOGIC_LABEL_FRACTIONS:
            point = self._logic_path_point(route, fraction)
            if point is None:
                continue
            px, py, ux, uy = point
            x, y = px - uy * offset, py + ux * offset
            box = self._logic_text_box(x, y, text)
            if fallback is None:
                fallback = (x, y, box)
            if not self._logic_box_busy(box, occupied):
                return x, y, box
        return fallback

    # ================= СМЕЩЕНИЯ АННОТАЦИЙ =================
    @staticmethod
    def _valid_offset(value):
        """Смещение [dx, dy] из JSON или None."""
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return [float(value[0]), float(value[1])]
            except (TypeError, ValueError):
                return None
        return None

    def _mark_offsets(self, link):
        """Смещения номеров связи: {"start": [dx, dy], "end": [dx, dy]}."""
        offsets = (link or {}).get("mark_offsets")
        return offsets if isinstance(offsets, dict) else {}

    def _mark_offset(self, link, part):
        """Смещение конкретного номера связи (или [0, 0])."""
        return self._valid_offset(self._mark_offsets(link).get(part)) \
            or [0.0, 0.0]

    def _label_offset(self, link):
        """Смещение наименования связи (или [0, 0])."""
        return self._valid_offset((link or {}).get("label_offset")) \
            or [0.0, 0.0]

    @staticmethod
    def _shifted_anchor(anchor, offset):
        """Аннотация, сдвинутая на сохранённое смещение (мировые ед.)."""
        if anchor is None:
            return None
        offset = LogicEditorMixin._valid_offset(offset)
        if offset is None or (not offset[0] and not offset[1]):
            return anchor
        dx, dy = offset
        x, y, box = anchor
        return (x + dx, y + dy,
                (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))

    def _logic_annotations(self, prepared):
        """Маркировки и подписи связей без наложений.

        Маркировка рисуется у обоих концов связи (structure2: «на концах и
        на начале»), имя — вдоль линии. Сохранённые мышкой смещения
        сдвигают аннотацию с автопозиции, поэтому после правки линии
        подпись остаётся там, где её оставили.
        """
        numbers, labels, occupied = [], [], []
        for link, route in prepared:
            number = self._logic_link_number(link)
            start = self._logic_number_anchor(route, number, occupied) \
                if number else None
            start = self._shifted_anchor(
                start, self._mark_offsets(link).get("start"))
            if start is not None:
                occupied.append(start[2])
            end = self._logic_end_number_anchor(route, number, occupied) \
                if number else None
            end = self._shifted_anchor(
                end, self._mark_offsets(link).get("end"))
            if end is not None:
                occupied.append(end[2])
            numbers.append((link, start, end))
        for link, route in prepared:
            text = self._logic_link_label_text(link)
            anchor = self._logic_label_anchor(route, text, occupied) \
                if text else None
            anchor = self._shifted_anchor(anchor, self._label_offset(link))
            if anchor is not None:
                occupied.append(anchor[2])
            labels.append((link, anchor))
        return numbers, labels

    # ================= ОТРИСОВКА =================
    def _logic_screen_box(self, box):
        """Мировая рамка подписи → экранная рамка для попадания мышью."""
        x1, y1 = self.world_to_screen(box[0], box[1])
        x2, y2 = self.world_to_screen(box[2], box[3])
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def _draw_logic_links(self):
        self._logic_label_boxes = []
        if not getattr(self, "show_logic", True):
            return
        prepared = []
        for link in self.logic_links:
            route = self._logic_route(link)
            if len(route) >= 2:
                prepared.append((link, route))
        numbers, labels = self._logic_annotations(prepared)

        for link, route in prepared:
            style = ll.link_style(link.get("kind"))
            color = style["color"]
            width = max(1, int(style["width"] * self.zoom))
            bus_style = ll.bus_link_style(
                self.elements, link, self._logic_split_ref)
            if bus_style:
                color, bus_width = bus_style
                width = max(2, int(bus_width * self.zoom))
                style = dict(style, dash=None)
            selected = link is self.selected_logic
            if selected:
                width += max(1, int(1.0 * self.zoom))
            points = [self.world_to_screen(x, y) for x, y in route]
            arrow = bool(link.get("arrow", True))
            coords = []
            if arrow:
                last_x, last_y = points[-1]
                prev_x, prev_y = points[-2]
                tail = math.hypot(last_x - prev_x, last_y - prev_y)
                if tail < 1e-6:
                    continue
                ux, uy = (last_x - prev_x) / tail, (last_y - prev_y) / tail
                for x, y in points[:-1]:
                    coords.extend((x, y))
                coords.extend((last_x - ux * 9 * self.zoom,
                               last_y - uy * 9 * self.zoom))
            else:
                for x, y in points:
                    coords.extend((x, y))
            self.canvas.create_line(*coords, fill=color, width=width,
                                    dash=style["dash"], joinstyle=tk.MITER,
                                    tags="logic_link")
            if arrow:
                self._draw_arrowhead(points[-2][0], points[-2][1],
                                     points[-1][0], points[-1][1], color,
                                     max(7.0, 9.0 * self.zoom), "logic_link")
            start_x, start_y = points[0]
            dot = max(2.0, 2.6 * self.zoom)
            self.canvas.create_oval(start_x - dot, start_y - dot,
                                    start_x + dot, start_y + dot,
                                    fill=color, outline="white",
                                    tags="logic_link")

        font = ("Arial", max(1, int(6 * self.zoom)))

        def draw_number(link, anchor, part):
            if anchor is None:
                return
            x, y, box = anchor
            sx, sy = self.world_to_screen(x, y)
            bx1, by1, bx2, by2 = self._logic_screen_box(box)
            self.canvas.create_rectangle(
                bx1 - 1, by1 - 1, bx2 + 1, by2 + 1,
                fill="white", outline="", tags="logic_label")
            self.canvas.create_text(
                sx, sy, text=self._logic_link_number(link),
                fill=ll.link_color(self.elements, link, self._logic_split_ref),
                font=font, anchor="center", tags="logic_label")
            self._logic_label_boxes.append(
                (link, part, self._logic_screen_box(box)))

        for link, start, end in numbers:
            draw_number(link, start, "start")
            draw_number(link, end, "end")
        for link, anchor in labels:
            if anchor is None:
                continue
            x, y, box = anchor
            sx, sy = self.world_to_screen(x, y)
            bx1, by1, bx2, by2 = self._logic_screen_box(box)
            self.canvas.create_rectangle(
                bx1 - 1, by1 - 1, bx2 + 1, by2 + 1,
                fill="white", outline="", tags="logic_label")
            self.canvas.create_text(
                sx, sy, text=self._logic_link_label_text(link),
                fill=ll.link_color(self.elements, link, self._logic_split_ref),
                font=font, anchor="center", justify="center",
                tags="logic_label")
            self._logic_label_boxes.append(
                (link, "label", self._logic_screen_box(box)))

        if self._logic_start is not None:
            point = self._logic_ref_point(
                "{}#{}".format(*self._logic_start))
            if point is not None:
                px, py = self.world_to_screen(*point)
                r = max(4.0, 6.0 * self.zoom)
                self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                        outline="red", width=2,
                                        tags="logic_start")
        self._draw_logic_legend()

    def _logic_used_kinds(self):
        """Типы связей, которые реально есть на схеме (порядок ленты)."""
        return [kind for kind in ll.LOGIC_LINK_ORDER
                if any(link.get("kind") == kind for link in self.logic_links)]

    def _draw_logic_legend(self):
        """Условные обозначения типов связей в правом верхнем углу полотна.

        Легенда — экранная подсказка: в PDF/PNG не выводится, чтобы не
        перекрывать чертёж.
        """
        self.canvas.delete("logic_legend")
        if not getattr(self, "show_logic_legend", False):
            return
        kinds = self._logic_used_kinds()
        if not kinds:
            return
        row_h = 18
        width = 236
        height = 12 + row_h * (len(kinds) + 1)
        canvas_width = max(self.canvas.winfo_width(), width + 24)
        x1 = canvas_width - width - 12
        y1 = 12
        x2 = x1 + width
        y2 = y1 + height
        self.canvas.create_rectangle(x1, y1, x2, y2, fill="white",
                                     outline="#b8b8b8", tags="logic_legend")
        self.canvas.create_text(x1 + 8, y1 + 6, text="Типы связей ФЛС",
                                anchor="nw", font=("Arial", 8, "bold"),
                                fill=ui_theme.ACCENT, tags="logic_legend")
        y = y1 + 12 + row_h
        for kind in kinds:
            style = ll.link_style(kind)
            self.canvas.create_line(
                x1 + 8, y - 4, x1 + 52, y - 4, fill=style["color"],
                width=max(1, int(style["width"])), dash=style["dash"],
                tags="logic_legend")
            self.canvas.create_text(
                x1 + 60, y - 4, anchor="w", text=style["title"],
                font=("Arial", 8), fill=style["color"], tags="logic_legend")
            y += row_h

    def _draw_logic_points(self):
        """Маркеры изломов связей ФЛС: у выделенной связи — крупнее.

        Точки видны у всех связей: излом можно перетащить без
        предварительного выделения, захват точки выбирает связь.
        """
        if not getattr(self, "show_logic", True):
            return
        selected = self.selected_logic
        for link in self.logic_links:
            points = link.get("points") or []
            if not points:
                continue
            style = ll.link_style(link.get("kind"))
            if link is selected:
                radius = max(3.5, 4.5 * self.zoom)
                fill, outline = "white", style["color"]
                width = max(1, int(1.5 * self.zoom))
            else:
                radius = max(2.0, 2.5 * self.zoom)
                fill, outline = style["color"], style["color"]
                width = 1
            for point in points:
                px, py = self.world_to_screen(point[0], point[1])
                self.canvas.create_rectangle(
                    px - radius, py - radius, px + radius, py + radius,
                    fill=fill, outline=outline, width=width,
                    tags="logic_point")

    def _draw_logic_scene(self, canvas):
        """Связи ФЛС для PDF/PNG: те же линии, стрелки и подписи."""
        if not getattr(self, "show_logic", True):
            return
        prepared = []
        for link in self.logic_links:
            route = self._logic_route(link)
            if len(route) >= 2:
                prepared.append((link, route))
        numbers, labels = self._logic_annotations(prepared)

        for link, route in prepared:
            style = ll.link_style(link.get("kind"))
            color = style["color"]
            line_width = 1
            bus_style = ll.bus_link_style(
                self.elements, link, self._logic_split_ref)
            if bus_style:
                color, width = bus_style
                line_width = max(2, int(width))
                style = dict(style, dash=None)
            arrow = bool(link.get("arrow", True))
            if arrow:
                last_x, last_y = route[-1]
                prev_x, prev_y = route[-2]
                distance = math.hypot(last_x - prev_x, last_y - prev_y)
                if distance < 1e-6:
                    continue
                ux, uy = ((last_x - prev_x) / distance,
                          (last_y - prev_y) / distance)
                coords = []
                for x, y in route[:-1]:
                    coords.extend((x, y))
                coords.extend((last_x - ux * 5.4, last_y - uy * 5.4))
                canvas.create_line(*coords, fill=color, width=line_width,
                                   dash=style["dash"])
                self._export_arrowhead(canvas, prev_x, prev_y,
                                       last_x, last_y, fill=color)
            else:
                coords = []
                for x, y in route:
                    coords.extend((x, y))
                canvas.create_line(*coords, fill=color, width=line_width,
                                   dash=style["dash"])

        def draw_number(link, anchor):
            if anchor is None:
                return
            x, y, box = anchor
            canvas.create_rectangle(box[0], box[1], box[2], box[3],
                                    fill="white", outline="")
            canvas.create_text(x, y, text=self._logic_link_number(link),
                               fill=ll.link_color(self.elements, link, self._logic_split_ref),
                               font=("Arial", 6), anchor="center")

        for link, start, end in numbers:
            draw_number(link, start)
            draw_number(link, end)
        for link, anchor in labels:
            if anchor is None:
                continue
            x, y, box = anchor
            canvas.create_rectangle(box[0], box[1], box[2], box[3],
                                    fill="white", outline="")
            canvas.create_text(x, y, text=self._logic_link_label_text(link),
                               fill=ll.link_color(self.elements, link, self._logic_split_ref),
                               font=("Arial", 6), anchor="center",
                               justify="center")

    # ================= СЕРИАЛИЗАЦИЯ =================
    def _logic_link_record(self, link):
        record = {
            "from": link.get("from", ""),
            "to": link.get("to", ""),
            "kind": link.get("kind", "discrete"),
        }
        for field in ("id", "continuation", "number", "ru", "iec"):
            value = link.get(field)
            if isinstance(value, str) and value.strip():
                record[field] = value.strip()
        if link.get("arrow") is False:
            record["arrow"] = False
        # Смещения номера и наименования, заданные перетаскиванием.
        label_offset = self._valid_offset(link.get("label_offset"))
        if label_offset and (label_offset[0] or label_offset[1]):
            record["label_offset"] = [round(label_offset[0], 1),
                                      round(label_offset[1], 1)]
        mark_offsets = {}
        for part, value in self._mark_offsets(link).items():
            offset = self._valid_offset(value)
            if offset and (offset[0] or offset[1]):
                mark_offsets[part] = [round(offset[0], 1),
                                      round(offset[1], 1)]
        if mark_offsets:
            record["mark_offsets"] = mark_offsets
        points = self._clean_points(link.get("points"))
        if points:
            record["points"] = points
        return record

    def _build_logic_links(self, links, id_mapping=None):
        result = []
        for link in links or []:
            if not isinstance(link, dict):
                continue
            from_ref = str(link.get("from") or "")
            to_ref = str(link.get("to") or "")
            from_id, from_port = self._logic_split_ref(from_ref)
            to_id, to_port = self._logic_split_ref(to_ref)
            if id_mapping is not None:
                from_id = id_mapping.get(from_id, "")
                to_id = id_mapping.get(to_id, "")
                if not from_id or not to_id:
                    continue
                from_ref = "{}#{}".format(from_id, from_port)
                to_ref = "{}#{}".format(to_id, to_port)
            start = self.elements.get(from_id)
            end = self.elements.get(to_id)
            if start is None or end is None:
                continue
            if from_ref == to_ref:
                continue
            if from_port not in start.ports or to_port not in end.ports:
                continue
            entry = {
                "from": from_ref, "to": to_ref,
                "kind": (link.get("kind")
                         if link.get("kind") in ll.LOGIC_LINK_KINDS
                         else "discrete"),
            }
            for field in ("id", "continuation", "number", "ru", "iec"):
                value = link.get(field)
                if isinstance(value, str) and value.strip():
                    entry[field] = value.strip()
            if link.get("arrow") is False:
                entry["arrow"] = False
            # Смещения номера и наименования из JSON.
            label_offset = self._valid_offset(link.get("label_offset"))
            if label_offset:
                entry["label_offset"] = list(label_offset)
            mark_offsets = {}
            for part, value in self._mark_offsets(link).items():
                offset = self._valid_offset(value)
                if offset:
                    mark_offsets[part] = list(offset)
            if mark_offsets:
                entry["mark_offsets"] = mark_offsets
            if id_mapping is not None or not entry.get("id"):
                entry["id"] = ll.next_link_id(result)
            points = self._clean_points(link.get("points"))
            if points:
                entry["points"] = points
            result.append(entry)
        return result

    # ================= СВОЙСТВА СВЯЗИ =================
    def edit_selected_logic(self):
        if self.selected_logic is None or self.selected_logic not in self.logic_links:
            messagebox.showinfo(
                "Логика",
                "Выберите связь ФЛС на схеме инструментом «Выбрать» "
                "(клик по линии), затем откройте свойства.")
            return
        self.edit_logic_link(self.selected_logic)

    def edit_logic_link(self, link):
        if link is None:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Связь ФЛС — свойства")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        tk.Label(dialog, anchor="w", fg="#1f4e79",
                 font=("Arial", 9, "bold"),
                 text="{}   →   {}".format(
                     self._logic_ref_label(link.get("from")),
                     self._logic_ref_label(link.get("to")))).pack(
            fill=tk.X, padx=10, pady=(8, 0))
        tk.Label(dialog, anchor="w", fg="#777777", font=("Arial", 7),
                 text="Тип задаёт цвет и штрих линии; номер виден у начала "
                      "линии, наименование — вдоль неё").pack(
            fill=tk.X, padx=10)

        form = tk.Frame(dialog, padx=10, pady=4)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        kind = link.get("kind")
        if kind not in ll.LOGIC_LINK_ORDER:
            kind = "discrete"
        kind_var = tk.StringVar(value=kind)
        number_var = tk.StringVar(value=link.get("number", ""))
        ru_var = tk.StringVar(value=link.get("ru", ""))
        iec_var = tk.StringVar(value=link.get("iec", ""))
        id_var = tk.StringVar(value=str(link.get("id") or ""))
        continuation_var = tk.StringVar(
            value=str(link.get("continuation") or ""))
        arrow_var = tk.BooleanVar(value=bool(link.get("arrow", True)))

        tk.Label(form, text="Тип связи:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=(8, 0))
        combo = ttk.Combobox(
            form, state="readonly", width=44,
            values=["{} — {}".format(ll.link_style(key)["title"],
                                     ll.link_style(key)["full"])
                    for key in ll.LOGIC_LINK_ORDER])
        combo.current(ll.LOGIC_LINK_ORDER.index(kind))
        combo.grid(row=0, column=1, sticky="we", pady=(8, 0))

        # Образец линии: цвет и штрих выбранного типа видны до сохранения.
        sample = tk.Canvas(form, width=170, height=16, highlightthickness=0,
                           bg=ui_theme.CANVAS)
        sample.grid(row=1, column=1, sticky="w")

        def paint_sample(*_args):
            style = ll.link_style(kind_var.get())
            sample.delete("all")
            sample.create_line(2, 8, 140, 8, fill=style["color"], width=3,
                               dash=style["dash"])
            sample.create_polygon(166, 8, 150, 2, 150, 14,
                                  fill=style["color"])

        def on_kind(event=None):
            index = combo.current()
            if 0 <= index < len(ll.LOGIC_LINK_ORDER):
                kind_var.set(ll.LOGIC_LINK_ORDER[index])
                paint_sample()

        combo.bind("<<ComboboxSelected>>", on_kind)
        paint_sample()

        def add_entry(row, title, variable, width=46):
            tk.Label(form, text=title, anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            entry = tk.Entry(form, textvariable=variable, width=width)
            entry.grid(row=row, column=1, sticky="we", pady=(6, 0))
            return entry

        tk.Label(form, text="Номер / маркировка:", anchor="w").grid(
            row=2, column=0, sticky="w", pady=(6, 0))
        number_line = tk.Frame(form)
        number_line.grid(row=2, column=1, sticky="we", pady=(6, 0))
        number_line.columnconfigure(0, weight=1)
        number_entry = tk.Entry(number_line, textvariable=number_var, width=20)
        number_entry.grid(row=0, column=0, sticky="we")
        tk.Button(number_line, text="Следующий", width=12,
                  command=lambda: number_var.set(
                      ll.next_logic_number(self.logic_links))
                  ).grid(row=0, column=1, padx=(6, 0))

        add_entry(3, "Наименование (рус.):", ru_var)
        add_entry(4, "Наименование (МЭК):", iec_var)
        add_entry(5, "ID связи:", id_var)
        add_entry(6, "Продолжение после шины (ID):", continuation_var)
        tk.Checkbutton(form, text="Стрелка по направлению связи",
                       variable=arrow_var).grid(
            row=7, column=1, sticky="w", pady=(6, 0))

        result = {"ok": False, "delete": False, "kind": kind,
                  "number": "", "ru": "", "iec": "", "id": "",
                  "continuation": "", "arrow": True}

        def accept(event=None):
            # Все значения снимаем ДО destroy(): после закрытия окна виджеты
            # недоступны, и обращение к combo/entry даёт TclError.
            index = combo.current()
            result["kind"] = (ll.LOGIC_LINK_ORDER[index]
                              if 0 <= index < len(ll.LOGIC_LINK_ORDER)
                              else kind)
            result["number"] = number_var.get().strip()
            result["ru"] = ru_var.get().strip()
            result["iec"] = iec_var.get().strip()
            result["id"] = id_var.get().strip()
            result["continuation"] = continuation_var.get().strip()
            result["arrow"] = bool(arrow_var.get())
            result["ok"] = True
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        def remove():
            result["delete"] = True
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Удалить связь", width=14,
                  command=remove).pack(side=tk.LEFT)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        number_entry.focus_set()
        self._center_dialog(dialog)
        dialog.wait_window(dialog)

        if result["delete"]:
            if link in self.logic_links:
                self._push_undo()
                self.logic_links.remove(link)
                if self.selected_logic is link:
                    self.selected_logic = None
                self._mark_modified()
                self.redraw_all()
            return
        if not result["ok"]:
            return
        new_kind = result.get("kind") or link.get("kind", "discrete")
        new_number = result.get("number", "")
        new_ru = result.get("ru", "")
        new_iec = result.get("iec", "")
        new_id = result.get("id", "")
        new_continuation = result.get("continuation", "")
        new_arrow = bool(result.get("arrow", True))
        changed = (
            new_kind != link.get("kind")
            or new_number != (link.get("number") or "")
            or new_ru != (link.get("ru") or "")
            or new_iec != (link.get("iec") or "")
            or new_id != (link.get("id") or "")
            or new_continuation != (link.get("continuation") or "")
            or new_arrow != bool(link.get("arrow", True))
        )
        if not changed:
            return
        self._push_undo()
        link["kind"] = new_kind
        link["number"] = new_number
        link["ru"] = new_ru
        link["iec"] = new_iec
        link["id"] = new_id
        link["continuation"] = new_continuation
        link["arrow"] = new_arrow
        self._mark_modified()
        self.redraw_all()

    def _logic_ref_label(self, ref):
        element_id, port = self._logic_split_ref(ref)
        element = self.elements.get(element_id)
        if element is None:
            return "—"
        title = getattr(element, "title", "") or ll.ELEMENT_TYPE_TITLES.get(
            element.type, element.type)
        return "{} · {} [{}]".format(element.name, title, port)

    def assign_selected_logic_number(self):
        link = self.selected_logic
        if link is None or link not in self.logic_links:
            messagebox.showinfo(
                "Логика",
                "Выберите связь ФЛС на схеме, затем нажмите «Присвоить номер».")
            return
        self._push_undo()
        link["number"] = ll.next_logic_number(self.logic_links)
        self._mark_modified()
        self.redraw_all()

    def renumber_logic_links(self):
        """Сквозная нумерация всех связей ФЛС с подтверждением."""
        if not self.logic_links:
            messagebox.showinfo("Логика", "На схеме нет связей ФЛС.")
            return
        if not messagebox.askyesno(
                "Нумерация связей",
                "Присвоить всем связям ФЛС номера по порядку, начиная "
                "с {}?\nТекущие номера будут заменены.".format(
                    ll.LOGIC_LINK_START)):
            return
        self._push_undo()
        for index, link in enumerate(self.logic_links,
                                     start=ll.LOGIC_LINK_START):
            link["number"] = str(index)
        self._mark_modified()
        self.redraw_all()

    # ================= ОБНОВЛЕНИЕ СВЯЗЕЙ =================
    @staticmethod
    def _logic_mark_key(value):
        """Ключ маркировки для сопоставления: без пробелов и регистра."""
        return str(value or "").strip().casefold()

    def _logic_full_mark(self, link):
        """Полная маркировка связи «ФБ / Функция: Сигнал».

        Пусто, если подпись совпадает с коротким сигналом: значит связь
        не выходит из функции функционального блока и полного обозначения
        у неё нет.
        """
        label, signal = ll.link_full_label(
            self.elements, link, self._logic_split_ref)
        if label and label != signal:
            return label
        return ""

    def _update_logic_groups(self):
        """Привязка групп связей с одинаковым номером/маркировкой.

        Возвращает (привязано связей, обновлено наименований, найдено
        групп). Связи с одним номером — один сигнал, изображённый в
        разных местах схемы: первая связь с наименованием становится
        источником, остальные получают то же наименование и привязку
        (продолжение) к ней. Если номер совпадает с маркировкой элемента
        (порт, клавиша, светодиод), наименование берётся из элемента.
        Если связь выходит из функции блока, источником служит полная
        маркировка «ФБ / Функция: Сигнал» — она прописывается и в связи-
        продолжении, у которых собственного имени может не быть.
        """
        # Маркировка элемента — приоритетный источник наименования.
        marks = {}
        for element in self.elements.values():
            key = self._logic_mark_key(getattr(element, "signal_no", ""))
            if key:
                marks[key] = element

        by_id = {str(link.get("id") or "").strip(): link
                 for link in self.logic_links}

        def group_key(link, seen=None):
            """Своя маркировка или маркировка связи, продолжением которой она есть."""
            key = self._logic_mark_key(link.get("number"))
            if key:
                return key
            seen = seen or set()
            reference = str(link.get("continuation") or "").strip()
            if not reference or reference in seen:
                return ""
            seen.add(reference)
            master = by_id.get(reference)
            if master is None or master is link:
                return ""
            return group_key(master, seen)

        groups = {}
        order = []
        for link in self.logic_links:
            key = group_key(link)
            if not key:
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(link)

        bound, renamed, found = 0, 0, 0
        for key in order:
            group = groups[key]
            # Источник наименования: элемент с такой маркировкой, затем
            # полная маркировка выхода функции, затем первая связь с
            # непустым коротким наименованием.
            element = marks.get(key)
            source = group[0]
            full_mark = ""
            if element is None:
                for link in group:
                    full_mark = self._logic_full_mark(link)
                    if full_mark:
                        source = link
                        break
                if not full_mark:
                    for link in group:
                        if (str(link.get("ru") or "").strip()
                                or str(link.get("iec") or "").strip()):
                            source = link
                            break
            if element is not None:
                found += 1
                ru = (getattr(element, "signal_ru", "") or "").strip()
                iec = (getattr(element, "signal_iec", "") or "").strip()
            elif full_mark:
                found += 1
                ru, iec = full_mark, ""
            else:
                ru = str(source.get("ru") or "").strip()
                iec = str(source.get("iec") or "").strip()
                if ru or iec:
                    # Связь-источник хранит исходное наименование группы.
                    found += 1
            master_id = str(source.get("id") or "").strip()
            if len(group) > 1 and not master_id:
                master_id = ll.next_link_id(self.logic_links)
                source["id"] = master_id
            for link in group:
                if link is source and (element is None or full_mark):
                    # Источник уже несёт полную подпись: перезапись её
                    # коротким сигналом потеряла бы «ФБ / Функция: Сигнал».
                    continue
                current_ru = str(link.get("ru") or "").strip()
                current_iec = str(link.get("iec") or "").strip()
                if ru and (current_ru != ru or (iec and current_iec != iec)):
                    link["ru"] = ru
                    link["iec"] = iec
                    renamed += 1
                elif not ru and iec and current_iec != iec:
                    link["iec"] = iec
                    renamed += 1
                if len(group) > 1 and link is not source \
                        and str(link.get("continuation") or "").strip() != master_id:
                    link["continuation"] = master_id
                    bound += 1
        return bound, renamed, found

    def update_logic_links(self):
        """«Обновить связи»: привязка участков сигнала с общим номером.

        Связи с одинаковым номером/маркировкой считаются одним сигналом:
        наименования выравниваются по источнику (элемент с маркировкой,
        полная маркировка выхода функции или связь с наименованием),
        остальные связи привязываются к первой как продолжения.
        """
        if not self.logic_links:
            messagebox.showinfo("Логика", "На схеме нет связей ФЛС.")
            return
        bound, renamed, found = self._update_logic_groups()
        if not bound and not renamed:
            messagebox.showinfo(
                "Обновление связей",
                "Связей с общим номером/маркировкой не найдено.\n\n"
                "Задайте связям один номер («Номер / маркировка» в "
                "свойствах связи) — они будут привязаны и получат общее "
                "наименование, например «ЗП / 1 ступень: Срабатывание».")
            return
        self._push_undo()
        self._mark_modified()
        self.redraw_all()
        parts = ["привязано связей: {}".format(bound)] if bound else []
        if renamed:
            parts.append("обновлено наименований: {}".format(renamed))
        parts.append("групп сигналов: {}".format(found))
        messagebox.showinfo(
            "Обновление связей",
            "Готово.\n\n" + ",\n".join(parts)
            + ".\n\nПродолжения получили полную маркировку сигнала.")

    # ================= СВОЙСТВА ЭЛЕМЕНТОВ =================
    def edit_selected_logic_block(self):
        selected = [self.elements[el_id] for el_id in self.selected_elements
                    if el_id in self.elements]
        blocks = [el for el in selected if el.type == "logic_block"]
        if not blocks:
            messagebox.showinfo("Логика",
                                "Выберите функциональный блок на схеме.")
            return
        self.edit_logic_element(blocks[0])

    def edit_selected_logic_function_structure(self):
        selected = [self.elements[el_id] for el_id in self.selected_elements
                    if el_id in self.elements]
        functions = [el for el in selected if el.type == "logic_function"]
        if not functions:
            messagebox.showinfo(
                "Логика",
                "Выберите логическую функцию на схеме.")
            return
        self.edit_logic_function_structure(functions[0])

    def edit_logic_function_structure(self, element):
        """Слоты, уставки и параметры отдельной функции."""
        if element is None:
            return
        data = self._edit_logic_function_data({
            "kind": getattr(element, "kind", "AND"),
            "title": getattr(element, "title", ""),
            "name": getattr(element, "name", ""),
            "iec_name": getattr(element, "iec_name", ""),
            "LNclass": getattr(element, "LNclass", ""),
            **{part: getattr(element, part, "") for part in ll.IEC_PARTS},
            "ru": getattr(element, "signal_ru", ""),
            "iec": getattr(element, "signal_iec", ""),
            "inputs": element._input_slots(),
            "outputs": element._output_slots(),
            "settings": getattr(element, "settings", []),
            "parameters": getattr(element, "parameters", []),
        }, self.root)
        if data is None:
            return
        self._push_undo()
        element.kind = data["kind"]
        element.title = data["title"]
        element.name = data["name"]
        element.iec_name = data["iec_name"]
        element.LNclass = data["LNclass"]
        for part in ll.IEC_PARTS:
            setattr(element, part, data.get(part, ""))
        element.signal_ru = data["ru"]
        element.signal_iec = data["iec"]
        element.inputs = list(data["inputs"])
        element.outputs = list(data["outputs"])
        element.settings = list(data["settings"])
        element.parameters = list(data["parameters"])
        element.input_count = max(1, len(element.inputs))
        element.generate_ports()
        self._prune_logic_links()
        self._mark_modified()
        self.redraw_all()

    def edit_logic_element(self, element):
        if element is None:
            return
        if element.type == "logic_block":
            self.edit_logic_block(element)
        elif element.type == "logic_function":
            self.edit_logic_function_element(element)
        elif element.type == "logic_bus":
            self.edit_logic_bus(element)
        elif element.type in ("logic_port_in", "logic_port_out"):
            self.edit_logic_port(element)
        elif ll.is_schematic_type(element.type):
            self.edit_schematic_element(element)
        else:
            self.edit_logic_signal_element(element)

    # ---------- элементы принципиальной схемы шкафа ----------
    def edit_schematic_element(self, element):
        """Свойства элемента и его текстовых полей.

        Поля блока — атрибуты символа: имя, значение и координаты вывода
        в локальной системе элемента. На чертеже видны только строки этой
        таблицы; лишние поля можно удалить, нужные — добавить.
        """
        if element is None:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Элемент принципиальной схемы — свойства")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.minsize(720, 520)

        outer = tk.Frame(dialog, padx=10, pady=8)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(3, weight=1)

        base_vars = {
            "element_type": tk.StringVar(
                value=getattr(element, "element_type", "")),
            "designation": tk.StringVar(
                value=getattr(element, "designation", "")),
            "description": tk.StringVar(
                value=getattr(element, "description", "")),
            "note": tk.StringVar(value=getattr(element, "note", "")),
        }

        def add_entry(row, column, caption, variable, width=28):
            tk.Label(outer, text=caption, anchor="w").grid(
                row=row, column=column, sticky="w", pady=(4, 0))
            tk.Entry(outer, textvariable=variable, width=width).grid(
                row=row, column=column + 1, sticky="we",
                padx=(6, 12), pady=(4, 0))

        add_entry(0, 0, "Тип:", base_vars["element_type"])
        add_entry(0, 2, "Обозначение:", base_vars["designation"])
        add_entry(1, 0, "Описание:", base_vars["description"])
        add_entry(1, 2, "Примечание:", base_vars["note"])

        tk.Label(
            outer, anchor="w",
            text="Поля блока (X/Y — в локальной системе элемента, 0,0 — центр):"
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        table_frame = tk.Frame(outer, padx=2, pady=2)
        table_frame.grid(row=3, column=0, columnspan=4, sticky="nsew",
                         pady=(4, 0))
        outer.rowconfigure(3, weight=1)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            table_frame, columns=("name", "value", "x", "y"),
            show="headings", selectmode="browse", height=8)
        for key, heading, width in (
                ("name", "Поле", 140), ("value", "Значение", 260),
                ("x", "X", 90), ("y", "Y", 90)):
            tree.heading(key, text=heading)
            tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical",
                               command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        rows = {}   # iid -> {"name":..., "value":..., "x":..., "y":...}

        def add_row(data):
            iid = tree.insert("", "end", values=(
                data["name"], data["value"],
                _format_coord(data["x"]), _format_coord(data["y"])))
            rows[iid] = data

        values = getattr(element, "field_values", {}) or {}
        positions = getattr(element, "field_positions", {}) or {}
        for name, value in values.items():
            point = positions.get(name) or [0.0, 0.0]
            add_row({"name": name, "value": value,
                     "x": point[0], "y": point[1]})

        def selected():
            selection = tree.selection()
            return selection[0] if selection else None

        def ask_field(current=None):
            data = current or {"name": "", "value": "",
                               "x": 0.0, "y": 0.0}
            return self._ask_fields(
                dialog, "Поле блока",
                (("name", "Имя поля", 28),
                 ("value", "Значение", 34),
                 ("x", "X (от центра)", 18),
                 ("y", "Y (от центра)", 18)),
                {"name": data["name"], "value": data["value"],
                 "x": _format_coord(data["x"]),
                 "y": _format_coord(data["y"])})

        def name_used(name, skip=None):
            return any(iid != skip and row["name"] == name
                       for iid, row in rows.items())

        def add_field():
            data = ask_field()
            if data is None:
                return
            name = data["name"].strip()
            if not name:
                messagebox.showinfo("Поля блока", "Имя поля не задано.",
                                    parent=dialog)
                return
            if name_used(name):
                messagebox.showinfo("Поля блока",
                                    "Поле «%s» уже есть." % name,
                                    parent=dialog)
                return
            add_row({"name": name, "value": data["value"],
                     "x": _parse_coord(data["x"]),
                     "y": _parse_coord(data["y"])})

        def edit_field():
            iid = selected()
            if iid is None:
                return
            row = rows[iid]
            data = ask_field(row)
            if data is None:
                return
            name = data["name"].strip()
            if not name:
                messagebox.showinfo("Поля блока", "Имя поля не задано.",
                                    parent=dialog)
                return
            if name_used(name, skip=iid):
                messagebox.showinfo("Поля блока",
                                    "Поле «%s» уже есть." % name,
                                    parent=dialog)
                return
            row.update({"name": name, "value": data["value"],
                        "x": _parse_coord(data["x"]),
                        "y": _parse_coord(data["y"])})
            tree.item(iid, values=(row["name"], row["value"],
                                   _format_coord(row["x"]),
                                   _format_coord(row["y"])))

        def remove_field():
            for iid in tree.selection():
                tree.delete(iid)
                rows.pop(iid, None)

        buttons = tk.Frame(outer)
        buttons.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        for text, command, width in (("Добавить…", add_field, 14),
                                     ("Изменить…", edit_field, 14),
                                     ("Удалить", remove_field, 10)):
            tk.Button(buttons, text=text, width=width,
                      command=command).pack(side=tk.LEFT, padx=(0, 4))
        tree.bind("<Double-1>", lambda event: edit_field())

        result = {"ok": False}

        def accept(event=None):
            result["ok"] = True
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        footer = tk.Frame(dialog)
        footer.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(footer, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(footer, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        if not result["ok"]:
            return

        self._push_undo()
        element.element_type = base_vars["element_type"].get().strip()
        element.designation = base_vars["designation"].get().strip()
        element.description = base_vars["description"].get().strip()
        element.note = base_vars["note"].get().strip()
        element.field_values = {row["name"]: row["value"]
                                for row in rows.values()}
        element.field_positions = {row["name"]: [row["x"], row["y"]]
                                   for row in rows.values()}
        self._mark_modified()
        self.redraw_all()

    def edit_logic_port(self, element):
        title = ("Входной порт — свойства"
                 if element.type == "logic_port_in"
                 else "Выходной порт — свойства")
        self._logic_common_dialog(element, title)

    def _logic_common_dialog(self, element, title, extra_builder=None,
                             delete=True):
        """Общий диалог: название, русское и МЭК наименование, номер."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)

        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        title_var = tk.StringVar(value=getattr(element, "title", ""))
        ru_var = tk.StringVar(value=getattr(element, "signal_ru", ""))
        iec_var = tk.StringVar(value=getattr(element, "signal_iec", ""))
        number_var = tk.StringVar(value=getattr(element, "signal_no", ""))

        def add_entry(row, caption, variable, width=48):
            tk.Label(form, text=caption, anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            entry = tk.Entry(form, textvariable=variable, width=width)
            entry.grid(row=row, column=1, sticky="we", pady=(6, 0))
            return entry

        add_entry(0, "Название:", title_var)
        add_entry(1, "Сигнал (рус.):", ru_var)
        add_entry(2, "Сигнал (МЭК):", iec_var)
        add_entry(3, "Номер / маркировка:", number_var)
        row = 4
        extra_vars = {}
        if extra_builder is not None:
            row = extra_builder(form, row, extra_vars)

        result = {"ok": False, "delete": False}

        def accept(event=None):
            result["ok"] = True
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        def remove():
            result["delete"] = True
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        if delete:
            tk.Button(buttons, text="Удалить", width=10,
                      command=remove).pack(side=tk.LEFT)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)

        if result["delete"]:
            self._push_undo()
            self.delete_element(element.id)
            self._mark_modified()
            self.redraw_all()
            return
        if not result["ok"]:
            return
        self._push_undo()
        old_ports = None
        if getattr(element, "type", "") == "logic_bus":
            old_ports = {name: (port["x"], port["y"])
                         for name, port in element.ports.items()}
        element.title = title_var.get().strip()
        element.signal_ru = ru_var.get().strip()
        element.signal_iec = iec_var.get().strip()
        element.signal_no = number_var.get().strip()
        if extra_builder is not None:
            self._apply_logic_extra(element, extra_vars)
        element.generate_ports()
        if old_ports is not None:
            self._rebind_logic_bus_links(element, old_ports)
        self._prune_logic_links()
        self._mark_modified()
        self.redraw_all()

    def edit_logic_signal_element(self, element):
        self._logic_common_dialog(
            element, "Функциональная клавиша / светодиод — свойства")

    def edit_logic_bus(self, element):
        length_var = tk.StringVar(value=str(int(getattr(element, "length", 480))))
        color_var = tk.StringVar(value=getattr(element, "color", "#00acc1"))
        description_var = tk.StringVar(
            value=getattr(element, "description", ""))
        fields_var = tk.BooleanVar(
            value=bool(getattr(element, "show_fields", False)))

        def extra(form, row, variables):
            variables["length"] = length_var
            variables["color"] = color_var
            variables["description"] = description_var
            variables["show_fields"] = fields_var
            tk.Label(form, text="Длина шины:", anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            tk.Entry(form, textvariable=length_var, width=12).grid(
                row=row, column=1, sticky="w", pady=(6, 0))
            tk.Label(form, text="Цвет:", anchor="w").grid(
                row=row + 1, column=0, sticky="w", pady=(6, 0))
            tk.Entry(form, textvariable=color_var, width=12).grid(
                row=row + 1, column=1, sticky="w", pady=(6, 0))
            tk.Label(form, text="Описание:", anchor="w").grid(
                row=row + 2, column=0, sticky="w", pady=(6, 0))
            tk.Entry(form, textvariable=description_var, width=42).grid(
                row=row + 2, column=1, sticky="we", pady=(6, 0))
            tk.Checkbutton(form, text="Выводить поля шины",
                           variable=fields_var, anchor="w").grid(
                row=row + 3, column=0, columnspan=2, sticky="w", pady=(6, 0))
            return row + 4

        self._logic_common_dialog(element, "Шина ФЛС — свойства", extra)

    def edit_logic_function_element(self, element):
        kind_var = tk.StringVar(value=getattr(element, "kind", "AND"))
        inputs_var = tk.StringVar(value=str(getattr(element, "input_count", 2)))

        def extra(form, row, variables):
            variables["kind"] = kind_var
            variables["inputs"] = inputs_var
            tk.Label(form, text="Вид узла:", anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            combo = ttk.Combobox(
                form, state="readonly", width=32,
                values=["{} — {}".format(key, value[1])
                        for key, value in ll.FUNCTION_KINDS.items()])
            keys = list(ll.FUNCTION_KINDS)
            if kind_var.get() in keys:
                combo.current(keys.index(kind_var.get()))
            combo.grid(row=row, column=1, sticky="w", pady=(6, 0))
            combo.bind("<<ComboboxSelected>>",
                       lambda event: kind_var.set(keys[combo.current()]))
            tk.Label(form, text="Число входов:", anchor="w").grid(
                row=row + 1, column=0, sticky="w", pady=(6, 0))
            tk.Spinbox(form, from_=1, to=12, textvariable=inputs_var,
                       width=6).grid(row=row + 1, column=1, sticky="w",
                                     pady=(6, 0))
            return row + 2

        self._logic_common_dialog(element, "Логический узел — свойства", extra)

    def _apply_logic_extra(self, element, variables):
        """Применение дополнительных полей после общего диалога."""
        if "length" in variables and hasattr(element, "length"):
            try:
                element.length = max(40.0, float(variables["length"].get()))
            except (TypeError, ValueError):
                pass
        if "color" in variables and hasattr(element, "color"):
            color = variables["color"].get().strip() or "#00acc1"
            try:
                self.root.winfo_rgb(color)
            except tk.TclError:
                color = "#00acc1"
            element.color = color
        if "kind" in variables and hasattr(element, "kind"):
            element.kind = variables["kind"].get() or "AND"
        if "inputs" in variables and hasattr(element, "input_count"):
            try:
                element.input_count = max(1, int(variables["inputs"].get()))
            except (TypeError, ValueError):
                pass
        if "description" in variables and hasattr(element, "description"):
            element.description = variables["description"].get().strip()
        if "show_fields" in variables and hasattr(element, "show_fields"):
            element.show_fields = bool(variables["show_fields"].get())

    # ---------- функциональный блок ----------
    def edit_logic_block(self, element):
        """Окно вставки и правки функционального блока.

        Правки применяются по кнопке «Сохранить»: значения снимаются с
        виджетов ДО их закрытия — после ``destroy()`` обращение к Text/Entry
        даёт TclError, из-за чего прежняя версия теряла все изменения.
        """
        if element is None:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Функциональный блок — свойства")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.minsize(860, 640)

        title_var = tk.StringVar(value=getattr(element, "title", ""))
        designation_var = tk.StringVar(
            value=getattr(element, "designation", ""))
        try:
            width_value = int(getattr(element, "width",
                                       ll.LogicBlock.MIN_WIDTH))
        except (TypeError, ValueError):
            width_value = int(ll.LogicBlock.MIN_WIDTH)
        width_var = tk.StringVar(value=str(width_value))
        # Поля FunctionBlock из structure2.xml.
        main_var = tk.BooleanVar(
            value=bool(getattr(element, "isMainFunction", False)))
        its_var = tk.BooleanVar(
            value=bool(getattr(element, "isInITS", False)))
        iec_var = tk.StringVar(value=getattr(element, "iec_name", ""))
        iec_part_vars = {
            part: tk.StringVar(value=getattr(element, part, ""))
            for part in ll.IEC_PARTS}
        path_var = tk.StringVar(value=getattr(element, "russian_path", ""))
        corp_var = tk.StringVar(value=getattr(element, "corp_prof_name", ""))
        # Принадлежность блока стандарту (шкаф / комплект / ИЭУ).
        cabinet_var = tk.StringVar(value=getattr(element, "cabinet", ""))
        kit_var = tk.StringVar(value=getattr(element, "kit", ""))
        ied_var = tk.StringVar(value=getattr(element, "ied", ""))

        outer = tk.Frame(dialog, padx=10, pady=8)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        # ---- шапка: название, обозначение, ширина ----
        header = tk.Frame(outer)
        header.grid(row=0, column=0, sticky="we")
        header.columnconfigure(1, weight=1)
        header.columnconfigure(3, weight=1)
        tk.Label(header, text="Название блока:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        tk.Entry(header, textvariable=title_var).grid(
            row=0, column=1, sticky="we", padx=(6, 12), pady=(0, 4))
        tk.Label(header, text="Обозначение:", anchor="w").grid(
            row=0, column=2, sticky="w", pady=(0, 4))
        tk.Entry(header, textvariable=designation_var, width=18).grid(
            row=0, column=3, sticky="we", padx=(6, 0), pady=(0, 4))
        tk.Label(header, text="Ширина, мир. ед.:", anchor="w").grid(
            row=1, column=0, sticky="w")
        tk.Spinbox(header, from_=int(ll.LogicBlock.MIN_WIDTH), to=1600,
                   increment=20, textvariable=width_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(6, 12))
        tk.Label(header, text="Ширина не меньше ширины по содержимому",
                 fg=ui_theme.TEXT_MUTED, anchor="w").grid(
            row=1, column=2, columnspan=2, sticky="w")
        tk.Label(header, text="МЭК 61850:", anchor="w").grid(
            row=2, column=0, sticky="w", pady=(4, 0))
        tk.Entry(header, textvariable=iec_var, width=24).grid(
            row=2, column=1, sticky="we", padx=(6, 12), pady=(4, 0))
        tk.Label(header, text="Путь (рус.):", anchor="w").grid(
            row=2, column=2, sticky="w", pady=(4, 0))
        tk.Entry(header, textvariable=path_var, width=18).grid(
            row=2, column=3, sticky="we", padx=(6, 0), pady=(4, 0))
        tk.Label(header, text="Корпоративное имя:", anchor="w").grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        tk.Entry(header, textvariable=corp_var, width=24).grid(
            row=3, column=1, sticky="we", padx=(6, 12), pady=(4, 0))
        flags = tk.Frame(header)
        flags.grid(row=3, column=2, columnspan=2, sticky="w", pady=(4, 0))
        tk.Checkbutton(flags, text="Основная функция",
                       variable=main_var).pack(side=tk.LEFT)
        tk.Checkbutton(flags, text="В ИТС",
                       variable=its_var).pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(header, text="Принадлежность:", anchor="w").grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        source = tk.Frame(header)
        source.grid(row=4, column=1, columnspan=3, sticky="we", pady=(4, 0))
        for label, variable, width in (
                ("Шкаф", cabinet_var, 22),
                ("Комплект", kit_var, 12),
                ("ИЭУ", ied_var, 12)):
            tk.Label(source, text=label, anchor="w").pack(side=tk.LEFT)
            tk.Entry(source, textvariable=variable, width=width).pack(
                side=tk.LEFT, padx=(4, 10))
        iec_parts_frame = tk.Frame(header)
        iec_parts_frame.grid(row=5, column=1, columnspan=3, sticky="we",
                             pady=(4, 0))
        tk.Label(header, text="МЭК по частям:", anchor="w").grid(
            row=5, column=0, sticky="w", pady=(4, 0))
        for part in ll.IEC_PARTS:
            tk.Label(iec_parts_frame, text=part, anchor="w").pack(side=tk.LEFT)
            tk.Entry(iec_parts_frame, textvariable=iec_part_vars[part],
                     width=10).pack(side=tk.LEFT, padx=(4, 10))

        # ---- предпросмотр блока ----
        preview = tk.Canvas(outer, height=170, bg=ui_theme.CANVAS,
                            highlightthickness=1,
                            highlightbackground=ui_theme.BORDER)
        preview.grid(row=1, column=0, sticky="we", pady=(8, 6))

        tk.Label(outer, anchor="w", fg=ui_theme.TEXT_MUTED,
                 text="Блок — контейнер: все входы и выходы находятся на "
                      "функциях. Вход функции — слева, выход — справа; "
                      "двойной клик по строке меняет функцию."
                 ).grid(row=2, column=0, sticky="we")

        # ---- таблица функций: единственные владельцы входов и выходов ----
        notebook = ttk.Notebook(outer)
        notebook.grid(row=3, column=0, sticky="nsew", pady=(6, 0))

        def make_table(parent, columns, headings, widths, display=None):
            frame = tk.Frame(parent, padx=6, pady=6)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=columns, show="headings",
                                selectmode="browse", height=7)
            for name, heading, width in zip(columns, headings, widths):
                tree.heading(name, text=heading)
                tree.column(name, width=width, anchor="w")
            if display:
                tree.configure(displaycolumns=display)
            scroll = ttk.Scrollbar(frame, orient="vertical",
                                   command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            tree.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            buttons = tk.Frame(frame)
            buttons.grid(row=1, column=0, columnspan=2, sticky="w",
                         pady=(6, 0))
            return frame, tree, buttons

        def add_button(parent, text, command, width=12):
            tk.Button(parent, text=text, width=width,
                      command=command).pack(side=tk.LEFT, padx=(0, 4))

        functions_tab, functions_tree, functions_buttons = make_table(
            notebook,
            ("kind", "title", "inputs", "outputs", "signal", "key", "ru",
             "iec"),
            ("Вид узла", "Название", "Входов", "Выходов", "Сигнал", "",
             "", ""),
            (130, 200, 70, 70, 200, 90, 160, 160),
            display=("kind", "title", "inputs", "outputs", "signal"))
        notebook.add(functions_tab, text="Функции")

        function_store = {}
        function_seq = [0]

        def function_values(function):
            kind = (function.get("kind") or "AND").upper()
            if kind not in ll.FUNCTION_KINDS:
                kind = "CUSTOM"
            return (
                ll.FUNCTION_KINDS[kind][1],
                function.get("title") or "",
                len(function.get("inputs") or []),
                len(function.get("outputs") or []),
                ll.signal_text(function.get("ru"), function.get("iec")),
                kind,
                function.get("ru") or "",
                function.get("iec") or "")

        def fill_functions(functions):
            functions_tree.delete(*functions_tree.get_children())
            function_store.clear()
            for function in functions or []:
                data = ll.normalize_function(function)
                function_seq[0] += 1
                iid = "f{}".format(function_seq[0])
                function_store[iid] = data
                functions_tree.insert("", "end", iid=iid,
                                      values=function_values(data))

        fill_functions(getattr(element, "functions", []))

        # ---- чтение таблиц в данные модели ----
        def collect_functions():
            functions = []
            for item in functions_tree.get_children():
                data = function_store.get(item)
                if data is None:
                    # Строка, добавленная в таблицу напрямую (импорт/тест).
                    values = list(functions_tree.item(item, "values"))
                    values += [""] * (8 - len(values))
                    kind = str(values[5]).strip().upper() or "AND"
                    try:
                        count = max(1, int(values[2]))
                    except (TypeError, ValueError):
                        count = 2
                    try:
                        out_count = max(1, int(values[3]))
                    except (TypeError, ValueError):
                        out_count = 1
                    data = {
                        "kind": kind,
                        "title": values[1],
                        "ru": values[6],
                        "iec": values[7],
                        "inputs": count,
                        "outputs": out_count,
                    }
                functions.append(ll.normalize_function(data))
            return functions

        def snapshot():
            return {
                "title": title_var.get().strip(),
                "designation": designation_var.get().strip(),
                "width": width_var.get().strip(),
                "functions": collect_functions(),
            }

        def refresh_preview(*_args):
            self._refresh_block_preview(preview, snapshot())

        title_var.trace_add("write", refresh_preview)
        designation_var.trace_add("write", refresh_preview)
        width_var.trace_add("write", refresh_preview)
        preview.bind("<Configure>", lambda event: refresh_preview())

        # ---- действия с таблицами ----
        def remove_selected(tree):
            for item in tree.selection():
                tree.delete(item)
            refresh_preview()

        def move_selected(tree, offset):
            selection = tree.selection()
            if not selection:
                return
            item = selection[0]
            index = tree.index(item) + offset
            if index < 0:
                return
            tree.move(item, "", index)
            tree.selection_set(item)
            refresh_preview()

        def store_function(data):
            function_seq[0] += 1
            iid = "f{}".format(function_seq[0])
            function_store[iid] = ll.normalize_function(data)
            return iid, function_values(function_store[iid])

        def add_function():
            data = self._edit_logic_function_data(None, dialog)
            if data is None:
                return
            iid, values = store_function(data)
            functions_tree.insert("", "end", iid=iid, values=values)
            refresh_preview()

        def edit_function():
            selection = functions_tree.selection()
            if not selection:
                return
            iid = selection[0]
            current = function_store.get(iid) or {}
            data = self._edit_logic_function_data(current, dialog)
            if data is None:
                return
            function_store[iid] = ll.normalize_function(data)
            functions_tree.item(iid, values=function_values(
                function_store[iid]))
            refresh_preview()

        for text, command, width in (
                ("Добавить…", add_function, 14),
                ("Изменить…", edit_function, 14),
                ("Удалить", lambda: remove_selected(functions_tree), 10),
                ("Вверх", lambda: move_selected(functions_tree, -1), 8),
                ("Вниз", lambda: move_selected(functions_tree, 1), 8)):
            add_button(functions_buttons, text, command, width)

        functions_tree.bind("<Double-1>", lambda event: edit_function())

        # ---- кнопки окна ----
        result = {"ok": False, "delete": False}

        def accept(event=None):
            result["title"] = title_var.get().strip()
            result["designation"] = designation_var.get().strip()
            result["width"] = width_var.get().strip()
            result["functions"] = collect_functions()
            result["isMainFunction"] = bool(main_var.get())
            result["isInITS"] = bool(its_var.get())
            result["iec_name"] = iec_var.get().strip()
            result.update({part: iec_part_vars[part].get().strip()
                           for part in ll.IEC_PARTS})
            result["russian_path"] = path_var.get().strip()
            result["corp_prof_name"] = corp_var.get().strip()
            result["cabinet"] = cabinet_var.get().strip()
            result["kit"] = kit_var.get().strip()
            result["ied"] = ied_var.get().strip()
            result["ok"] = True
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        def remove():
            result["delete"] = True
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Удалить блок", width=14,
                  command=remove).pack(side=tk.LEFT)
        dialog.bind("<Escape>", cancel)

        dialog.update_idletasks()
        refresh_preview()
        self._center_dialog(dialog)
        dialog.wait_window(dialog)

        if result["delete"]:
            self._push_undo()
            self.delete_element(element.id)
            self._mark_modified()
            self.redraw_all()
            return
        if not result["ok"]:
            return
        self._push_undo()
        element.title = result["title"]
        element.designation = result["designation"]
        element.isMainFunction = result["isMainFunction"]
        element.isInITS = result["isInITS"]
        element.iec_name = result["iec_name"]
        for part in ll.IEC_PARTS:
            setattr(element, part, result[part])
        element.russian_path = result["russian_path"]
        element.corp_prof_name = result["corp_prof_name"]
        element.cabinet = result["cabinet"]
        element.kit = result["kit"]
        element.ied = result["ied"]
        try:
            element.width = max(ll.LogicBlock.MIN_WIDTH,
                                float(result["width"] or 0))
        except (TypeError, ValueError):
            pass
        element.functions = result["functions"]
        element.generate_ports()
        before = len(self.logic_links)
        self._prune_logic_links()
        removed = before - len(self.logic_links)
        self._mark_modified()
        self.redraw_all()
        if removed:
            messagebox.showinfo(
                "Функциональный блок",
                "Связей с удалёнными портами удалено: {}.".format(removed))

    def _refresh_block_preview(self, canvas, snapshot):
        """Предпросмотр блока в окне свойств: те же линии, что на схеме."""
        canvas.delete("all")
        block = ll.LogicBlock("preview", 0.0, 0.0)
        block.name = ""
        block.title = snapshot.get("title") or "Функциональный блок"
        block.designation = snapshot.get("designation") or ""
        try:
            block.width = max(ll.LogicBlock.MIN_WIDTH,
                              float(snapshot.get("width") or 0))
        except (TypeError, ValueError):
            block.width = ll.LogicBlock.MIN_WIDTH
        block.functions = [dict(item) for item in
                           snapshot.get("functions") or []]
        block.generate_ports()
        layout = block._layout()
        pad = 12.0
        width = max(canvas.winfo_width(), 240)
        height = max(canvas.winfo_height(), 120)
        scale = min((width - 2 * pad) / max(layout["width"], 1.0),
                    (height - 2 * pad) / max(layout["height"], 1.0), 1.0)
        scale = max(scale, 0.05)
        offset_x = (pad + (width - 2 * pad - layout["width"] * scale) / 2.0
                    - layout["x1"] * scale)
        offset_y = (pad + (height - 2 * pad - layout["height"] * scale) / 2.0
                    - layout["y1"] * scale)
        block.draw(canvas, scale, offset_x, offset_y)

    def _ask_fields(self, parent, title, fields, values=None, choices=None):
        """Небольшой модальный диалог: список полей → словарь значений.

        ``choices`` — словарь ``поле → список значений`` для выпадающих списков.
        """
        values = dict(values or {})
        choices = choices or {}
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.transient(parent)
        dialog.resizable(False, False)
        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        variables = {}
        row = 0
        for key, caption, width in fields:
            tk.Label(form, text=caption, anchor="w").grid(
                row=row, column=0, sticky="w", pady=(4, 0))
            variable = tk.StringVar(value=str(values.get(key, "") or ""))
            variables[key] = variable
            if key in choices:
                options = list(choices[key])
                combo = ttk.Combobox(form, state="readonly", width=width,
                                     values=options)
                current = variables[key].get()
                if current in options:
                    combo.current(options.index(current))
                combo.grid(row=row, column=1, sticky="we", pady=(4, 0))
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda event, c=combo, v=variable, os=options:
                    v.set(os[c.current()]))
            elif key == "type":
                keys = list(ll.SLOT_TYPE_ORDER)
                combo = ttk.Combobox(
                    form, state="readonly", width=width,
                    values=[ll.SLOT_TYPES[key_] for key_ in keys])
                current = variables[key].get()
                if current in keys:
                    combo.current(keys.index(current))
                combo.grid(row=row, column=1, sticky="we", pady=(4, 0))
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda event, c=combo, v=variable, ks=keys:
                    v.set(ks[c.current()]))
            else:
                tk.Entry(form, textvariable=variable, width=width).grid(
                    row=row, column=1, sticky="we", pady=(4, 0))
            row += 1
        result = {"data": None}

        def accept(event=None):
            result["data"] = {key: variable.get().strip()
                              for key, variable in variables.items()}
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="ОК", width=10,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        if parent is not None:
            try:
                parent.grab_set()
            except tk.TclError:
                pass
        return result["data"]

    def _edit_logic_function_data(self, data, parent):
        """Функция ФЛС: вид, слоты, уставки и параметры.

        Уставки и параметры (программные переключатели) находятся внутри
        функции и на схеме не отображаются — их правят здесь.
        """
        dialog = tk.Toplevel(parent)
        dialog.title("Функция — свойства")
        dialog.transient(parent)
        dialog.resizable(True, True)
        dialog.minsize(760, 560)

        data = ll.normalize_function(data or {})
        kind_var = tk.StringVar(value=data.get("kind") or "AND")
        title_var = tk.StringVar(value=data.get("title") or "")
        name_var = tk.StringVar(value=data.get("name") or "")
        iec_name_var = tk.StringVar(value=data.get("iec_name") or "")
        lnclass_var = tk.StringVar(value=data.get("LNclass") or "")
        iec_part_vars = {
            part: tk.StringVar(value=data.get(part) or "")
            for part in ll.IEC_PARTS}
        ru_var = tk.StringVar(value=data.get("ru") or "")
        iec_var = tk.StringVar(value=data.get("iec") or "")

        outer = tk.Frame(dialog, padx=10, pady=8)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(3, weight=1)

        tk.Label(outer, text="Вид узла:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=(4, 0))
        keys = list(ll.FUNCTION_KINDS)
        combo = ttk.Combobox(
            outer, state="readonly", width=32,
            values=["{} — {}".format(key, ll.FUNCTION_KINDS[key][1])
                    for key in keys])
        if kind_var.get() in keys:
            combo.current(keys.index(kind_var.get()))
        combo.grid(row=0, column=1, columnspan=3, sticky="we",
                   pady=(4, 0))
        combo.bind("<<ComboboxSelected>>",
                   lambda event: kind_var.set(keys[combo.current()]))

        def add_entry(row, column, caption, variable, width=30):
            tk.Label(outer, text=caption, anchor="w").grid(
                row=row, column=column, sticky="w", pady=(4, 0))
            tk.Entry(outer, textvariable=variable, width=width).grid(
                row=row, column=column + 1, sticky="we",
                padx=(6, 12), pady=(4, 0))

        add_entry(1, 0, "Название:", title_var)
        add_entry(1, 2, "Имя функции:", name_var)
        add_entry(2, 0, "МЭК 61850:", iec_name_var)
        add_entry(2, 2, "LNclass:", lnclass_var)
        add_entry(3, 0, "Сигнал (рус.):", ru_var)
        add_entry(3, 2, "Сигнал (МЭК):", iec_var)
        for index, part in enumerate(ll.IEC_PARTS):
            add_entry(4, (index // 2) * 2, part + ":", iec_part_vars[part], 20)

        notebook = ttk.Notebook(outer)
        notebook.grid(row=5, column=0, columnspan=4, sticky="nsew",
                      pady=(8, 0))
        outer.rowconfigure(5, weight=1)

        def make_table(parent, columns, headings, widths):
            frame = tk.Frame(parent, padx=6, pady=6)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=columns, show="headings",
                                selectmode="browse", height=6)
            for name, heading, width in zip(columns, headings, widths):
                tree.heading(name, text=heading)
                tree.column(name, width=width, anchor="w")
            scroll = ttk.Scrollbar(frame, orient="vertical",
                                   command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            tree.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            buttons = tk.Frame(frame)
            buttons.grid(row=1, column=0, columnspan=2, sticky="w",
                         pady=(6, 0))
            return frame, tree, buttons

        def add_button(parent, text, command, width=12):
            tk.Button(parent, text=text, width=width,
                      command=command).pack(side=tk.LEFT, padx=(0, 4))

        inputs_tab, inputs_tree, inputs_buttons = make_table(
            notebook, ("name", "desc", "iec", "type"),
            ("Наименование", "Описание", "МЭК", "Тип слота"),
            (190, 240, 160, 220))
        notebook.add(inputs_tab, text="Входы")
        outputs_tab, outputs_tree, outputs_buttons = make_table(
            notebook, ("name", "desc", "iec", "type"),
            ("Наименование", "Описание", "МЭК", "Тип слота"),
            (190, 240, 160, 220))
        notebook.add(outputs_tab, text="Выходы")
        settings_tab, settings_tree, settings_buttons = make_table(
            notebook,
            ("name", "min", "max", "step", "unit", "default", "desc"),
            ("Уставка", "Мин.", "Макс.", "Шаг", "Ед.", "По умолч.",
             "Описание"),
            (150, 70, 70, 60, 60, 90, 220))
        notebook.add(settings_tab, text="Уставки")
        parameters_tab, parameters_tree, parameters_buttons = make_table(
            notebook, ("name", "value", "default", "desc"),
            ("Параметр", "Значение", "По умолч.", "Описание"),
            (150, 180, 110, 260))
        notebook.add(parameters_tab, text="Параметры")

        # У каждой таблицы свои iid: автономера Tkinter повторяются, и общий
        # словарь затирал бы входы данными выходов.
        slot_store = {}   # table -> iid -> исходный слот (LD/LN/DO/DA)

        def fill_slots(tree, slots):
            tree.delete(*tree.get_children())
            store = slot_store.setdefault(tree, {})
            store.clear()
            for slot in slots:
                iid = tree.insert("", "end", values=(
                    slot.get("name", ""), slot.get("description", ""),
                    slot.get("iec_name", ""),
                    ll.slot_type_title(slot.get("type", ""))))
                store[iid] = dict(slot)

        def fill_settings(tree, settings):
            tree.delete(*tree.get_children())
            for setting in settings:
                tree.insert("", "end", values=(
                    setting.get("name", ""), setting.get("min_value", ""),
                    setting.get("max_value", ""), setting.get("step", ""),
                    setting.get("unit", ""), setting.get("default_value", ""),
                    setting.get("description", "")))

        def fill_parameters(tree, parameters):
            tree.delete(*tree.get_children())
            for parameter in parameters:
                tree.insert("", "end", values=(
                    parameter.get("name", ""), parameter.get("value", ""),
                    parameter.get("default_value", ""),
                    parameter.get("description", "")))

        fill_slots(inputs_tree, data.get("inputs") or [])
        fill_slots(outputs_tree, data.get("outputs") or [])
        fill_settings(settings_tree, data.get("settings") or [])
        fill_parameters(parameters_tree, data.get("parameters") or [])

        def selected_values(tree):
            selection = tree.selection()
            return list(tree.item(selection[0], "values")) if selection \
                else None

        def slot_type_key(title):
            for key, value in ll.SLOT_TYPES.items():
                if value == title:
                    return key
            return ll.DEFAULT_SLOT_TYPE

        def add_slot(tree, direction):
            values = self._ask_fields(
                dialog, "Вход функции" if direction == "in" else "Выход функции",
                (("name", "Наименование", 34),
                 ("description", "Описание", 34),
                 ("iec_name", "МЭК", 34),
                 ("type", "Тип слота", 34)),
                {"type": ll.DEFAULT_SLOT_TYPE})
            if values is None:
                return
            slot = ll.new_slot(direction, values["name"],
                               values["description"], values["iec_name"],
                               values["type"])
            iid = tree.insert("", "end", values=(
                slot["name"], slot["description"], slot["iec_name"],
                ll.slot_type_title(slot["type"])))
            slot_store.setdefault(tree, {})[iid] = slot

        def edit_slot(tree, direction):
            current = selected_values(tree)
            if current is None:
                return
            current += [""] * (4 - len(current))
            values = self._ask_fields(
                dialog, "Слот функции",
                (("name", "Наименование", 34),
                 ("description", "Описание", 34),
                 ("iec_name", "МЭК", 34),
                 ("type", "Тип слота", 34)),
                {"name": current[0], "description": current[1],
                 "iec_name": current[2], "type": slot_type_key(current[3])})
            if values is None:
                return
            iid = tree.selection()[0]
            tree.item(iid, values=(
                values["name"], values["description"], values["iec_name"],
                ll.slot_type_title(values["type"])))
            if iid in slot_store.get(tree, {}):
                slot_store[tree][iid].update({
                    "name": values["name"],
                    "description": values["description"],
                    "iec_name": values["iec_name"],
                    "type": values["type"],
                })

        def add_setting():
            values = self._ask_fields(
                dialog, "Уставка",
                (("name", "Наименование", 34),
                 ("min_value", "Минимум", 34),
                 ("max_value", "Максимум", 34),
                 ("step", "Шаг", 34),
                 ("unit", "Единица", 34),
                 ("default_value", "По умолчанию", 34),
                 ("description", "Описание", 34)))
            if values is None:
                return
            settings_tree.insert("", "end", values=(
                values["name"], values["min_value"], values["max_value"],
                values["step"], values["unit"], values["default_value"],
                values["description"]))

        def edit_setting():
            current = selected_values(settings_tree)
            if current is None:
                return
            current += [""] * (7 - len(current))
            keys = ("name", "min_value", "max_value", "step", "unit",
                    "default_value", "description")
            labels = ("Наименование", "Минимум", "Максимум", "Шаг",
                      "Единица", "По умолчанию", "Описание")
            values = self._ask_fields(
                dialog, "Уставка",
                tuple((key, label, 34)
                      for key, label in zip(keys, labels)),
                dict(zip(keys, current)))
            if values is None:
                return
            settings_tree.item(settings_tree.selection()[0], values=tuple(
                values[key] for key in keys))

        def add_parameter():
            values = self._ask_fields(
                dialog, "Параметр (программный переключатель)",
                (("name", "Наименование", 34),
                 ("value", "Значение / состояния", 34),
                 ("default_value", "По умолчанию", 34),
                 ("description", "Описание", 34)))
            if values is None:
                return
            parameters_tree.insert("", "end", values=(
                values["name"], values["value"], values["default_value"],
                values["description"]))

        def edit_parameter():
            current = selected_values(parameters_tree)
            if current is None:
                return
            current += [""] * (4 - len(current))
            keys = ("name", "value", "default_value", "description")
            labels = ("Наименование", "Значение / состояния",
                      "По умолчанию", "Описание")
            values = self._ask_fields(
                dialog, "Параметр",
                tuple((key, label, 34)
                      for key, label in zip(keys, labels)),
                dict(zip(keys, current)))
            if values is None:
                return
            parameters_tree.item(parameters_tree.selection()[0], values=tuple(
                values[key] for key in keys))

        def remove_selected(tree):
            for item in tree.selection():
                tree.delete(item)

        def move_selected(tree, offset):
            selection = tree.selection()
            if not selection:
                return
            item = selection[0]
            index = tree.index(item) + offset
            if index < 0:
                return
            tree.move(item, "", index)
            tree.selection_set(item)

        for tree, buttons, direction in (
                (inputs_tree, inputs_buttons, "in"),
                (outputs_tree, outputs_buttons, "out")):
            add_button(buttons, "Добавить…",
                       lambda t=tree, d=direction: add_slot(t, d), 14)
            add_button(buttons, "Изменить…",
                       lambda t=tree, d=direction: edit_slot(t, d), 14)
            add_button(buttons, "Удалить",
                       lambda t=tree: remove_selected(t), 10)
            add_button(buttons, "Вверх",
                       lambda t=tree: move_selected(t, -1), 8)
            add_button(buttons, "Вниз",
                       lambda t=tree: move_selected(t, 1), 8)
            tree.bind("<Double-1>",
                      lambda event, t=tree, d=direction: edit_slot(t, d))

        for text, command in (("Добавить…", add_setting),
                              ("Изменить…", edit_setting),
                              ("Удалить",
                               lambda: remove_selected(settings_tree)),
                              ("Вверх",
                               lambda: move_selected(settings_tree, -1)),
                              ("Вниз",
                               lambda: move_selected(settings_tree, 1))):
            add_button(settings_buttons, text, command)
        settings_tree.bind("<Double-1>", lambda event: edit_setting())

        for text, command in (("Добавить…", add_parameter),
                              ("Изменить…", edit_parameter),
                              ("Удалить",
                               lambda: remove_selected(parameters_tree)),
                              ("Вверх",
                               lambda: move_selected(parameters_tree, -1)),
                              ("Вниз",
                               lambda: move_selected(parameters_tree, 1))):
            add_button(parameters_buttons, text, command)
        parameters_tree.bind("<Double-1>",
                             lambda event: edit_parameter())

        result = {"data": None}

        def collect_slots(tree, direction):
            slots = []
            for item in tree.get_children():
                values = list(tree.item(item, "values"))
                values += [""] * (4 - len(values))
                slot = dict(slot_store.get(tree, {}).get(item) or {})
                slot.update({
                    "name": values[0], "description": values[1],
                    "iec_name": values[2], "type": slot_type_key(values[3]),
                })
                slots.append(ll.normalize_slots([slot], direction)[0])
            return slots

        def collect_settings():
            settings = []
            for item in settings_tree.get_children():
                values = list(settings_tree.item(item, "values"))
                values += [""] * (7 - len(values))
                settings.append({
                    "name": values[0], "min_value": values[1],
                    "max_value": values[2], "step": values[3],
                    "unit": values[4], "default_value": values[5],
                    "description": values[6],
                })
            return settings

        def collect_parameters():
            parameters = []
            for item in parameters_tree.get_children():
                values = list(parameters_tree.item(item, "values"))
                values += [""] * (4 - len(values))
                parameters.append({
                    "name": values[0], "value": values[1],
                    "default_value": values[2], "description": values[3],
                })
            return parameters

        def accept(event=None):
            result["data"] = {
                "kind": kind_var.get() or "AND",
                "title": title_var.get().strip(),
                "name": name_var.get().strip(),
                "iec_name": iec_name_var.get().strip(),
                "LNclass": lnclass_var.get().strip(),
                **{part: iec_part_vars[part].get().strip()
                   for part in ll.IEC_PARTS},
                "ru": ru_var.get().strip(),
                "iec": iec_var.get().strip(),
                "inputs": collect_slots(inputs_tree, "in"),
                "outputs": collect_slots(outputs_tree, "out"),
                "settings": collect_settings(),
                "parameters": collect_parameters(),
            }
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        return result["data"]
