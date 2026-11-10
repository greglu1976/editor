# -*- coding: utf-8 -*-
"""Опорные точки аналоговых связей: полилиния, маркеры и совместимость JSON.

Запуск:
    python3 tests/test_analog_points.py           # полный набор, нужен tkinter
    python3 tests/test_analog_points.py --no-gui  # только геометрия ломаной

Проверяет:

1. ``_analog_route`` — маршрут «конец from → изломы → конец to»,
   ``_path_midpoint`` — середину ломаной для подписи цепей;
2. попадание в линию и в сегмент, выбор связи кликом, Ctrl+клик и Delete;
3. вставку излома двойным кликом по сегменту и удаление по маркеру;
4. перетаскивание маркера и отмену через Undo;
5. сдвиг изломов вместе с ТТ/ТН или шкафом;
6. сохранение в JSON, чтение обратно, старые файлы без ``points``
   и мусор в поле ``points``;
7. копирование/вставку со смещением изломов;
8. отрисовку пунктирной полилинии, стрелки, подписи и маркеров;
9. экспорт PDF/PNG: ломаная и острие стрелки попадают в сцену.
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
    app.selected_elements = []
    app.selected_connection = None
    app.selected_analog = None
    app.protection_links = []
    app.comments = []
    app.current_path = None


def _pair(app):
    """Шкаф с одним комплектом, ТТ и аналоговая связь ТТ → комплект."""
    import library
    cabinet = _add(app, "cabinet", 200, 200)
    app.elements[cabinet].komplets = library.normalize_komplets(
        [{"name": "К1"}])
    transformer = _add(app, "current_transformer", 500, 200)
    link = app._add_analog_link(cabinet + "#0", transformer)
    return cabinet, transformer, link


def _bent(app):
    """Та же связь с двумя изломами: от ТТ влево, затем вверх."""
    cabinet, transformer, link = _pair(app)
    link["voltage"] = "Ua"
    link["points"] = [[400.0, 200.0], [400.0, 100.0]]
    return cabinet, transformer, link


def test_midpoint():
    print("1. геометрия ломаной")
    try:
        import main
    except Exception as error:                      # pragma: no cover
        print("  пропуск: main не импортируется (%s)" % error)
        return
    middle = main.CircuitEditor._path_midpoint
    result = middle([(0, 0), (100, 0)])
    check(result is not None and close(result[:2], (50, 0))
          and close(result[2:], (1, 0)),
          "середина прямой и её направление")
    result = middle([(0, 0), (100, 0), (100, 100)])
    check(result is not None and close(result[:2], (100, 0)),
          "середина ломаной попадает на угол")
    check(middle([(0, 0), (0, 0)]) is None,
          "нулевая длина — середины нет")


def test_route(app):
    print("2. маршрут аналоговой связи")
    _reset(app)
    cabinet, transformer, link = _pair(app)
    start = app._analog_ref_point(link["from"])
    end = app._analog_ref_point(link["to"])
    route = app._analog_route(link)
    check(len(route) == 2, "без изломов маршрут — два конца")
    check(close(route[0], start) and close(route[-1], end),
          "маршрут начинается и заканчивается концами связи")

    link["points"] = [[400.0, 200.0], [400.0, 100.0]]
    route = app._analog_route(link)
    check(len(route) == 4, "изломы добавляют точки маршрута")
    check(close(route[1], (400.0, 200.0))
          and close(route[2], (400.0, 100.0)),
          "изломы стоят между концами")

    broken = {"from": link["from"], "to": link["to"],
              "points": [[10, 20], [30]]}
    check(len(app._analog_route(broken)) == 3,
          "битые пары не ломают маршрут")


def test_hit(app):
    print("3. попадание в линию и сегмент")
    _reset(app)
    _, _, link = _bent(app)
    app.selected_analog = None
    app.redraw_all()

    sx, sy = app.world_to_screen(450.0, 200.0)
    check(app._analog_link_at(sx, sy) is link,
          "клик по первому сегменту находит связь")
    check(app._analog_segment_at(sx, sy) == (link, 0),
          "номер сегмента — 0")
    sx, sy = app.world_to_screen(400.0, 150.0)
    check(app._analog_segment_at(sx, sy) == (link, 1),
          "номер вертикального сегмента — 1")
    check(app._analog_link_at(*app.world_to_screen(450.0, 300.0)) is None,
          "вдали от линии — None")

    app.on_left_click(_event(sx, sy))
    check(app.selected_analog is link, "клик по линии выбирает связь")
    check(app.selected_elements == [], "выбор элементов снят")
    check(app.selected_connection is None, "выбор провода снят")


def test_edit(app):
    print("4. вставка, удаление и перетаскивание изломов")
    _reset(app)
    _, _, link = _bent(app)
    app.redraw_all()

    # Двойной клик по вертикальному сегменту — вставка в него
    sx, sy = app.world_to_screen(400.0, 150.0)
    app.on_double_click(_event(sx, sy))
    check(len(link["points"]) == 3, "двойной клик по сегменту вставил излом")
    check(close(link["points"][1], [400.0, 150.0], 10.0),
          "излом вставлен в месте клика (с привязкой к сетке)")
    check(app.selected_analog is link, "вставка выделяет связь")

    # Двойной клик по маркеру — удаление излома
    sx, sy = app.world_to_screen(*link["points"][1])
    app.on_double_click(_event(sx, sy))
    check(len(link["points"]) == 2, "двойной клик по маркеру удалил излом")

    # Удаляем оставшиеся изломы: пустое поле не хранится
    for _ in range(2):
        sx, sy = app.world_to_screen(*link["points"][0])
        app.on_double_click(_event(sx, sy))
    check("points" not in link, "пустой список изломов не хранится")
    check(len(app._analog_route(link)) == 2, "связь снова прямая")

    # Перетаскивание маркера
    link["points"] = [[400.0, 200.0]]
    app.selected_analog = link
    app.redraw_all()
    sx, sy = app.world_to_screen(400.0, 200.0)
    app.on_left_click(_event(sx, sy))
    check(app._dragging_point == ("link", link, 0),
          "нажатие на маркер начинает перетаскивание")
    nx, ny = app.world_to_screen(360.0, 240.0)
    app.on_drag(_event(nx, ny))
    check(not close(link["points"][0], [400.0, 200.0]),
          "излом следует за курсором")
    app.on_release(_event(nx, ny))
    check(app._dragging_point is None, "перетаскивание завершено")

    app.undo_last_action()
    restored = app.analog_links[0]
    check(close(restored["points"][0], [400.0, 200.0]),
          "отмена возвращает излом на место")

    # Delete удаляет выбранную связь
    app.selected_analog = restored
    app.delete_selected()
    check(restored not in app.analog_links,
          "Delete удаляет выбранную аналоговую связь")


def test_ctrl_delete(app):
    print("5. Ctrl+клик и кнопка свойств")
    _reset(app)
    _, _, link = _pair(app)
    app.redraw_all()
    route = app._analog_route(link)
    # точка на линии рядом с ТТ, вне габаритов шкафа
    x = route[0][0] + (route[-1][0] - route[0][0]) * 0.2
    y = route[0][1] + (route[-1][1] - route[0][1]) * 0.2
    sx, sy = app.world_to_screen(x, y)
    app.on_left_click(_event(sx, sy, state=0x0004))
    check(link not in app.analog_links, "Ctrl+клик удаляет связь")
    check(app.selected_analog is None, "выбор снят после удаления")


def test_shift_routes(app):
    print("6. сдвиг изломов вместе с элементом")
    _reset(app)
    cabinet, transformer, link = _bent(app)
    other = _add(app, "breaker", 700, 200)
    other_link = app._add_analog_link(cabinet + "#0", other)
    check(other_link is None, "произвольный элемент не подключается")

    app.selected_elements = [transformer]
    app._remember_drag_routes()
    app.elements[transformer].x += 40
    app.elements[transformer].y += 20
    app._shift_drag_routes()
    check(close(link["points"][0], [440.0, 220.0])
          and close(link["points"][1], [440.0, 120.0]),
          "изломы связи сдвинулись вместе с ТТ")

    app.selected_elements = [cabinet]
    app._remember_drag_routes()
    app.elements[cabinet].x += 20
    app._shift_drag_routes()
    check(close(link["points"][0], [460.0, 220.0]),
          "шкаф на другом конце тоже двигает изломы")

    app.selected_elements = [_add(app, "breaker", 900, 400)]
    app._remember_drag_routes()
    app._shift_drag_routes()
    check(close(link["points"][0], [460.0, 220.0]),
          "посторонний элемент изломы не двигает")


def test_round_trip(app):
    print("7. сохранение, загрузка и совместимость")
    _reset(app)
    _, _, link = _bent(app)
    link["current"] = "Ia"

    folder = tempfile.mkdtemp(prefix="analog-")
    path = os.path.join(folder, "scheme.json")
    app.current_path = path
    check(app._write_scheme() is True, "схема сохранена")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    record = data["analog_links"][0]
    check(record.get("points") == [[400.0, 200.0], [400.0, 100.0]],
          "изломы записаны в JSON")
    check(record.get("voltage") == "Ua" and record.get("current") == "Ia",
          "цепи напряжения и тока сохранены")
    check(set(record) == {"from", "to", "voltage", "current", "points"},
          "в записи нет служебных полей")

    built = app._build_analog_links(data["analog_links"])
    check(built and built[0]["points"] == [[400.0, 200.0], [400.0, 100.0]],
          "изломы читаются обратно")
    check(len(app._analog_route(built[0])) == 4,
          "после загрузки маршрут остаётся ломаной")

    old = [{key: value for key, value in record.items() if key != "points"}]
    built = app._build_analog_links(old)
    check("points" not in built[0], "старый файл без изломов читается")
    check(len(app._analog_route(built[0])) == 2, "старая связь прямая")

    broken = copy.deepcopy(old)
    broken[0]["points"] = [[10, 20], [30], "x", [None, 2]]
    built = app._build_analog_links(broken)
    check(built[0]["points"] == [[10.0, 20.0]],
          "битые изломы при загрузке отбрасываются")


def test_paste(app):
    print("8. копирование и вставка")
    _reset(app)
    cabinet, transformer, link = _bent(app)
    app.selected_elements = [cabinet, transformer]
    app.copy_selection()
    check(bool(app.clipboard_analog), "связь попала в буфер")
    check(app.clipboard_analog[0]["points"] is not link["points"],
          "изломы в буфере скопированы, а не связаны")

    app.paste_selection()
    new_link = next(item for item in app.analog_links if item is not link)
    new_transformer = app.elements[new_link["from"]]
    dx = new_transformer.x - app.elements[transformer].x
    dy = new_transformer.y - app.elements[transformer].y
    check(close(new_link["points"][0], [400.0 + dx, 200.0 + dy]),
          "первый излом смещён вместе с элементом")
    check(close(new_link["points"][1], [400.0 + dx, 100.0 + dy]),
          "второй излом смещён на тот же вектор")
    check(new_link.get("voltage") == "Ua", "подпись цепи скопирована")


def test_draw(app):
    print("9. отрисовка ломаной, стрелки и маркеров")
    _reset(app)
    _, _, link = _bent(app)
    app.selected_analog = None
    app.redraw_all()

    lines = [item for item in app.canvas.find_withtag("analog_link")
             if app.canvas.type(item) == "line"]
    check(bool(lines), "линия связи нарисована")
    coords = app.canvas.coords(lines[0])
    check(len(coords) == 8, "линия построена по четырём точкам")
    check(app.canvas.itemcget(lines[0], "fill") == app.ANALOG_COLOR,
          "цвет линии — фиолетовый")
    check(bool(app.canvas.itemcget(lines[0], "dash")),
          "линия пунктирная")
    polygons = [item for item in app.canvas.find_withtag("analog_link")
                if app.canvas.type(item) == "polygon"]
    check(bool(polygons), "острие стрелки нарисовано")

    boxes = app._analog_label_boxes
    check(len(boxes) == 1 and boxes[0][0] is link,
          "подпись цепи привязана к связи")
    sx = (boxes[0][1][0] + boxes[0][1][2]) / 2.0
    sy = (boxes[0][1][1] + boxes[0][1][3]) / 2.0
    check(app._analog_label_at(sx, sy) is link,
          "двойной клик по подписи находит связь")

    app.selected_analog = link
    app.redraw_all()
    markers = app.canvas.find_withtag("analog_point")
    check(len(markers) == 2, "маркеры изломов нарисованы")
    check(all(app.canvas.type(item) == "rectangle" for item in markers),
          "маркеры — квадраты")
    selected_line = [item for item in app.canvas.find_withtag("analog_link")
                     if app.canvas.type(item) == "line"][0]
    check(int(float(app.canvas.itemcget(selected_line, "width"))) > 1,
          "выбранная связь толще обычной")


def test_export(app):
    print("10. экспорт: ломаная и острие стрелки")
    import pdfexport
    _reset(app)
    _, _, link = _bent(app)
    recorder = pdfexport.SceneRecorder()
    app._draw_scene(recorder)

    lines = [call for call in recorder.calls
             if call[0] == "create_line"
             and call[2].get("fill") == app.ANALOG_COLOR
             and call[2].get("dash")]
    check(bool(lines), "пунктирная линия попала в сцену")
    coords = lines[0][1]
    check(len(coords) == 8, "в экспорте линия тоже из четырёх точек")
    check(close(coords[2:4], (400, 200)) and close(coords[4:6], (400, 100)),
          "изломы сохранены в экспорте")

    heads = [call for call in recorder.calls
             if call[0] == "create_polygon"
             and call[2].get("fill") == app.ANALOG_COLOR]
    check(bool(heads), "острие стрелки попало в сцену")
    check(any(abs(head[1][0] - 105) < 1 for head in heads),
          "острие стоит на конце связи у комплекта")


def run_gui():
    import main
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
        test_ctrl_delete(app)
        test_shift_routes(app)
        test_round_trip(app)
        test_paste(app)
        test_draw(app)
        test_export(app)
    finally:
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Опорные точки аналоговых связей")
    parser.add_argument("--no-gui", action="store_true",
                        help="без окон tkinter")
    args = parser.parse_args(argv)

    test_midpoint()
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
