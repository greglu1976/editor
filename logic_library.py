# -*- coding: utf-8 -*-
"""Элементы функционально-логических схем (ФЛС) устройства.

Модуль добавляет к библиотеке элементов редактора первичных схем набор
символов функциональной логики ИЭУ:

* ``logic_bus``      — вертикальная шина (шина процесса/сигналов);
* ``logic_key``      — функциональная клавиша со светодиодом;
* ``logic_led``      — светодиодный индикатор;
* ``logic_block``    — функциональный блок (логическое устройство) с
                       сигналами и вставленными логическими узлами;
* ``logic_function`` — отдельный логический узел (И, ИЛИ, НЕ, …).

Связи ФЛС описаны в ``LOGIC_LINK_KINDS``: аналоговые, дискретные,
управляющие, информационный обмен внутри ИЭУ и между ИЭУ. У каждой связи
есть номер/маркировка, русское наименование сигнала и наименование по МЭК.

Геометрия — в мировых единицах (``library.CELL`` = 20), поэтому элементы
масштабируются вместе с чертежом и попадают в PDF/PNG теми же вызовами
``draw(canvas, zoom, offset_x, offset_y)``, что и остальные элементы.
"""

from __future__ import annotations

import copy
import math

from library import CELL, Component

# ==========================================================================
# Связи ФЛС
# ==========================================================================
# Цвета повторяют легенду образца «Цветовая кодировка информации»:
#   синий   — аналоговые цепи с уровня процесса;
#   зелёный — дискретные цепи с уровня процесса;
#   фиолетовый — управляющие воздействия;
#   красный — информационный обмен внутри ИЭУ;
#   малиновый — информационный обмен между ИЭУ.
LOGIC_LINK_KINDS = {
    "analog": {
        "title": "Аналоговые цепи",
        "full": "Аналоговые цепи с уровня процесса",
        "color": "#1565c0",
        "dash": None,
        "width": 1.6,
    },
    "discrete": {
        "title": "Дискретные цепи",
        "full": "Дискретные цепи с уровня процесса",
        "color": "#2e7d32",
        "dash": None,
        "width": 1.6,
    },
    "control": {
        "title": "Управляющие",
        "full": "Управляющие воздействия",
        "color": "#7b1fa2",
        "dash": None,
        "width": 1.8,
    },
    "internal": {
        "title": "Обмен внутри ИЭУ",
        "full": "Информационный обмен внутри ИЭУ",
        "color": "#c62828",
        "dash": (7, 3),
        "width": 1.6,
    },
    "external": {
        "title": "Обмен между ИЭУ",
        "full": "Информационный обмен между ИЭУ",
        "color": "#d81b60",
        "dash": (7, 3),
        "width": 1.6,
    },
}

LOGIC_LINK_ORDER = ("analog", "discrete", "control", "internal", "external")

#: С какого номера начинается автоматическая нумерация связей.
LOGIC_LINK_START = 9000

LOGIC_COMPONENT_TYPES = (
    "logic_bus", "logic_key", "logic_led", "logic_block", "logic_function",
)

PREFIX_BY_TYPE = {
    "logic_bus": "Ш",
    "logic_key": "К",
    "logic_led": "HL",
    "logic_block": "Б",
    "logic_function": "ЛУ",
}

ELEMENT_TYPE_TITLES = {
    "logic_bus": "Шина вертикальная",
    "logic_key": "Функциональная клавиша",
    "logic_led": "Светодиод",
    "logic_block": "Функциональный блок (логическое устройство)",
    "logic_function": "Логический узел",
}

PALETTE_ITEMS = [
    ("Шина вертикальная (ФЛС)", "logic_bus"),
    ("Функциональная клавиша", "logic_key"),
    ("Светодиод", "logic_led"),
    ("Функциональный блок", "logic_block"),
    ("Логический узел (И, ИЛИ, НЕ…)", "logic_function"),
]

#: Виды логических узлов: символ на схеме и русское название.
FUNCTION_KINDS = {
    "AND": ("&", "И"),
    "OR": ("≥1", "ИЛИ"),
    "NOT": ("1", "НЕ"),
    "XOR": ("=1", "Исключающее ИЛИ"),
    "RS": ("SR", "RS-триггер"),
    "TIMER": ("T", "Выдержка времени"),
    "CUSTOM": ("ƒ", "Функция"),
}

FUNCTION_KIND_ORDER = ("AND", "OR", "NOT", "XOR", "RS", "TIMER", "CUSTOM")

#: Направление сигнала в строке блока/функции.
SIGNAL_DIRECTIONS = {
    "out": "выход",
    "in": "вход",
    "both": "вход/выход",
    "none": "внутренний",
}

#: Русские обозначения направления, которые принимает диалог блока.
SIGNAL_DIRECTION_ALIASES = {
    "выход": "out", "исх": "out", "out": "out",
    "вход": "in", "вх": "in", "in": "in",
    "вход/выход": "both", "вх/вых": "both", "both": "both",
    "внутренний": "none", "внутр": "none", "none": "none",
}

#: Тип входного сигнала блока по префиксу кода (A01, D01, C01 …).
INPUT_CODE_KINDS = {
    "A": "аналоговый",
    "D": "дискретный",
    "C": "управляющий",
    "G": "GOOSE",
    "S": "служебный",
}


def input_code_kind(code):
    """Тип входного сигнала по коду: A… — аналоговый, D… — дискретный."""
    prefix = str(code or "").strip()[:1].upper()
    return INPUT_CODE_KINDS.get(prefix, "—")


def link_style(kind):
    """Стиль линии связи: цвет, штрих, толщина."""
    return LOGIC_LINK_KINDS.get(kind, LOGIC_LINK_KINDS["discrete"])


def link_title(kind):
    return link_style(kind)["title"]


def next_logic_number(links, start=LOGIC_LINK_START):
    """Следующий свободный номер связи (числовые маркировки)."""
    highest = start - 1
    for link in links or []:
        raw = str(link.get("number") or "").strip()
        if raw.isdigit():
            highest = max(highest, int(raw))
    return str(highest + 1)


def signal_text(ru, iec, fallback=""):
    """Подпись сигнала одной строкой: русское наименование и МЭК в скобках.

    Одна строка выбрана осознанно: PDF/PNG-экспорт рисует подпись одним
    вызовом create_text и не переносит строки, поэтому многострочная
    подпись на экране и в экспорте выглядела бы по-разному.
    """
    ru = (ru or "").strip()
    iec = (iec or "").strip()
    if ru and iec and iec != ru:
        return "{} ({})".format(ru, iec)
    return ru or iec or fallback


def _text_width(text, size=8):
    """Приблизительная ширина строки в мировых единицах."""
    text = str(text or "")
    if not text:
        return 0.0
    longest = max(len(line) for line in text.splitlines())
    return longest * size * 0.62


def _round_up(value, step):
    """Округление вверх до шага: габариты блока кратны сетке."""
    step = float(step)
    return math.ceil(float(value) / step) * step


def _round_to(value, step):
    """Ближайшая линия сетки: кромки блока и выводы — на сетке."""
    step = float(step)
    return math.floor(float(value) / step + 0.5) * step


def _font_size(zoom, size):
    return max(1, int(round(size * zoom)))


def _line_width(zoom, width=1.6):
    return max(1, int(round(width * zoom)))


def draw_led(canvas, cx, cy, zoom, radius=7.0):
    """Светодиод: треугольник, катодная планка и два вывода."""
    r = radius * zoom
    lw = max(1, int(2 * zoom))
    canvas.create_line(cx - r * 1.8, cy, cx - r, cy, width=lw, fill="black")
    canvas.create_line(cx + r, cy, cx + r * 1.8, cy, width=lw, fill="black")
    canvas.create_polygon(cx - r, cy - r * 0.75, cx - r, cy + r * 0.75,
                          cx + r * 0.9, cy, fill="white", outline="black",
                          width=lw)
    canvas.create_line(cx + r * 0.9, cy - r * 0.85,
                       cx + r * 0.9, cy + r * 0.85,
                       width=lw, fill="black")


def draw_key(canvas, cx, cy, zoom, radius=8.0):
    """Функциональная клавиша: два контакта и подвижная планка."""
    r = radius * zoom
    lw = max(1, int(2 * zoom))
    canvas.create_line(cx - r * 2.0, cy, cx - r * 0.9, cy,
                       width=lw, fill="black")
    canvas.create_line(cx - r * 0.9, cy - r, cx - r * 0.9, cy + r,
                       width=lw, fill="black")
    canvas.create_line(cx - r * 0.1, cy - r, cx - r * 0.1, cy + r,
                       width=lw, fill="black")
    canvas.create_line(cx - r * 1.2, cy + r * 1.25,
                       cx + r * 0.25, cy - r * 1.25,
                       width=lw, fill="black")
    canvas.create_line(cx - r * 0.1, cy, cx + r, cy, width=lw, fill="black")


# ==========================================================================
# Базовый класс элементов ФЛС
# ==========================================================================
class LogicComponent(Component):
    """Общее для элементов ФЛС: подпись названия и сигналов."""

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic"
        self.title = ""
        self.signal_ru = ""
        self.signal_iec = ""
        self.signal_no = ""

    def _draw_title(self, canvas, zoom, offset_x, offset_y, world_x, world_y,
                    anchor="center", size=8, color="black"):
        """Название над символом; bbox запоминается для перетаскивания."""
        text = self.title or self.name
        if not text:
            self._label_bbox = None
            return
        dx, dy = getattr(self, "label_offset", (0.0, 0.0))
        sx = (world_x + dx) * zoom + offset_x
        sy = (world_y + dy) * zoom + offset_y
        item = canvas.create_text(sx, sy, text=text, anchor=anchor,
                                  font=("Arial", _font_size(zoom, size)),
                                  fill=color, tags="element_label")
        try:
            self._label_bbox = canvas.bbox(item) if item is not None else None
        except Exception:
            self._label_bbox = None

    def _draw_signal(self, canvas, zoom, offset_x, offset_y, world_x, world_y,
                     size=7, color="#7b1fa2"):
        """Русское наименование сигнала и МЭК справа от символа."""
        text = signal_text(self.signal_ru, self.signal_iec)
        if not text:
            return
        sx = world_x * zoom + offset_x
        sy = world_y * zoom + offset_y
        canvas.create_text(sx, sy, text=text, anchor="w",
                           font=("Arial", _font_size(zoom, size)),
                           fill=color, justify="left")

    def _draw_number(self, canvas, zoom, offset_x, offset_y, world_x, world_y,
                     size=7, color="#1f4e79"):
        number = (self.signal_no or "").strip()
        if not number:
            return
        sx = world_x * zoom + offset_x
        sy = world_y * zoom + offset_y
        canvas.create_text(sx, sy, text=number, anchor="w",
                           font=("Arial", _font_size(zoom, size)),
                           fill=color)

    def _draw_name(self, canvas, zoom, offset_x, offset_y, world_x, world_y):
        if not self.name:
            return
        sx = world_x * zoom + offset_x
        sy = world_y * zoom + offset_y
        canvas.create_text(sx, sy, text=self.name, anchor="nw",
                           font=("Arial", _font_size(zoom, 7)),
                           fill="#555555")

    def world_to_screen(self, x, y):
        """Мировые координаты → экранные в контексте текущего draw()."""
        zoom, offset_x, offset_y = getattr(self, "_draw_ctx", (1.0, 0.0, 0.0))
        return x * zoom + offset_x, y * zoom + offset_y


# ==========================================================================
# 1. ВЕРТИКАЛЬНАЯ ШИНА
# ==========================================================================
class LogicBus(LogicComponent):
    """Шина сигналов: вертикальная линия с отводами через клетку."""

    WIDTH = 5.0

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_bus"
        self.rotation = 0
        self.length = CELL * 24
        self.title = "Шина"
        self.color = "#00acc1"
        self.generate_ports()

    def _vertical(self):
        return getattr(self, "rotation", 0) % 180 == 0

    def generate_ports(self):
        half = self.length / 2.0
        self.ports = {}
        if self._vertical():
            self.ports["top"] = {"x": self.x, "y": self.y - half,
                                 "node_id": "N_{}_top".format(self.id)}
            self.ports["bottom"] = {"x": self.x, "y": self.y + half,
                                    "node_id": "N_{}_bottom".format(self.id)}
            self.ports["center"] = {"x": self.x, "y": self.y,
                                    "node_id": "N_{}_center".format(self.id)}
            index = 1
            cy = self.y - half + CELL
            while cy <= self.y + half - CELL + 0.01:
                if abs(cy - self.y) > 0.01:
                    name = "p{}".format(index)
                    self.ports[name] = {
                        "x": self.x, "y": cy,
                        "node_id": "N_{}_{}".format(self.id, name)}
                    index += 1
                cy += CELL
        else:
            self.ports["left"] = {"x": self.x - half, "y": self.y,
                                  "node_id": "N_{}_left".format(self.id)}
            self.ports["right"] = {"x": self.x + half, "y": self.y,
                                   "node_id": "N_{}_right".format(self.id)}
            self.ports["center"] = {"x": self.x, "y": self.y,
                                    "node_id": "N_{}_center".format(self.id)}
            index = 1
            cx = self.x - half + CELL
            while cx <= self.x + half - CELL + 0.01:
                if abs(cx - self.x) > 0.01:
                    name = "p{}".format(index)
                    self.ports[name] = {
                        "x": cx, "y": self.y,
                        "node_id": "N_{}_{}".format(self.id, name)}
                    index += 1
                cx += CELL

    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        half = self.length / 2.0
        lw = max(2, int(self.WIDTH * zoom))
        color = getattr(self, "color", "#00acc1") or "#00acc1"
        if self._vertical():
            x1, y1 = self.world_to_screen(self.x, self.y - half)
            x2, y2 = self.world_to_screen(self.x, self.y + half)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill=color)
            self._draw_title(canvas, zoom, offset_x, offset_y,
                             self.x, self.y - half - 14, anchor="s")
            self._draw_name(canvas, zoom, offset_x, offset_y,
                            self.x + 8, self.y - half)
            self._draw_signal(canvas, zoom, offset_x, offset_y,
                              self.x + 10, self.y, size=7, color=color)
            self._draw_number(canvas, zoom, offset_x, offset_y,
                              self.x + 10, self.y + 14, size=7)
        else:
            x1, y1 = self.world_to_screen(self.x - half, self.y)
            x2, y2 = self.world_to_screen(self.x + half, self.y)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill=color)
            self._draw_title(canvas, zoom, offset_x, offset_y,
                             self.x, self.y - 14, anchor="s")
            self._draw_name(canvas, zoom, offset_x, offset_y,
                            self.x - half, self.y + 6)
            self._draw_signal(canvas, zoom, offset_x, offset_y,
                              self.x - half + 10, self.y - 12,
                              size=7, color=color)
            self._draw_number(canvas, zoom, offset_x, offset_y,
                              self.x - half + 10, self.y + 2, size=7)

    def get_bounding_box(self):
        half = self.length / 2.0
        if self._vertical():
            return (self.x - 10, self.y - half - 20,
                    self.x + 10, self.y + half)
        return (self.x - half, self.y - 20, self.x + half, self.y + 10)


# ==========================================================================
# 2. ФУНКЦИОНАЛЬНАЯ КЛАВИША
# ==========================================================================
class LogicKey(LogicComponent):
    """Клавиша со светодиодом: рамка с двумя символами и подписями."""

    WIDTH = 160
    HEIGHT = 48

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_key"
        self.title = "Функциональная клавиша"
        self.signal_ru = ""
        self.signal_iec = ""
        self.signal_no = ""
        self.show_led = True
        self.generate_ports()

    def _rect(self):
        half_w = self.WIDTH / 2.0
        half_h = self.HEIGHT / 2.0
        return (self.x - half_w, self.y - half_h,
                self.x + half_w, self.y + half_h)

    def generate_ports(self):
        x1, y1, x2, y2 = self._rect()
        self.ports = {
            "left": {"x": x1, "y": self.y,
                     "node_id": "N_{}_left".format(self.id)},
            "right": {"x": x2, "y": self.y,
                      "node_id": "N_{}_right".format(self.id)},
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="black", width=lw)
        cx, cy = self.world_to_screen(self.x, self.y)
        draw_key(canvas, cx - 34 * zoom, cy, zoom, 8.0)
        if self.show_led:
            draw_led(canvas, cx + 34 * zoom, cy, zoom, 7.0)
        self._draw_title(canvas, zoom, offset_x, offset_y,
                         self.x, y1 - 10, anchor="s")
        self._draw_name(canvas, zoom, offset_x, offset_y, x1 + 4, y1 + 2)
        self._draw_signal(canvas, zoom, offset_x, offset_y,
                          x2 + 8, self.y, size=7)
        number_x = x2 + 8 + max(70.0, _text_width(
            signal_text(self.signal_ru, self.signal_iec), 7) + 16)
        self._draw_number(canvas, zoom, offset_x, offset_y,
                          number_x, self.y, size=7)

    def get_bounding_box(self):
        x1, y1, x2, y2 = self._rect()
        # Название над рамкой — часть кликабельной области элемента.
        return (x1, y1 - 18, x2, y2)


# ==========================================================================
# 3. СВЕТОДИОД
# ==========================================================================
class LogicLed(LogicComponent):
    """Светодиодный индикатор в рамке."""

    WIDTH = 100
    HEIGHT = 40

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_led"
        self.title = "Светодиод"
        self.generate_ports()

    def _rect(self):
        half_w = self.WIDTH / 2.0
        half_h = self.HEIGHT / 2.0
        return (self.x - half_w, self.y - half_h,
                self.x + half_w, self.y + half_h)

    def generate_ports(self):
        x1, _y1, x2, _y2 = self._rect()
        self.ports = {
            "left": {"x": x1, "y": self.y,
                     "node_id": "N_{}_left".format(self.id)},
            "right": {"x": x2, "y": self.y,
                      "node_id": "N_{}_right".format(self.id)},
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="black", width=lw)
        cx, cy = self.world_to_screen(self.x, self.y)
        draw_led(canvas, cx, cy, zoom, 8.0)
        self._draw_title(canvas, zoom, offset_x, offset_y,
                         self.x, y1 - 10, anchor="s")
        self._draw_name(canvas, zoom, offset_x, offset_y, x1 + 4, y1 + 2)
        self._draw_signal(canvas, zoom, offset_x, offset_y,
                          x2 + 8, self.y, size=7)
        number_x = x2 + 8 + max(70.0, _text_width(
            signal_text(self.signal_ru, self.signal_iec), 7) + 16)
        self._draw_number(canvas, zoom, offset_x, offset_y,
                          number_x, self.y, size=7)

    def get_bounding_box(self):
        x1, y1, x2, y2 = self._rect()
        # Название над рамкой — часть кликабельной области элемента.
        return (x1, y1 - 18, x2, y2)


# ==========================================================================
# 4. ЛОГИЧЕСКИЙ УЗЕЛ
# ==========================================================================
class LogicFunction(LogicComponent):
    """Отдельный логический узел: И, ИЛИ, НЕ, RS-триггер и т. п."""

    WIDTH = 104
    HEIGHT = 62

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_function"
        self.kind = "AND"
        self.title = ""
        self.signal_ru = ""
        self.signal_iec = ""
        self.input_count = 2
        self.generate_ports()

    def _rect(self):
        half_w = self.WIDTH / 2.0
        half_h = self.HEIGHT / 2.0
        return (self.x - half_w, self.y - half_h,
                self.x + half_w, self.y + half_h)

    def _input_points(self):
        count = max(1, int(self.input_count or 1))
        x1, y1, _x2, y2 = self._rect()
        if count == 1:
            return [(x1, self.y)]
        step = (y2 - y1 - 16.0) / (count - 1)
        return [(x1, y1 + 8.0 + step * index) for index in range(count)]

    def generate_ports(self):
        x1, _y1, x2, _y2 = self._rect()
        self.ports = {}
        for index, (px, py) in enumerate(self._input_points()):
            self.ports["in{}".format(index)] = {
                "x": px, "y": py,
                "node_id": "N_{}_in{}".format(self.id, index)}
        self.ports["out"] = {"x": x2, "y": self.y,
                             "node_id": "N_{}_out".format(self.id)}

    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="black", width=lw)
        symbol, _name = FUNCTION_KINDS.get(self.kind,
                                           FUNCTION_KINDS["CUSTOM"])
        cx, cy = self.world_to_screen(self.x, self.y)
        canvas.create_text(cx, cy, text=symbol,
                           font=("Arial", _font_size(zoom, 14), "bold"),
                           fill="black")
        for px, py in self._input_points():
            sx, sy = self.world_to_screen(px, py)
            canvas.create_line(sx - 8 * zoom, sy, sx, sy,
                               width=lw, fill="black")
        ox, oy = self.world_to_screen(x2, self.y)
        canvas.create_line(ox, oy, ox + 8 * zoom, oy, width=lw, fill="black")
        title = self.title or FUNCTION_KINDS.get(
            self.kind, FUNCTION_KINDS["CUSTOM"])[1]
        self._draw_title(canvas, zoom, offset_x, offset_y,
                         self.x, y1 - 10, anchor="s")
        self._draw_name(canvas, zoom, offset_x, offset_y, x1 + 4, y1 + 2)
        self._draw_signal(canvas, zoom, offset_x, offset_y,
                          x2 + 10, self.y - 6, size=7)
        self._draw_number(canvas, zoom, offset_x, offset_y,
                          x2 + 10, self.y + 10, size=7)
        # Название вида узла мелким шрифтом под символом
        if self.title:
            canvas.create_text(cx, cy + 12 * zoom,
                               text=FUNCTION_KINDS.get(
                                   self.kind, FUNCTION_KINDS["CUSTOM"])[1],
                               font=("Arial", _font_size(zoom, 6)),
                               fill="#666666")

    def get_bounding_box(self):
        x1, y1, x2, y2 = self._rect()
        # Название над рамкой — часть кликабельной области элемента.
        return (x1, y1 - 18, x2, y2)


# ==========================================================================
# 5. ФУНКЦИОНАЛЬНЫЙ БЛОК
# ==========================================================================
class LogicBlock(LogicComponent):
    """Функциональный блок (логическое устройство).

    Внутри блока две колонки: слева — входы (A01, D01, C01 …), справа —
    вставленные логические узлы и строки сигналов. Узлы начинаются от
    верхней кромки блока, поэтому число входов не сдвигает их: входы
    растут вниз в своей колонке.

    Геометрия кратна сетке (``CELL`` = 20): кромки блока лежат на линиях
    сетки, все выводы — на их пересечениях, поэтому связи ложатся по
    сетке без дробных координат.
    """

    HEADER = 40       # полоса заголовка — 2 клетки
    GAP = 20          # отступ от заголовка до содержимого — 1 клетка
    GUTTER = 120      # колонка входов — 6 клеток
    ROW_H = 40        # строка сигнала — 2 клетки
    FUNC_H = 80       # логический узел — 4 клетки
    PAD = 20          # отступ справа и снизу — 1 клетка
    MIN_WIDTH = 360

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_block"
        self.title = "Функциональный блок"
        self.designation = ""
        self.width = self.MIN_WIDTH
        self.inputs = ["D01", "D02", "D03"]
        self.rows = [
            {"dir": "out", "ru": "Состояние", "iec": "State"},
            {"dir": "out", "ru": "Индикация исправности", "iec": "Health"},
        ]
        self.functions = []
        self.generate_ports()

    # ---------- геометрия ----------
    def _block_width(self):
        widest = _text_width(self.title, 9) + 2 * CELL
        for code in self.inputs:
            widest = max(widest, self.GUTTER + _text_width(code, 8) + 2 * CELL)
        for row in self.rows:
            widest = max(widest,
                         self.GUTTER + _text_width(row.get("ru"), 8) + 3 * CELL
                         + _text_width(row.get("iec"), 7) + self.PAD)
        for function in self.functions:
            widest = max(widest,
                         self.GUTTER + _text_width(function.get("title"), 8)
                         + 5 * CELL + _text_width(function.get("ru"), 8)
                         + self.PAD)
        width = max(self.MIN_WIDTH, float(self.width or 0), widest)
        return _round_up(width, 2 * CELL)

    def _layout(self):
        """Раскладка блока: кромки и выводы лежат на сетке.

        Отступы считаются от верхней кромки: заголовок, клетка отступа,
        затем независимые колонки — входы слева, узлы и сигналы справа.
        Поэтому число дискретных входов не меняет положение узлов.
        """
        width = self._block_width()
        x1 = _round_to(self.x - width / 2.0, CELL)
        x2 = x1 + width

        content_top = self.HEADER + self.GAP
        input_offsets = [content_top + CELL * index
                         for index in range(len(self.inputs))]
        function_offsets = [
            content_top + self.FUNC_H * index + self.FUNC_H / 2.0
            for index in range(len(self.functions))]
        rows_top = content_top + self.FUNC_H * len(self.functions)
        row_offsets = [rows_top + self.ROW_H * index + self.ROW_H / 2.0
                       for index in range(len(self.rows))]

        # Номинальная высота — по правой колонке (узлы и сигналы).
        # Верх блока привязан к ней, поэтому входы не сдвигают узлы:
        # когда их становится больше, блок растёт только вниз.
        right_bottom = rows_top + self.ROW_H * len(self.rows)
        nominal_height = _round_up(max(content_top, right_bottom) + self.PAD,
                                   2 * CELL)
        inputs_bottom = content_top + CELL * (len(self.inputs) + 1)
        height = max(nominal_height,
                     _round_up(inputs_bottom + self.PAD, 2 * CELL))
        y1 = _round_to(self.y - nominal_height / 2.0, CELL)
        y2 = y1 + height

        return {
            "x1": x1, "x2": x2, "y1": y1, "y2": y2,
            "width": width, "height": height,
            "gutter": self.GUTTER,
            "content_x1": x1 + self.GUTTER,
            "content_x2": x2 - self.PAD,
            "inputs": [(code, y1 + offset)
                       for code, offset in zip(self.inputs, input_offsets)],
            "rows": [(row, y1 + offset)
                     for row, offset in zip(self.rows, row_offsets)],
            "functions": [(function, y1 + offset)
                          for function, offset in zip(self.functions,
                                                      function_offsets)],
        }

    def generate_ports(self):
        layout = self._layout()
        self.ports = {}
        for index, (code, py) in enumerate(layout["inputs"]):
            self.ports["in{}".format(index)] = {
                "x": layout["x1"], "y": py,
                "node_id": "N_{}_in{}".format(self.id, index)}
        out_index = 0
        for row, py in layout["rows"]:
            if (row.get("dir") or "out") in ("out", "both"):
                self.ports["out{}".format(out_index)] = {
                    "x": layout["x2"], "y": py,
                    "node_id": "N_{}_out{}".format(self.id, out_index)}
                out_index += 1
        for _function, py in layout["functions"]:
            self.ports["out{}".format(out_index)] = {
                "x": layout["x2"], "y": py,
                "node_id": "N_{}_out{}".format(self.id, out_index)}
            out_index += 1

    # ---------- отрисовка ----------
    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        layout = self._layout()
        x1, x2 = layout["x1"], layout["x2"]
        y1, y2 = layout["y1"], layout["y2"]
        fx1 = layout["content_x1"]
        fx2 = layout["content_x2"]
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))

        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="#fbfdff",
                                outline="black", width=lw)
        # Заголовок — по центру блока: кромки привязаны к сетке и могут
        # сместиться относительно точки вставки на полклетки.
        self._draw_title(canvas, zoom, offset_x, offset_y,
                         (x1 + x2) / 2.0, y1 + self.HEADER / 2.0, size=9)
        self._draw_name(canvas, zoom, offset_x, offset_y, x1 + 6, y1 + 4)
        if self.designation:
            canvas.create_text(sx2 - 6 * zoom, sy1 + 6 * zoom,
                               text=self.designation, anchor="ne",
                               font=("Arial", _font_size(zoom, 7)),
                               fill="#1f4e79")

        # Граница колонки входов
        gx = fx1 * zoom + offset_x
        canvas.create_line(gx, sy1 + self.HEADER * zoom, gx, sy2,
                           fill="#c8d3e0", width=1)

        # Входы: отводы на сетке в левой колонке
        for index, (code, py) in enumerate(layout["inputs"]):
            px = x1 * zoom + offset_x
            spy = py * zoom + offset_y
            canvas.create_line(px - 8 * zoom, spy, px, spy,
                               width=lw, fill="black")
            canvas.create_text(px + 7 * zoom, spy, text=code, anchor="w",
                               font=("Arial", _font_size(zoom, 8)),
                               fill="black")

        # Строки сигналов — в правой колонке, под узлами
        for row, py in layout["rows"]:
            by1 = (py - self.ROW_H / 2.0 + 4) * zoom + offset_y
            by2 = (py + self.ROW_H / 2.0 - 4) * zoom + offset_y
            canvas.create_rectangle(
                fx1 * zoom + offset_x + 4 * zoom, by1,
                fx2 * zoom + offset_x - 4 * zoom, by2,
                fill="#ececec", outline="#b8b8b8", width=1)
            ru = (row.get("ru") or "").strip()
            iec = (row.get("iec") or "").strip()
            canvas.create_text(fx1 * zoom + offset_x + 10 * zoom,
                               py * zoom + offset_y, text=ru or iec,
                               anchor="w",
                               font=("Arial", _font_size(zoom, 8)),
                               fill="black")
            if iec and iec != ru:
                canvas.create_text(fx2 * zoom + offset_x - 10 * zoom,
                                   py * zoom + offset_y, text=iec,
                                   anchor="e",
                                   font=("Arial", _font_size(zoom, 6)),
                                   fill="#666666")
            direction = row.get("dir") or "out"
            if direction in ("out", "both"):
                px = x2 * zoom + offset_x
                canvas.create_line(px, py * zoom + offset_y,
                                   px + 8 * zoom, py * zoom + offset_y,
                                   width=lw, fill="black")

        # Вставленные логические узлы — от верхней кромки
        for function, py in layout["functions"]:
            self._draw_function(canvas, zoom, offset_x, offset_y,
                                layout, function, py)

    def _draw_function(self, canvas, zoom, offset_x, offset_y,
                       layout, function, py):
        fx1 = layout["content_x1"] + 8
        fx2 = layout["content_x2"] - 8
        fy1 = py - (self.FUNC_H - 16) / 2.0
        fy2 = py + (self.FUNC_H - 16) / 2.0
        sx1, sy1 = self.world_to_screen(fx1, fy1)
        sx2, sy2 = self.world_to_screen(fx2, fy2)
        lw = max(1, int(1.6 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="#444444", width=lw)
        kind = (function.get("kind") or "AND").upper()
        symbol, kind_name = FUNCTION_KINDS.get(kind, FUNCTION_KINDS["CUSTOM"])
        canvas.create_text(sx1 + 14 * zoom, (sy1 + sy2) / 2.0,
                           text=symbol,
                           font=("Arial", _font_size(zoom, 13), "bold"),
                           fill="black")
        # Входы узла — короткие штрихи у левой грани вставленного блока.
        try:
            count = max(1, int(function.get("inputs") or 2))
        except (TypeError, ValueError):
            count = 2
        if count == 1:
            ys = [(sy1 + sy2) / 2.0]
        else:
            step = (sy2 - sy1 - 12 * zoom) / (count - 1)
            ys = [sy1 + 6 * zoom + step * index for index in range(count)]
        for y in ys:
            canvas.create_line(sx1 - 6 * zoom, y, sx1, y,
                               width=lw, fill="black")
        title = (function.get("title") or kind_name).strip()
        canvas.create_text(sx1 + 34 * zoom, sy1 + 10 * zoom,
                           text=title, anchor="w",
                           font=("Arial", _font_size(zoom, 8)),
                           fill="black")
        ru = (function.get("ru") or "").strip()
        iec = (function.get("iec") or "").strip()
        if ru or iec:
            canvas.create_text(sx1 + 34 * zoom, sy1 + 25 * zoom,
                               text=signal_text(ru, iec), anchor="w",
                               font=("Arial", _font_size(zoom, 7)),
                               fill="#7b1fa2", justify="left")
        # Выход узла — на правую кромку блока
        canvas.create_line(sx2, (sy1 + sy2) / 2.0,
                           layout["x2"] * zoom + offset_x,
                           (sy1 + sy2) / 2.0,
                           width=lw, fill="black")

    def get_bounding_box(self):
        layout = self._layout()
        return (layout["x1"], layout["y1"] - 18,
                layout["x2"], layout["y2"])


# ==========================================================================
# Фабрика и сериализация
# ==========================================================================
def create_component(comp_type, comp_id, x, y, grid_size=20):
    if comp_type == "logic_bus":
        return LogicBus(comp_id, x, y, grid_size)
    if comp_type == "logic_key":
        return LogicKey(comp_id, x, y, grid_size)
    if comp_type == "logic_led":
        return LogicLed(comp_id, x, y, grid_size)
    if comp_type == "logic_block":
        return LogicBlock(comp_id, x, y, grid_size)
    if comp_type == "logic_function":
        return LogicFunction(comp_id, x, y, grid_size)
    raise ValueError("Неизвестный элемент ФЛС: {}".format(comp_type))


#: Поля, которые сохраняются в JSON для каждого типа ФЛС.
LOGIC_FIELDS = {
    "logic_bus": ("length", "title", "signal_ru", "signal_iec",
                  "signal_no", "color", "rotation"),
    "logic_key": ("title", "signal_ru", "signal_iec", "signal_no", "show_led"),
    "logic_led": ("title", "signal_ru", "signal_iec", "signal_no"),
    "logic_block": ("title", "designation", "width", "inputs", "rows",
                    "functions"),
    "logic_function": ("kind", "title", "signal_ru", "signal_iec",
                       "signal_no", "input_count"),
}


def is_logic_type(comp_type):
    return comp_type in LOGIC_COMPONENT_TYPES


def element_payload(el):
    """Поля элемента ФЛС для JSON."""
    payload = {}
    for field in LOGIC_FIELDS.get(getattr(el, "type", ""), ()):
        if hasattr(el, field):
            payload[field] = copy.deepcopy(getattr(el, field))
    return payload


def restore_element(el, payload):
    """Восстанавливает поля элемента ФЛС из JSON."""
    if not isinstance(payload, dict):
        return
    for field in LOGIC_FIELDS.get(getattr(el, "type", ""), ()):
        if field in payload:
            value = copy.deepcopy(payload[field])
            setattr(el, field, value)
    # Защита от ручных правок JSON: приводим списки и числа к рабочему виду.
    if getattr(el, "type", "") == "logic_block":
        inputs = getattr(el, "inputs", None)
        el.inputs = [str(code) for code in inputs] if isinstance(inputs, list) else []
        rows = getattr(el, "rows", None)
        el.rows = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                direction = str(row.get("dir") or "out").casefold()
                direction = SIGNAL_DIRECTION_ALIASES.get(direction, direction)
                if direction not in SIGNAL_DIRECTIONS:
                    direction = "out"
                el.rows.append({
                    "dir": direction,
                    "ru": str(row.get("ru") or ""),
                    "iec": str(row.get("iec") or ""),
                })
            else:
                el.rows.append({"dir": "out", "ru": str(row), "iec": ""})
        functions = getattr(el, "functions", None)
        el.functions = []
        for function in functions if isinstance(functions, list) else []:
            if not isinstance(function, dict):
                continue
            kind = str(function.get("kind") or "AND").upper()
            try:
                count = max(1, int(function.get("inputs") or 2))
            except (TypeError, ValueError):
                count = 2
            el.functions.append({
                "kind": kind if kind in FUNCTION_KINDS else "CUSTOM",
                "title": str(function.get("title") or ""),
                "ru": str(function.get("ru") or ""),
                "iec": str(function.get("iec") or ""),
                "inputs": count,
            })
        try:
            el.width = max(LogicBlock.MIN_WIDTH, float(getattr(el, "width", 0)))
        except (TypeError, ValueError):
            el.width = LogicBlock.MIN_WIDTH
    if getattr(el, "type", "") == "logic_function":
        kind = str(getattr(el, "kind", "AND")).upper()
        el.kind = kind if kind in FUNCTION_KINDS else "CUSTOM"
        try:
            el.input_count = max(1, int(getattr(el, "input_count", 2)))
        except (TypeError, ValueError):
            el.input_count = 2
    if getattr(el, "type", "") == "logic_bus":
        try:
            el.length = max(40.0, float(getattr(el, "length", 480)))
        except (TypeError, ValueError):
            el.length = 480.0
        if not isinstance(getattr(el, "color", ""), str):
            el.color = "#00acc1"
    el.generate_ports()


def copy_element_fields(source, target):
    """Копирует поля ФЛС при копировании/вставке фрагмента."""
    for field in LOGIC_FIELDS.get(getattr(source, "type", ""), ()):
        if hasattr(source, field):
            setattr(target, field, copy.deepcopy(getattr(source, field)))
    target.generate_ports()


def draw_palette_icon(canvas, comp_type, size=46):
    """Компактный значок элемента ФЛС для палитры (без масштабирования
    реального символа: шина и блок в натуральную величину не влезают)."""
    s = size / 46.0
    center = size / 2.0
    lw = max(1, int(2 * s))
    if comp_type == "logic_bus":
        canvas.create_line(center, 4 * s, center, size - 4 * s,
                           width=max(2, int(4 * s)), fill="#00acc1")
        for y in (14, 23, 32):
            canvas.create_line(center - 8 * s, y * s,
                               center + 8 * s, y * s, width=1,
                               fill="#00838f")
    elif comp_type == "logic_key":
        canvas.create_rectangle(4 * s, 13 * s, size - 4 * s, 33 * s,
                                outline="black", width=lw)
        draw_key(canvas, 16 * s, 23 * s, s, 5.0)
        draw_led(canvas, 31 * s, 23 * s, s, 4.0)
    elif comp_type == "logic_led":
        canvas.create_rectangle(8 * s, 14 * s, size - 8 * s, 32 * s,
                                outline="black", width=lw)
        draw_led(canvas, center, 23 * s, s, 5.0)
    elif comp_type == "logic_block":
        canvas.create_rectangle(5 * s, 7 * s, size - 5 * s, size - 7 * s,
                                outline="black", width=lw)
        canvas.create_line(5 * s, 13 * s, size - 5 * s, 13 * s, width=1)
        for y in (19, 25, 31):
            canvas.create_line(11 * s, y * s, size - 11 * s, y * s,
                               width=1, fill="#9e9e9e")
        canvas.create_line(1 * s, 19 * s, 5 * s, 19 * s, width=1)
        canvas.create_line(1 * s, 25 * s, 5 * s, 25 * s, width=1)
    elif comp_type == "logic_function":
        canvas.create_rectangle(12 * s, 9 * s, size - 12 * s, size - 9 * s,
                                outline="black", width=lw)
        canvas.create_text(center, center, text="&",
                           font=("Arial", max(7, int(10 * s)), "bold"))
        canvas.create_line(4 * s, 16 * s, 12 * s, 16 * s, width=1)
        canvas.create_line(4 * s, 30 * s, 12 * s, 30 * s, width=1)
        canvas.create_line(size - 12 * s, center, size - 4 * s, center,
                           width=1)
