# -*- coding: utf-8 -*-
"""Извлечение условных обозначений из DXF в таблицу символов редактора.

Источник: ``mount_elements/Чертеж1.txt`` (DWG, сохранённый как DXF ASCII).
На чертеже каждый символ подписан текстом MTEXT; геометрия символа — это
линии, полилинии, дуги и окружности рядом с подписью. Скрипт берёт геометрию
по номеру сущности (порядок в секции ENTITIES), переносит её в локальные
координаты символа и записывает ``schematic_symbols.py``.

Если чертёж изменится, достаточно поправить таблицу ``SYMBOLS`` ниже и
запустить скрипт заново:

    python tools/dxf_to_schematic.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "mount_elements", "Чертеж1.txt")
OUTPUT = os.path.join(ROOT, "schematic_symbols.py")

# Масштаб DXF -> мировые единицы редактора (CELL = 20).
SCALE = 3.0

# Описание символов: тип, название, префикс обозначения, номера сущностей
# в секции ENTITIES, подпись на чертеже и порты в координатах DXF.
# Порты заданы в тех же координатах, что и геометрия, и масштабируются
# вместе с ней.
SYMBOLS = [
    dict(type="sc_current_input", title="Токовый вход", prefix="TA",
         label="токовый вход", entities=(2, 3, 4, 5, 6, 7),
         ports={"left": (23.5, 308.0), "right": (50.5, 308.0)}),
    dict(type="sc_voltage_input", title="Вход напряжения", prefix="TV",
         label="вход напряжения", entities=(62, 63, 64, 65, 66),
         ports={"left": (137.5, 311.0), "right": (164.5, 311.0)}),
    dict(type="sc_break_point", title="Точка разрыва", prefix="X",
         label="Точка разрыва", entities=(0, 1),
         ports={"left": (103.5, 317.0), "right": (108.5, 317.0)}),
    dict(type="sc_lamp", title="Лампа", prefix="HL",
         label="лампа", entities=(67, 68, 69, 70, 71),
         ports={"left": (30.5, 281.0), "right": (48.5, 281.0)}),
    dict(type="sc_busbar", title="Шинка", prefix="BB",
         label="Шинка", entities=(72, 73, 74, 75),
         ports={"left": (30.5, 256.0), "right": (42.5, 256.0)}),
    dict(type="sc_resistor", title="Резистор", prefix="R",
         label="Резистор", entities=(77, 78, 79),
         ports={"left": (26.5, 235.0), "right": (44.5, 235.0)}),
    dict(type="sc_device_terminal", title="Клемма устройства", prefix="X",
         label="Клемма устройства", entities=(8,),
         ports={"left": (87.5, 283.0), "right": (99.5, 283.0)}),
    dict(type="sc_closing_contact", title="Замыкающий контакт", prefix="KA",
         label="замыкающий контакт", entities=(47, 48, 49, 50),
         ports={"left": (80.5, 232.0), "right": (107.5, 235.4)}),
    dict(type="sc_opening_contact", title="Размыкающий контакт", prefix="KA",
         label="размыкающий контакт", entities=(51, 52, 53, 54, 55),
         ports={"left": (82.5, 254.0), "right": (110.5, 250.0)}),
    dict(type="sc_changeover_contact", title="Переключающий контакт",
         prefix="SA", label="переключающий контакт",
         entities=(56, 57, 58, 59, 60, 61),
         ports={"common": (82.5, 208.0), "contact1": (110.5, 212.0),
                "contact2": (97.5, 214.0)}),
    dict(type="sc_switch_on", title="Переключатель 2-позиционный (вкл.)",
         prefix="SA", label="Переключатель 2-позиционный, включенный",
         entities=(20, 21, 22, 23, 24, 25, 26),
         ports={"left": (81.5, 149.0), "right": (99.5, 149.0)}),
    dict(type="sc_switch_off", title="Переключатель 2-позиционный (откл.)",
         prefix="SA", label="Переключатель 2-позиционный, отключенный",
         entities=(13, 14, 15, 16, 17, 18, 19),
         ports={"left": (80.5, 178.0), "right": (98.5, 178.0)}),
    dict(type="sc_relay_coil", title="Катушка реле", prefix="KA",
         label="Катушка реле", entities=(27, 28, 29, 30, 31, 32, 33, 34, 35, 36),
         ports={"left": (135.5, 140.0), "right": (153.5, 140.0)}),
    dict(type="sc_device", title="Устройство", prefix="A",
         label="устройство", entities=(43, 44, 45, 46),
         ports={"left": (61.5, 63.0), "right": (85.5, 63.0)}),
    dict(type="sc_discrete_input", title="Дискретный вход", prefix="DI",
         label="дискретный вход", entities=(9, 10, 11, 12),
         ports={"left": (139.5, 253.0), "right": (160.5, 253.0)}),
    dict(type="sc_feed_terminal", title="Клемма проходная", prefix="X",
         label="клемма проходная", entities=(40,),
         ports={"left": (137.5, 102.0), "right": (139.5, 102.0)}),
    dict(type="sc_disconnect_terminal", title="Клемма с размыкателем",
         prefix="X", label="клемма с размыкателем", entities=(41, 42),
         ports={"left": (138.5, 82.0), "right": (140.5, 82.0)}),
]

#: Дополнительные элементы: отдельный DXF и YAML-описание полей/портов.
#: Поля — подписи MTEXT, которые нужно нарисовать на символе; порты
#: задаются словами «Начало/Конец» и «отрезок слева/справа».
EXTRA_SYMBOLS = [
    dict(type="sc_test_block", title="Тестовый блок", prefix="TB",
         path=os.path.join("mount_elements", "test_block.txt"),
         description=os.path.join("mount_elements", "test_block.yaml")),
]

GEO = ("LINE", "LWPOLYLINE", "CIRCLE", "ARC")


def _pairs(path):
    data = open(path, encoding="cp1251", errors="replace").read().splitlines()
    return [(data[i].strip(), data[i + 1].rstrip())
            for i in range(0, len(data) - 1, 2)]


def _entity_groups(pairs, start, end):
    out, cur = [], None
    for code, value in pairs[start:end]:
        if code == "0":
            cur = [(code, value)]
            out.append(cur)
        elif cur is not None:
            cur.append((code, value))
    return out


def _section(pairs, name):
    start = end = None
    for i, pair in enumerate(pairs):
        if pair == ("0", "SECTION") and i + 1 < len(pairs) \
                and pairs[i + 1][1].strip() == name:
            start = i + 2
        elif start is not None and pair == ("0", "ENDSEC"):
            end = i
            break
    if start is None or end is None:
        raise ValueError("Секция %s не найдена в DXF" % name)
    return _entity_groups(pairs, start, end)


def _fields(group):
    result = defaultdict(list)
    for code, value in group[1:]:
        result[code].append(value.strip())
    return result


def _one(fields, code, default=""):
    return fields[code][0] if fields[code] else default


def _num(fields, code, default=0.0):
    try:
        return float(_one(fields, code, default))
    except (TypeError, ValueError):
        return default


def _decode(text):
    return re.sub(r"\\U\+([0-9A-Fa-f]{4})",
                  lambda m: chr(int(m.group(1), 16)), text or "")


def _expand(group, blocks, apply_scale=False):
    """INSERT -> список примитивов блока со сдвигом и (опционально) масштабом.

    Для основного чертежа масштаб INSERT не применяется: таблица SYMBOLS
    собрана по прежним координатам, и её нельзя менять при перегенерации.
    """
    kind = group[0][1].strip()
    fields = _fields(group)
    if kind == "INSERT":
        name = _one(fields, "2")
        dx, dy = _num(fields, "10"), _num(fields, "20")
        sx = (_num(fields, "41", 1.0) or 1.0) if apply_scale else 1.0
        sy = (_num(fields, "42", 1.0) or 1.0) if apply_scale else 1.0
        return [_primitive(sub, dx, dy, sx, sy)
                for sub in blocks.get(name, [])]
    return [_primitive(group, 0.0, 0.0)]


def _primitive(group, dx, dy, sx=1.0, sy=1.0):
    kind = group[0][1].strip()
    if kind not in GEO:
        return None
    fields = _fields(group)
    if _one(fields, "60") == "1":  # невидимая линия динамического блока
        return None
    if kind == "LINE":
        return ("line",
                _num(fields, "10") * sx + dx, _num(fields, "20") * sy + dy,
                _num(fields, "11") * sx + dx, _num(fields, "21") * sy + dy)
    if kind == "LWPOLYLINE":
        points, x = [], None
        for code, value in group[1:]:
            if code == "10":
                x = float(value)
            elif code == "20" and x is not None:
                points.append((x * sx + dx, float(value) * sy + dy))
                x = None
        closed = bool(int(_num(fields, "70")) & 1)
        return ("poly", points, closed)
    if kind == "CIRCLE":
        return ("circle", _num(fields, "10") * sx + dx,
                _num(fields, "20") * sy + dy,
                _num(fields, "40") * max(abs(sx), abs(sy)))
    if kind == "ARC":
        # Зеркальный INSERT по X: угол отсчитывается в другую сторону.
        start, end = _num(fields, "50"), _num(fields, "51")
        if sx < 0:
            start, end = 180.0 - end, 180.0 - start
        return ("arc", _num(fields, "10") * sx + dx,
                _num(fields, "20") * sy + dy,
                _num(fields, "40") * max(abs(sx), abs(sy)), start, end)
    return None


def _blocks(pairs):
    result = {}
    current = None
    for group in _section(pairs, "BLOCKS"):
        kind = group[0][1].strip()
        if kind == "BLOCK":
            names = _fields(group)["2"]
            current = names[0] if names else None
            if current:
                result[current] = []
        elif kind == "ENDBLK":
            current = None
        elif current and kind in GEO:
            result[current].append(group)
    return result


def _bounds(primitives):
    xs, ys = [], []
    for item in primitives:
        kind = item[0]
        if kind == "line":
            xs += [item[1], item[3]]
            ys += [item[2], item[4]]
        elif kind == "poly":
            xs += [p[0] for p in item[1]]
            ys += [p[1] for p in item[1]]
        elif kind in ("circle", "arc"):
            xs += [item[1] - item[3], item[1] + item[3]]
            ys += [item[2] - item[3], item[2] + item[3]]
        elif kind == "text":
            # Приблизительные габариты подписи — только для рамки выделения.
            _, text, tx, ty = item
            half = max(3.0, len(text) * 2.0)
            xs += [tx - half, tx + half]
            ys += [ty - 4.0, ty + 4.0]
    return min(xs), min(ys), max(xs), max(ys)


def _local(value, cx, cy):
    """DXF (Y вверх) -> локальные координаты редактора (Y вниз)."""
    x, y = value
    return (round((x - cx) * SCALE, 3), round(-(y - cy) * SCALE, 3))


def _transform(prim, cx, cy):
    if prim[0] == "line":
        return ("line",) + _local((prim[1], prim[2]), cx, cy) \
            + _local((prim[3], prim[4]), cx, cy)
    if prim[0] == "poly":
        return ("poly", [_local(p, cx, cy) for p in prim[1]], prim[2])
    if prim[0] == "circle":
        return ("circle",) + _local((prim[1], prim[2]), cx, cy) \
            + (round(prim[3] * SCALE, 3),)
    if prim[0] == "arc":
        # Arc в tkinter считает углы против часовой стрелки от оси X вниз,
        # поэтому при отражении Y меняем направление: -a2..-a1.
        return ("arc",) + _local((prim[1], prim[2]), cx, cy) \
            + (round(prim[3] * SCALE, 3), round(-prim[5], 3),
               round(-prim[4], 3))
    return prim


def _render_number(value):
    text = ("%.3f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _literal(value):
    if isinstance(value, tuple):
        return "(" + ", ".join(_literal(v) for v in value) + (
            ",)" if len(value) == 1 else ")")
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, bool):
        return "True" if value else "False"
    return _render_number(value)


def _entities(pairs, apply_scale=False):
    """Геометрия и подписи ENTITIES; INSERT раскрывается в примитивы.

    Номера сущностей в таблице SYMBOLS считаются только по геометрии,
    INSERT и подписям: служебные ATTDEF/HATCH в них не входят.
    """
    blocks = _blocks(pairs)
    entities = []
    labels = {}
    for group in _section(pairs, "ENTITIES"):
        kind = group[0][1].strip()
        if kind in GEO or kind == "INSERT":
            for prim in _expand(group, blocks, apply_scale):
                if prim:
                    entities.append(prim)
        elif kind in ("MTEXT", "TEXT"):
            fields = _fields(group)
            text = _decode("".join(fields["1"]))
            if text:
                entities.append(("text", text))
                labels[text.strip().lower()] = (_num(fields, "10"),
                                                _num(fields, "20"))
    return entities, labels


def _read_description(path):
    """Поля и порты из YAML-описания элемента (простой формат проекта)."""
    fields, ports = [], {}
    section = None
    current = None
    with open(path, encoding="utf-8-sig") as handle:
        for raw in handle:
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("Поля:"):
                section, current = "fields", None
                continue
            if line.startswith("Порты:"):
                section, current = "ports", None
                continue
            if section == "fields" and line.strip().startswith("- "):
                fields.append(line.strip()[2:].strip())
                continue
            if section != "ports":
                continue
            match = re.match(r"^\s+(\d+):\s*$", line)
            if match:
                current = match.group(1)
                ports[current] = {}
                continue
            match = re.match(r"^\s+(Начало|Конец):\s*(.+?)\s*$", line)
            if match and current:
                ports[current][match.group(1)] = match.group(2)
    return fields, ports


def _port_point(lines, phrase):
    """Точка порта: «отрезок слева» — левый конец, «справа» — правый."""
    side = phrase.lower()
    if "слева" in side:
        line = min(lines, key=lambda item: min(item[1], item[3]))
        _kind, x1, y1, x2, y2 = line
        return (x1, y1) if x1 <= x2 else (x2, y2)
    if "справа" in side:
        line = max(lines, key=lambda item: max(item[1], item[3]))
        _kind, x1, y1, x2, y2 = line
        return (x1, y1) if x1 >= x2 else (x2, y2)
    raise ValueError("не понятно, где порт: %r" % phrase)


def _extra_symbol(spec):
    """Символ из отдельного DXF с полями и портами из YAML."""
    path = os.path.join(ROOT, spec["path"])
    entities, labels = _entities(_pairs(path), apply_scale=True)
    raw = [prim for prim in entities if prim[0] != "text"]
    if not raw:
        raise ValueError("Нет геометрии в %s" % path)
    x1, y1, x2, y2 = _bounds(raw)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    primitives = [_transform(prim, cx, cy) for prim in raw]

    field_names, port_specs = _read_description(
        os.path.join(ROOT, spec["description"]))
    fields = {}
    field_primitives = []
    for name in field_names:
        point = labels.get(name.strip().lower())
        if point is None:
            raise ValueError("Подпись %r не найдена в %s" % (name, path))
        lx, ly = _local(point, cx, cy)
        fields[name] = {"x": lx, "y": ly}
        field_primitives.append(("text", name, lx, ly))

    lines = [prim for prim in raw if prim[0] == "line"]
    ports = {}
    for name, anchors in port_specs.items():
        for anchor, phrase in anchors.items():
            point = _port_point(lines, phrase)
            lx, ly = _local(point, cx, cy)
            ports[name] = {
                "x": lx, "y": ly,
                "direction": "in" if anchor == "Начало" else "out",
            }

    bx1, by1, bx2, by2 = _bounds(primitives + field_primitives)
    return {
        "type": spec["type"],
        "title": spec["title"],
        "prefix": spec["prefix"],
        "source": spec["title"],
        "primitives": primitives,
        "ports": ports,
        "fields": fields,
        "bbox": (round(bx1, 3), round(by1, 3),
                 round(bx2, 3), round(by2, 3)),
    }


def build():
    entities, labels = _entities(_pairs(SOURCE))

    result = []
    for spec in SYMBOLS:
        label_key = spec["label"].lower()
        if label_key not in labels:
            raise ValueError("Подпись %r не найдена в DXF" % spec["label"])
        raw = []
        for index in spec["entities"]:
            if index >= len(entities):
                raise ValueError("Нет сущности #%d в DXF" % index)
            prim = entities[index]
            if prim[0] == "text":
                raise ValueError("Сущность #%d — подпись, не геометрия" % index)
            raw.append(prim)
        if not raw:
            raise ValueError("Пустой символ %s" % spec["type"])
        x1, y1, x2, y2 = _bounds(raw)
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        primitives = [_transform(p, cx, cy) for p in raw]
        bx1, by1, bx2, by2 = _bounds(primitives)
        ports = {
            name: {"x": _local(xy, cx, cy)[0], "y": _local(xy, cx, cy)[1],
                   "direction": "out" if name in
                   ("right", "contact1", "contact2") else "in"}
            for name, xy in spec["ports"].items()
        }
        result.append({
            "type": spec["type"],
            "title": spec["title"],
            "prefix": spec["prefix"],
            "source": spec["label"],
            "primitives": primitives,
            "ports": ports,
            "bbox": (round(bx1, 3), round(by1, 3),
                     round(bx2, 3), round(by2, 3)),
        })
    return result


def write(symbols):
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""Условные обозначения принципиальной схемы шкафа.',
        "",
        "Сгенерировано из mount_elements/Чертеж1.txt и",
        "mount_elements/test_block.txt скриптом tools/dxf_to_schematic.py.",
        "Не редактируйте вручную — измените описание символов в скрипте",
        "и запустите его заново.",
        '"""',
        "",
        "SCALE = %s" % _render_number(SCALE),
        "",
        "SYMBOLS = {",
    ]
    for item in symbols:
        lines.append("    %r: {" % item["type"])
        for key in ("title", "prefix", "source"):
            lines.append("        %r: %r," % (key, item[key]))
        lines.append("        'bbox': %s," % _literal(item["bbox"]))
        lines.append("        'primitives': [")
        for prim in item["primitives"]:
            lines.append("            %s," % _literal(prim))
        lines.append("        ],")
        lines.append("        'ports': {")
        for name, port in item["ports"].items():
            lines.append("            %r: {'x': %s, 'y': %s, 'direction': %r},"
                         % (name, _render_number(port["x"]),
                            _render_number(port["y"]), port["direction"]))
        lines.append("        },")
        if item.get("fields"):
            lines.append("        'fields': {")
            for name, field in item["fields"].items():
                lines.append("            %r: {'x': %s, 'y': %s},"
                             % (name, _render_number(field["x"]),
                                _render_number(field["y"])))
            lines.append("        },")
        lines.append("    },")
    lines += ["}", ""]
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print("Записано %d символов: %s" % (len(symbols), OUTPUT))


def main():
    if not os.path.exists(SOURCE):
        sys.stderr.write("Нет файла %s\n" % SOURCE)
        return 1
    symbols = build()
    symbols.extend(_extra_symbol(spec) for spec in EXTRA_SYMBOLS)
    write(symbols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
