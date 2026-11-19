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
14. смену типа выбранной связи из ленты и отмену;
15. легенду типов связей на полотне;
16. сквозную нумерацию связей.
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
except ImportError:         # pragma: no cover
    tk = None

import logic_library as ll

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
    ll.restore_element(bus, ll.element_payload(bus))
    check(close(bus.length, 300) and "p1" in bus.ports,
          "длина шины и отводы восстановлены")


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
    check(len(app.elements) == 5, "созданы все пять элементов")
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
    polygons = [item for item in app.canvas.find_withtag("logic_link")
                if app.canvas.type(item) == "polygon"]
    check(bool(polygons), "стрелка направления нарисована")

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
        test_links(app)
        test_link_geometry(app)
        test_block(app)
        test_round_trip(app)
        test_copy_paste(app)
        test_export(app)
        test_delete(app)
        test_link_dialog(app, root)
        test_block_dialog(app, root)
        test_block_insert_dialog(app)
        test_ribbon_kind(app)
        test_legend(app)
        test_renumber(app)
        test_block_preview(app, root)
        test_block_grid(app)
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
