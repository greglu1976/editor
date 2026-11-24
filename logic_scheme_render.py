# -*- coding: utf-8 -*-
"""Отрисовка функционально-логической схемы без редактора.

Модуль собирает схему из JSON-файла редактора (элементы + связи) и рисует
её на любой канве с примитивами Tk-canvas: на экранную канву, на записывающую
канву PDF (:class:`pdfexport.SceneRecorder`) или на растровую канву PNG
(:class:`pngexport.RasterCanvas`). Используется:

* редактором — для экспорта PDF/PNG (методы миксина делегируют сюда);
* DOCX-выгрузкой стандарта — чтобы вставить схему ИЭУ как рисунок;
* генератором схемы из функций ИЭУ — для предпросмотра.

Геометрия и подписи связей — те же, что в редакторе: линии с номером у
обоих концов и наименованием сигнала вдоль линии, без наложений.

Модуль не зависит от GUI: достаточно Pillow для PNG и pdfexport для шрифта.
"""

from __future__ import annotations

import copy
import math

import ea_standard as es
import library
import logic_library as ll
import pdfexport

try:
    import pngexport
except Exception:                                    # pragma: no cover
    pngexport = None


#: Цвет аналоговых цепей — как в редакторе.
ANALOG_COLOR = "#7b1fa2"


# ==========================================================================
# Точки и ссылки
# ==========================================================================
def clean_points(value):
    """Опорные точки связи: [[x, y], ...]; битые пары отбрасываются."""
    result = []
    if not isinstance(value, (list, tuple)):
        return result
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            x, y = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            continue
        result.append([round(x, 1), round(y, 1)])
    return result


def split_ref(ref):
    """Ссылка «id#порт» → (id, порт)."""
    element_id, sep, port = str(ref or "").partition("#")
    return element_id, (port if sep else "")


def ref_point(elements, ref):
    """Мировая точка порта по ссылке (или центр элемента)."""
    element_id, port_name = split_ref(ref)
    element = elements.get(element_id)
    if element is None:
        return None
    port = element.ports.get(port_name)
    if port:
        return (port["x"], port["y"])
    return (element.x, element.y)


def ref_valid(elements, ref):
    """Ссылка ведёт на существующий порт?"""
    element_id, port_name = split_ref(ref)
    element = elements.get(element_id)
    return element is not None and port_name in element.ports


def route(elements, link):
    """Мировые точки маршрута связи: порт → изломы → порт."""
    start = ref_point(elements, (link or {}).get("from"))
    end = ref_point(elements, (link or {}).get("to"))
    if start is None or end is None:
        return []
    result = [tuple(start)]
    result.extend((float(point[0]), float(point[1]))
                  for point in clean_points(link.get("points")))
    result.append(tuple(end))
    return result


def continuation(links, link):
    """Связь до шины, продолжением которой является данная связь."""
    reference = str((link or {}).get("continuation") or "").strip()
    if not reference:
        return {}
    for other in links or []:
        if other is link:
            continue
        if str(other.get("id") or "").strip() == reference:
            return other
    return {}


# ==========================================================================
# Подписи связей
# ==========================================================================
def link_label_text(elements, link):
    """Подпись сигнала на линии; не дублирует подпись клавиши/светодиода."""
    text, signal = ll.link_full_label(elements, link, split_ref)
    if not text:
        return ""
    link_ru = (link.get("ru") or "").strip()
    link_iec = (link.get("iec") or "").strip()
    for ref in (link.get("from"), link.get("to")):
        element_id, _port = split_ref(ref)
        element = elements.get(element_id)
        if element is None:
            continue
        if element.type in ("logic_key", "logic_led", "logic_function",
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


def link_number(elements, links, link):
    """Номер на линии; не повторяет маркировку подключённого элемента."""
    number = (link.get("number") or "").strip()
    if not number:
        number = (continuation(links, link).get("number") or "").strip()
    if not number:
        return ""
    for ref in (link.get("from"), link.get("to")):
        element_id, _port = split_ref(ref)
        element = elements.get(element_id)
        if element is not None \
                and (getattr(element, "signal_no", "") or "").strip() == number:
            return ""
    return number


# ==========================================================================
# Размещение подписей без наложений
# ==========================================================================
LABEL_FRACTIONS = (0.5, 0.38, 0.62, 0.28, 0.72, 0.2, 0.8, 0.14, 0.86)


def text_box(x, y, text, size=6.0):
    width = max(14.0, len(text) * size * 0.55)
    height = max(9.0, size * 1.4)
    return (x - width / 2.0, y - height / 2.0,
            x + width / 2.0, y + height / 2.0)


def box_busy(box, occupied, pad=2.0):
    x1, y1, x2, y2 = box
    for ox1, oy1, ox2, oy2 in occupied:
        if x1 - pad < ox2 and ox1 - pad < x2 \
                and y1 - pad < oy2 and oy1 - pad < y2:
            return True
    return False


def path_point(points, fraction):
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


def number_anchor(route, number, occupied):
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
        box = text_box(nx, ny, number)
        if fallback is None:
            fallback = (nx, ny, box)
        if not box_busy(box, occupied):
            return nx, ny, box
    return fallback


def end_number_anchor(route, number, occupied):
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
        box = text_box(nx, ny, number)
        if fallback is None:
            fallback = (nx, ny, box)
        if not box_busy(box, occupied):
            return nx, ny, box
    return fallback


def label_anchor(route, text, occupied, offset=12.0):
    """Позиция подписи сигнала вдоль линии с обходом занятых мест."""
    fallback = None
    for fraction in LABEL_FRACTIONS:
        point = path_point(route, fraction)
        if point is None:
            continue
        px, py, ux, uy = point
        x, y = px - uy * offset, py + ux * offset
        box = text_box(x, y, text)
        if fallback is None:
            fallback = (x, y, box)
        if not box_busy(box, occupied):
            return x, y, box
    return fallback


def valid_offset(value):
    """Смещение [dx, dy] из JSON или None."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return None
    return None


def shifted_anchor(anchor, offset):
    """Аннотация, сдвинутая на сохранённое мышкой смещение."""
    if anchor is None:
        return None
    offset = valid_offset(offset)
    if offset is None or (not offset[0] and not offset[1]):
        return anchor
    dx, dy = offset
    x, y, box = anchor
    return (x + dx, y + dy,
            (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))


def annotations(elements, links, prepared):
    """Маркировки и подписи связей без наложений.

    Маркировка рисуется у обоих концов связи (structure2: «на концах и
    на начале»), имя — вдоль линии. Смещения, заданные перетаскиванием
    в редакторе (``mark_offsets``/``label_offset``), сдвигают аннотации
    с автопозиции — экспорт совпадает с тем, что нарисовано на полотне.
    """
    numbers, labels, occupied = [], [], []
    for link, points in prepared:
        number = link_number(elements, links, link)
        start = number_anchor(points, number, occupied) if number else None
        start = shifted_anchor(start, (link.get("mark_offsets")
                                       or {}).get("start"))
        if start is not None:
            occupied.append(start[2])
        end = end_number_anchor(points, number, occupied) if number else None
        end = shifted_anchor(end, (link.get("mark_offsets")
                                   or {}).get("end"))
        if end is not None:
            occupied.append(end[2])
        numbers.append((link, start, end))
    for link, points in prepared:
        text = link_label_text(elements, link)
        anchor = label_anchor(points, text, occupied) if text else None
        anchor = shifted_anchor(anchor, link.get("label_offset"))
        if anchor is not None:
            occupied.append(anchor[2])
        labels.append((link, anchor))
    return numbers, labels


# ==========================================================================
# Отрисовка связей ФЛС
# ==========================================================================
def arrowhead(canvas, x1, y1, x2, y2, fill, size=9.0):
    """Треугольное острие стрелки в точке (x2, y2)."""
    distance = math.hypot(x2 - x1, y2 - y1)
    if distance < 1e-6:
        return
    ux, uy = (x2 - x1) / distance, (y2 - y1) / distance
    base_x, base_y = x2 - ux * size, y2 - uy * size
    half = size * 0.45
    canvas.create_polygon(
        x2, y2,
        base_x - uy * half, base_y + ux * half,
        base_x + uy * half, base_y - ux * half,
        fill=fill, outline=fill)


def draw_logic_links(canvas, elements, links):
    """Связи ФЛС для PDF/PNG: те же линии, стрелки и подписи."""
    prepared = []
    for link in links or []:
        points = route(elements, link)
        if len(points) >= 2:
            prepared.append((link, points))
    numbers, labels = annotations(elements, links, prepared)

    for link, points in prepared:
        style = ll.link_style(link.get("kind"))
        color = style["color"]
        line_width = 1
        bus_style = ll.bus_link_style(elements, link, split_ref)
        if bus_style:
            color, width = bus_style
            line_width = max(2, int(width))
            style = dict(style, dash=None)
        arrow = bool(link.get("arrow", True))
        if arrow:
            last_x, last_y = points[-1]
            prev_x, prev_y = points[-2]
            distance = math.hypot(last_x - prev_x, last_y - prev_y)
            if distance < 1e-6:
                continue
            ux, uy = ((last_x - prev_x) / distance,
                      (last_y - prev_y) / distance)
            coords = []
            for x, y in points[:-1]:
                coords.extend((x, y))
            coords.extend((last_x - ux * 5.4, last_y - uy * 5.4))
            canvas.create_line(*coords, fill=color, width=line_width,
                               dash=style["dash"])
            arrowhead(canvas, prev_x, prev_y, last_x, last_y, fill=color)
        else:
            coords = []
            for x, y in points:
                coords.extend((x, y))
            canvas.create_line(*coords, fill=color, width=line_width,
                               dash=style["dash"])

    def draw_number(link, anchor):
        if anchor is None:
            return
        x, y, box = anchor
        canvas.create_rectangle(box[0], box[1], box[2], box[3],
                                fill="white", outline="")
        canvas.create_text(x, y, text=link_number(elements, links, link),
                           fill=ll.link_color(elements, link, split_ref),
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
        canvas.create_text(x, y, text=link_label_text(elements, link),
                           fill=ll.link_color(elements, link, split_ref),
                           font=("Arial", 6), anchor="center",
                           justify="center")


# ==========================================================================
# Аналоговые цепи
# ==========================================================================
def split_analog_ref(ref):
    """«id#3» → (id, 3); «id» → (id, None)."""
    element_id, sep, index = str(ref or "").partition("#")
    if sep and index.isdigit():
        return element_id, int(index)
    return element_id, None


def analog_ref_point(elements, ref):
    """Мировая точка конца аналоговой связи: порт комплекта или центр ТТ/ТН."""
    element_id, index = split_analog_ref(ref)
    element = elements.get(element_id)
    if element is None:
        return None
    if index is not None and element.type == "cabinet":
        point = getattr(element, "analog_point", None)
        if callable(point):
            return point(index)
    return (element.x, element.y)


def analog_route(elements, link):
    """Мировые точки аналоговой связи: «from» → изломы → «to»."""
    start = analog_ref_point(elements, (link or {}).get("from"))
    end = analog_ref_point(elements, (link or {}).get("to"))
    if start is None or end is None:
        return []
    points = [tuple(start)]
    points.extend((float(point[0]), float(point[1]))
                  for point in clean_points(link.get("points")))
    points.append(tuple(end))
    return points


def analog_signals_text(link):
    """Подпись аналоговой связи: цепи напряжения и тока."""
    parts = []
    voltage = str((link or {}).get("voltage") or "").strip()
    current = str((link or {}).get("current") or "").strip()
    if voltage:
        parts.append(voltage)
    if current:
        parts.append(current)
    return " / ".join(parts)


def draw_analog_links(canvas, elements, links):
    """Аналоговые цепи для PDF/PNG: пунктир, стрелка и подпись цепей."""
    for link in links or []:
        if not isinstance(link, dict):
            continue
        points = analog_route(elements, link)
        if len(points) < 2:
            continue
        last_x, last_y = points[-1]
        prev_x, prev_y = points[-2]
        distance = math.hypot(last_x - prev_x, last_y - prev_y)
        if distance < 1e-6:
            continue
        ux, uy = ((last_x - prev_x) / distance,
                  (last_y - prev_y) / distance)
        coords = []
        for x, y in points[:-1]:
            coords.extend((x, y))
        coords.extend((last_x - ux * 5.4, last_y - uy * 5.4))
        canvas.create_line(*coords, fill=ANALOG_COLOR, width=1, dash=(6, 3))
        arrowhead(canvas, prev_x, prev_y, last_x, last_y, fill=ANALOG_COLOR)
        signals = analog_signals_text(link)
        if signals:
            middle = path_point(points, 0.5)
            if middle is not None:
                mid_x, mid_y, mx, my = middle
                canvas.create_text(mid_x - my * 11, mid_y + mx * 11,
                                   text=signals, fill=ANALOG_COLOR,
                                   font=("Arial", 6), anchor="center")


# ==========================================================================
# Сборка схемы из JSON
# ==========================================================================
def build_elements(data):
    """Элементы схемы из JSON файла редактора.

    Поддерживаются все элементы ФЛС и оборудование; шкафы и контейнеры
    восстанавливаются упрощённо (карточка без обращения к каталогам) —
    для отрисовки этого достаточно.
    """
    elements = {}
    for item in data.get("elements", []):
        try:
            el = library.create_component(
                item["type"], item["id"], item.get("x", 0), item.get("y", 0))
        except (KeyError, ValueError):
            continue
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
        payload = item.get("cabinet") or {}
        if el.type == "cabinet" and payload:
            el.cabinet_key = payload.get("key", "")
            el.title = payload.get("title") or el.title
            el.info = dict(payload.get("info") or {})
            el.komplets = list(payload.get("komplets") or [])
        payload = item.get("container") or {}
        if el.type == "container" and payload:
            el.container_key = payload.get("key", "")
            el.code = payload.get("code") or el.code
            el.title = payload.get("title") or el.title
            el.size = payload.get("size") or el.size
            try:
                el.set_slots(payload.get("slots") or el.slots)
            except (TypeError, ValueError):
                pass
        if ll.is_logic_type(el.type):
            ll.restore_element(el, item.get("logic") or {})
        el.generate_ports()
        elements[item["id"]] = el
    return elements


def _resolve_port(el, port_name, node_id):
    """Имя порта: прямое совпадение, затем поиск по node_id."""
    if port_name in el.ports:
        return port_name
    if node_id:
        for p_name, p_data in el.ports.items():
            if p_data.get("node_id") == node_id:
                return p_name
    return None


def build_connections(data, elements):
    """Электрические связи из JSON (с проверкой портов)."""
    connections = []
    for c in data.get("connections", []):
        el1 = elements.get(c.get("element_from"))
        el2 = elements.get(c.get("element_to"))
        if not el1 or not el2:
            continue
        port1 = _resolve_port(el1, c.get("port_from"), c.get("node_from"))
        port2 = _resolve_port(el2, c.get("port_to"), c.get("node_to"))
        if port1 and port2:
            entry = {"from": el1.id, "to": el2.id,
                     "port_from": port1, "port_to": port2}
            points = clean_points(c.get("points"))
            if points:
                entry["points"] = points
            connections.append(entry)
    return connections


def build_logic_links(data, elements):
    """Связи ФЛС из JSON (с проверкой портов)."""
    result = []
    for link in data.get("logic_links", []):
        if not isinstance(link, dict):
            continue
        from_ref = str(link.get("from") or "")
        to_ref = str(link.get("to") or "")
        from_id, from_port = split_ref(from_ref)
        to_id, to_port = split_ref(to_ref)
        start = elements.get(from_id)
        end = elements.get(to_id)
        if start is None or end is None or from_ref == to_ref:
            continue
        if from_port not in start.ports or to_port not in end.ports:
            continue
        entry = {"from": from_ref, "to": to_ref,
                 "kind": (link.get("kind")
                          if link.get("kind") in ll.LOGIC_LINK_KINDS
                          else "discrete")}
        for field in ("id", "continuation", "number", "ru", "iec"):
            value = link.get(field)
            if isinstance(value, str) and value.strip():
                entry[field] = value.strip()
        if link.get("arrow") is False:
            entry["arrow"] = False
        # Смещения номера и наименования из JSON редактора.
        label_offset = valid_offset(link.get("label_offset"))
        if label_offset:
            entry["label_offset"] = list(label_offset)
        mark_offsets = {}
        raw_offsets = link.get("mark_offsets")
        if isinstance(raw_offsets, dict):
            for part, value in raw_offsets.items():
                offset = valid_offset(value)
                if offset:
                    mark_offsets[part] = list(offset)
        if mark_offsets:
            entry["mark_offsets"] = mark_offsets
        points = clean_points(link.get("points"))
        if points:
            entry["points"] = points
        result.append(entry)
    return result


def connection_points(elements, connection):
    """Мировые точки маршрута электрической связи."""
    first = elements.get((connection or {}).get("from"))
    second = elements.get((connection or {}).get("to"))
    if first is None or second is None:
        return []
    port1 = first.ports.get(connection.get("port_from")) \
        or {"x": first.x, "y": first.y}
    port2 = second.ports.get(connection.get("port_to")) \
        or {"x": second.x, "y": second.y}
    points = [(port1["x"], port1["y"])]
    points.extend((point[0], point[1])
                  for point in connection.get("points") or [])
    points.append((port2["x"], port2["y"]))
    return points


# ==========================================================================
# Рендер схемы
# ==========================================================================
#: Отступ от крайних линий схемы при экспорте, в пунктах.
EXPORT_MARGIN = 30.0


def render_scene(canvas, data):
    """Нарисовать схему целиком на канву (подложка и комментарии не входят).

    Порядок слоёв как в редакторе: провода, элементы, связи ФЛС.
    """
    elements = build_elements(data)
    connections = build_connections(data, elements)
    links = build_logic_links(data, elements)

    # 1. Провода между выводами — под символами
    for connection in connections:
        points = connection_points(elements, connection)
        if len(points) < 2:
            continue
        coords = []
        for x, y in points:
            coords.extend((x, y))
        bus_style = ll.bus_connection_style(elements, connection)
        if bus_style:
            color, bus_width = bus_style
            canvas.create_line(*coords, fill=color,
                               width=max(2, int(bus_width)))
        else:
            canvas.create_line(*coords, fill="black", width=2)

    # 2. Символы элементов
    for element in elements.values():
        element.draw(canvas, 1.0, 0.0, 0.0)

    # 3. Аналоговые цепи — поверх символов, под связями ФЛС
    draw_analog_links(canvas, elements, data.get("analog_links") or [])

    # 4. Связи ФЛС с подписями
    draw_logic_links(canvas, elements, links)
    return elements, connections, links


def export_png(data, path, resolution=2.0):
    """Собрать схему в PNG. Возвращает размер картинки (w, h).

    Требует Pillow (модуль :mod:`pngexport`); без него возбуждает
    ``RuntimeError``.
    """
    if pngexport is None:
        raise RuntimeError(
            "не установлен Pillow: python -m pip install pillow")
    recorder = pdfexport.SceneRecorder()
    render_scene(recorder, data)
    min_x, min_y, max_x, max_y = recorder.bounds() or (0.0, 0.0, 800.0, 600.0)
    min_x -= EXPORT_MARGIN
    min_y -= EXPORT_MARGIN
    max_x += EXPORT_MARGIN
    max_y += EXPORT_MARGIN
    width = max(50.0, max_x - min_x)
    height = max(50.0, max_y - min_y)
    return pngexport.export_png(path, recorder, width, height,
                                -min_x, -min_y, scale=1.0,
                                resolution=resolution)


def load(path):
    """Прочитать JSON схемы (элементы + связи)."""
    import json
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def export_png_file(scheme_path, image_path, resolution=2.0):
    """Файл схемы → файл PNG. Возвращает размер картинки (w, h)."""
    return export_png(load(scheme_path), image_path, resolution)


# ==========================================================================
# Генерация схемы из функций ИЭУ (structure2)
# ==========================================================================
#: Горизонтальный шаг между блоками функций, мировых единиц (сетка 20).
BLOCK_STEP = 480


def _logic_function(entry):
    """Функция structure2 → функция ФЛС редактора."""
    return {
        "kind": "CUSTOM",
        "title": entry.get("name") or "",
        "name": entry.get("name") or "",
        "iec_name": entry.get("iec_name") or "",
        "LNclass": entry.get("LNclass") or "",
        "ru": "",
        "iec": entry.get("iec_name") or "",
        "inputs": list(entry.get("inputs") or []),
        "outputs": list(entry.get("outputs") or []),
        "settings": list(entry.get("settings") or []),
        "parameters": list(entry.get("parameters") or []),
    }


def scheme_from_ied(ied):
    """Схема ФЛС из функциональной модели ИЭУ (structure2).

    Каждый блок функций (FunctionBlock) становится функциональным блоком
    на схеме, каждая функция (Function) — функцией внутри него со своими
    входами и выходами. Связи не строятся: их рисует пользователь.
    """
    elements = []
    for index, raw_block in enumerate(ied.get("function_blocks") or []):
        block = copy.deepcopy(raw_block)
        # Полные русские и МЭК-обозначения функций и сигналов лежат в
        # информационных сигналах отчетов и исходящих сообщений ИЭУ.
        es.enrich_function_block(block, ied)
        functions = [_logic_function(fn)
                     for fn in (block.get("functions") or [])]
        if not functions:
            functions = [ll.normalize_function(
                {"kind": "CUSTOM", "title": block.get("name") or "Функция",
                 "inputs": 1, "outputs": 1})]
        payload = {
            "title": block.get("name") or "Функциональный блок",
            "designation": (block.get("name") or block.get("corp_prof_name")
                            or ""),
            "functions": functions,
            "isMainFunction": bool(block.get("isMainFunction")),
            "isInITS": bool(block.get("isInITS")),
            "iec_name": block.get("iec_name") or "",
            "russian_path": block.get("russian_path") or "",
            "corp_prof_name": block.get("corp_prof_name") or "",
        }
        elements.append({
            "id": "B%d" % (index + 1),
            "type": "logic_block",
            "name": payload["title"],
            "x": index * BLOCK_STEP,
            "y": 0,
            "logic": copy.deepcopy(payload),
        })
    if not elements:
        # У ИЭУ нет блоков функций — один блок с обозначением ИЭУ.
        title = str(ied.get("description") or ied.get("number") or "ИЭУ")
        elements.append({
            "id": "B1", "type": "logic_block", "name": title,
            "x": 0, "y": 0,
            "logic": {"title": title,
                      "functions": [ll.normalize_function(
                          {"kind": "CUSTOM", "title": "Функция",
                           "inputs": 1, "outputs": 1})]},
        })
    return {"elements": elements, "connections": [], "logic_links": []}
