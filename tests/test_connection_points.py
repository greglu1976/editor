# -*- coding: utf-8 -*-
"""Опорные точки связей: полилиния, маркеры и совместимость JSON.

Запуск:
    python3 tests/test_connection_points.py           # полный набор, нужен tkinter
    python3 tests/test_connection_points.py --no-gui  # только формат точек

Проверяет:

1. ``_clean_points`` — формат ``[[x, y], ...]``, битые пары отбрасываются,
   значения округляются до 0.1;
2. ``_connection_points`` — маршрут «порт → изломы → порт», отсутствие поля
   ``points`` даёт прямую линию;
3. попадание в маркер излома и в сегмент провода, выбор связи кликом;
4. вставку точки двойным кликом по сегменту и удаление двойным кликом по
   маркеру, удаление выбранной связи клавишей Delete;
5. перетаскивание точки и сдвиг изломов вместе с элементом;
6. сохранение в JSON, чтение обратно, старые файлы без ``points`` и мусор
   в поле ``points``;
7. копирование/вставку со смещением изломов и отмену действий;
8. отрисовку полилинии и маркеров выбранной связи;
9. экспорт SSD: изломы не меняют узлы связности и состав оборудования.
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

try:                        # GUI-часть необязательна (например, в CI)
    import tkinter as tk
except ImportError:         # pragma: no cover - зависит от сборки Python
    tk = None

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def close(left, right, tolerance=0.05):
    """Сравнение чисел и пар координат с допуском на округление."""
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return (len(left) == len(right)
                and all(close(a, b, tolerance) for a, b in zip(left, right)))
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return left == right


def _event(x, y, state=0):
    """Поддельное событие мыши: обработчикам нужны только координаты."""
    return SimpleNamespace(x=x, y=y, state=state, num=None, delta=0)


def _add(app, etype, x, y):
    """Добавляет элемент и возвращает его id."""
    before = set(app.elements)
    app.add_element(etype, x, y)
    return next(iter(set(app.elements) - before))


def _reset(app):
    """Пустая схема для очередной проверки."""
    app.elements = {}
    app.connections = []
    app.selected_elements = []
    app.selected_connection = None
    app.protection_links = []
    app.analog_links = []
    app.comments = []
    app.current_path = None


def _pair(app):
    """Два выключателя и связь «верх → верх» между ними."""
    first = _add(app, "breaker", 100, 100)
    second = _add(app, "breaker", 300, 100)
    connection = app.create_connection(first, second, "top", "top")
    return first, second, connection


def test_clean_points():
    print("1. формат опорных точек")
    try:
        import main
    except Exception as error:                      # pragma: no cover
        print("  пропуск: main не импортируется (%s)" % error)
        return
    clean = main.CircuitEditor._clean_points
    check(clean(None) == [], "None → пустой список")
    check(clean("100,200") == [], "строка → пустой список")
    check(clean([[10, 20]]) == [[10.0, 20.0]], "пара чисел сохраняется")
    check(clean([(1, 2)]) == [[1.0, 2.0]], "кортеж тоже принимается")
    check(clean([[10, 20], [30], "x", [1, 2, 3], [None, 5]]) == [[10.0, 20.0]],
          "битые пары отбрасываются")
    check(clean([["10.44", "20.46"]]) == [[10.4, 20.5]],
          "значения округляются до 0.1")


def test_route(app):
    print("2. маршрут связи")
    _reset(app)
    first, second, connection = _pair(app)
    port1 = app.elements[first].ports["top"]
    port2 = app.elements[second].ports["top"]

    route = app._connection_points(connection)
    check(len(route) == 2, "без изломов маршрут — два порта")
    check(close(route[0], (port1["x"], port1["y"])),
          "маршрут начинается в порту from")
    check(close(route[-1], (port2["x"], port2["y"])),
          "маршрут заканчивается в порту to")

    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]
    route = app._connection_points(connection)
    check(len(route) == 4, "изломы добавляют точки маршрута")
    check(close(route[1], (100.0, 60.0)) and close(route[2], (200.0, 60.0)),
          "изломы стоят между портами")

    check(app.create_connection(first, second, "top", "top") is connection,
          "повторная связь не дублируется")
    check(app.create_connection(first, second, "bottom", "bottom") is not connection,
          "связь по другим портам создаётся отдельно")


def test_hit(app):
    print("3. попадание в маркер и сегмент")
    _reset(app)
    _, _, connection = _pair(app)
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]
    app.selected_connection = connection
    app.redraw_all()

    sx, sy = app.world_to_screen(100.0, 60.0)
    check(app._connection_point_at(sx + 2, sy - 1) == (connection, 0),
          "маркер излома находится под курсором")
    check(app._connection_point_at(sx + 40, sy + 40) is None,
          "мимо маркера — None")

    sx, sy = app.world_to_screen(150.0, 60.0)
    check(app._connection_segment_at(sx, sy) == (connection, 1),
          "сегмент между изломами определяется")
    check(app._connection_at(sx, sy) is connection,
          "клик по линии находит связь")

    app.selected_connection = None
    app.on_left_click(_event(sx, sy))
    check(app.selected_connection is connection,
          "клик по проводу выбирает связь")
    check(app.selected_elements == [], "выбор элементов снят")


def test_edit(app):
    print("4. вставка, удаление и перетаскивание точек")
    _reset(app)
    _, _, connection = _pair(app)
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]
    app.redraw_all()

    # Двойной клик по сегменту 1 — точка встаёт между изломами
    sx, sy = app.world_to_screen(150.0, 60.0)
    app.on_double_click(_event(sx, sy))
    check(len(connection["points"]) == 3, "двойной клик по сегменту вставил точку")
    check(close(connection["points"][1], [150.0, 60.0], 10.0),
          "точка вставлена в месте клика (с привязкой к сетке)")
    check(app.selected_connection is connection,
          "вставка выделяет связь для правки")

    # Двойной клик по маркеру — точка удаляется
    sx, sy = app.world_to_screen(*connection["points"][1])
    app.on_double_click(_event(sx, sy))
    check(len(connection["points"]) == 2, "двойной клик по маркеру удалил точку")

    # Удаляем оставшиеся изломы: пустое поле не хранится
    for _ in range(2):
        sx, sy = app.world_to_screen(*connection["points"][0])
        app.on_double_click(_event(sx, sy))
    check("points" not in connection, "пустой список изломов не хранится")
    check(len(app._connection_points(connection)) == 2,
          "после удаления изломов связь снова прямая")

    # Перетаскивание маркера
    connection["points"] = [[100.0, 60.0]]
    app.selected_connection = connection
    app.redraw_all()
    sx, sy = app.world_to_screen(100.0, 60.0)
    app.on_left_click(_event(sx, sy))
    check(app._dragging_point == (connection, 0),
          "нажатие на маркер начинает перетаскивание")
    nx, ny = app.world_to_screen(180.0, 40.0)
    app.on_drag(_event(nx, ny))
    check(not close(connection["points"][0], [100.0, 60.0]),
          "точка следует за курсором")
    app.on_release(_event(nx, ny))
    check(app._dragging_point is None, "перетаскивание завершено")
    moved = [list(point) for point in connection["points"]]

    app.undo_last_action()
    restored = app.connections[0]
    check(close(restored["points"][0], [100.0, 60.0]),
          "отмена возвращает точку на место")
    check(not close(restored["points"][0], moved[0]),
          "отмена отличается от перемещённого положения")

    # Delete удаляет выбранную связь
    app.selected_connection = restored
    app.delete_selected()
    check(restored not in app.connections,
          "Delete удаляет выбранную связь")


def test_shift_routes(app):
    print("5. сдвиг изломов вместе с элементом")
    _reset(app)
    first, second, connection = _pair(app)
    third = _add(app, "breaker", 500, 100)
    other = app.create_connection(second, third, "top", "top")
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]
    other["points"] = [[300.0, 60.0]]

    app.selected_elements = [first]
    app._remember_drag_routes()
    app.elements[first].x += 40
    app.elements[first].y += 20
    app._shift_drag_routes()

    check(close(connection["points"][0], [140.0, 80.0])
          and close(connection["points"][1], [240.0, 80.0]),
          "изломы связи выделенного элемента сдвинулись")
    check(close(other["points"][0], [300.0, 60.0]),
          "изломы чужой связи остались на месте")

    # Элемент, не входящий в связь, изломы не двигает
    app.selected_elements = [third]
    app._remember_drag_routes()
    app.elements[third].x += 20
    app._shift_drag_routes()
    check(close(connection["points"][0], [140.0, 80.0]),
          "связь без выделенного элемента не сдвигается")


def test_round_trip(app):
    print("6. сохранение, загрузка и совместимость")
    _reset(app)
    first, second, connection = _pair(app)
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]

    folder = tempfile.mkdtemp(prefix="points-")
    path = os.path.join(folder, "scheme.json")
    app.current_path = path
    check(app._write_scheme() is True, "схема сохранена")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    record = data["connections"][0]
    check(record.get("points") == [[100.0, 60.0], [200.0, 60.0]],
          "изломы записаны в JSON")
    check(record.get("element_from") == first
          and record.get("element_to") == second
          and record.get("port_from") == "top"
          and record.get("port_to") == "top",
          "топология связи не изменилась")
    check("node_from" in record and "node_to" in record,
          "узлы схемы сохранены")

    built = app._build_connections(data, app.elements)
    check(built and built[0]["points"] == [[100.0, 60.0], [200.0, 60.0]],
          "изломы читаются обратно")
    check(len(app._connection_points(built[0])) == 4,
          "после загрузки маршрут остаётся полилинией")

    # Старый файл: поля points нет — связь прямая
    old = {"elements": data["elements"],
           "connections": [{key: value for key, value in record.items()
                            if key != "points"}]}
    built = app._build_connections(old, app.elements)
    check("points" not in built[0], "старый файл без изломов читается")
    check(len(app._connection_points(built[0])) == 2,
          "старая связь рисуется прямой")

    # Мусор в points не ломает загрузку
    broken = copy.deepcopy(old)
    broken["connections"][0]["points"] = [[10, 20], [30], "x", [None, 2]]
    built = app._build_connections(broken, app.elements)
    check(built[0]["points"] == [[10.0, 20.0]],
          "битые изломы при загрузке отбрасываются")


def test_paste(app):
    print("7. копирование и вставка")
    _reset(app)
    first, second, connection = _pair(app)
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]

    app.selected_elements = [first, second]
    app.copy_selection()
    app.paste_selection()

    new_connection = next(item for item in app.connections
                          if item is not connection)
    new_first = app.elements[new_connection["from"]]
    dx = new_first.x - app.elements[first].x
    dy = new_first.y - app.elements[first].y
    check(new_connection["from"] not in (first, second)
          and new_connection["to"] not in (first, second),
          "вставленная связь ведёт к новым элементам")
    check(len(new_connection["points"]) == 2, "изломы скопированы")
    check(close(new_connection["points"][0], [100.0 + dx, 60.0 + dy]),
          "первый излом смещён вместе с элементом")
    check(close(new_connection["points"][1], [200.0 + dx, 60.0 + dy]),
          "второй излом смещён на тот же вектор")


def test_draw(app):
    print("8. отрисовка полилинии и маркеров")
    _reset(app)
    _, _, connection = _pair(app)
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]
    app.selected_connection = None
    app.redraw_all()

    coords = app.canvas.coords(connection["canvas_id"])
    check(len(coords) == 8, "линия построена по четырём точкам")
    route = app._connection_points(connection)
    check(close(coords[:2], app.world_to_screen(*route[0]))
          and close(coords[-2:], app.world_to_screen(*route[-1])),
          "концы линии совпадают с портами")
    check(app.canvas.itemcget(connection["canvas_id"], "fill") == "black",
          "невыбранная связь чёрная")

    app.selected_connection = connection
    app.redraw_all()
    check(app.canvas.itemcget(connection["canvas_id"], "fill") == "#1565c0",
          "выбранная связь подсвечена")
    markers = app.canvas.find_withtag("connection_point")
    check(len(markers) == 2, "маркеры изломов нарисованы")
    check(all(app.canvas.type(item) == "rectangle" for item in markers),
          "маркеры — квадраты")


def test_export(app):
    print("9. экспорт не зависит от изломов")
    import ssdexport
    _reset(app)
    _, _, connection = _pair(app)
    plain = copy.deepcopy(app.connections)
    connection["points"] = [[100.0, 60.0], [200.0, 60.0]]
    bent = copy.deepcopy(app.connections)

    _, flat_stats = ssdexport.build_ssd(app.elements, plain)
    _, bent_stats = ssdexport.build_ssd(app.elements, bent)
    check(flat_stats["connectivity_nodes"] == bent_stats["connectivity_nodes"],
          "число узлов связности не изменилось")
    check(flat_stats["terminals"] == bent_stats["terminals"],
          "число присоединений не изменилось")
    check(flat_stats["equipment"] == bent_stats["equipment"],
          "состав оборудования не изменился")


def run_gui():
    import main
    # Диалоги сохранения не должны блокировать тест
    main.messagebox.showinfo = lambda *args, **kwargs: None
    main.messagebox.showerror = lambda *args, **kwargs: None

    root = tk.Tk()
    root.withdraw()
    app = main.CircuitEditor(root)
    try:
        root.update()
        app.zoom = 1.0
        app.offset_x = app.offset_y = 0.0
        test_route(app)
        test_hit(app)
        test_edit(app)
        test_shift_routes(app)
        test_round_trip(app)
        test_paste(app)
        test_draw(app)
        test_export(app)
    finally:
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Опорные точки связей")
    parser.add_argument("--no-gui", action="store_true",
                        help="без окон tkinter")
    args = parser.parse_args(argv)

    test_clean_points()
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
