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
import re

import ea_model
import schematic_library as sl
from library import CELL, Component

#: Части МЭК 61850-пути, общие с моделью стандарта.
IEC_PARTS = ea_model.IEC_PARTS

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
    # Принципиальная схема шкафа: обычные проводники между контактами,
    # клеммами и входами/выходами устройств.
    "schematic": {
        "title": "Цепь принципиальной схемы",
        "full": "Цепь принципиальной схемы шкафа",
        "color": "#212121",
        "dash": None,
        "width": 1.4,
    },
}

LOGIC_LINK_ORDER = ("analog", "discrete", "control", "internal", "external",
                    "schematic")

#: С какого номера начинается автоматическая нумерация связей.
LOGIC_LINK_START = 9000

LOGIC_COMPONENT_TYPES = (
    "logic_bus", "logic_key", "logic_led", "logic_block", "logic_function",
    "logic_port_in", "logic_port_out",
)

PREFIX_BY_TYPE = {
    "logic_bus": "Ш",
    "logic_key": "К",
    "logic_led": "HL",
    "logic_block": "Б",
    "logic_function": "ЛУ",
    "logic_port_in": "X",
    "logic_port_out": "X",
}

ELEMENT_TYPE_TITLES = {
    "logic_bus": "Шина вертикальная",
    "logic_key": "Функциональная клавиша",
    "logic_led": "Светодиод",
    "logic_block": "Функциональный блок (логическое устройство)",
    "logic_function": "Логический узел",
    "logic_port_in": "Входной порт",
    "logic_port_out": "Выходной порт",
}

PALETTE_ITEMS = [
    ("Шина вертикальная (ФЛС)", "logic_bus"),
    ("Функциональная клавиша", "logic_key"),
    ("Светодиод", "logic_led"),
    ("Функциональный блок", "logic_block"),
    ("Логический узел (И, ИЛИ, НЕ…)", "logic_function"),
    ("Входной порт", "logic_port_in"),
    ("Выходной порт", "logic_port_out"),
]

# Принципиальная схема шкафа: обозначения перенесены из DXF.
SCHEMATIC_COMPONENT_TYPES = sl.COMPONENT_TYPES
SCHEMATIC_PALETTE_ITEMS = sl.PALETTE_ITEMS
ALL_COMPONENT_TYPES = LOGIC_COMPONENT_TYPES + SCHEMATIC_COMPONENT_TYPES


def is_schematic_type(comp_type):
    """Относится ли тип к элементам принципиальной схемы шкафа."""
    return sl.is_schematic_type(comp_type)


def is_logic_type(comp_type):
    """Тип работает через общий слой ФЛС/принципиальной схемы."""
    return (comp_type in LOGIC_COMPONENT_TYPES
            or is_schematic_type(comp_type))


PREFIX_BY_TYPE.update(sl.PREFIX_BY_TYPE)
ELEMENT_TYPE_TITLES.update(sl.TYPE_TITLES)

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

#: Перечисление SlotTypes из structure2.xml.
SLOT_TYPES = ea_model.SLOT_TYPES
SLOT_TYPE_ORDER = ea_model.SLOT_TYPE_ORDER
DEFAULT_SLOT_TYPE = ea_model.DEFAULT_SLOT_TYPE


def slot_type_title(slot_type):
    return SLOT_TYPES.get(slot_type, "")


def slot_kind(slot_type):
    """Вид связи ФЛС, соответствующий типу слота."""
    return ea_model.link_kind_for_slot(slot_type)


def slot_type_for_kind(kind):
    return ea_model.slot_type_for_link(kind)


def new_slot(direction="in", name="", description="", iec_name="",
             slot_type=""):
    """Вход/выход функции по модели structure2 (Input / Output)."""
    return ea_model.new_slot(direction, name, description, iec_name,
                             slot_type or DEFAULT_SLOT_TYPE)


def slot_type_for_code(code):
    """Тип слота по коду входа блока: A… — аналоговый, C… — управляющий."""
    prefix = str(code or "").strip()[:1].upper()
    if prefix == "A":
        return "analog_process_level"
    if prefix == "C":
        return "control_operation"
    if prefix == "G":
        return "external_info_exchange"
    if prefix == "S":
        return "internal_info_exchange"
    return "discrete_process_level"


def slot_label(slot, fallback=""):
    """Подпись слота: русское имя, МЭК или запасной текст."""
    return signal_text(slot.get("name"), slot.get("iec_name"),
                       slot.get("description") or fallback)


def normalize_slots(values, direction="in"):
    """Список слотов из JSON: понимает число, строку и список словарей."""
    if isinstance(values, int) and not isinstance(values, bool):
        return [new_slot(direction) for _ in range(max(0, values))]
    if not isinstance(values, (list, tuple)):
        return []
    result = []
    for item in values:
        if isinstance(item, str):
            result.append(new_slot(direction, name=item,
                                   slot_type=slot_type_for_code(item)))
        elif isinstance(item, dict):
            result.append(ea_model.normalize_slot(item, direction))
    return result


def normalize_function(function):
    """Функция ФЛС по полям structure2: слоты, уставки, параметры."""
    function = dict(function or {})
    kind = str(function.get("kind") or "AND").upper()
    if kind not in FUNCTION_KINDS:
        kind = "CUSTOM"
    inputs = function.get("inputs")
    if inputs is None and function.get("input_count") is not None:
        inputs = function.get("input_count")
    slots_in = normalize_slots(inputs, "in")
    if not slots_in and isinstance(inputs, int) and inputs > 0:
        slots_in = [new_slot("in") for _ in range(inputs)]
    slots_out = normalize_slots(function.get("outputs"), "out")
    if not slots_out:
        slots_out = [new_slot("out")]
    for index, slot in enumerate(slots_in, 1):
        slot["id"] = slot.get("id") or "in%d" % index
    for index, slot in enumerate(slots_out, 1):
        slot["id"] = slot.get("id") or "out%d" % index
    settings = []
    for item in function.get("settings") or []:
        settings.append(ea_model.normalize_setting(item))
    parameters = []
    for item in function.get("parameters") or []:
        parameters.append(ea_model.normalize_parameter(item))
    return {
        "kind": kind,
        "title": str(function.get("title") or ""),
        "name": str(function.get("name") or ""),
        "ru": str(function.get("ru") or ""),
        "iec": str(function.get("iec") or ""),
        "iec_name": str(function.get("iec_name") or ""),
        "LNclass": str(function.get("LNclass") or ""),
        **{part: str(function.get(part) or "")
           for part in ea_model.IEC_PARTS},
        "inputs": slots_in,
        "outputs": slots_out,
        "settings": settings,
        "parameters": parameters,
    }


def function_slot_rows(function):
    """Сколько строк нужно функции: максимум из входов и выходов."""
    return max(len(function.get("inputs") or []),
               len(function.get("outputs") or []), 1)


def function_height(function, minimum=80, cell=20):
    """Высота функции кратна сетке и вмещает все входы и выходы."""
    need = function_slot_rows(function) * cell + 2 * cell
    return _round_up(max(minimum, need), cell)


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


def next_link_id(links):
    """Следующий свободный идентификатор связи (Connection.id)."""
    used = {str(link.get("id") or "").strip() for link in links or []}
    index = 1
    while str(index) in used:
        index += 1
    return str(index)


def port_signal_text(port):
    """Наименование сигнала вывода: имя слота и МЭК."""
    port = port or {}
    return signal_text(port.get("slot_name"), port.get("slot_iec"))


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


def _default_split_ref(ref):
    element_id, sep, port = str(ref or "").partition("#")
    return element_id, (port if sep else "")


def link_signal_text(elements, link, split_ref=None):
    """Короткое наименование сигнала связи: из полей связи или выхода."""
    split_ref = split_ref or _default_split_ref
    text = signal_text(link.get("ru"), link.get("iec"))
    if text:
        return text
    for ref in (link.get("from"), link.get("to")):
        element_id, port_name = split_ref(ref)
        element = elements.get(element_id)
        if element is None:
            continue
        port = element.ports.get(port_name) or {}
        if port.get("direction") == "out":
            text = port_signal_text(port)
            if text:
                break
    return text


_FUNCTION_OUTPUT_RE = re.compile(r"^fn(\d+)_out(\d+)$")


def link_full_label(elements, link, split_ref=None):
    """Подпись связи ФЛС и короткий сигнал для проверки дублей.

    Для связи от выхода функции внутри функционального блока выводится
    полное обозначение «ФБ / Функция: Сигнал»: «Обозначение» блока, «Имя
    функции» и «Наименование» её выхода. Если какого-то поля нет, оно
    пропускается; если полное обозначение собрать нельзя, остаётся
    обычная подпись сигнала.
    """
    split_ref = split_ref or _default_split_ref
    signal = link_signal_text(elements, link, split_ref)
    for ref in (link.get("from"), link.get("to")):
        element_id, port_name = split_ref(ref)
        element = elements.get(element_id)
        if element is None or getattr(element, "type", "") != "logic_block":
            continue
        port = element.ports.get(port_name) or {}
        if port.get("direction") != "out":
            continue
        match = _FUNCTION_OUTPUT_RE.match(port_name)
        if match is None:
            continue
        functions = getattr(element, "functions", None) or []
        fn_index, slot_index = (int(match.group(1)), int(match.group(2)))
        if fn_index >= len(functions):
            continue
        function = normalize_function(functions[fn_index])
        outputs = function.get("outputs") or []
        if slot_index >= len(outputs):
            continue
        slot = outputs[slot_index]
        signal_name = str(slot.get("name") or "").strip() or signal
        # В каталоге ФБ полная маркировка «ФБ / Функция: Сигнал» приходит
        # из таблиц информационных сигналов и хранится в описании выхода.
        full = str(slot.get("description") or "").strip()
        if " / " in full:
            return full, signal_name
        parts = []
        designation = str(getattr(element, "designation", "") or "").strip()
        function_name = str(function.get("name")
                            or function.get("title") or "").strip()
        if designation:
            parts.append(designation)
        if function_name:
            parts.append(function_name)
        label = " / ".join(parts)
        if signal_name:
            label = (label + ": " if label else "") + signal_name
        if label:
            return label, signal_name
    return signal, signal


def bus_link_color(elements, link, split_ref=None):
    """Цвет связи шина—шина — цвет подключённых шин.

    Возвращается None, если хотя бы один конец связи не шина: такие связи
    окрашиваются по своему типу. Пустой цвет шины заменяется тем же
    значением, которым шина рисуется в :meth:`LogicBus.draw`.
    """
    split_ref = split_ref or _default_split_ref
    buses = []
    for ref in (link.get("from"), link.get("to")):
        element_id, _port = split_ref(ref)
        element = elements.get(element_id)
        if element is None or getattr(element, "type", "") != "logic_bus":
            return None
        buses.append(element)
    for bus in buses:
        color = str(getattr(bus, "color", "") or "").strip()
        if color:
            return color
    return "#00acc1"


def bus_link_style(elements, link, split_ref=None):
    """Стиль связи между двумя шинами: цвет и толщина самой шины.

    Для остальных связей возвращается None — у них цвет и толщина задаются
    типом связи.
    """
    color = bus_link_color(elements, link, split_ref)
    if color is None:
        return None
    return color, float(LogicBus.WIDTH)


def link_color(elements, link, split_ref=None):
    """Цвет линии и подписей связи.

    У связи шина—шина весь цвет берётся от шины, у остальных — из стиля
    типа связи. Используется и редактором, и экспортом сцены, чтобы линия,
    номер и наименование всегда выглядели одинаково.
    """
    return bus_link_color(elements, link, split_ref) \
        or link_style(link.get("kind"))["color"]


def bus_connection_style(elements, connection):
    """Стиль провода между двумя логическими шинами: цвет и толщина шины.

    Обычные провода рисуются чёрными, но соединять две шины нужно цветом
    и толщиной самой шины — как на чертеже. Возвращает None для всех
    остальных проводов.
    """
    color = bus_link_color(elements, connection)
    if color is None:
        return None
    return color, float(LogicBus.WIDTH)


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
        self.description = ""
        self.color = "#00acc1"
        # Поля шины (название, сигнал, номер) по умолчанию не выводятся:
        # они дублируют подписи подключённых связей.
        self.show_fields = False
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
        # Шина — не вход и не выход: к ней подключаются любые связи.
        for port in self.ports.values():
            port.setdefault("direction", "bus")
            port.setdefault("slot_type", DEFAULT_SLOT_TYPE)

    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        half = self.length / 2.0
        lw = max(2, int(self.WIDTH * zoom))
        color = getattr(self, "color", "#00acc1") or "#00acc1"
        if self._vertical():
            x1, y1 = self.world_to_screen(self.x, self.y - half)
            x2, y2 = self.world_to_screen(self.x, self.y + half)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill=color)
            if getattr(self, "show_fields", False):
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
            if getattr(self, "show_fields", False):
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
                     "node_id": "N_{}_left".format(self.id),
                     "direction": "in",
                     "slot_type": DEFAULT_SLOT_TYPE},
            "right": {"x": x2, "y": self.y,
                      "node_id": "N_{}_right".format(self.id),
                      "direction": "out",
                      "slot_type": DEFAULT_SLOT_TYPE},
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
                     "node_id": "N_{}_left".format(self.id),
                     "direction": "in",
                     "slot_type": DEFAULT_SLOT_TYPE},
            "right": {"x": x2, "y": self.y,
                      "node_id": "N_{}_right".format(self.id),
                      "direction": "out",
                      "slot_type": DEFAULT_SLOT_TYPE},
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
# 4. ПОРТЫ ЗАВЕДЕНИЯ И ВЫВОДА СИГНАЛА
# ==========================================================================
class LogicPort(LogicComponent):
    """Порт связи с «внешним миром» схемы (structure2: внешний обмен).

    Входной порт заводит сигнал в схему: у него один вывод справа, и это
    выход — сигнал уходит из порта в схему. Выходной порт выводит сигнал
    из схемы: его вывод слева — вход. Наименование сигнала и номер
    маркировки служат источником для связей («Обновить связи»).
    """

    WIDTH = 120
    HEIGHT = 40
    STUB = 20          # длина вывода подключения — 1 клетка

    #: Направление сигнала на выводе: "out" у входного порта, "in" —
    #: у выходного.
    PORT_DIRECTION = "out"
    TITLE = "Порт"

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = ("logic_port_in" if self.PORT_DIRECTION == "out"
                     else "logic_port_out")
        self.title = self.TITLE
        self.generate_ports()

    # ---------- геометрия ----------
    def _rect(self):
        half_w = self.WIDTH / 2.0
        half_h = self.HEIGHT / 2.0
        return (self.x - half_w, self.y - half_h,
                self.x + half_w, self.y + half_h)

    def _stub_line(self):
        """Линия вывода: (начало, конец) в мировых координатах."""
        x1, _y1, x2, _y2 = self._rect()
        if self.PORT_DIRECTION == "out":
            return (x2, self.y), (x2 + self.STUB, self.y)
        return (x1, self.y), (x1 - self.STUB, self.y)

    # ---------- порты ----------
    def generate_ports(self):
        (start_x, start_y), (end_x, end_y) = self._stub_line()
        self.ports = {
            "stub": {
                "x": end_x, "y": end_y,
                "node_id": "N_{}_stub".format(self.id),
                "direction": self.PORT_DIRECTION,
                "slot_type": DEFAULT_SLOT_TYPE,
                # Имена сигнала — для подписи новой связи и «Обновить связи».
                "slot_name": self.signal_ru,
                "slot_iec": self.signal_iec,
            },
        }

    # ---------- отрисовка ----------
    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="black", width=lw)
        (start_x, start_y), (end_x, end_y) = self._stub_line()
        canvas.create_line(*self.world_to_screen(start_x, start_y),
                           *self.world_to_screen(end_x, end_y),
                           width=lw, fill="black")
        # Стрелка направления сигнала внутри рамки: вправо у входного
        # порта, влево у выходного.
        if self.PORT_DIRECTION == "out":
            tip, base = x2 - 10, x2 - 30
        else:
            tip, base = x1 + 10, x1 + 30
        tip_x, tip_y = self.world_to_screen(tip, self.y)
        b1_x, b1_y = self.world_to_screen(base, self.y - 10)
        b2_x, b2_y = self.world_to_screen(base, self.y + 10)
        canvas.create_polygon(tip_x, tip_y, b1_x, b1_y, b2_x, b2_y,
                              fill="black")

        self._draw_title(canvas, zoom, offset_x, offset_y,
                         self.x, y1 - 10, anchor="s")
        self._draw_name(canvas, zoom, offset_x, offset_y, x1 + 4, y1 + 2)
        # Наименование сигнала — с той стороны, где нет вывода.
        if self.PORT_DIRECTION == "out":
            self._draw_signal(canvas, zoom, offset_x, offset_y,
                              x2 + 8, self.y, size=7)
            number_x = x2 + 8 + max(70.0, _text_width(
                signal_text(self.signal_ru, self.signal_iec), 7) + 16)
            self._draw_number(canvas, zoom, offset_x, offset_y,
                              number_x, self.y, size=7)
        else:
            text = signal_text(self.signal_ru, self.signal_iec)
            if text:
                tx, ty = self.world_to_screen(x2 + 8, self.y)
                canvas.create_text(tx, ty, text=text, anchor="w",
                                   font=("Arial", _font_size(zoom, 7)),
                                   fill="#7b1fa2", justify="left")
            number = (self.signal_no or "").strip()
            if number:
                number_x = x2 + 8 + max(70.0, _text_width(text, 7) + 16)
                nx, ny = self.world_to_screen(number_x, self.y)
                canvas.create_text(nx, ny, text=number, anchor="w",
                                   font=("Arial", _font_size(zoom, 7)),
                                   fill="#1f4e79")

    def get_bounding_box(self):
        x1, y1, x2, y2 = self._rect()
        (_sx, _sy), (ex, _ey) = self._stub_line()
        left, right = min(x1, ex), max(x2, ex)
        # Название над рамкой и вывод — часть кликабельной области.
        return (left, y1 - 18, right, y2)


class LogicPortIn(LogicPort):
    """Входной порт: заведение сигнала извне схемы (вывод — выход)."""

    PORT_DIRECTION = "out"
    TITLE = "Входной порт"


class LogicPortOut(LogicPort):
    """Выходной порт: вывод сигнала из схемы (вывод — вход)."""

    PORT_DIRECTION = "in"
    TITLE = "Выходной порт"


# ==========================================================================
# 5. ЛОГИЧЕСКИЙ УЗЕЛ
# ==========================================================================
class LogicFunction(LogicComponent):
    """Логический узел: прямоугольник со входами слева и выходами справа.

    Каждый вход и выход — слот ``SlotTypes`` с собственным портом. Уставки и
    параметры (программные переключатели) хранятся внутри функции и на
    функциональной схеме не отображаются.
    """

    WIDTH = 120
    MIN_HEIGHT = 80

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_function"
        self.kind = "AND"
        self.title = ""
        self.iec_name = ""
        self.LNclass = ""
        self.LD = self.LN = self.DO = self.DA = ""
        self.signal_ru = ""
        self.signal_iec = ""
        self.input_count = 2
        self.inputs = []
        self.outputs = []
        self.settings = []
        self.parameters = []
        self.generate_ports()

    # ---------- слоты ----------
    def _input_slots(self):
        if self.inputs:
            return [ea_model.normalize_slot(item, "in")
                    for item in self.inputs]
        count = max(1, int(self.input_count or 1))
        return [new_slot("in") for _ in range(count)]

    def _output_slots(self):
        if self.outputs:
            return [ea_model.normalize_slot(item, "out")
                    for item in self.outputs]
        return [new_slot("out")]

    def _height(self):
        return function_height({"inputs": self._input_slots(),
                                "outputs": self._output_slots()},
                               self.MIN_HEIGHT)

    def _rect(self):
        width = _round_up(self.WIDTH, CELL)
        height = self._height()
        x1 = _round_to(self.x - width / 2.0, CELL)
        y1 = _round_to(self.y - height / 2.0, CELL)
        return (x1, y1, x1 + width, y1 + height)

    @staticmethod
    def _slot_points(x, y1, y2, count):
        """Точки слотов на сетке: сверху вниз через клетку."""
        count = max(1, int(count))
        return [(x, y1 + CELL * (index + 1)) for index in range(count)]

    def generate_ports(self):
        x1, y1, x2, y2 = self._rect()
        inputs = self._input_slots()
        outputs = self._output_slots()
        self.ports = {}
        for index, (slot, point) in enumerate(zip(
                inputs, self._slot_points(x1, y1, y2, len(inputs)))):
            self.ports["in{}".format(index)] = {
                "x": point[0], "y": point[1],
                "node_id": "N_{}_in{}".format(self.id, index),
                "direction": "in",
                "slot_id": slot.get("id", ""),
                "slot_type": slot.get("type", DEFAULT_SLOT_TYPE),
                "slot_name": slot.get("name", ""),
                "slot_iec": slot.get("iec_name", ""),
            }
        for index, (slot, point) in enumerate(zip(
                outputs, self._slot_points(x2, y1, y2, len(outputs)))):
            self.ports["out{}".format(index)] = {
                "x": point[0], "y": point[1],
                "node_id": "N_{}_out{}".format(self.id, index),
                "direction": "out",
                "slot_id": slot.get("id", ""),
                "slot_type": slot.get("type", DEFAULT_SLOT_TYPE),
                "slot_name": slot.get("name", ""),
                "slot_iec": slot.get("iec_name", ""),
            }
        if "out0" in self.ports:
            # Старые связи ссылались на единственный вывод «out».
            self.ports["out"] = dict(self.ports["out0"])
            self.ports["out"]["node_id"] = "N_{}_out".format(self.id)

    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="black", width=lw)
        symbol, kind_name = FUNCTION_KINDS.get(self.kind,
                                               FUNCTION_KINDS["CUSTOM"])
        # Символ ставим правее подписей входов, чтобы не накладывался
        # на них, но не дальше правого края рамки.
        inputs = self._input_slots()
        labels_right = max([6.0 + _text_width(
            slot_label(slot, "in%d" % index), 6)
            for index, slot in enumerate(inputs)] or [0.0])
        cx, cy = self.world_to_screen(
            min(max(x1 + 40, x1 + labels_right + 8), x2 - 16),
            (y1 + y2) / 2.0)
        canvas.create_text(cx, cy, text=symbol,
                           font=("Arial", _font_size(zoom, 14), "bold"),
                           fill="black")

        for index, (slot, point) in enumerate(zip(
                inputs, self._slot_points(x1, y1, y2, len(inputs)))):
            sx, sy = self.world_to_screen(*point)
            canvas.create_line(sx - 8 * zoom, sy, sx, sy,
                               width=lw, fill="black")
            canvas.create_text(sx + 6 * zoom, sy,
                               text=slot_label(slot, "in%d" % index),
                               anchor="w",
                               font=("Arial", _font_size(zoom, 6)),
                               fill="#333333")
        outputs = self._output_slots()
        for index, (slot, point) in enumerate(zip(
                outputs, self._slot_points(x2, y1, y2, len(outputs)))):
            sx, sy = self.world_to_screen(*point)
            canvas.create_line(sx, sy, sx + 8 * zoom, sy,
                               width=lw, fill="black")
            canvas.create_text(sx - 6 * zoom, sy,
                               text=slot_label(slot, "out%d" % index),
                               anchor="e",
                               font=("Arial", _font_size(zoom, 6)),
                               fill="#333333")

        self._draw_title(canvas, zoom, offset_x, offset_y,
                         self.x, y1 - 10, anchor="s")
        self._draw_name(canvas, zoom, offset_x, offset_y, x1 + 4, y1 + 2)
        self._draw_signal(canvas, zoom, offset_x, offset_y,
                          x2 + 10, y1 + 6, size=7)
        self._draw_number(canvas, zoom, offset_x, offset_y,
                          x2 + 10, y1 + 20, size=7)
        if self.title:
            canvas.create_text(cx, cy + 12 * zoom, text=kind_name,
                               font=("Arial", _font_size(zoom, 6)),
                               fill="#666666")

    def get_bounding_box(self):
        x1, y1, x2, y2 = self._rect()
        # Название над рамкой — часть кликабельной области элемента.
        return (x1, y1 - 18, x2, y2)


# ==========================================================================
# 6. ФУНКЦИОНАЛЬНЫЙ БЛОК
# ==========================================================================
class LogicBlock(LogicComponent):
    """Функциональный блок — контейнер для функций (structure2.xml).

    Блок — это рамка с именем сверху; внутри сверху вниз идут функции.
    Собственных входов и выходов у блока нет: все слоты (входы слева,
    выходы справа) принадлежат функциям, и у каждого слота есть свой
    порт для подключения связи.

    Геометрия кратна сетке (``CELL`` = 20): кромки блока лежат на линиях
    сетки, все выводы — на их пересечениях, поэтому связи ложатся по
    сетке без дробных координат.
    """

    HEADER = 40       # полоса заголовка — 2 клетки
    GAP = 20          # отступ от заголовка до функций — 1 клетка
    PAD = 20          # отступ справа и снизу — 1 клетка
    FUNC_H = 80       # минимальная высота функции — 4 клетки
    MIN_WIDTH = 360

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "logic_block"
        self.title = "Функциональный блок"
        self.designation = ""
        self.width = self.MIN_WIDTH
        # Блок — контейнер: сразу с одной функцией, чтобы у него были
        # входы слева и выход справа; остальные функции добавляет пользователь.
        self.functions = [normalize_function({
            "kind": "AND", "title": "Функция", "inputs": 1, "outputs": 1,
        })]
        # Поля FunctionBlock из structure2.xml.
        self.isMainFunction = False
        self.isInITS = False
        self.iec_name = ""
        self.LD = self.LN = self.DO = self.DA = ""
        self.russian_path = ""
        self.corp_prof_name = ""
        # Принадлежность каталогу стандарта: откуда пришёл блок.
        # Заполняется при размещении FunctionalBlockEntry на схему.
        self.cabinet = ""
        self.kit = ""
        self.ied = ""
        self.generate_ports()

    # ---------- геометрия ----------
    def _block_width(self):
        widest = _text_width(self.title, 9) + 2 * CELL
        for function in self.functions:
            function = normalize_function(function)
            widest = max(widest,
                         _text_width(function.get("title"), 8)
                         + _text_width(function.get("ru"), 8)
                         + 6 * CELL + self.PAD)
            for slot in ((function.get("inputs") or [])
                         + (function.get("outputs") or [])):
                widest = max(widest, 6 * CELL
                             + _text_width(slot_label(slot), 7) + self.PAD)
        width = max(self.MIN_WIDTH, float(self.width or 0), widest)
        return _round_up(width, 2 * CELL)

    def _layout(self):
        """Рамка блока: имя сверху, функции сверху вниз; кромки на сетке."""
        width = self._block_width()
        x1 = _round_to(self.x - width / 2.0, CELL)
        x2 = x1 + width
        # Функции занимают внутреннюю область; их левая и правая кромки —
        # это и есть порты входов и выходов соответственно.
        fx1 = _round_to(x1 + self.PAD + CELL, CELL)
        fx2 = _round_to(x2 - self.PAD - CELL, CELL)

        content_top = self.HEADER + self.GAP
        spans = []
        offset = content_top
        for function in self.functions:
            function = normalize_function(function)
            height = function_height(function, self.FUNC_H, CELL)
            spans.append((function, offset, height))
            offset += height
        content_height = offset - content_top
        height = _round_up(content_top + max(content_height, self.FUNC_H)
                           + self.PAD, 2 * CELL)
        y1 = _round_to(self.y - height / 2.0, CELL)
        y2 = y1 + height

        return {
            "x1": x1, "x2": x2, "y1": y1, "y2": y2,
            "width": width, "height": height,
            "fx1": fx1, "fx2": fx2,
            "functions": [(function, y1 + top + item_height / 2.0, item_height)
                          for function, top, item_height in spans],
        }

    @staticmethod
    def _function_slot_points(x, py, height, count):
        """Точки слотов внутри функции: сверху вниз через клетку."""
        count = max(1, int(count))
        top = py - height / 2.0 + CELL
        return [(x, top + CELL * index) for index in range(count)]

    def generate_ports(self):
        """Порты есть только у слотов функций: входы слева, выходы справа."""
        layout = self._layout()
        self.ports = {}
        for fn_index, (function, py, height) in enumerate(
                layout["functions"]):
            function = normalize_function(function)
            for slot_index, (slot, point) in enumerate(zip(
                    function.get("inputs") or [],
                    self._function_slot_points(
                        layout["fx1"], py, height,
                        len(function.get("inputs") or [])))):
                self.ports["fn{}_in{}".format(fn_index, slot_index)] = {
                    "x": point[0], "y": point[1],
                    "node_id": "N_{}_fn{}_in{}".format(
                        self.id, fn_index, slot_index),
                    "direction": "in",
                    "slot_id": slot.get("id", ""),
                    "slot_type": slot.get("type", DEFAULT_SLOT_TYPE),
                    "slot_name": slot.get("name", ""),
                    "slot_iec": slot.get("iec_name", ""),
                }
            for slot_index, (slot, point) in enumerate(zip(
                    function.get("outputs") or [],
                    self._function_slot_points(
                        layout["fx2"], py, height,
                        len(function.get("outputs") or [])))):
                self.ports["fn{}_out{}".format(fn_index, slot_index)] = {
                    "x": point[0], "y": point[1],
                    "node_id": "N_{}_fn{}_out{}".format(
                        self.id, fn_index, slot_index),
                    "direction": "out",
                    "slot_id": slot.get("id", ""),
                    "slot_type": slot.get("type", DEFAULT_SLOT_TYPE),
                    "slot_name": slot.get("name", ""),
                    "slot_iec": slot.get("iec_name", ""),
                }

    # ---------- отрисовка ----------
    def draw(self, canvas, zoom, offset_x, offset_y):
        self._draw_ctx = (zoom, offset_x, offset_y)
        layout = self._layout()
        x1, x2 = layout["x1"], layout["x2"]
        y1, y2 = layout["y1"], layout["y2"]
        sx1, sy1 = self.world_to_screen(x1, y1)
        sx2, sy2 = self.world_to_screen(x2, y2)
        lw = max(1, int(2 * zoom))

        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="#fbfdff",
                                outline="black", width=lw)
        # Линия под заголовком отделяет имя контейнера от функций.
        hy = (y1 + self.HEADER) * zoom + offset_y
        canvas.create_line(sx1, hy, sx2, hy, fill="#c8d3e0", width=1)
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

        # Функции идут сверху вниз; входы слева, выходы справа.
        for function, py, height in layout["functions"]:
            self._draw_function(canvas, zoom, offset_x, offset_y,
                                layout, function, py, height)

    def _draw_function(self, canvas, zoom, offset_x, offset_y,
                       layout, function, py, height):
        function = normalize_function(function)
        fx1, fx2 = layout["fx1"], layout["fx2"]
        fy1 = py - height / 2.0 + CELL / 2.0
        fy2 = py + height / 2.0 - CELL / 2.0
        sx1, sy1 = self.world_to_screen(fx1, fy1)
        sx2, sy2 = self.world_to_screen(fx2, fy2)
        lw = max(1, int(1.6 * zoom))
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="white",
                                outline="#444444", width=lw)
        kind = (function.get("kind") or "AND").upper()
        symbol, kind_name = FUNCTION_KINDS.get(kind, FUNCTION_KINDS["CUSTOM"])
        inputs = function.get("inputs") or []
        # Символ ставим правее подписей входов, чтобы не накладывался
        # на них, но не дальше правого края функции.
        labels_right = max([5.0 + _text_width(
            slot_label(slot, "in%d" % index), 6)
            for index, slot in enumerate(inputs)] or [0.0])
        symbol_x = min(max(30.0, labels_right + 8.0),
                       (fx2 - fx1) - 16.0)
        canvas.create_text(sx1 + symbol_x * zoom, (sy1 + sy2) / 2.0,
                           text=symbol,
                           font=("Arial", _font_size(zoom, 13), "bold"),
                           fill="black")

        for index, (slot, point) in enumerate(zip(
                inputs, self._function_slot_points(fx1, py, height,
                                                   len(inputs)))):
            sx, sy = self.world_to_screen(*point)
            canvas.create_line(sx - 6 * zoom, sy, sx, sy,
                               width=lw, fill="black")
            canvas.create_text(sx + 5 * zoom, sy,
                               text=slot_label(slot, "in%d" % index),
                               anchor="w",
                               font=("Arial", _font_size(zoom, 6)),
                               fill="#333333")
        outputs = function.get("outputs") or []
        for index, (slot, point) in enumerate(zip(
                outputs, self._function_slot_points(fx2, py, height,
                                                    len(outputs)))):
            sx, sy = self.world_to_screen(*point)
            canvas.create_line(sx, sy, sx + 6 * zoom, sy,
                               width=lw, fill="black")
            canvas.create_text(sx - 5 * zoom, sy,
                               text=slot_label(slot, "out%d" % index),
                               anchor="e",
                               font=("Arial", _font_size(zoom, 6)),
                               fill="#333333")

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

    def get_bounding_box(self):
        layout = self._layout()
        return (layout["x1"], layout["y1"] - 18,
                layout["x2"], layout["y2"])


# ==========================================================================
# Фабрика и сериализация
# ==========================================================================
def create_component(comp_type, comp_id, x, y, grid_size=20):
    if is_schematic_type(comp_type):
        return sl.create_component(comp_type, comp_id, x, y, grid_size)
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
    if comp_type == "logic_port_in":
        return LogicPortIn(comp_id, x, y, grid_size)
    if comp_type == "logic_port_out":
        return LogicPortOut(comp_id, x, y, grid_size)
    raise ValueError("Неизвестный элемент ФЛС: {}".format(comp_type))


def standard_block_functions(functions):
    """Функции structure2 → функции ФЛС редактора.

    Сохраняются русское имя и обозначение по МЭК, входы/выходы (сигналы),
    уставки и параметры — всё, что приходит из каталога функциональных
    блоков стандарта.
    """
    result = []
    for function in functions or []:
        if not isinstance(function, dict):
            continue
        result.append(normalize_function({
            "kind": "CUSTOM",
            "title": str(function.get("name") or ""),
            "name": str(function.get("name") or ""),
            "ru": str(function.get("name") or ""),
            "iec": str(function.get("iec_name") or ""),
            "iec_name": str(function.get("iec_name") or ""),
            "LNclass": str(function.get("LNclass") or ""),
            **{part: function.get(part, "") for part in ea_model.IEC_PARTS},
            "inputs": function.get("inputs") or [],
            "outputs": function.get("outputs") or [],
            "settings": function.get("settings") or [],
            "parameters": function.get("parameters") or [],
        }))
    return result


def block_from_standard(entry, comp_id, x, y, grid_size=20):
    """FunctionalBlockEntry стандарта → готовый блок на схеме ФЛС.

    Блок несёт принадлежность к шкафу/комплекту/ИЭУ и полный набор
    функций с сигналами, уставками и параметрами, поэтому его можно сразу
    помещать на чертеж из окна стандарта.
    """
    entry = entry if isinstance(entry, dict) else {}
    block = create_component("logic_block", comp_id, x, y, grid_size)
    name = str(entry.get("name") or "").strip()
    path = str(entry.get("russian_path") or "").strip()
    iec = str(entry.get("iec_name") or "").strip()
    block.title = name or path or "Функциональный блок"
    # «Обозначение» — русский префикс полной маркировки «ФБ / Функция:
    # Сигнал»; МЭК-обозначение хранится отдельным полем блока.
    block.designation = name or path or iec
    block.iec_name = iec
    for part in ea_model.IEC_PARTS:
        setattr(block, part, str(entry.get(part) or ""))
    block.russian_path = path or name
    block.corp_prof_name = str(entry.get("corp_prof_name") or "").strip()
    block.isMainFunction = bool(entry.get("isMainFunction"))
    block.isInITS = bool(entry.get("isInITS"))
    block.cabinet = str(entry.get("cabinet") or "")
    block.kit = str(entry.get("kit") or "")
    block.ied = str(entry.get("ied") or "")
    block.functions = standard_block_functions(entry.get("functions"))
    block.generate_ports()
    return block


#: Поля, которые сохраняются в JSON для каждого типа ФЛС.
LOGIC_FIELDS = {
    "logic_bus": ("length", "title", "description", "signal_ru", "signal_iec",
                  "signal_no", "color", "rotation", "show_fields"),
    "logic_key": ("title", "signal_ru", "signal_iec", "signal_no", "show_led"),
    "logic_led": ("title", "signal_ru", "signal_iec", "signal_no"),
    "logic_block": ("title", "designation", "width", "functions",
                    "isMainFunction", "isInITS", "iec_name",
                    "LD", "LN", "DO", "DA",
                    "russian_path", "corp_prof_name",
                    "cabinet", "kit", "ied"),
    "logic_function": ("kind", "title", "name", "iec_name", "LNclass",
                       "LD", "LN", "DO", "DA",
                       "signal_ru", "signal_iec", "signal_no", "input_count",
                       "inputs", "outputs", "settings", "parameters"),
    "logic_port_in": ("title", "signal_ru", "signal_iec", "signal_no"),
    "logic_port_out": ("title", "signal_ru", "signal_iec", "signal_no"),
}


def element_payload(el):
    """Поля элемента ФЛС/принципиальной схемы для JSON."""
    if is_schematic_type(getattr(el, "type", "")):
        return sl.element_payload(el)
    payload = {}
    for field in LOGIC_FIELDS.get(getattr(el, "type", ""), ()):
        if hasattr(el, field):
            payload[field] = copy.deepcopy(getattr(el, field))
    return payload


def restore_element(el, payload):
    """Восстанавливает поля ФЛС/принципиальной схемы из JSON."""
    if not isinstance(payload, dict):
        return
    if is_schematic_type(getattr(el, "type", "")):
        sl.restore_element(el, payload)
        return
    for field in LOGIC_FIELDS.get(getattr(el, "type", ""), ()):
        if field in payload:
            value = copy.deepcopy(payload[field])
            setattr(el, field, value)
    # Защита от ручных правок JSON: приводим списки и числа к рабочему виду.
    if getattr(el, "type", "") == "logic_block":
        # Блок — контейнер: собственных входов и выходов нет, все слоты
        # принадлежат функциям (structure2.xml). Устаревшие поля inputs/rows
        # из старых схем больше не восстанавливаются.
        for field in ("inputs", "rows"):
            if hasattr(el, field):
                delattr(el, field)
        functions = getattr(el, "functions", None)
        el.functions = []
        for function in functions if isinstance(functions, list) else []:
            if isinstance(function, dict):
                el.functions.append(normalize_function(function))
        for field in ("isMainFunction", "isInITS"):
            setattr(el, field, bool(getattr(el, field, False)))
        for field in ("iec_name", "russian_path", "corp_prof_name",
                      "cabinet", "kit", "ied") + ea_model.IEC_PARTS:
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, "")
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
        el.inputs = normalize_slots(getattr(el, "inputs", None), "in")
        el.outputs = normalize_slots(getattr(el, "outputs", None), "out")
        if not el.outputs:
            el.outputs = [new_slot("out")]
        for field in ("iec_name", "LNclass") + ea_model.IEC_PARTS:
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, "")
        el.settings = [ea_model.normalize_setting(item)
                       for item in getattr(el, "settings", None) or []]
        el.parameters = [ea_model.normalize_parameter(item)
                         for item in getattr(el, "parameters", None) or []]
    if getattr(el, "type", "") == "logic_bus":
        try:
            el.length = max(40.0, float(getattr(el, "length", 480)))
        except (TypeError, ValueError):
            el.length = 480.0
        if not isinstance(getattr(el, "color", ""), str):
            el.color = "#00acc1"
        if not isinstance(getattr(el, "description", ""), str):
            el.description = ""
        el.show_fields = bool(getattr(el, "show_fields", False))
    if str(getattr(el, "type", "")).startswith("logic_port"):
        for field in ("title", "signal_ru", "signal_iec", "signal_no"):
            if not isinstance(getattr(el, field, ""), str):
                setattr(el, field, "")
    el.generate_ports()


def copy_element_fields(source, target):
    """Копирует поля ФЛС/принципиальной схемы при копировании."""
    if is_schematic_type(getattr(source, "type", "")):
        sl.copy_element_fields(source, target)
        return
    for field in LOGIC_FIELDS.get(getattr(source, "type", ""), ()):
        if hasattr(source, field):
            setattr(target, field, copy.deepcopy(getattr(source, field)))
    target.generate_ports()


def draw_palette_icon(canvas, comp_type, size=46):
    """Компактный значок элемента ФЛС/принципиальной схемы для палитры."""
    if is_schematic_type(comp_type):
        sl.draw_palette_icon(canvas, comp_type, size)
        return
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
    elif comp_type in ("logic_port_in", "logic_port_out"):
        out = comp_type == "logic_port_out"
        canvas.create_rectangle(12 * s, 13 * s, size - 12 * s, 33 * s,
                                outline="black", width=lw)
        if out:
            # Выходной порт: сигнал входит в порт (стрелка влево-внутрь).
            canvas.create_line(2 * s, 23 * s, 16 * s, 23 * s, width=lw)
            canvas.create_polygon(14 * s, 19 * s, 14 * s, 27 * s, 6 * s,
                                  23 * s, fill="black")
            canvas.create_polygon(center, 23 * s, center - 8 * s, 18 * s,
                                  center - 8 * s, 28 * s, fill="#666666")
        else:
            # Входной порт: сигнал уходит из порта в схему.
            canvas.create_line(size - 2 * s, 23 * s, size - 16 * s, 23 * s,
                               width=lw)
            canvas.create_polygon(size - 14 * s, 19 * s, size - 14 * s,
                                  27 * s, size - 6 * s, 23 * s, fill="black")
            canvas.create_polygon(center, 23 * s, center + 8 * s, 18 * s,
                                  center + 8 * s, 28 * s, fill="#666666")
