# -*- coding: utf-8 -*-
"""Редактор функционально-логических схем (ФЛС) устройства.

Методы этого миксина подключаются к ``main.CircuitEditor`` и добавляют
вкладку «Логика»: элементы ФЛС, цветные связи с номером и наименованием
сигнала, свойства функциональных блоков и вставку логических узлов.

Схема хранится в том же JSON, что и первичная: элементы получают поле
``logic``, связи — отдельный список ``logic_links``.
"""

from __future__ import annotations

import copy
import math

import tkinter as tk
from tkinter import messagebox, ttk

import logic_library as ll
import ui_theme


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


def _ri_logic_link(canvas):
    canvas.create_line(3, 24, 20, 8, width=2, fill="#2e7d32")
    canvas.create_line(20, 8, 29, 8, width=2, fill="#2e7d32")
    canvas.create_polygon(29, 8, 24, 5, 24, 11, fill="#2e7d32")


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
                    ("Функция", "logic_function", _ri_logic_function)):
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
                    _ri_logic_link, 88)
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

        self._ribbon_group(page, "Связи", build_links)

        self._ribbon_group(page, "Свойства", lambda row: [
            self._ribbon_button(row, "Свойства связи",
                                self.edit_selected_logic, _ri_logic_link,
                                96).pack(side=tk.LEFT),
            self._ribbon_button(row, "Свойства блока",
                                self.edit_selected_logic_block,
                                _ri_logic_block, 96).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Нумерация", lambda row: [
            self._ribbon_button(row, "Присвоить номер",
                                self.assign_selected_logic_number,
                                _ri_logic_link, 104).pack(side=tk.LEFT),
        ])
        return page

    def set_logic_link_kind(self, kind):
        self.logic_link_kind = kind
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
        for link, box in self._logic_label_boxes:
            if box and box[0] - 2 <= sx <= box[2] + 2 \
                    and box[1] - 2 <= sy <= box[3] + 2:
                return link
        return None

    def _logic_point_at(self, sx, sy):
        link = self.selected_logic
        if link is None or link not in self.logic_links:
            return None
        radius = max(5.0, 6.0 * self.zoom)
        for index, point in enumerate(link.get("points") or []):
            px, py = self.world_to_screen(point[0], point[1])
            if math.hypot(sx - px, sy - py) <= radius:
                return ("link", link, index)
        return None

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
                        "логического узла или отводу шины.")
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
        self._push_undo()
        link = {
            "from": first_ref,
            "to": second_ref,
            "kind": self.logic_link_kind,
            "number": ll.next_logic_number(self.logic_links),
            "ru": "",
            "iec": "",
            "arrow": True,
        }
        self.logic_links.append(link)
        return link

    def _logic_link_label_text(self, link):
        """Подпись сигнала на линии; не дублирует подпись клавиши/светодиода."""
        text = ll.signal_text(link.get("ru"), link.get("iec"))
        if not text:
            return ""
        link_ru = (link.get("ru") or "").strip()
        link_iec = (link.get("iec") or "").strip()
        for ref in (link.get("from"), link.get("to")):
            element_id, _port = self._logic_split_ref(ref)
            element = self.elements.get(element_id)
            if element is None:
                continue
            if element.type in ("logic_key", "logic_led", "logic_function"):
                own_ru = (getattr(element, "signal_ru", "") or "").strip()
                own_iec = (getattr(element, "signal_iec", "") or "").strip()
                if own_ru and link_ru == own_ru \
                        and (not link_iec or link_iec == own_iec):
                    return ""
                own = ll.signal_text(own_ru, own_iec)
                if own and own == text:
                    return ""
        return text

    def _logic_link_number(self, link):
        """Номер на линии; не повторяет маркировку подключённого элемента."""
        number = (link.get("number") or "").strip()
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

    def _logic_annotations(self, prepared):
        """Номера и подписи связей: [(link, (x, y, box) | None)] без наложений."""
        numbers, labels, occupied = [], [], []
        for link, route in prepared:
            number = self._logic_link_number(link)
            anchor = self._logic_number_anchor(route, number, occupied) \
                if number else None
            if anchor is not None:
                occupied.append(anchor[2])
            numbers.append((link, anchor))
        for link, route in prepared:
            text = self._logic_link_label_text(link)
            anchor = self._logic_label_anchor(route, text, occupied) \
                if text else None
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
        for link, anchor in numbers:
            if anchor is None:
                continue
            x, y, box = anchor
            sx, sy = self.world_to_screen(x, y)
            bx1, by1, bx2, by2 = self._logic_screen_box(box)
            self.canvas.create_rectangle(
                bx1 - 1, by1 - 1, bx2 + 1, by2 + 1,
                fill="white", outline="", tags="logic_label")
            self.canvas.create_text(
                sx, sy, text=self._logic_link_number(link),
                fill=ll.link_style(link.get("kind"))["color"],
                font=font, anchor="center", tags="logic_label")
            self._logic_label_boxes.append((link, self._logic_screen_box(box)))
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
                fill=ll.link_style(link.get("kind"))["color"],
                font=font, anchor="center", justify="center",
                tags="logic_label")
            self._logic_label_boxes.append((link, self._logic_screen_box(box)))

        if self._logic_start is not None:
            point = self._logic_ref_point(
                "{}#{}".format(*self._logic_start))
            if point is not None:
                px, py = self.world_to_screen(*point)
                r = max(4.0, 6.0 * self.zoom)
                self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                        outline="red", width=2,
                                        tags="logic_start")

    def _draw_logic_points(self):
        link = self.selected_logic
        if link is None or link not in self.logic_links:
            return
        radius = max(3.0, 4.0 * self.zoom)
        style = ll.link_style(link.get("kind"))
        for point in link.get("points") or []:
            px, py = self.world_to_screen(point[0], point[1])
            self.canvas.create_rectangle(
                px - radius, py - radius, px + radius, py + radius,
                fill="white", outline=style["color"],
                width=max(1, int(1.5 * self.zoom)),
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
                canvas.create_line(*coords, fill=color, width=1,
                                   dash=style["dash"])
                self._export_arrowhead(canvas, prev_x, prev_y,
                                       last_x, last_y, fill=color)
            else:
                coords = []
                for x, y in route:
                    coords.extend((x, y))
                canvas.create_line(*coords, fill=color, width=1,
                                   dash=style["dash"])

        for link, anchor in numbers:
            if anchor is None:
                continue
            x, y, box = anchor
            canvas.create_rectangle(box[0], box[1], box[2], box[3],
                                    fill="white", outline="")
            canvas.create_text(x, y, text=self._logic_link_number(link),
                               fill=ll.link_style(link.get("kind"))["color"],
                               font=("Arial", 6), anchor="center")
        for link, anchor in labels:
            if anchor is None:
                continue
            x, y, box = anchor
            canvas.create_rectangle(box[0], box[1], box[2], box[3],
                                    fill="white", outline="")
            canvas.create_text(x, y, text=self._logic_link_label_text(link),
                               fill=ll.link_style(link.get("kind"))["color"],
                               font=("Arial", 6), anchor="center",
                               justify="center")

    # ================= СЕРИАЛИЗАЦИЯ =================
    def _logic_link_record(self, link):
        record = {
            "from": link.get("from", ""),
            "to": link.get("to", ""),
            "kind": link.get("kind", "discrete"),
        }
        for field in ("number", "ru", "iec"):
            value = link.get(field)
            if isinstance(value, str) and value.strip():
                record[field] = value.strip()
        if link.get("arrow") is False:
            record["arrow"] = False
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
            for field in ("number", "ru", "iec"):
                value = link.get(field)
                if isinstance(value, str) and value.strip():
                    entry[field] = value.strip()
            if link.get("arrow") is False:
                entry["arrow"] = False
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
                 text="Номер/маркировка и наименование сигнала по-русски и по МЭК"
                 ).pack(fill=tk.X, padx=10)

        form = tk.Frame(dialog, padx=10, pady=4)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        kind_var = tk.StringVar(value=link.get("kind", "discrete"))
        number_var = tk.StringVar(value=link.get("number", ""))
        ru_var = tk.StringVar(value=link.get("ru", ""))
        iec_var = tk.StringVar(value=link.get("iec", ""))
        arrow_var = tk.BooleanVar(value=bool(link.get("arrow", True)))

        tk.Label(form, text="Тип связи:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=(8, 0))
        combo = ttk.Combobox(
            form, state="readonly", width=44,
            values=["{} — {}".format(kind, ll.link_style(kind)["full"])
                    for kind in ll.LOGIC_LINK_ORDER])
        combo.current(ll.LOGIC_LINK_ORDER.index(kind_var.get())
                      if kind_var.get() in ll.LOGIC_LINK_ORDER else 1)
        combo.grid(row=0, column=1, sticky="we", pady=(8, 0))

        def add_entry(row, title, variable, width=46):
            tk.Label(form, text=title, anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            entry = tk.Entry(form, textvariable=variable, width=width)
            entry.grid(row=row, column=1, sticky="we", pady=(6, 0))
            return entry

        number_line = tk.Frame(form)
        number_line.grid(row=1, column=1, sticky="we", pady=(6, 0))
        number_line.columnconfigure(0, weight=1)
        number_entry = tk.Entry(number_line, textvariable=number_var, width=20)
        number_entry.grid(row=0, column=0, sticky="we")
        tk.Button(number_line, text="Следующий", width=12,
                  command=lambda: number_var.set(
                      ll.next_logic_number(self.logic_links))
                  ).grid(row=0, column=1, padx=(6, 0))
        tk.Label(form, text="Номер / маркировка:", anchor="w").grid(
            row=1, column=0, sticky="w", pady=(6, 0))

        add_entry(2, "Наименование (рус.):", ru_var)
        add_entry(3, "Наименование (МЭК):", iec_var)
        tk.Checkbutton(form, text="Стрелка по направлению связи",
                       variable=arrow_var).grid(
            row=4, column=1, sticky="w", pady=(6, 0))

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
                self.redraw_all()
            return
        if not result["ok"]:
            return
        kind = ll.LOGIC_LINK_ORDER[combo.current()] \
            if combo.current() >= 0 else link.get("kind", "discrete")
        changed = (
            kind != link.get("kind")
            or number_var.get().strip() != (link.get("number") or "")
            or ru_var.get().strip() != (link.get("ru") or "")
            or iec_var.get().strip() != (link.get("iec") or "")
            or bool(arrow_var.get()) != bool(link.get("arrow", True))
        )
        if not changed:
            return
        self._push_undo()
        link["kind"] = kind
        link["number"] = number_var.get().strip()
        link["ru"] = ru_var.get().strip()
        link["iec"] = iec_var.get().strip()
        link["arrow"] = bool(arrow_var.get())
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
        self.redraw_all()

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

    def edit_logic_element(self, element):
        if element is None:
            return
        if element.type == "logic_block":
            self.edit_logic_block(element)
        elif element.type == "logic_function":
            self.edit_logic_function_element(element)
        elif element.type == "logic_bus":
            self.edit_logic_bus(element)
        else:
            self.edit_logic_signal_element(element)

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
            self.redraw_all()
            return
        if not result["ok"]:
            return
        self._push_undo()
        element.title = title_var.get().strip()
        element.signal_ru = ru_var.get().strip()
        element.signal_iec = iec_var.get().strip()
        element.signal_no = number_var.get().strip()
        if extra_builder is not None:
            self._apply_logic_extra(element, extra_vars)
        element.generate_ports()
        self._prune_logic_links()
        self.redraw_all()

    def edit_logic_signal_element(self, element):
        self._logic_common_dialog(
            element, "Функциональная клавиша / светодиод — свойства")

    def edit_logic_bus(self, element):
        length_var = tk.StringVar(value=str(int(getattr(element, "length", 480))))
        color_var = tk.StringVar(value=getattr(element, "color", "#00acc1"))

        def extra(form, row, variables):
            variables["length"] = length_var
            variables["color"] = color_var
            tk.Label(form, text="Длина шины:", anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            tk.Entry(form, textvariable=length_var, width=12).grid(
                row=row, column=1, sticky="w", pady=(6, 0))
            tk.Label(form, text="Цвет:", anchor="w").grid(
                row=row + 1, column=0, sticky="w", pady=(6, 0))
            tk.Entry(form, textvariable=color_var, width=12).grid(
                row=row + 1, column=1, sticky="w", pady=(6, 0))
            return row + 2

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

    # ---------- функциональный блок ----------
    def edit_logic_block(self, element):
        dialog = tk.Toplevel(self.root)
        dialog.title("Функциональный блок — свойства")
        dialog.transient(self.root)
        dialog.resizable(True, True)

        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        title_var = tk.StringVar(value=getattr(element, "title", ""))
        designation_var = tk.StringVar(
            value=getattr(element, "designation", ""))
        width_var = tk.StringVar(value=str(int(getattr(element, "width", 360))))

        def add_entry(row, caption, variable, width=48):
            tk.Label(form, text=caption, anchor="w").grid(
                row=row, column=0, sticky="nw", pady=(6, 0))
            entry = tk.Entry(form, textvariable=variable, width=width)
            entry.grid(row=row, column=1, sticky="we", pady=(6, 0))
            return entry

        add_entry(0, "Название блока:", title_var)
        add_entry(1, "Обозначение:", designation_var)
        add_entry(2, "Ширина (мир. ед.):", width_var)

        tk.Label(form, text="Входные сигналы (коды, по одному в строке):",
                 anchor="w").grid(row=3, column=0, columnspan=2,
                                  sticky="w", pady=(10, 0))
        inputs_text = tk.Text(form, width=60, height=5, wrap="none")
        inputs_text.grid(row=4, column=0, columnspan=2, sticky="we")
        inputs_text.insert("1.0", "\n".join(getattr(element, "inputs", [])))

        tk.Label(form,
                 text="Сигналы блока: направление | русское | МЭК "
                      "(направление: out/выход, in/вход, both, none)",
                 anchor="w").grid(row=5, column=0, columnspan=2,
                                  sticky="w", pady=(10, 0))
        rows_text = tk.Text(form, width=60, height=6, wrap="none")
        rows_text.grid(row=6, column=0, columnspan=2, sticky="we")
        rows_text.insert("1.0", self._format_block_rows(
            getattr(element, "rows", [])))

        tk.Label(form, text="Вставленные логические узлы:", anchor="w").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        functions_frame = tk.Frame(form)
        functions_frame.grid(row=8, column=0, columnspan=2, sticky="we")
        functions_list = tk.Listbox(functions_frame, height=5, width=52)
        functions_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        functions = copy.deepcopy(getattr(element, "functions", []))
        self._refresh_block_functions(functions_list, functions)

        def add_function():
            data = self._edit_logic_function_data(None, dialog)
            if data is not None:
                functions.append(data)
                self._refresh_block_functions(functions_list, functions)

        def edit_function():
            selection = functions_list.curselection()
            if not selection:
                return
            index = selection[0]
            data = self._edit_logic_function_data(functions[index], dialog)
            if data is not None:
                functions[index] = data
                self._refresh_block_functions(functions_list, functions)

        def remove_function():
            selection = functions_list.curselection()
            if selection:
                del functions[selection[0]]
                self._refresh_block_functions(functions_list, functions)

        function_buttons = tk.Frame(form)
        function_buttons.grid(row=9, column=0, columnspan=2, sticky="w",
                              pady=(4, 0))
        tk.Button(function_buttons, text="Добавить…", width=14,
                  command=add_function).pack(side=tk.LEFT)
        tk.Button(function_buttons, text="Изменить…", width=14,
                  command=edit_function).pack(side=tk.LEFT, padx=(4, 0))
        tk.Button(function_buttons, text="Удалить", width=10,
                  command=remove_function).pack(side=tk.LEFT, padx=(4, 0))

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
        tk.Button(buttons, text="Удалить блок", width=14,
                  command=remove).pack(side=tk.LEFT)
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)

        if result["delete"]:
            self._push_undo()
            self.delete_element(element.id)
            self.redraw_all()
            return
        if not result["ok"]:
            return
        self._push_undo()
        element.title = title_var.get().strip()
        element.designation = designation_var.get().strip()
        try:
            element.width = max(element.MIN_WIDTH, float(width_var.get()))
        except (TypeError, ValueError):
            pass
        element.inputs = [line.strip() for line in
                          inputs_text.get("1.0", "end").splitlines()
                          if line.strip()]
        element.rows = self._parse_block_rows(
            rows_text.get("1.0", "end"))
        element.functions = functions
        element.generate_ports()
        self._prune_logic_links()
        self.redraw_all()

    @staticmethod
    def _format_block_rows(rows):
        lines = []
        for row in rows or []:
            lines.append("{} | {} | {}".format(
                row.get("dir") or "out",
                row.get("ru") or "",
                row.get("iec") or ""))
        return "\n".join(lines)

    @staticmethod
    def _parse_block_rows(text):
        rows = []
        for line in str(text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) == 1:
                direction, ru, iec = "out", parts[0], ""
            elif len(parts) == 2:
                direction, ru, iec = parts[0] or "out", parts[1], ""
            else:
                direction, ru, iec = parts[0] or "out", parts[1], parts[2]
            direction = ll.SIGNAL_DIRECTION_ALIASES.get(
                direction.casefold(), direction)
            if direction not in ll.SIGNAL_DIRECTIONS:
                # Строка без направления: «русское | МЭК»
                ru, iec = direction, ru
                direction = "out"
            rows.append({"dir": direction, "ru": ru, "iec": iec})
        return rows

    @staticmethod
    def _refresh_block_functions(listbox, functions):
        listbox.delete(0, tk.END)
        for function in functions:
            kind = (function.get("kind") or "AND").upper()
            kind_name = ll.FUNCTION_KINDS.get(kind, ll.FUNCTION_KINDS["CUSTOM"])[1]
            title = (function.get("title") or "").strip() or kind_name
            listbox.insert(tk.END, "{} — {}".format(kind_name, title))

    def _edit_logic_function_data(self, data, parent):
        """Диалог логического узла для вставки в блок."""
        dialog = tk.Toplevel(parent)
        dialog.title("Логический узел")
        dialog.transient(parent)
        dialog.resizable(False, False)

        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        data = data or {}
        kind_var = tk.StringVar(value=(data.get("kind") or "AND").upper())
        title_var = tk.StringVar(value=data.get("title") or "")
        ru_var = tk.StringVar(value=data.get("ru") or "")
        iec_var = tk.StringVar(value=data.get("iec") or "")
        inputs_var = tk.StringVar(value=str(data.get("inputs") or 2))

        tk.Label(form, text="Вид узла:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=(6, 0))
        keys = list(ll.FUNCTION_KINDS)
        combo = ttk.Combobox(
            form, state="readonly", width=32,
            values=["{} — {}".format(key, ll.FUNCTION_KINDS[key][1])
                    for key in keys])
        if kind_var.get() in keys:
            combo.current(keys.index(kind_var.get()))
        combo.grid(row=0, column=1, sticky="we", pady=(6, 0))
        combo.bind("<<ComboboxSelected>>",
                   lambda event: kind_var.set(keys[combo.current()]))

        def add_entry(row, caption, variable, width=40):
            tk.Label(form, text=caption, anchor="w").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            tk.Entry(form, textvariable=variable, width=width).grid(
                row=row, column=1, sticky="we", pady=(6, 0))

        add_entry(1, "Название узла:", title_var)
        add_entry(2, "Сигнал (рус.):", ru_var)
        add_entry(3, "Сигнал (МЭК):", iec_var)
        tk.Label(form, text="Число входов:", anchor="w").grid(
            row=4, column=0, sticky="w", pady=(6, 0))
        tk.Spinbox(form, from_=1, to=12, textvariable=inputs_var,
                   width=6).grid(row=4, column=1, sticky="w", pady=(6, 0))

        result = {"data": None}

        def accept(event=None):
            try:
                count = max(1, int(inputs_var.get()))
            except (TypeError, ValueError):
                count = 2
            result["data"] = {
                "kind": kind_var.get() or "AND",
                "title": title_var.get().strip(),
                "ru": ru_var.get().strip(),
                "iec": iec_var.get().strip(),
                "inputs": count,
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
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        return result["data"]
