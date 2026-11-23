# -*- coding: utf-8 -*-
"""Элементы и связи функционально-логических схем (ФЛС).

Запуск:
    python3 tests/test_logic_scheme.py           # полный набор, нужен tkinter
    python3 tests/test_logic_scheme.py --no-gui  # только модель и сериализация

Проверяет:

1. создание пяти элементов ФЛС и их выводы;
2. вертикальную шину: отводы через клетку, изменение длины;
3. связи: тип, цвет, номер, русское и МЭК наименование;
4. свойства связи и присваивание следующего номера;
5. функциональный блок как контейнер: функции со входами слева и выходами справа;
6. изломы связи: вставка, удаление, перетаскивание;
7. сохранение и загрузку JSON (элементы + связи);
8. копирование/вставку с новыми номерами;
9. отрисовку и экспорт в сцену PDF/PNG;
10. удаление элемента вместе с его связями;
11. диалог связи: введённый номер и тип не теряются после закрытия окна;
12. окно функционального блока: таблица функций сохраняется;
13. вставка блока с палитры сразу открывает окно свойств;
13а. диалог функции: новый вход сохраняется, идентификаторы слотов не
    смешиваются;
14. смену типа выбранной связи из ленты и отмену;
15. легенду типов связей на полотне;
16. сквозную нумерацию связей;
20. входной и выходной порты: выводы, наименование сигнала, JSON;
21. «Обновить связи»: общий номер — привязка продолжением и выравнивание
    наименований (элемент с маркировкой, полная маркировка ФБ / Функция:
    Сигнал, связь-источник), в том числе у связей без номера;
22. перенос точек: захват излома любой связи и перетаскивание линии целиком;
23. перетаскивание номера и наименования связи мышкой со сохранением
    смещений в JSON и в экспорте; у новых связей стрелка отключена;
24. перепривязку связей к другим отводам при изменении длины шины;
25. полное обозначение сигнала на связи ФБ / Функция: Сигнал;
26. изменение длины шины маркерами вверх/вниз, связь шины с шиной и
    отключение вывода полей шины.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:         # pragma: no cover
    tk = None
    ttk = None

import logic_library as ll
import logic_scheme_render as lsr
import ui_theme

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def close(left, right, tolerance=0.05):
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return (len(left) == len(right)
                and all(close(a, b, tolerance) for a, b in zip(left, right)))
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return left == right


def _event(x, y, state=0):
    return SimpleNamespace(x=x, y=y, state=state, num=None, delta=0)


def _add(app, etype, x, y):
    before = set(app.elements)
    app.add_element(etype, x, y)
    return next(iter(set(app.elements) - before))


def _reset(app):
    app.elements = {}
    app.connections = []
    app.analog_links = []
    app.logic_links = []
    app.selected_elements = []
    app.selected_connection = None
    app.selected_analog = None
    app.selected_logic = None
    app.protection_links = []
    app.comments = []
    app.current_path = None


def _by_type(app, etype):
    return next(element for element in app.elements.values()
                if element.type == etype)


# ==========================================================================
# Модель без GUI
# ==========================================================================
def test_numbering():
    print("1. нумерация и подписи связей")
    links = []
    check(ll.next_logic_number(links) == "9000",
          "первый свободный номер — 9000")
    links = [{"number": "9000"}, {"number": "9107"}, {"number": "abc"}]
    check(ll.next_logic_number(links) == "9108",
          "номер продолжается после максимального числового")
    check(ll.signal_text("Пуск", "Start") == "Пуск (Start)",
          "русское наименование и МЭК в скобках")
    check(ll.signal_text("", "Start") == "Start",
          "без русского остаётся МЭК")
    check(ll.signal_text("", "", "К1") == "К1", "запасная подпись")


def test_payload():
    print("2. поля элементов и сериализация модели")
    block = ll.LogicBlock("B1", 0, 0)
    block.title = "Управление В"
    block.functions = [{"kind": "OR", "title": "Пуск",
                        "inputs": [{"name": "D01"}, {"name": "D02"}],
                        "outputs": [{"name": "Пуск"}]}]
    payload = ll.element_payload(block)
    check(payload["title"] == "Управление В"
          and payload["functions"][0]["kind"] == "OR"
          and len(payload["functions"][0]["inputs"]) == 2
          and len(payload["functions"][0]["outputs"]) == 1,
          "поля блока и слоты функций попадают в JSON")
    check("inputs" not in payload and "rows" not in payload,
          "у блока нет собственных входов и строк сигналов")

    restored = ll.LogicBlock("B2", 0, 0)
    ll.restore_element(restored, payload)
    check(restored.title == block.title
          and restored.functions[0]["kind"] == "OR",
          "поля блока читаются обратно")
    check("fn0_in0" in restored.ports and "fn0_out0" in restored.ports
          and not any(name.startswith(("in", "out"))
                      for name in restored.ports),
          "после восстановления порты только у слотов функций")

    bus = ll.LogicBus("S1", 0, 0)
    bus.length = 300
    bus.show_fields = True
    ll.restore_element(bus, ll.element_payload(bus))
    check(close(bus.length, 300) and "p1" in bus.ports,
          "длина шины и отводы восстановлены")
    check(bus.show_fields is True,
          "признак вывода полей шины сохраняется в JSON")


def test_full_signal_label():
    print("2а. полное обозначение сигнала на связи")
    block = ll.LogicBlock("B1", 0, 0)
    block.designation = "ДЗШ"
    block.functions = [{
        "name": "ПО", "title": "Пуск",
        "outputs": [{"name": "Пуск", "iec_name": "Start"}],
    }]
    block.generate_ports()
    elements = {"B1": block}
    link = {"from": "B1#fn0_out0", "to": "K1#left",
            "ru": "Пуск", "iec": "Start", "number": "9000"}
    label, signal = ll.link_full_label(elements, link, lsr.split_ref)
    check(label == "ДЗШ / ПО: Пуск" and signal == "Пуск",
          "подпись собрана из обозначения блока, имени функции и выхода")
    check(lsr.link_label_text(elements, link) == "ДЗШ / ПО: Пуск",
          "экспорт схемы использует полное обозначение")

    key = ll.LogicKey("K1", 0, 0)
    key.signal_ru = "Пуск"
    check(lsr.link_label_text(dict(elements, K1=key), link) == "",
          "полная подпись не дублирует подпись клавиши")

    block.designation = ""
    check(ll.link_full_label(elements, link, lsr.split_ref)[0] == "ПО: Пуск",
          "без обозначения блока остаются функция и сигнал")
    check(ll.link_full_label({}, link, lsr.split_ref)[0] == "Пуск (Start)",
          "без блока остаётся обычная подпись сигнала")


# ==========================================================================
# GUI
# ==========================================================================
def test_structure2_model():
    print("2a. модель structure2: слоты, уставки, параметры")
    function = ll.normalize_function({
        "kind": "AND",
        "inputs": 2,
        "outputs": 2,
        "settings": [{"name": "t", "unit": "с"}],
        "parameters": [{"name": "Режим", "conditions": "а / б"}],
    })
    check(len(function["inputs"]) == 2 and len(function["outputs"]) == 2,
          "входы и выходы функции нормализованы")
    check(function["settings"][0]["unit"] == "с", "уставка сохранена")
    check(function["parameters"][0]["value"] == "а / б",
          "состояния переключателя стали значением параметра")

    comp = ll.LogicFunction("F1", 0, 0)
    comp.inputs = [ll.new_slot("in", "Пуск", "", "Start",
                               "discrete_process_level")]
    comp.outputs = [ll.new_slot("out", "Отключение", "", "Trip",
                                "control_operation")]
    comp.settings = [{"name": "t", "unit": "с", "min_value": "0",
                      "max_value": "10", "step": "0.1",
                      "default_value": "1", "description": ""}]
    comp.parameters = [{"name": "Режим", "value": "а / б",
                        "default_value": "а", "description": ""}]
    comp.generate_ports()
    check("in0" in comp.ports and comp.ports["in0"]["slot_name"] == "Пуск",
          "вход функции получил порт с именем слота")
    check(comp.ports["out0"]["slot_type"] == "control_operation",
          "тип выхода — управляющее воздействие")
    payload = ll.element_payload(comp)
    restored = ll.LogicFunction("F2", 0, 0)
    ll.restore_element(restored, payload)
    check(len(restored.inputs) == 1 and len(restored.outputs) == 1,
          "слоты читаются из JSON")
    check(restored.settings and restored.parameters,
          "уставки и параметры читаются из JSON")


def test_elements(app):
    print("3. элементы ФЛС")
    _reset(app)
    ids = {etype: _add(app, etype, 100 + index * 180, 300)
           for index, etype in enumerate(ll.LOGIC_COMPONENT_TYPES)}
    check(len(app.elements) == len(ll.LOGIC_COMPONENT_TYPES),
          "созданы все %d элементов" % len(ll.LOGIC_COMPONENT_TYPES))
    for etype, element_id in ids.items():
        element = app.elements[element_id]
        check(element.type == etype and bool(element.ports),
              "%s: есть выводы" % etype)
        x1, y1, x2, y2 = element.get_bounding_box()
        check(x2 > x1 and y2 > y1, "%s: ненулевой габарит" % etype)
    check(app.elements[ids["logic_bus"]].name.startswith("Ш"),
          "шина получает обозначение Ш…")
    check(app.elements[ids["logic_key"]].name.startswith("К"),
          "клавиша получает обозначение К…")
    check(app.elements[ids["logic_led"]].name.startswith("HL"),
          "светодиод получает обозначение HL…")
    check(app.elements[ids["logic_block"]].name.startswith("Б"),
          "блок получает обозначение Б…")
    check(app.elements[ids["logic_function"]].name.startswith("ЛУ"),
          "узел получает обозначение ЛУ…")
    check(app.elements[ids["logic_port_in"]].name.startswith("X")
          and app.elements[ids["logic_port_out"]].name.startswith("X"),
          "порты получают обозначения X…")


def test_bus(app):
    print("4. вертикальная шина")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    check(bus.ports["top"]["y"] < bus.y < bus.ports["bottom"]["y"],
          "верхний и нижний выводы по вертикали")
    taps = [name for name in bus.ports if name.startswith("p")]
    check(len(taps) >= 10, "отводы идут через клетку (%d)" % len(taps))
    old_bottom = bus.ports["bottom"]["y"]
    bus.length = 200
    bus.generate_ports()
    check(bus.ports["bottom"]["y"] < old_bottom,
          "уменьшение длины сдвигает нижний вывод")
    check(len([n for n in bus.ports if n.startswith("p")]) < len(taps),
          "отводов стало меньше")

    # Перепривязка связей: отводы нумеруются от верхнего края, поэтому
    # после изменения длины связь должна остаться на прежней высоте —
    # за счёт перехода на другой отвод.
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    app.logic_link_kind = "discrete"
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    old_point = app._logic_ref_point(link["from"])
    old_ports = {name: (port["x"], port["y"])
                 for name, port in bus.ports.items()}
    bus.length += 80          # все отводы сдвигаются на 2 клетки
    bus.generate_ports()
    app._rebind_logic_bus_links(bus, old_ports)
    app._prune_logic_links()
    check(link in app.logic_links,
          "связь сохранилась после изменения длины шины")
    check(close(app._logic_ref_point(link["from"])[1], old_point[1]),
          "связь осталась на прежней высоте")
    check(app._logic_split_ref(link["from"])[1] != "p2",
          "связь перепривязана к другому отводу")

    # Уменьшение длины: отвод исчезает, связь перепривязывается, а не
    # пропадает вместе с ним.
    last_tap = max((name for name in bus.ports if name.startswith("p")),
                   key=lambda name: int(name[1:]))
    key2 = app.elements[_add(app, "logic_key", 350, 500)]
    link2 = app._add_logic_link((bus.id, last_tap), (key2.id, "left"))
    old_ports = {name: (port["x"], port["y"])
                 for name, port in bus.ports.items()}
    bus.length -= 80
    bus.generate_ports()
    app._rebind_logic_bus_links(bus, old_ports)
    app._prune_logic_links()
    check(last_tap not in bus.ports, "отвод на краю шины исчез")
    check(link2 in app.logic_links,
          "связь с исчезнувшего отвода сохранена")
    check(app._logic_ref_point(link2["from"]) is not None,
          "связь перепривязана к оставшемуся отводу")

    # Маркеры вверх/вниз меняют длину шины мышью, не сдвигая связи.
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    app.logic_link_kind = "discrete"
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    old_y = app._logic_ref_point(link["from"])[1]
    old_bottom = bus.ports["bottom"]["y"]
    app.current_tool = "select"
    app.selected_elements = [bus.id]
    app.redraw_all()
    sx, sy = app.world_to_screen(bus.x, bus.y + bus.length / 2.0)
    check(app.find_resize_handle(bus.id, sx, sy) == "bottom",
          "нижний маркер шины находится по координатам")
    app.on_left_click(_event(sx, sy))
    check(app.resizing_element == bus.id
          and app.resize_handle == "bottom"
          and bool(app._resize_old_ports),
          "нажатие на маркер начинает изменение длины вниз")
    nx, ny = app.world_to_screen(bus.x, bus.y + bus.length / 2.0 + 40)
    app.on_drag(_event(nx, ny))
    check(close(bus.length, 520)
          and close(bus.ports["bottom"]["y"], old_bottom + 40),
          "нижний край шины сдвинулся вниз на 40")
    check(close(app._logic_ref_point(link["from"])[1], old_y),
          "подключённая связь осталась на прежней высоте")
    app.on_release(_event(nx, ny))
    check(app.resizing_element is None,
          "изменение шины завершено")


def test_bus_links(app):
    print("4а. связь шины с шиной и поля шины")
    _reset(app)
    first = app.elements[_add(app, "logic_bus", 100, 300)]
    second = app.elements[_add(app, "logic_bus", 300, 300)]
    app.logic_link_kind = "control"
    link = app._add_logic_link((first.id, "p2"), (second.id, "p3"))
    check(link is not None
          and app._logic_ref_valid(link["from"])
          and app._logic_ref_valid(link["to"]),
          "связь между отводами двух шин создана")
    link["ru"] = "Связь шин"
    app.redraw_all()
    lines = [item for item in app.canvas.find_withtag("logic_link")
             if app.canvas.type(item) == "line"]
    check(bool(lines), "связь шина—шина нарисована")
    expected_width = max(2, int(ll.LogicBus.WIDTH * app.zoom))
    check(lines and app.canvas.itemcget(lines[0], "fill") == first.color
          and float(app.canvas.itemcget(lines[0], "width")) == expected_width,
          "линия связи имеет цвет и толщину шины")
    labels = [item for item in app.canvas.find_withtag("logic_label")
              if app.canvas.type(item) == "text"]
    check(labels and all(app.canvas.itemcget(item, "fill") == first.color
                         for item in labels),
          "номер и наименование связи имеют цвет шины")
    check(ll.bus_link_style({first.id: first}, link,
                            app._logic_split_ref) is None,
          "обычная связь сохраняет стиль своего типа")

    # Тот же стиль попадает в экспорт сцены PDF/PNG.
    link["points"] = [[200.0, 300.0], [250.0, 300.0]]
    recorder = __import__("pdfexport").SceneRecorder()
    app._draw_scene(recorder)
    scene_lines = [call for call in recorder.calls
                   if call[0] == "create_line"
                   and call[2].get("fill") == first.color
                   and call[2].get("width") == max(2, int(ll.LogicBus.WIDTH))
                   and len(call[1]) >= 8]
    check(bool(scene_lines), "стиль шины сохранён в экспорте")
    scene_texts = [call for call in recorder.calls
                   if call[0] == "create_text"
                   and call[2].get("fill") == first.color]
    check(bool(scene_texts), "подписи связи окрашены цветом шины в экспорте")

    # Обычный провод между двумя шинами (не связь ФЛС) также должен быть
    # цвета и толщины шины — и в редакторе, и в экспорте.
    connection = app.create_connection(first.id, second.id,
                                       "bottom", "bottom")
    app.redraw_all()
    wire_id = connection.get("canvas_id")
    check(wire_id is not None
          and app.canvas.itemcget(wire_id, "fill") == first.color
          and float(app.canvas.itemcget(wire_id, "width")) == expected_width,
          "провод шина—шина окрашен цветом шины и имеет её толщину")
    check(ll.bus_connection_style({first.id: first, second.id: second},
                                  connection)
          == (first.color, ll.LogicBus.WIDTH),
          "стиль провода между шинами берётся от шины")
    recorder = __import__("pdfexport").SceneRecorder()
    app._draw_scene(recorder)
    wire_calls = [call for call in recorder.calls
                  if call[0] == "create_line"
                  and call[2].get("fill") == first.color
                  and call[2].get("width") == max(2, int(ll.LogicBus.WIDTH))
                  and len(call[1]) == 4]
    check(bool(wire_calls), "стиль провода сохранён в экспорте сцены")

    first.title = "Шина-источник"
    first.name = "Ш1"
    first.signal_ru = "Сигнал шины"
    first.signal_no = "9700"
    first.show_fields = False
    app.redraw_all()
    texts = [app.canvas.itemcget(item, "text")
             for item in app.canvas.find_all()
             if app.canvas.type(item) == "text"]
    check("Сигнал шины" not in texts and "9700" not in texts
          and "Ш1" not in texts,
          "поля шины по умолчанию не выводятся")
    first.show_fields = True
    app.redraw_all()
    texts = [app.canvas.itemcget(item, "text")
             for item in app.canvas.find_all()
             if app.canvas.type(item) == "text"]
    check("Сигнал шины" in texts and "9700" in texts,
          "включённые поля шины выводятся")


def test_links(app):
    print("5. связи ФЛС")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    app.logic_link_kind = "discrete"
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    check(link is not None, "связь создана")
    check(link["number"] == "9000", "номер присвоен автоматически")
    check(link["kind"] == "discrete", "тип связи сохранён")

    link["ru"] = "Команда ВКЛ В"
    link["iec"] = "Close command"
    app.redraw_all()
    check(len(app._logic_label_boxes) >= 2,
          "на линии есть номер и наименование")
    lines = [item for item in app.canvas.find_withtag("logic_link")
             if app.canvas.type(item) == "line"]
    check(bool(lines), "линия связи нарисована")
    check(app.canvas.itemcget(lines[0], "fill")
          == ll.link_style("discrete")["color"],
          "цвет линии соответствует типу")
    labels = [item for item in app.canvas.find_withtag("logic_label")
              if app.canvas.type(item) == "text"]
    check(labels and all(app.canvas.itemcget(item, "fill")
                         == ll.link_style("discrete")["color"]
                         for item in labels),
          "подписи обычной связи сохраняют цвет типа")
    polygons = [item for item in app.canvas.find_withtag("logic_link")
                if app.canvas.type(item) == "polygon"]
    check(not polygons, "у новой связи стрелки нет (по умолчанию)")
    link["arrow"] = True
    app.redraw_all()
    polygons = [item for item in app.canvas.find_withtag("logic_link")
                if app.canvas.type(item) == "polygon"]
    check(bool(polygons), "включённая стрелка нарисована")

    # выбор и свойства через модель
    app.selected_logic = link
    app.assign_selected_logic_number()
    check(link["number"] == "9001", "кнопка «Присвоить номер» даёт следующий")
    app.selected_logic = None


def test_link_geometry(app):
    print("6. изломы связи ФЛС")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    link["points"] = [[200.0, 300.0], [200.0, 200.0]]
    app.selected_logic = link
    app.redraw_all()

    sx, sy = app.world_to_screen(200.0, 250.0)
    segment = app._logic_segment_at(sx, sy)
    check(segment is not None and segment[0] is link,
          "сегмент связи находится по координатам")
    app.on_double_click(_event(sx, sy))
    check(len(link["points"]) == 3, "двойной клик вставил излом")

    point = link["points"][1]
    sx, sy = app.world_to_screen(*point)
    app.on_double_click(_event(sx, sy))
    check(len(link["points"]) == 2, "двойной клик по маркеру удалил излом")

    app.selected_logic = link
    app.redraw_all()
    sx, sy = app.world_to_screen(*link["points"][0])
    app.on_left_click(_event(sx, sy))
    check(app._dragging_point == ("link", link, 0),
          "нажатие на маркер начинает перетаскивание")
    nx, ny = app.world_to_screen(220.0, 320.0)
    app.on_drag(_event(nx, ny))
    check(not close(link["points"][0], [200.0, 300.0]),
          "излом следует за курсором")
    app.on_release(_event(nx, ny))


def test_block(app):
    print("7. функциональный блок — контейнер, входы/выходы на функциях")
    _reset(app)
    block = app.elements[_add(app, "logic_block", 500, 300)]
    block.functions = [
        {"kind": "AND", "title": "Логика пуска", "ru": "Пуск",
         "iec": "Start", "inputs": 3, "outputs": 1},
        {"kind": "TIMER", "title": "Задержка", "ru": "Выдержка",
         "iec": "Delay", "inputs": 1, "outputs": 1},
    ]
    block.generate_ports()
    check(not any(name.startswith(("in", "out"))
                  for name in block.ports),
          "у блока нет собственных входов и выходов")
    inputs = [name for name in block.ports if "_in" in name]
    outputs = [name for name in block.ports if "_out" in name]
    check(len(inputs) == 4, "четыре входа функций")
    check(len(outputs) == 2, "два выхода функций")
    check(all("node_id" in port for port in block.ports.values()),
          "у портов есть идентификаторы узлов")

    app.redraw_all()
    texts = [app.canvas.itemcget(item, "text")
             for item in app.canvas.find_all()
             if app.canvas.type(item) == "text"]
    joined = "\n".join(texts)
    check("Логика пуска" in joined and "&" in joined,
          "вложенная функция И нарисована")
    check("Выдержка" in joined, "вложенная функция с сигналом нарисована")
    check("Пуск" in joined and "Start" in joined,
          "сигнал функции виден по-русски и по МЭК")


def test_round_trip(app):
    print("8. сохранение и загрузка")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    block = app.elements[_add(app, "logic_block", 600, 300)]
    block.title = "Управление В"
    block.functions = [{"kind": "OR", "title": "Пуск", "ru": "Пуск",
                        "iec": "Start", "inputs": 2, "outputs": 1}]
    block.generate_ports()
    link = app._add_logic_link((bus.id, "p3"), (key.id, "left"))
    link["kind"] = "control"
    link["ru"] = "Включить"
    link["iec"] = "Close"
    link["points"] = [[200.0, 300.0]]

    folder = tempfile.mkdtemp(prefix="logic-")
    path = os.path.join(folder, "scheme.json")
    app.current_path = path
    check(app._write_scheme() is True, "схема сохранена")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    logic_elements = [item for item in data["elements"] if item.get("logic")]
    check(len(logic_elements) == 3, "в JSON есть поле logic у трёх элементов")
    record = data["logic_links"][0]
    check(record["kind"] == "control" and record["number"] == "9000"
          and record["ru"] == "Включить" and record["iec"] == "Close",
          "связь сохранена с типом, номером и наименованиями")
    check(record["points"] == [[200.0, 300.0]], "излом сохранён")

    elements = app._build_elements(data)
    app.elements = elements
    app.logic_links = app._build_logic_links(data.get("logic_links", []))
    check(len(app.elements) == 3 and len(app.logic_links) == 1,
          "элементы и связи читаются обратно")
    restored = next(el for el in app.elements.values()
                    if el.type == "logic_block")
    check(restored.title == "Управление В"
          and restored.functions[0]["kind"] == "OR",
          "поля блока восстановлены")
    app.redraw_all()
    check(len(app._logic_label_boxes) >= 2,
          "после загрузки подписи связи нарисованы")


def test_copy_paste(app):
    print("9. копирование и вставка")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    link["ru"] = "Пуск"
    app.selected_elements = [bus.id, key.id]
    app.copy_selection()
    check(bool(app.clipboard_logic), "связь попала в буфер")
    app.paste_selection()
    check(len(app.logic_links) == 2, "связь вставлена вместе с элементами")
    new_link = [item for item in app.logic_links if item is not link][0]
    check(new_link["number"] != link["number"],
          "у вставленной связи новый номер")
    check(new_link.get("ru") == "Пуск", "наименование скопировано")


def test_export(app):
    print("10. экспорт в сцену PDF/PNG")
    import pdfexport
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    link["kind"] = "analog"
    link["ru"] = "Напряжение"
    link["iec"] = "Voltage"
    link["arrow"] = True
    link["points"] = [[200.0, 300.0], [200.0, 220.0]]
    recorder = pdfexport.SceneRecorder()
    app._draw_scene(recorder)
    color = ll.link_style("analog")["color"]
    lines = [call for call in recorder.calls
             if call[0] == "create_line" and call[2].get("fill") == color]
    check(bool(lines), "линия ФЛС попала в сцену")
    check(any(len(call[1]) == 8 for call in lines),
          "изломы сохранены в экспорте")
    heads = [call for call in recorder.calls
             if call[0] == "create_polygon"
             and call[2].get("fill") == color]
    check(bool(heads), "стрелка попала в сцену")
    texts = [call[2].get("text") for call in recorder.calls
             if call[0] == "create_text"]
    check(any("Напряжение" in str(text) for text in texts),
          "наименование сигнала попало в экспорт")


def test_delete(app):
    print("11. удаление элемента вместе со связями")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    check(len(app.logic_links) == 1, "связь создана")
    app.delete_element(key.id)
    check(len(app.logic_links) == 0,
          "удаление элемента убирает его связи ФЛС")


def _walk(widget):
    result = [widget]
    for child in widget.winfo_children():
        result.extend(_walk(child))
    return result


def _dialogs(root):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def _find(widget, widget_class):
    return [w for w in _walk(widget) if w.winfo_class() == widget_class]


def _click(widget, text):
    for button in _find(widget, "Button"):
        if button.cget("text") == text:
            button.invoke()
            return True
    return False


def _dialog_action(root, action, delay=250):
    """Выполнить action(диалог), пока wait_window уже ждёт закрытия."""
    def run():
        dialogs = _dialogs(root)
        if dialogs:
            action(dialogs[-1])
    root.after(delay, run)


def test_link_dialog(app, root):
    print("12. диалог связи: номер и тип применяются")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    app.logic_link_kind = "discrete"
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    app.is_modified = False

    def fill(dialog):
        entries = _find(dialog, "Entry")
        if len(entries) < 3:
            return
        entries[0].delete(0, tk.END)
        entries[0].insert(0, "А-12")
        entries[1].insert(0, "Пуск")
        entries[2].insert(0, "Start")
        combos = _find(dialog, "TCombobox")
        if combos:
            combos[0].current(0)          # аналоговые цепи
        _click(dialog, "Сохранить")

    _dialog_action(root, fill)
    app.edit_logic_link(link)
    check(link["number"] == "А-12", "введённый номер сохранён")
    check(link["kind"] == "analog", "выбранный тип связи сохранён")
    check(link["ru"] == "Пуск" and link["iec"] == "Start",
          "наименования сигнала сохранены")
    check(app.is_modified is True, "схема помечена изменённой")
    app.redraw_all()
    texts = [app.canvas.itemcget(item, "text")
             for item in app.canvas.find_all()
             if app.canvas.type(item) == "text"]
    check("А-12" in texts, "номер виден на линии")


def test_block_dialog(app, root):
    print("13. окно функционального блока: правки сохраняются")
    _reset(app)
    block = app.elements[_add(app, "logic_block", 600, 300)]
    app.is_modified = False

    def fill(dialog):
        entries = _find(dialog, "Entry")
        if not entries:
            return
        entries[0].delete(0, tk.END)
        entries[0].insert(0, "Управление В")
        trees = _find(dialog, "Treeview")
        if not trees:
            return
        functions = trees[0]
        functions.delete(*functions.get_children())
        functions.insert("", "end",
                         values=("И", "Пуск", "2", "1", "Пуск (Start)",
                                 "AND", "Пуск", "Start"))
        _click(dialog, "Сохранить")

    _dialog_action(root, fill)
    app.edit_logic_block(block)
    check(block.title == "Управление В", "название блока сохранено")
    check(bool(block.functions) and block.functions[0]["kind"] == "AND"
          and block.functions[0]["ru"] == "Пуск",
          "функция сохранена")
    check(len(block.functions[0]["inputs"]) == 2
          and len(block.functions[0]["outputs"]) == 1,
          "входы и выходы функции сохранены")
    check(sorted(block.ports) == [
        "fn0_in0", "fn0_in1", "fn0_out0"],
        "порты только у слотов функции")
    check(app.is_modified is True, "схема помечена изменённой")


def test_function_dialog_slots(app, root):
    """Регрессия: добавленный вход и правки функции доходят до модели."""
    print("13а. диалог функции: вход сохраняется, выход не подменяется")
    data = ll.normalize_function({
        "kind": "AND", "title": "Пуск", "name": "Start",
        "inputs": [{"name": "A", "description": "Первый"}],
        "outputs": [{"name": "Y", "description": "Выход"}],
    })

    def add_slot(function_dialog):
        def fill_nested():
            nested = [w for w in function_dialog.winfo_children()
                      if isinstance(w, tk.Toplevel)]
            if not nested:
                return
            entries = _find(nested[-1].winfo_children()[0], "Entry")
            entries[0].delete(0, tk.END)
            entries[0].insert(0, "B")
            _click(nested[-1], "ОК")

        root.after(150, fill_nested)
        _click(function_dialog, "Добавить…")   # первая таблица — входы
        root.after(150, lambda: _click(function_dialog, "Сохранить"))

    _dialog_action(root, add_slot)
    saved = app._edit_logic_function_data(data, root)
    check(saved is not None, "диалог функции закрывается с результатом")
    if saved is None:
        return
    check([slot["name"] for slot in saved["inputs"]] == ["A", "B"],
          "новый вход сохранён вместе с существующими")
    check(saved["title"] == "Пуск" and saved["name"] == "Start",
          "остальные поля функции не потеряны")
    check(saved["inputs"][0]["id"] == "in1"
          and saved["outputs"][0]["id"] == "out1"
          and saved["outputs"][0]["name"] == "Y",
          "вход не получает идентификатор выхода")


def test_block_insert_dialog(app):
    print("14. вставка блока открывает окно свойств")
    _reset(app)
    app.set_tool("logic_block")
    opened = []
    original = app.edit_logic_block
    app.edit_logic_block = lambda element: opened.append(element)
    try:
        app.on_left_click(_event(*app.world_to_screen(400, 300)))
    finally:
        app.edit_logic_block = original
    check(len(opened) == 1, "окно блока открылось при вставке")
    check(bool(opened) and opened[0].type == "logic_block",
          "окно открыто для вставленного блока")


def test_ribbon_kind(app):
    print("15. тип выбранной связи меняется из ленты")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    link["kind"] = "discrete"
    app.set_tool("select")
    app.selected_logic = link
    app.set_logic_link_kind("control")
    check(link["kind"] == "control", "тип связи изменён из ленты")
    check(app.current_tool == "select", "режим выбора не сброшен")
    app.undo_last_action()
    check(bool(app.logic_links)
          and app.logic_links[0]["kind"] == "discrete",
          "отмена возвращает прежний тип")


def test_legend(app):
    print("16. легенда типов связей")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    link = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    link["kind"] = "analog"
    app.show_logic_legend = True
    app.redraw_all()
    items = app.canvas.find_withtag("logic_legend")
    check(bool(items), "легенда нарисована")
    texts = [app.canvas.itemcget(item, "text") for item in items
             if app.canvas.type(item) == "text"]
    check(any("Аналоговые" in str(text) for text in texts),
          "в легенде есть тип связи схемы")
    app.show_logic_legend = False
    app.redraw_all()
    check(not app.canvas.find_withtag("logic_legend"),
          "выключенная легенда убрана с полотна")


def test_renumber(app):
    print("17. сквозная нумерация связей")
    _reset(app)
    bus = app.elements[_add(app, "logic_bus", 100, 300)]
    key = app.elements[_add(app, "logic_key", 350, 300)]
    first = app._add_logic_link((bus.id, "p2"), (key.id, "left"))
    second = app._add_logic_link((bus.id, "p4"), (key.id, "right"))
    first["number"] = "5"
    second["number"] = "7"
    app.renumber_logic_links()
    check([link["number"] for link in app.logic_links]
          == [str(ll.LOGIC_LINK_START), str(ll.LOGIC_LINK_START + 1)],
          "номера идут по порядку от LOGIC_LINK_START")


def test_block_preview(app, root):
    print("18. предпросмотр блока в окне свойств")
    canvas = tk.Canvas(root, width=320, height=180)
    canvas.pack()
    root.update()
    snapshot = {
        "title": "Управление В",
        "designation": "Б1",
        "width": "420",
        "functions": [{"kind": "AND", "title": "Пуск", "inputs": 2,
                       "outputs": 1, "ru": "Пуск", "iec": "Start"}],
    }
    app._refresh_block_preview(canvas, snapshot)
    root.update()
    check(len(canvas.find_all()) > 10, "предпросмотр нарисован")
    snapshot["functions"] = snapshot["functions"] + [
        {"kind": "OR", "title": "Задержка", "inputs": 1, "outputs": 1}]
    app._refresh_block_preview(canvas, snapshot)
    root.update()
    check(len(canvas.find_all()) > 10,
          "предпросмотр перерисовывается без ошибок")
    canvas.destroy()


def test_block_grid(app):
    print("19. сетка и стороны портов функций")
    _reset(app)
    block = app.elements[_add(app, "logic_block", 500, 300)]
    block.functions = [{"kind": "AND", "title": "Пуск", "inputs": 2,
                        "outputs": 1}]
    block.generate_ports()
    layout = block._layout()
    cell = ll.CELL
    check(layout["x1"] % cell == 0 and layout["y1"] % cell == 0
          and layout["x2"] % cell == 0 and layout["y2"] % cell == 0,
          "кромки блока на сетке")
    check(all(port["x"] % cell == 0 and port["y"] % cell == 0
              for port in block.ports.values()),
          "все порты на сетке")
    check(all(block.ports[name]["x"] == layout["fx1"]
              for name in ("fn0_in0", "fn0_in1")),
          "входы_functions слева от функции")
    check(block.ports["fn0_out0"]["x"] == layout["fx2"],
          "выход функции справа от функции")

    first_offset = block.ports["fn0_in0"]["y"] - layout["y1"]
    block.functions = block.functions + [
        {"kind": "OR", "title": "Задержка", "inputs": 1, "outputs": 1}]
    block.generate_ports()
    grown = block._layout()
    check(block.ports["fn0_in0"]["y"] - grown["y1"] == first_offset,
          "добавление функции не сдвигает предыдущую относительно верха")
    check(grown["height"] > layout["height"],
          "блок растёт вниз под новую функцию")
    check(all(port["y"] % cell == 0 for port in block.ports.values()),
          "порты остаются на сетке после роста")


def test_ports(app):
    print("20. входной и выходной порты")
    _reset(app)
    port_in = app.elements[_add(app, "logic_port_in", 200, 200)]
    port_out = app.elements[_add(app, "logic_port_out", 600, 200)]
    check(port_in.name.startswith("X") and port_out.name.startswith("X")
          and port_in.name != port_out.name,
          "порты получают обозначения X1, X2")
    check(port_in.ports["stub"]["direction"] == "out"
          and port_in.ports["stub"]["x"] > port_in.x,
          "у входного порта вывод-выход справа")
    check(port_out.ports["stub"]["direction"] == "in"
          and port_out.ports["stub"]["x"] < port_out.x,
          "у выходного порта вывод-вход слева")

    port_in.signal_ru = "Отключение ОТТН"
    port_in.signal_iec = "TRIP"
    port_in.signal_no = "9005"
    port_in.generate_ports()
    check(port_in.ports["stub"]["slot_name"] == "Отключение ОТТН"
          and port_in.ports["stub"]["slot_iec"] == "TRIP",
          "наименование сигнала порта передаётся на вывод")

    payload = ll.element_payload(port_in)
    check(payload["signal_no"] == "9005" and payload["title"] == "Входной порт",
          "поля порта попадают в JSON")
    restored = ll.LogicPortIn("X9", 0, 0)
    ll.restore_element(restored, payload)
    check(restored.signal_ru == "Отключение ОТТН"
          and restored.ports["stub"]["direction"] == "out",
          "поля порта читаются обратно")

    # Связь порт → функция: имя связи берётся с порта.
    block = app.elements[_add(app, "logic_block", 600, 200)]
    inputs = [name for name, port in block.ports.items()
              if port.get("direction") == "in"]
    link = app._add_logic_link((port_in.id, "stub"),
                               (block.id, inputs[0]))
    check(link is not None and link["ru"] == "Отключение ОТТН",
          "имя связи по умолчанию — с порта")

    app.redraw_all()
    texts = [app.canvas.itemcget(item, "text")
             for item in app.canvas.find_all()
             if app.canvas.type(item) == "text"]
    check(any("Входной порт" in text for text in texts)
          or any(port_in.name in text for text in texts),
          "подпись порта нарисована на полотне")


def test_update_links(app):
    print("21. обновление связей: общий номер — привязка и наименование")
    _reset(app)
    port_in = app.elements[_add(app, "logic_port_in", 100, 200)]
    block = app.elements[_add(app, "logic_block", 600, 200)]
    port_in.signal_ru = "Отключение ОТТН"
    port_in.signal_iec = "TRIP"
    port_in.signal_no = "9005"
    port_in.generate_ports()
    block.functions = [ll.normalize_function(
        {"kind": "AND", "title": "Функция", "inputs": 2, "outputs": 1})]
    block.generate_ports()
    inputs = [name for name, port in block.ports.items()
              if port.get("direction") == "in"]

    app.logic_link_kind = "discrete"
    first = app._add_logic_link((port_in.id, "stub"),
                                (block.id, inputs[0]))
    first["number"] = "9005"
    key = app.elements[_add(app, "logic_key", 100, 500)]
    second = app._add_logic_link((key.id, "right"),
                                 (block.id, inputs[1]))
    second["number"] = "9005"          # тот же сигнал, наименования нет

    bound, renamed, found = app._update_logic_groups()
    check((bound, renamed, found) == (1, 1, 1),
          "группа найдена: %d/%d/%d" % (bound, renamed, found))
    check(second["ru"] == "Отключение ОТТН" and second["iec"] == "TRIP",
          "наименование выровнено по элементу с маркировкой")
    check(str(second.get("continuation") or "") == str(first["id"]),
          "вторая связь привязана к первой как продолжение")
    check(not first.get("continuation"), "первая связь — источник")

    # Группа без элемента: наименование берётся из связи с именем.
    third = app._add_logic_link((block.id, "fn0_out0"), (key.id, "left"))
    fourth = app._add_logic_link((key.id, "right"), (block.id, inputs[1]))
    third["number"] = "9006"
    fourth["number"] = "9006"
    third["ru"] = "Пуск АВР"
    bound, renamed, found = app._update_logic_groups()
    check(fourth["ru"] == "Функция: Пуск АВР"
          and str(fourth.get("continuation") or "") == str(third["id"]),
          "продолжение получает полную маркировку выхода функции")

    # Полная маркировка «ФБ / Функция: Сигнал» доходит до связей-
    # продолжений, в том числе когда у continuation нет своего номера.
    led = app.elements[_add(app, "logic_led", 300, 500)]
    block.designation = "ЗП"
    block.functions = [ll.normalize_function({
        "kind": "CUSTOM", "title": "1 ступень", "name": "1 ступень",
        "outputs": [{"name": "Срабатывание", "iec_name": "Op"}]})]
    block.generate_ports()
    fifth = app._add_logic_link((block.id, "fn0_out0"), (key.id, "left"))
    fifth["number"] = "9007"
    sixth = app._add_logic_link((key.id, "right"), (led.id, "left"))
    sixth["number"] = "9007"
    app._update_logic_groups()
    check(sixth["ru"] == "ЗП / 1 ступень: Срабатывание"
          and str(sixth.get("continuation") or "") == str(fifth["id"]),
          "связь с той же маркировкой получила полное обозначение")
    seventh = app._add_logic_link((key.id, "right"), (led.id, "left"))
    seventh["number"] = ""
    seventh["continuation"] = fifth["id"]
    app._update_logic_groups()
    check(seventh["ru"] == "ЗП / 1 ступень: Срабатывание",
          "связь-продолжение без номера обновлена полной маркировкой")

    # Связи без номера не трогаются.
    unnumbered = app._add_logic_link((key.id, "right"), (block.id, inputs[0]))
    app._update_logic_groups()
    check(not unnumbered.get("continuation") and not unnumbered.get("ru"),
          "связь без номера осталась без изменений")

    # Пустой номер в другой группе не мешает нумерации
    numbers = [link.get("number") for link in app.logic_links]
    check(numbers.count("9005") == 2 and numbers.count("9006") == 2,
          "номера групп сохранились")


def test_point_drag(app):
    print("22. перенос точек и линии связи ФЛС")
    _reset(app)
    port_in = app.elements[_add(app, "logic_port_in", 100, 200)]
    block = app.elements[_add(app, "logic_block", 700, 200)]
    block.functions = [ll.normalize_function(
        {"kind": "AND", "title": "Функция", "inputs": 1, "outputs": 1})]
    block.generate_ports()
    app.logic_link_kind = "discrete"
    link = app._add_logic_link((port_in.id, "stub"), (block.id, "fn0_in0"))
    link["points"] = [[300.0, 260.0], [300.0, 340.0]]
    app.current_tool = "select"
    app.selected_logic = None
    app.zoom = 1.0
    app.offset_x = app.offset_y = 0.0

    # Точка невыделенной связи находится и захват выбирает связь.
    sx, sy = app.world_to_screen(300.0, 260.0)
    hit = app._logic_point_at(sx, sy)
    check(hit is not None and hit[1] is link,
          "точка невыделенной связи обнаружена")
    app.on_left_click(_event(sx, sy))
    check(app.selected_logic is link
          and app._dragging_point == ("link", link, 0),
          "захват точки выбрал связь и начал перетаскивание")

    # Тащим точку: линия перестраивается.
    ex, ey = app.world_to_screen(340.0, 260.0)
    app.on_drag(_event(ex, ey))
    check(link["points"][0] == [340.0, 260.0],
          "излом перетащен в новое место")
    app.on_release(_event(ex, ey))
    check(app._dragging_point is None, "перетаскивание точки завершено")

    # Линия целиком: клик по свободному участку и сдвиг.
    app.selected_logic = None
    route = app._logic_route(link)
    mx = (route[1][0] + route[2][0]) / 2.0
    my = (route[1][1] + route[2][1]) / 2.0
    sx, sy = app.world_to_screen(mx, my)
    app.on_left_click(_event(sx, sy))
    check(app._dragging_logic_route is not None
          and app._dragging_logic_route[0] is link,
          "клик по линии начал перетаскивание маршрута")
    before = [list(point) for point in link["points"]]
    ex, ey = app.world_to_screen(mx + 40.0, my)
    app.on_drag(_event(ex, ey))
    shifted = link["points"]
    check(all(close(new[0], old[0] + 40.0) and close(new[1], old[1])
              for new, old in zip(shifted, before)),
          "все изломы сдвинуты вместе с линией")
    app.on_release(_event(ex, ey))
    check(app._dragging_logic_route is None
          and app.selected_logic is link,
          "перетаскивание линии завершено, связь осталась выбрана")

    # Клик без движения не меняет маршрут.
    before = [list(point) for point in link["points"]]
    app.on_left_click(_event(sx, sy))
    app.on_release(_event(sx, sy))
    check(link["points"] == before, "клик без сдвига не меняет линию")


def test_mark_drag(app):
    print("23. номер и наименование перетаскиваются, стрелка выключена")
    _reset(app)
    port_in = app.elements[_add(app, "logic_port_in", 100, 200)]
    block = app.elements[_add(app, "logic_block", 700, 200)]
    app.logic_link_kind = "discrete"
    link = app._add_logic_link((port_in.id, "stub"), (block.id, "fn0_in0"))
    check(link.get("arrow") is False, "у новой связи стрелка отключена")
    link["ru"] = "Отключение ОТТН"
    app.current_tool = "select"
    app.selected_logic = None
    app.zoom = 1.0
    app.offset_x = app.offset_y = 0.0
    app.redraw_all()

    def box_of(part):
        for item_link, item_part, box in app._logic_label_boxes:
            if item_link is link and item_part == part:
                return box
        return None

    # Перетаскивание наименования.
    box = box_of("label")
    check(box is not None, "наименование нарисовано на полотне")
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    app.on_left_click(_event(cx, cy))
    check(app._dragging_logic_mark is not None
          and app._dragging_logic_mark[1] == "label",
          "клик по наименованию начал перетаскивание")
    app.on_drag(_event(cx + 50, cy + 30))
    app.on_release(_event(cx + 50, cy + 30))
    check(link.get("label_offset") == [50.0, 30.0],
          "смещение наименования сохранено в связи")
    app.redraw_all()
    moved = box_of("label")
    check(abs(moved[0] - box[0] - 50) < 2.0
          and abs(moved[1] - box[1] - 30) < 2.0,
          "наименование нарисовано в новом месте")

    # Перетаскивание номера у начала линии.
    box = box_of("start")
    check(box is not None, "номер нарисован у начала линии")
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    app.on_left_click(_event(cx, cy))
    check(app._dragging_logic_mark is not None
          and app._dragging_logic_mark[1] == "start",
          "клик по номеру начал перетаскивание")
    app.on_drag(_event(cx + 20, cy - 40))
    app.on_release(_event(cx + 20, cy - 40))
    check(link.get("mark_offsets", {}).get("start") == [20.0, -40.0],
          "смещение номера сохранено в связи")

    # Клики без движения ничего не меняют.
    before = [list(link.get("label_offset") or [0.0, 0.0])]
    box = box_of("label")
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    app.on_left_click(_event(cx, cy))
    app.on_release(_event(cx, cy))
    check([list(link.get("label_offset") or [0.0, 0.0])] == before,
          "клик без движения не сдвигает наименование")

    # Сериализация: смещения и стрелка сохраняются в JSON.
    record = app._logic_link_record(link)
    check(record.get("label_offset") == [50.0, 30.0]
          and record.get("mark_offsets") == {"start": [20.0, -40.0]}
          and record.get("arrow") is False,
          "смещения и стрелка попадают в JSON")
    restored = app._build_logic_links([record], None)
    check(restored[0].get("label_offset") == [50.0, 30.0]
          and restored[0].get("mark_offsets") == {"start": [20.0, -40.0]}
          and restored[0].get("arrow") is False,
          "смещения и стрелка читаются обратно")

    # Экспорт PDF/PNG: аннотации со смещениями.
    data = {"elements": [], "connections": [], "logic_links": [record]}
    for element in app.elements.values():
        item = {"id": element.id, "type": element.type,
                "name": element.name, "x": element.x, "y": element.y}
        if ll.is_logic_type(element.type):
            item["logic"] = ll.element_payload(element)
        data["elements"].append(item)
    elements = lsr.build_elements(data)
    links = lsr.build_logic_links(data, elements)
    prepared = [(item, lsr.route(elements, item)) for item in links]
    numbers, labels = lsr.annotations(elements, links, prepared)
    plain = {key: value for key, value in record.items()
             if key not in ("label_offset", "mark_offsets")}
    data2 = {"elements": data["elements"], "connections": [],
             "logic_links": [plain]}
    elements2 = lsr.build_elements(data2)
    links2 = lsr.build_logic_links(data2, elements2)
    prepared2 = [(item, lsr.route(elements2, item)) for item in links2]
    numbers2, labels2 = lsr.annotations(elements2, links2, prepared2)
    label, label2 = labels[0][1], labels2[0][1]
    check(abs(label[0] - (label2[0] + 50)) < 0.5
          and abs(label[1] - (label2[1] + 30)) < 0.5,
          "экспорт рисует наименование со смещением")
    number, number2 = numbers[0][1], numbers2[0][1]
    check(number is not None and number2 is not None
          and abs(number[0] - (number2[0] + 20)) < 0.5
          and abs(number[1] - (number2[1] - 40)) < 0.5,
          "экспорт рисует номер со смещением")


def test_schematic_elements(app):
    print("28. принципиальная схема шкафа (элементы из DXF)")
    import schematic_library as sl
    _reset(app)
    lamp = app.elements[_add(app, "sc_lamp", 100, 200)]
    contact = app.elements[_add(app, "sc_closing_contact", 300, 200)]
    coil = app.elements[_add(app, "sc_relay_coil", 500, 200)]
    test_block = app.elements[_add(app, "sc_test_block", 700, 200)]
    check(lamp.type == "sc_lamp" and contact.type == "sc_closing_contact"
          and coil.type == "sc_relay_coil"
          and test_block.type == "sc_test_block",
          "элементы принципиальной схемы поставлены на чертёж")
    check(lamp.name.startswith("HL") and coil.name.startswith("KA")
          and test_block.name.startswith("TB"),
          "элементы получили префиксы из библиотеки")
    check(set(lamp.ports) == {"left", "right"}
          and set(coil.ports) == {"left", "right"},
          "у элементов два вывода — слева и справа")
    check(set(test_block.ports) == {"1", "2"}
          and test_block.ports["1"]["direction"] == "in"
          and test_block.ports["2"]["direction"] == "out",
          "у тестового блока порты 1 и 2 из YAML-описания")
    icon = getattr(app, "_tool_icons", {}).get("sc_test_block")
    check(("Тестовый блок", "sc_test_block") in sl.PALETTE_ITEMS
          and icon is not None and len(icon.find_all()) > 5,
          "тестовый блок добавлен в палитру принципиальных схем")
    app.redraw_all()
    texts = {app.canvas.itemcget(item, "text")
             for item in app.canvas.find_all()
             if app.canvas.type(item) == "text"}
    check({"ОУ", "В1", "В2"} <= texts,
          "поля ОУ, В1, В2 нарисованы на тестовом блоке")
    app.logic_link_kind = "schematic"
    link = app._add_logic_link((lamp.id, "right"), (contact.id, "left"))
    check(link is not None and link["kind"] == "schematic",
          "элементы связаны цепью принципиальной схемы")
    tabs = getattr(app, "_palette_tab_buttons", {})
    check("Принципиальная схема" in tabs,
          "в палитре есть вкладка принципиальной схемы")
    app._set_palette_mode("Принципиальная схема")
    app.root.update()
    check(app._palette_frames["Принципиальная схема"].winfo_manager() == "pack"
          and app._palette_frames["Первичная схема"].winfo_manager() == "",
          "вкладка принципиальной схемы показывает свои элементы")
    app.set_tool("sc_resistor")
    check(app.logic_link_kind == "schematic"
          and app.current_tool == "sc_resistor",
          "выбор элемента принципиальной схемы включает её цепь")
    payload = sl.element_payload(lamp)
    check(payload["type"] == "Лампа",
          "свойства элемента сохраняются в JSON")
    lamp.designation = "HL77"
    sl.restore_element(lamp, sl.element_payload(lamp))
    check(lamp.designation == "HL77" and set(lamp.ports) == {"left", "right"},
          "восстановление из JSON сохраняет подпись и порты")

    # Палитра: три вкладки, без выпадающего списка, переключение вкладок.
    import main
    check(all(mode in getattr(app, "_palette_frames", {})
              for mode in main.PALETTE_MODES),
          "панель элементов переключается на три схемы")

    def _walk(widget):
        yield widget
        for child in widget.winfo_children():
            for item in _walk(child):
                yield item

    combos = [item for item in _walk(app._palette_wrap)
              if isinstance(item, ttk.Combobox)]
    check(not combos, "выпадающего списка в палитре больше нет")
    check(set(tabs) == set(main.PALETTE_MODES) and len(tabs) == 3,
          "вкладки панелей: %s" % ", ".join(main.PALETTE_MODES))
    check(tabs["Принципиальная схема"].cget("bg") == ui_theme.TOOL_ACTIVE
          and tabs["Первичная схема"].cget("bg") == ui_theme.PALETTE,
          "активная вкладка палитры выделена цветом темы")
    app._set_palette_mode("Первичная схема")
    app.root.update()
    check(app._palette_mode.get() == "Первичная схема"
          and tabs["Первичная схема"].cget("bg") == ui_theme.TOOL_ACTIVE,
          "вкладки палитры переключаются кликом")

    # Регрессия: элементы принципиальной схемы не выделялись кликом из-за
    # двойного сдвига bbox (spec['bbox'] локальный, а _rotated_bbox сам
    # прибавляет координаты центра элемента).
    app.zoom = 1.0
    app.offset_x = app.offset_y = 0.0
    bx1, by1, bx2, by2 = coil.get_bounding_box()
    cx, cy = app.world_to_screen((bx1 + bx2) / 2.0, (by1 + by2) / 2.0)
    check(app._element_at(cx, cy) == coil.id,
          "bbox элемента принципиальной схемы совпадает с его положением")
    app.set_tool("select")
    app.selected_elements = []
    app.on_left_click(_event(cx, cy))
    check(coil.id in app.selected_elements,
          "элемент принципиальной схемы выделяется кликом по нему")


def run_gui():
    import main
    main.messagebox.showinfo = lambda *args, **kwargs: None
    main.messagebox.showerror = lambda *args, **kwargs: None
    main.messagebox.askyesno = lambda *args, **kwargs: True

    root = tk.Tk()
    root.withdraw()
    app = main.CircuitEditor(root)
    try:
        root.update()
        app.zoom = 1.0
        app.offset_x = app.offset_y = 0.0
        test_elements(app)
        test_bus(app)
        test_bus_links(app)
        test_links(app)
        test_link_geometry(app)
        test_block(app)
        test_round_trip(app)
        test_copy_paste(app)
        test_export(app)
        test_delete(app)
        test_link_dialog(app, root)
        test_block_dialog(app, root)
        test_function_dialog_slots(app, root)
        test_block_insert_dialog(app)
        test_ribbon_kind(app)
        test_legend(app)
        test_renumber(app)
        test_block_preview(app, root)
        test_block_grid(app)
        test_ports(app)
        test_update_links(app)
        test_point_drag(app)
        test_mark_drag(app)
        test_schematic_elements(app)
    finally:
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Элементы функционально-логических схем")
    parser.add_argument("--no-gui", action="store_true",
                        help="без окон tkinter")
    args = parser.parse_args(argv)

    test_numbering()
    test_payload()
    test_full_signal_label()
    test_structure2_model()
    if args.no_gui:
        print("\nGUI-проверки пропущены (--no-gui)")
    elif tk is None:
        print("\nGUI-проверки пропущены: tkinter недоступен")
    else:
        run_gui()

    print()
    if FAILURES:
        print("ПРОВАЛЕНО: %d" % len(FAILURES))
        for message in FAILURES:
            print("  - %s" % message)
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
