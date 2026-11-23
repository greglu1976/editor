# -*- coding: utf-8 -*-
"""Элементы принципиальной схемы шкафа.

Условные обозначения извлечены из ``mount_elements/Чертеж1.txt`` (DWG/DXF)
скриптом ``tools/dxf_to_schematic.py`` и лежат в ``schematic_symbols.py``.
Здесь они подключены к общему механизму редактора: порты, связи, JSON,
палитра и экспорт работают так же, как для элементов ФЛС и монтажа.
"""

from __future__ import annotations

import copy
import json
import math
import os

import apppaths
from library import Component, rotate_point
from schematic_symbols import SYMBOLS

#: Правки библиотеки, сделанные пользователем: координаты полей символов.
#: Файл лежит в папке данных (``db``), поэтому переживает перезапуск и
#: не теряется при обновлении ``schematic_symbols.py``.
OVERRIDES_FILE = "schematic_symbols.json"

COMPONENT_TYPES = tuple(SYMBOLS)
PREFIX_BY_TYPE = {key: spec["prefix"] for key, spec in SYMBOLS.items()}
TYPE_TITLES = {key: spec["title"] for key, spec in SYMBOLS.items()}
PALETTE_ITEMS = [(spec["title"], key) for key, spec in SYMBOLS.items()]

#: Поля элемента принципиальной схемы.
FIELDS = ("type", "designation", "description", "note",
          "field_values", "field_positions")


def is_schematic_type(comp_type):
    """Относится ли тип к элементам принципиальной схемы шкафа."""
    return str(comp_type).split(":", 1)[0] in COMPONENT_TYPES


class SchematicElement(Component):
    """Условное обозначение, нарисованное по геометрии из DXF."""

    def __init__(self, comp_id, x, y, grid_size=20, comp_type=""):
        super().__init__(comp_id, x, y, grid_size)
        self.type = comp_type if comp_type in SYMBOLS else COMPONENT_TYPES[0]
        self.spec = SYMBOLS[self.type]
        self.rotation = 0
        # «Тип» — название элемента, «Обозначение» — позиционное обозначение.
        self.element_type = self.spec["title"]
        self.designation = ""
        self.description = ""
        self.note = ""
        # Подписи-атрибуты символа (как атрибуты блока в AutoCAD):
        # значение и локальная позиция каждой подписи хранятся в элементе.
        spec_fields = self.spec.get("fields") or {}
        self.field_values = {name: name for name in spec_fields}
        self.field_positions = {
            name: [float(field.get("x", 0.0)), float(field.get("y", 0.0))]
            for name, field in spec_fields.items()}
        self._field_bboxes = {}
        self.generate_ports()

    @property
    def title(self):
        return self.element_type

    @title.setter
    def title(self, value):
        self.element_type = str(value or "")

    def generate_ports(self):
        ports = {}
        for name, spec in self.spec["ports"].items():
            dx, dy = rotate_point(spec["x"], spec["y"], self.rotation)
            ports[name] = {
                "x": self.x + dx, "y": self.y + dy,
                "direction": spec.get("direction", "in"),
                "node_id": "N_%s_%s" % (self.id, name),
            }
        self.ports = ports

    def get_bounding_box(self):
        # spec['bbox'] уже локальные координаты; _rotated_bbox сам добавляет
        # центр элемента. Передача мировых координат давала двойной сдвиг,
        # из-за чего новый элемент не выделялся кликом по нему.
        return self._rotated_bbox(self.spec["bbox"])

    def _world_point(self, dx, dy):
        rx, ry = rotate_point(dx, dy, self.rotation)
        return self.x + rx, self.y + ry

    @staticmethod
    def _to_screen(point, zoom, offset_x, offset_y):
        return (point[0] * zoom + offset_x, point[1] * zoom + offset_y)

    def _arc_points(self, prim, steps=24):
        _kind, cx, cy, radius, start, end = prim
        if end < start:
            end += 360
        result = []
        for index in range(steps + 1):
            angle = math.radians(start + (end - start) * index / steps)
            local_x = cx + radius * math.cos(angle)
            local_y = cy + radius * math.sin(angle)
            result.append(self._world_point(local_x, local_y))
        return result

    def draw(self, canvas, zoom, offset_x, offset_y):
        width = max(1, int(1.4 * zoom))
        self._field_bboxes = {}
        for prim in self.spec["primitives"]:
            kind = prim[0]
            if kind == "line":
                _, x1, y1, x2, y2 = prim
                points = [self._world_point(x1, y1),
                          self._world_point(x2, y2)]
            elif kind == "poly":
                points = [self._world_point(px, py) for px, py in prim[1]]
                if prim[2]:
                    points.append(points[0])
            elif kind == "arc":
                points = self._arc_points(prim)
            elif kind == "circle":
                _, cx, cy, radius = prim
                world = self._world_point(cx, cy)
                sx, sy = self._to_screen(world, zoom, offset_x, offset_y)
                r = max(1.0, radius * zoom)
                canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                   fill="", outline="black", width=width)
                continue
            elif kind == "text":
                _, text, tx, ty = prim
                world = self._world_point(tx, ty)
                sx, sy = self._to_screen(world, zoom, offset_x, offset_y)
                canvas.create_text(sx, sy, text=text, anchor="center",
                                   font=("Arial", max(1, int(9 * zoom))),
                                   fill="black")
                continue
            else:
                continue
            screen = [self._to_screen(p, zoom, offset_x, offset_y)
                      for p in points]
            coords = [value for point in screen for value in point]
            canvas.create_line(*coords, fill="black", width=width)

        # Атрибуты символа: рисуем только те поля, которые есть в свойствах
        # элемента; значение и позицию можно править и перетаскивать мышкой.
        for name, value in self.field_values.items():
            text = str(value or "").strip()
            if not text:
                continue
            position = self.field_positions.get(name)
            if position is None:
                continue
            world = self._world_point(position[0], position[1])
            sx, sy = self._to_screen(world, zoom, offset_x, offset_y)
            item = canvas.create_text(
                sx, sy, text=text, anchor="center",
                font=("Arial", max(1, int(9 * zoom))), fill="black",
                tags="element_label")
            try:
                self._field_bboxes[name] = canvas.bbox(item)
            except Exception:
                pass

        text = str(getattr(self, "designation", "") or "").strip()
        if text:
            bx1, _by1, bx2, by2 = self.get_bounding_box()
            self._label_text(canvas, zoom, offset_x, offset_y,
                             (bx1 + bx2) / 2.0, by2 + 8,
                             anchor="center", size=9)
        self._draw_label(canvas, zoom, offset_x, offset_y)


def create_component(comp_type, comp_id, x, y, grid_size=20):
    if not is_schematic_type(comp_type):
        raise ValueError("Неизвестный элемент принципиальной схемы: %s"
                         % comp_type)
    return SchematicElement(comp_id, x, y, grid_size, comp_type)


def element_payload(el):
    payload = {}
    for field in FIELDS:
        attribute = "element_type" if field == "type" else field
        if hasattr(el, attribute):
            payload[field] = copy.deepcopy(getattr(el, attribute))
    return payload


def restore_element(el, payload):
    if not isinstance(payload, dict):
        return
    for field in FIELDS:
        attribute = "element_type" if field == "type" else field
        if field in payload:
            setattr(el, attribute, copy.deepcopy(payload[field]))
    el.element_type = str(el.element_type or TYPE_TITLES.get(el.type, ""))
    for field in ("designation", "description", "note"):
        if not isinstance(getattr(el, field, ""), str):
            setattr(el, field, str(getattr(el, field, "")))
    el.spec = SYMBOLS[el.type]
    spec_fields = el.spec.get("fields") or {}
    raw_values = payload.get("field_values")
    if isinstance(raw_values, dict):
        values = {str(name): str(value or "")
                  for name, value in raw_values.items()}
    else:
        values = {name: name for name in spec_fields}
    raw_positions = payload.get("field_positions")
    positions = raw_positions if isinstance(raw_positions, dict) else {}
    # Старые схемы хранили смещение от позиции в описании символа.
    raw_offsets = payload.get("field_offsets")
    offsets = raw_offsets if isinstance(raw_offsets, dict) else {}
    el.field_values = values
    el.field_positions = {}
    for name in values:
        point = _point(positions.get(name))
        if point is None:
            base = spec_fields.get(name) or {}
            offset = _point(offsets.get(name)) or [0.0, 0.0]
            point = [float(base.get("x", 0.0)) + offset[0],
                     float(base.get("y", 0.0)) + offset[1]]
        el.field_positions[name] = point
    el.generate_ports()


def _point(value):
    """[x, y] из JSON или None, если значение не похоже на точку."""
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError, IndexError):
        return None


def read_overrides():
    """Правки библиотеки из папки данных (пустой словарь, если файла нет)."""
    path = apppaths.data_path(OVERRIDES_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_overrides(symbols, overrides):
    """Наложить правки пользователя на таблицу символов.

    Сейчас правятся только поля: их имена и координаты вывода. Геометрия
    символа остаётся из ``schematic_symbols.py``.
    """
    for comp_type, data in overrides.items():
        spec = symbols.get(comp_type)
        if spec is None or not isinstance(data, dict):
            continue
        fields = data.get("fields")
        if not isinstance(fields, dict):
            continue
        clean = {}
        for name, value in fields.items():
            point = _point(value)
            if point is not None:
                clean[str(name)] = {"x": point[0], "y": point[1]}
        spec["fields"] = clean


def save_symbol_fields(comp_type, positions):
    """Сохранить поля символа в библиотеку и вернуть путь к файлу правок.

    ``positions`` — отображение «имя поля → [X, Y]» в локальной системе
    элемента. Новые элементы этого типа сразу получают сохранённые поля;
    уже нарисованные элементы не меняются.
    """
    if comp_type not in SYMBOLS:
        raise ValueError("Неизвестный элемент: %s" % comp_type)
    fields = {}
    for name, value in positions.items():
        name = str(name).strip()
        point = _point(value)
        if name and point is not None:
            fields[name] = [point[0], point[1]]

    overrides = read_overrides()
    overrides[comp_type] = {"fields": fields}
    path = apppaths.data_path(OVERRIDES_FILE)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(overrides, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)

    SYMBOLS[comp_type]["fields"] = {
        name: {"x": point[0], "y": point[1]}
        for name, point in fields.items()}
    return path


def copy_element_fields(source, target):
    for field in FIELDS:
        attribute = "element_type" if field == "type" else field
        if hasattr(source, attribute):
            setattr(target, attribute, copy.deepcopy(getattr(source, attribute)))
    target.spec = SYMBOLS[target.type]
    values = getattr(source, "field_values", {}) or {}
    positions = getattr(source, "field_positions", {}) or {}
    target.field_values = {str(name): str(value or "")
                           for name, value in values.items()}
    target.field_positions = {
        name: _point(positions.get(name)) or [0.0, 0.0]
        for name in target.field_values}
    target.generate_ports()


def draw_palette_icon(canvas, comp_type, size=46):
    spec = SYMBOLS.get(comp_type)
    if spec is None:
        return
    x1, y1, x2, y2 = spec["bbox"]
    span_x = max(1.0, x2 - x1)
    span_y = max(1.0, y2 - y1)
    scale = min((size - 12) / span_x, (size - 12) / span_y)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    center = size / 2.0

    def point(px, py):
        return (center + (px - cx) * scale, center + (py - cy) * scale)

    for prim in spec["primitives"]:
        kind = prim[0]
        if kind == "line":
            points = [point(prim[1], prim[2]), point(prim[3], prim[4])]
        elif kind == "poly":
            points = [point(px, py) for px, py in prim[1]]
            if prim[2]:
                points.append(points[0])
        elif kind == "arc":
            _, ax, ay, radius, start, end = prim
            if end < start:
                end += 360
            points = []
            for index in range(17):
                angle = math.radians(start + (end - start) * index / 16.0)
                points.append(point(ax + radius * math.cos(angle),
                                    ay + radius * math.sin(angle)))
        elif kind == "circle":
            _, ax, ay, radius = prim
            sx, sy = point(ax, ay)
            r = max(1.0, radius * scale)
            canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                               fill="", outline="black", width=1)
            continue
        else:
            continue
        canvas.create_line(*[value for p in points for value in p],
                           fill="black", width=1)


# Правки, сохранённые из окна свойств, действуют и после перезапуска.
apply_overrides(SYMBOLS, read_overrides())
