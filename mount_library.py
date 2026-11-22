# -*- coding: utf-8 -*-
"""Элементы монтажных и принципиальных схем шкафов.

Модуль добавляет к редактору четыре объекта, которые ставятся на схему
так же, как элементы ФЛС (через общий механизм
``logic_library``/``scheme_io``):

* ``mount_terminal``   — клемма: проходная, с размыкателем или
                         измерительная;
* ``mount_test_block`` — испытательный (тестовый) блок 4+1 или 6+1;
* ``mount_switch``     — переключатель на два или три положения;
* ``mount_ied``        — ИЭУ прямоугольником с полями и внутренними
                         портами/функциями.

У каждого элемента есть базовые поля «Тип» (вид элемента),
«Обозначение» и «Описание» плюс свои поля (номер, назначение,
подключение, примечание).

ИЭУ хранит порты и функции полностью: функции из каталога
FunctionalBlocks можно перенести на монтажную схему без повторного ввода,
а порты — привязать к клеммам линиями монтажной цепи.
"""

from __future__ import annotations

import copy

import ea_model
from library import Component

COMPONENT_TYPES = ("mount_terminal", "mount_test_block", "mount_switch",
                   "mount_ied")

PREFIX_BY_TYPE = {
    "mount_terminal": "X",
    "mount_test_block": "BI",
    "mount_switch": "SA",
    "mount_ied": "IEU",
}

TYPE_TITLES = {
    "mount_terminal": "Клемма",
    "mount_test_block": "Испытательный блок",
    "mount_switch": "Переключатель",
    "mount_ied": "ИЭУ",
}

PALETTE_ITEMS = [
    ("Клемма проходная", "mount_terminal:feed"),
    ("Клемма с размыкателем", "mount_terminal:disconnect"),
    ("Клемма измерительная", "mount_terminal:measure"),
    ("Испытательный блок 4+1", "mount_test_block:4+1"),
    ("Испытательный блок 6+1", "mount_test_block:6+1"),
    ("Переключатель 2 положения", "mount_switch:2"),
    ("Переключатель 3 положения", "mount_switch:3"),
    ("ИЭУ (прямоугольник)", "mount_ied"),
]

TERMINAL_VARIANTS = {
    "feed": "Проходная",
    "measure": "Измерительная",
    "disconnect": "С размыкателем",
}
TERMINAL_VARIANT_BY_TITLE = {
    title: key for key, title in TERMINAL_VARIANTS.items()
}

TEST_BLOCK_VARIANTS = {
    "4+1": 4,
    "6+1": 6,
}

#: Переключатель: число положений подвижного контакта.
SWITCH_VARIANTS = {
    "2": "Два положения",
    "3": "Три положения",
}
SWITCH_VARIANT_BY_TITLE = {
    title: key for key, title in SWITCH_VARIANTS.items()
}

FIELDS = {
    "mount_terminal": ("variant", "number", "designation", "description",
                       "purpose", "connection", "note"),
    "mount_test_block": ("variant", "designation", "description", "purpose",
                         "note"),
    "mount_switch": ("variant", "designation", "description", "purpose",
                     "note"),
    "mount_ied": ("designation", "description", "type", "cabinet", "kit",
                  "ied", "ports", "functions"),
}


def _text(value):
    return "" if value is None else str(value)


def is_mount_type(comp_type):
    return comp_type in COMPONENT_TYPES


def split_palette_type(value):
    """\"mount_terminal:measure\" → (тип, вариант)."""
    text = _text(value)
    if ":" not in text:
        return text, ""
    kind, variant = text.split(":", 1)
    return kind, variant.strip()


def normalize_port(port):
    port = port if isinstance(port, dict) else {}
    direction = _text(port.get("direction")).strip().lower()
    if direction not in ("in", "out"):
        direction = "in"
    return {
        "name": _text(port.get("name")).strip(),
        "description": _text(port.get("description")).strip(),
        "iec": _text(port.get("iec") or port.get("iec_name")).strip(),
        "direction": direction,
        "terminal": _text(port.get("terminal")).strip(),
        "function": _text(port.get("function")).strip(),
    }


def normalize_ports(values):
    if not isinstance(values, (list, tuple)):
        return []
    return [normalize_port(item) for item in values if isinstance(item, dict)]


def new_port(**values):
    return normalize_port(values)


def normalize_function(function):
    """Функция ИЭУ на монтажной схеме: данные structure2 + источник."""
    result = ea_model.normalize_function(function)
    source = function if isinstance(function, dict) else {}
    for key in ("block", "cabinet", "kit", "ied", "source"):
        value = _text(source.get(key)).strip()
        if value:
            result[key] = value
    return result


def normalize_functions(values):
    if not isinstance(values, (list, tuple)):
        return []
    return [normalize_function(item) for item in values
            if isinstance(item, dict)]


def functions_from_entry(entry):
    """Функции FunctionalBlockEntry для размещения внутри ИЭУ."""
    entry = entry if isinstance(entry, dict) else {}
    source = {
        "block": entry.get("name") or entry.get("russian_path") or "",
        "cabinet": entry.get("cabinet") or "",
        "kit": entry.get("kit") or "",
        "ied": entry.get("ied") or "",
        "source": "functional_blocks",
    }
    functions = entry.get("functions")
    if not isinstance(functions, list):
        functions = ea_model.block_functions(entry)
    result = []
    for function in functions or []:
        if not isinstance(function, dict):
            continue
        item = normalize_function(function)
        item.update(source)
        result.append(item)
    return result


def function_label(function):
    function = function if isinstance(function, dict) else {}
    name = _text(function.get("name") or function.get("title")).strip()
    iec = _text(function.get("iec_name")).strip()
    if name and iec and iec != name:
        return "%s (%s)" % (name, iec)
    return name or iec


class MountElement(Component):
    """Общая база монтажных элементов."""

    def _rect(self):
        return (self.x - 20, self.y - 20, self.x + 20, self.y + 20)

    def draw(self, canvas, zoom, offset_x, offset_y):
        pass


class MountTerminal(MountElement):
    """Клемма: проходная, с размыкателем или измерительная."""

    WIDTH = 42
    HEIGHT = 84

    def __init__(self, comp_id, x, y, grid_size=20, variant="feed"):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "mount_terminal"
        self.variant = variant if variant in TERMINAL_VARIANTS else "feed"
        self.number = ""
        self.designation = ""
        self.description = ""
        self.purpose = ""
        self.connection = ""
        self.note = ""
        self.generate_ports()

    def _draw_description(self, canvas, zoom, sx, sy):
        text = _text(getattr(self, "description", "")).strip()
        if text:
            canvas.create_text(sx, sy, text=text,
                               font=("Arial", max(7, int(7 * zoom))),
                               fill="#697586")

    def _rect(self):
        return (self.x - self.WIDTH / 2.0, self.y - self.HEIGHT / 2.0,
                self.x + self.WIDTH / 2.0, self.y + self.HEIGHT / 2.0)

    def generate_ports(self):
        self.ports = {
            "top": {"x": self.x, "y": self.y - self.HEIGHT / 2.0,
                    "direction": "in", "node_id": "N_%s_top" % self.id},
            "bottom": {"x": self.x, "y": self.y + self.HEIGHT / 2.0,
                       "direction": "out",
                       "node_id": "N_%s_bottom" % self.id},
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = x1 * zoom + offset_x, y1 * zoom + offset_y
        sx2, sy2 = x2 * zoom + offset_x, y2 * zoom + offset_y
        cx = (sx1 + sx2) / 2.0
        cy_mid = (sy1 + sy2) / 2.0
        lw = max(1, int(1.5 * zoom))
        canvas.create_rectangle(sx1, sy1 + 8 * zoom, sx2, sy2 - 8 * zoom,
                                fill="white", outline="black", width=lw)
        # Винтовые зажимы сверху и снизу.
        for cy in (sy1 + 4 * zoom, sy2 - 4 * zoom):
            r = max(2.0, 4 * zoom)
            canvas.create_rectangle(cx - r, cy - r, cx + r, cy + r,
                                    fill="#e0e0e0", outline="black", width=1)
        if self.variant == "measure":
            # Измерительная клемма: испытательная (разъёмная) вставка —
            # две скобы, между которыми вынимается перемычка.
            r = max(3.0, 9 * zoom)
            canvas.create_oval(cx - r, cy_mid - r,
                               cx + r, cy_mid + r,
                               fill="white", outline="black", width=lw)
            canvas.create_text(cx, cy_mid, text="I",
                               font=("Arial", max(7, int(8 * zoom))))
        elif self.variant == "disconnect":
            # Клемма с размыкателем: вертикальная перемычка с ножом,
            # который можно вынуть и разорвать цепь.
            canvas.create_line(cx, sy1 + 8 * zoom, cx,
                               cy_mid - 12 * zoom,
                               fill="black", width=lw)
            canvas.create_line(cx, cy_mid + 12 * zoom, cx, sy2 - 8 * zoom,
                               fill="black", width=lw)
            # Гнёзда размыкателя.
            for y in (cy_mid - 12 * zoom, cy_mid + 12 * zoom):
                w = max(3.0, 6 * zoom)
                canvas.create_line(cx - w, y, cx + w, y,
                                   fill="black", width=lw)
            # Нож (подвижный контакт) под углом.
            blade = max(9.0, 14 * zoom)
            canvas.create_line(cx, cy_mid - 12 * zoom,
                               cx + blade * 0.5, cy_mid + 10 * zoom,
                               fill="black", width=lw)
        else:
            canvas.create_line(cx, sy1 + 8 * zoom, cx, sy2 - 8 * zoom,
                               fill="black", width=lw)
        text = _text(self.number or self.designation)
        if text:
            canvas.create_text(cx, sy1 - 10 * zoom, text=text,
                               font=("Arial", max(7, int(8 * zoom))))
        self._draw_description(canvas, zoom, cx, sy2 + 10 * zoom)
        self._draw_label(canvas, zoom, offset_x, offset_y)


class MountTestBlock(MountElement):
    """Испытательный блок 4+1 или 6+1: N цепей слева, общий вывод справа."""

    WIDTH = 150
    TOP_H = 26
    ROW_H = 18
    BOTTOM_H = 10

    def __init__(self, comp_id, x, y, grid_size=20, variant="4+1"):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "mount_test_block"
        self.variant = variant if variant in TEST_BLOCK_VARIANTS else "4+1"
        self.designation = ""
        self.description = ""
        self.purpose = ""
        self.note = ""
        self.generate_ports()

    def contact_count(self):
        return TEST_BLOCK_VARIANTS.get(self.variant, 4)

    def _rect(self):
        height = self.TOP_H + self.contact_count() * self.ROW_H + self.BOTTOM_H
        return (self.x - self.WIDTH / 2.0, self.y - height / 2.0,
                self.x + self.WIDTH / 2.0, self.y + height / 2.0)

    def _contact_y(self, index):
        x1, y1, _x2, _y2 = self._rect()
        return y1 + self.TOP_H + index * self.ROW_H + self.ROW_H / 2.0

    def generate_ports(self):
        x1, _y1, x2, _y2 = self._rect()
        self.ports = {}
        for index in range(self.contact_count()):
            self.ports["contact{}".format(index + 1)] = {
                "x": x1, "y": self._contact_y(index), "direction": "in",
                "node_id": "N_%s_c%d" % (self.id, index + 1),
            }
        self.ports["common"] = {
            "x": x2, "y": self.y, "direction": "out",
            "node_id": "N_%s_common" % self.id,
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = x1 * zoom + offset_x, y1 * zoom + offset_y
        sx2, sy2 = x2 * zoom + offset_x, y2 * zoom + offset_y
        lw = max(1, int(1.4 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="#f7f9fc",
                                outline="black", width=lw)
        canvas.create_line(sx1, sy1 + self.TOP_H * zoom,
                           sx2, sy1 + self.TOP_H * zoom, width=1)
        title = _text(self.designation or self.name or "БИ")
        canvas.create_text((sx1 + sx2) / 2.0, sy1 + 12 * zoom, text=title,
                           font=("Arial", max(7, int(9 * zoom)), "bold"))
        canvas.create_text(sx2 - 8 * zoom, sy1 + 12 * zoom, text=self.variant,
                           anchor="e",
                           font=("Arial", max(7, int(8 * zoom))))
        for index in range(self.contact_count()):
            cy = self._contact_y(index) * zoom + offset_y
            canvas.create_text(sx1 + 8 * zoom, cy, text=str(index + 1),
                               anchor="w",
                               font=("Arial", max(7, int(8 * zoom))))
            canvas.create_line(sx1, cy, sx1 + 14 * zoom, cy, width=1)
            canvas.create_oval(sx1 - 2 * zoom, cy - 2 * zoom,
                               sx1 + 2 * zoom, cy + 2 * zoom,
                               fill="black", outline="black")
        cy = self.y * zoom + offset_y
        canvas.create_text(sx2 - 12 * zoom, cy, text="общ.",
                           anchor="e",
                           font=("Arial", max(7, int(8 * zoom))))
        canvas.create_oval(sx2 - 2 * zoom, cy - 2 * zoom,
                           sx2 + 2 * zoom, cy + 2 * zoom,
                           fill="black", outline="black")
        text = _text(getattr(self, "description", "")).strip()
        if text:
            canvas.create_text((sx1 + sx2) / 2.0, sy2 + 10 * zoom,
                               text=text, width=(sx2 - sx1),
                               font=("Arial", max(7, int(7 * zoom))),
                               fill="#697586")
        self._draw_label(canvas, zoom, offset_x, offset_y)


class MountSwitch(MountElement):
    """Переключатель на два или три положения.

    Общий вывод сверху, неподвижные выводы внизу; подвижный контакт
    рисуется наклонной линией к каждому положению (по ГОСТ 2.755 —
    переключатель с размыканием и переключением).
    """

    WIDTH = 60
    HEIGHT = 70
    STEP = 16

    def __init__(self, comp_id, x, y, grid_size=20, variant="2"):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "mount_switch"
        self.variant = variant if variant in SWITCH_VARIANTS else "2"
        self.designation = ""
        self.description = ""
        self.purpose = ""
        self.note = ""
        self.generate_ports()

    def position_count(self):
        return 3 if self.variant == "3" else 2

    def _contact_points(self):
        """Мировые координаты неподвижных выводов (слева направо)."""
        _x1, _y1, _x2, y2 = self._rect()
        span = self.STEP * (self.position_count() - 1)
        return [
            {"x": self.x - span / 2.0 + index * self.STEP,
             "y": y2 - self.HEIGHT * 0.25}
            for index in range(self.position_count())
        ]

    def generate_ports(self):
        self.ports = {
            "common": {
                "x": self.x, "y": self.y - self.HEIGHT / 2.0,
                "direction": "in",
                "node_id": "N_%s_common" % self.id,
            },
        }
        for index, point in enumerate(self._contact_points()):
            self.ports["position{}".format(index + 1)] = {
                "x": point["x"], "y": point["y"], "direction": "out",
                "node_id": "N_%s_p%d" % (self.id, index + 1),
            }

    def draw(self, canvas, zoom, offset_x, offset_y):
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = x1 * zoom + offset_x, y1 * zoom + offset_y
        sx2, sy2 = x2 * zoom + offset_x, y2 * zoom + offset_y
        cx = (sx1 + sx2) / 2.0
        lw = max(1, int(1.5 * zoom))
        points = self._contact_points()
        top_y = sy1 + 8 * zoom
        # Общий (подвижный) вывод: вертикальная линия сверху.
        canvas.create_line(cx, sy1, cx, sy2, fill="black", width=lw)
        canvas.create_oval(cx - 2.5 * zoom, sy1 - 2.5 * zoom,
                           cx + 2.5 * zoom, sy1 + 2.5 * zoom,
                           fill="black", outline="black")
        # Неподвижные выводы и наклонные плечи подвижного контакта:
        # контактная линия от оси вращения вниз к каждому положению.
        for point in points:
            px, py = point["x"] * zoom + offset_x, point["y"] * zoom + offset_y
            # Плечо подвижного контакта (наклонная линия).
            canvas.create_line(cx, top_y, px, py, fill="black", width=lw)
            # Неподвижный вывод.
            canvas.create_line(px, py, px, sy2, fill="black", width=lw)
            canvas.create_oval(px - 2.5 * zoom, py - 2.5 * zoom,
                               px + 2.5 * zoom, py + 2.5 * zoom,
                               fill="black", outline="black")
        # Номера положений под неподвижными выводами.
        for index, point in enumerate(points):
            px = point["x"] * zoom + offset_x
            canvas.create_text(px, sy2 + 10 * zoom, text=str(index + 1),
                               font=("Arial", max(7, int(8 * zoom))))
        # Обозначение и описание.
        text = _text(self.designation or self.name)
        if text:
            canvas.create_text(cx, sy1 - 10 * zoom, text=text,
                               font=("Arial", max(7, int(8 * zoom))))
        desc = _text(getattr(self, "description", "")).strip()
        if desc:
            canvas.create_text((sx1 + sx2) / 2.0, sy2 + 22 * zoom,
                               text=desc, width=(sx2 - sx1),
                               font=("Arial", max(7, int(7 * zoom))),
                               fill="#697586")
        self._draw_label(canvas, zoom, offset_x, offset_y)


class MountIed(MountElement):
    """ИЭУ прямоугольником: поля, порты слева, функции справа."""

    WIDTH = 250
    HEADER_H = 56
    ROW_H = 20
    MIN_HEIGHT = 96

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "mount_ied"
        self.designation = ""
        self.description = ""
        self.ied_type = ""
        self.cabinet = ""
        self.kit = ""
        self.ied = ""
        self.port_items = []
        self.function_items = []
        self.generate_ports()

    def _rows(self):
        return max(len(self.port_items), len(self.function_items), 1)

    def _rect(self):
        height = max(self.MIN_HEIGHT,
                     self.HEADER_H + self._rows() * self.ROW_H + 12)
        return (self.x - self.WIDTH / 2.0, self.y - height / 2.0,
                self.x + self.WIDTH / 2.0, self.y + height / 2.0)

    def _row_y(self, index):
        x1, y1, _x2, _y2 = self._rect()
        return y1 + self.HEADER_H + index * self.ROW_H + self.ROW_H / 2.0

    def generate_ports(self):
        x1, _y1, x2, _y2 = self._rect()
        self.ports = {}
        for index, port in enumerate(self.port_items):
            self.ports["port{}".format(index + 1)] = {
                "x": x1, "y": self._row_y(index),
                "direction": port.get("direction", "in"),
                "node_id": "N_%s_p%d" % (self.id, index + 1),
                "slot_name": port.get("name", ""),
                "slot_iec": port.get("iec", ""),
            }
        for index, function in enumerate(self.function_items):
            outputs = function.get("outputs") or []
            if not outputs:
                continue
            self.ports["func{}".format(index + 1)] = {
                "x": x2, "y": self._row_y(index),
                "direction": "out",
                "node_id": "N_%s_f%d" % (self.id, index + 1),
                "slot_name": function_label(function),
                "slot_iec": _text(outputs[0].get("iec_name")),
            }

    def add_function(self, function, source=None):
        item = normalize_function(function)
        if source:
            for key, value in source.items():
                if value:
                    item[key] = value
        self.function_items.append(item)
        self.generate_ports()
        return item

    def add_port(self, **values):
        item = new_port(**values)
        self.port_items.append(item)
        self.generate_ports()
        return item

    def draw(self, canvas, zoom, offset_x, offset_y):
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = x1 * zoom + offset_x, y1 * zoom + offset_y
        sx2, sy2 = x2 * zoom + offset_x, y2 * zoom + offset_y
        lw = max(1, int(1.5 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="#f2f6fb",
                                outline="#1f4e79", width=lw)
        canvas.create_line(sx1, sy1 + self.HEADER_H * zoom,
                           sx2, sy1 + self.HEADER_H * zoom,
                           fill="#1f4e79", width=1)
        header = [
            (_text(self.designation or self.name or "ИЭУ"), 10, "bold"),
            (_text(self.description), 24, "normal"),
            (_text(self.ied_type), 40, "normal"),
        ]
        for text, dy, weight in header:
            if text:
                canvas.create_text(sx1 + 8 * zoom, sy1 + dy * zoom,
                                   text=text, anchor="w",
                                   font=("Arial", max(7, int(8 * zoom)),
                                         weight),
                                   fill="#1f4e79")
        divider = sx1 + (sx2 - sx1) * 0.52
        canvas.create_line(divider, sy1 + self.HEADER_H * zoom,
                           divider, sy2, fill="#b0bec5", width=1)
        for index, port in enumerate(self.port_items):
            cy = self._row_y(index) * zoom + offset_y
            text = _text(port.get("name") or port.get("description"))
            if port.get("direction") == "out":
                text = "> " + text
            else:
                text = "< " + text
            canvas.create_text(sx1 + 6 * zoom, cy, text=text, anchor="w",
                               font=("Arial", max(7, int(8 * zoom))))
            canvas.create_oval(sx1 - 2 * zoom, cy - 2 * zoom,
                               sx1 + 2 * zoom, cy + 2 * zoom,
                               fill="#1f4e79", outline="#1f4e79")
        for index, function in enumerate(self.function_items):
            cy = self._row_y(index) * zoom + offset_y
            canvas.create_text(divider + 6 * zoom, cy,
                               text=function_label(function), anchor="w",
                               font=("Arial", max(7, int(8 * zoom))))
            if "func{}".format(index + 1) in self.ports:
                canvas.create_oval(sx2 - 2 * zoom, cy - 2 * zoom,
                                   sx2 + 2 * zoom, cy + 2 * zoom,
                                   fill="#2e7d32", outline="#2e7d32")
        self._draw_label(canvas, zoom, offset_x, offset_y)


def create_component(comp_type, comp_id, x, y, grid_size=20, variant=""):
    kind, inline_variant = split_palette_type(comp_type)
    variant = inline_variant or variant
    if kind == "mount_terminal":
        return MountTerminal(comp_id, x, y, grid_size, variant or "feed")
    if kind == "mount_test_block":
        return MountTestBlock(comp_id, x, y, grid_size, variant or "4+1")
    if kind == "mount_switch":
        return MountSwitch(comp_id, x, y, grid_size, variant or "2")
    if kind == "mount_ied":
        return MountIed(comp_id, x, y, grid_size)
    raise ValueError("Неизвестный элемент монтажной схемы: %s" % comp_type)


def element_payload(el):
    payload = {}
    kind = getattr(el, "type", "")
    attr_by_field = {}
    if kind == "mount_ied":
        attr_by_field = {"type": "ied_type", "ports": "port_items",
                         "functions": "function_items"}
    for field in FIELDS.get(kind, ()):
        attribute = attr_by_field.get(field, field)
        if not hasattr(el, attribute):
            continue
        payload[field] = copy.deepcopy(getattr(el, attribute))
    if kind == "mount_terminal":
        payload.setdefault("variant", el.variant)
        payload.setdefault("number", el.number)
    elif kind == "mount_test_block":
        payload.setdefault("variant", el.variant)
    elif kind == "mount_switch":
        payload.setdefault("variant", el.variant)
    return payload


def restore_element(el, payload):
    """Применить сохранённые поля монтажного элемента."""
    if not isinstance(payload, dict):
        return
    kind = getattr(el, "type", "")
    fields = {field: field for field in FIELDS.get(kind, ())}
    # В JSON поля называются type/ports/functions, в объекте —
    # ied_type/port_items/function_items: type занят типом элемента.
    if kind == "mount_ied":
        fields.update({"type": "ied_type", "ports": "port_items",
                       "functions": "function_items"})
    for field, attribute in fields.items():
        if field in payload:
            setattr(el, attribute, copy.deepcopy(payload[field]))
    if kind == "mount_terminal":
        variant = _text(payload.get("variant")).strip()
        if variant in TERMINAL_VARIANT_BY_TITLE:
            variant = TERMINAL_VARIANT_BY_TITLE[variant]
        el.variant = variant if variant in TERMINAL_VARIANTS else "feed"
        for field in ("number", "designation", "description", "purpose",
                      "connection", "note"):
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, _text(getattr(el, field, "")))
    elif kind == "mount_test_block":
        variant = _text(payload.get("variant")).strip()
        el.variant = variant if variant in TEST_BLOCK_VARIANTS else "4+1"
        for field in ("designation", "description", "purpose", "note"):
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, _text(getattr(el, field, "")))
    elif kind == "mount_switch":
        variant = _text(payload.get("variant")).strip()
        if variant in SWITCH_VARIANT_BY_TITLE:
            variant = SWITCH_VARIANT_BY_TITLE[variant]
        try:
            variant = str(int(variant))
        except (TypeError, ValueError):
            variant = "2"
        el.variant = variant if variant in SWITCH_VARIANTS else "2"
        for field in ("designation", "description", "purpose", "note"):
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, _text(getattr(el, field, "")))
    elif kind == "mount_ied":
        for field in ("designation", "description", "ied_type", "cabinet",
                      "kit", "ied"):
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, _text(getattr(el, field, "")))
        el.port_items = normalize_ports(getattr(el, "port_items", None))
        el.function_items = normalize_functions(
            getattr(el, "function_items", None))
    el.generate_ports()


def copy_element_fields(source, target):
    kind = getattr(source, "type", "")
    attr_by_field = {}
    if kind == "mount_ied":
        attr_by_field = {"type": "ied_type", "ports": "port_items",
                         "functions": "function_items"}
    for field in FIELDS.get(kind, ()):
        attribute = attr_by_field.get(field, field)
        if hasattr(source, attribute):
            setattr(target, attribute,
                    copy.deepcopy(getattr(source, attribute)))
    target.generate_ports()


def draw_palette_icon(canvas, comp_type, size=46):
    kind, variant = split_palette_type(comp_type)
    s = size / 46.0
    center = size / 2.0
    lw = max(1, int(1.5 * s))
    if kind == "mount_terminal":
        canvas.create_rectangle(16 * s, 10 * s, 30 * s, 36 * s,
                                fill="white", outline="black", width=lw)
        for y in (8 * s, 38 * s):
            canvas.create_rectangle(center - 4 * s, y - 3 * s,
                                    center + 4 * s, y + 3 * s,
                                    fill="#e0e0e0", outline="black", width=1)
        if variant == "measure":
            canvas.create_oval(center - 5 * s, 18 * s,
                               center + 5 * s, 28 * s,
                               fill="white", outline="black", width=1)
            canvas.create_text(center, 23 * s, text="I",
                               font=("Arial", max(7, int(8 * s))))
        elif variant == "disconnect":
            # Клемма с размыкателем: перемычка с ножом.
            canvas.create_line(center, 10 * s, center, 18 * s, width=1)
            canvas.create_line(center, 28 * s, center, 36 * s, width=1)
            canvas.create_line(center - 3 * s, 18 * s,
                               center + 3 * s, 18 * s, width=1)
            canvas.create_line(center - 3 * s, 28 * s,
                               center + 3 * s, 28 * s, width=1)
            canvas.create_line(center, 18 * s,
                               center + 4 * s, 27 * s, width=1)
        else:
            canvas.create_line(center, 10 * s, center, 36 * s, width=1)
    elif kind == "mount_test_block":
        count = TEST_BLOCK_VARIANTS.get(variant, 4)
        top, bottom = 9 * s, 37 * s
        canvas.create_rectangle(10 * s, top, 36 * s, bottom,
                                fill="#f7f9fc", outline="black", width=lw)
        for index in range(count):
            y = top + (index + 1) * (bottom - top) / (count + 1.0)
            canvas.create_line(4 * s, y, 10 * s, y, width=1)
        canvas.create_line(36 * s, center, 42 * s, center, width=1)
        canvas.create_text(23 * s, 13 * s, text=variant or "4+1",
                           font=("Arial", max(7, int(8 * s))))
    elif kind == "mount_switch":
        # Общий вывод сверху и наклонные плечи к неподвижным выводам.
        count = 3 if variant == "3" else 2
        top = 8 * s
        bottom = 34 * s
        span = 14 * s * (count - 1)
        positions = [center - span / 2.0 + index * 14 * s
                     for index in range(count)]
        canvas.create_line(center, 3 * s, center, bottom, width=1)
        for px in positions:
            canvas.create_line(center, top, px, bottom, width=1)
            canvas.create_line(px, bottom, px, 40 * s, width=1)
        for index, px in enumerate(positions):
            canvas.create_text(px, 42 * s, text=str(index + 1),
                               font=("Arial", max(6, int(7 * s))))
    elif kind == "mount_ied":
        canvas.create_rectangle(5 * s, 7 * s, 40 * s, 39 * s,
                                fill="#f2f6fb", outline="#1f4e79", width=lw)
        canvas.create_line(5 * s, 17 * s, 40 * s, 17 * s,
                           fill="#1f4e79", width=1)
        canvas.create_line(23 * s, 17 * s, 23 * s, 39 * s,
                           fill="#b0bec5", width=1)
        for y in (23 * s, 30 * s, 36 * s):
            canvas.create_line(1 * s, y, 5 * s, y, width=1)
            canvas.create_line(23 * s, y, 40 * s, y, width=1, fill="#9e9e9e")
