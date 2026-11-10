# -*- coding: utf-8 -*-
"""Опорные точки связей защиты (РЗА): полилиния, маркеры и совместимость JSON.

Запуск:
    python3 tests/test_protection_points.py           # полный набор, нужен tkinter
    python3 tests/test_protection_points.py --no-gui  # только формат точек

Проверяет:

1. ``_clean_points`` — формат ``[[x, y], ...]``, битые пары отбрасываются,
   значения округляются до 0.1;
2. ``_protection_route`` — маршрут «порт комплекта → изломы → узел»,
   отсутствие поля ``points`` даёт прямую линию;
3. попадание в сегмент и в маркер связи, выбор связи кликом;
4. вставку точки двойным кликом по сегменту и удаление по маркеру,
   перетаскивание маркера и отмену через Undo;
5. сохранение в JSON (с примечанием), чтение обратно, старые файлы без
   ``points`` и мусор в поле ``points``;
6. вставку из файла (insert_from_json) — переназначение ссылок и сдвиг изломов;
7. отрисовку полилинии со стрелкой и маркеров выбранной связи;
8. правый клик — окно данных связи (диспетчеризация _link_at/edit_link_data).
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
    app.analog_links = []
    app.protection_links = []
    app.selected_elements = []
    app.selected_connection = None
    app.selected_analog = None
    app.selected_protection = None
    app.selected_container_link = None
    app.comments = []
    app.current_path = None
    app.show_protection = True
    app.show_cabinets = True
    app.show_containers = True


def _pair(app):
    """Шкаф с комплектом, оборудование и связь защиты комплект → узел."""
    import library
    cabinet = _add(app, "cabinet", 200, 200)
    app.elements[cabinet].komplets = library.normalize_komplets(
        [{"name": "К1"}])
    app.elements[cabinet].generate_ports()
    device = _add(app, "transformer", 500, 200)
    link = app._add_protection_link(cabinet + "#0", device)
    return cabinet, device, link


def _bent(app):
    """Та же связь с одним изломом посередине."""
    _, _, link = _pair(app)
    link["points"] = [[350.0, 200.0]]
    return link


def test_clean_points():
    print("1. формат опорных точек")
    try:
        import main
    except Exception as error:                      # pragma: no cover
        print("  пропуск: main не импортируется (%s)" % error)
        return
    clean = main.CircuitEditor._clean_points
    check(clean(None) == [], "None → пустой список")
    check(clean([[10, 20]]) == [[10.0, 20.0]], "пара чисел сохраняется")
    check(clean([["10.44", "20.46"]]) == [[10.4, 20.5]],
          "значения округляются до 0.1")
    check(clean([[10, 20], [30], "x", [1, 2, 3]]) == [[10.0, 20.0]],
          "битые пары отбрасываются")


def test_route(app):
    print("2. маршрут связи защиты")
    _reset(app)
    cabinet, device, link = _pair(app)
    route = app._protection_route(link)
    check(len(route) == 2, "без изломов маршрут — порт и узел")
    port = app._komplekt_port(app.elements[cabinet], "0")
    check(close(route[0], (port["x"], port["y"])),
          "маршрут начинается в порту комплекта")
    check(close(route[-1], (app.elements[device].x, app.elements[device].y)),
          "маршрут заканчивается в узле оборудования")

    link["points"] = [[350.0, 200.0], [350.0, 120.0]]
    route = app._protection_route(link)
    check(len(route) == 4, "изломы добавляют точки маршрута")
    check(close(route[1], (350.0, 200.0))
          and close(route[2], (350.0, 120.0)),
          "изломы стоят между портом и узлом")

    broken = {"komplekt": link["komplekt"], "element": link["element"],
              "points": [[10, 20], [30]]}
    check(len(app._protection_route(broken)) == 3,
          "битые пары не ломают маршрут")


def test_hit(app):
    print("3. попадание в сегмент и маркер")
    _reset(app)
    _, _, link = _bent(app)
    app.redraw_all()

    sx, sy = app.world_to_screen(350.0, 200.0)
    check(app._protection_point_at(sx + 2, sy - 1) == ("link", link, 0),
          "маркер излома находится под курсором")
    check(app._protection_point_at(sx + 60, sy + 60) is None,
          "мимо маркера — None")

    sx, sy = app.world_to_screen(300.0, 200.0)
    check(app._protection_segment_at(sx, sy) == (link, 0),
          "сегмент между портом и изломом определяется")
    check(app._protection_link_at(sx, sy) is link,
          "клик по линии находит связь защиты")

    app.selected_protection = None
    app.on_left_click(_event(sx, sy))
    check(app.selected_protection is link,
          "клик по линии выбирает связь защиты")
    check(app.selected_elements == [], "выбор элементов снят")


def test_edit(app):
    print("4. вставка, удаление и перетаскивание точек")
    _reset(app)
    _, _, link = _pair(app)
    link["points"] = [[350.0, 200.0]]
    app.redraw_all()

    # Двойной клик по сегменту 0 — точка встаёт между портом и изломом
    sx, sy = app.world_to_screen(275.0, 200.0)
    app.on_double_click(_event(sx, sy))
    check(len(link["points"]) == 2, "двойной клик по сегменту вставил точку")
    check(close(link["points"][0], [275.0, 200.0], 10.0),
          "точка вставлена в месте клика (с привязкой к сетке)")
    check(app.selected_protection is link,
          "вставка выделяет связь для правки")

    # Двойной клик по маркеру — точка удаляется
    sx, sy = app.world_to_screen(*link["points"][0])
    app.on_double_click(_event(sx, sy))
    check(len(link["points"]) == 1, "двойной клик по маркеру удалил точку")

    # Удаляем оставшийся излом: пустое поле не хранится
    for _ in range(2):
        sx, sy = app.world_to_screen(*link["points"][0])
        app.on_double_click(_event(sx, sy))
    check("points" not in link, "пустой список изломов не хранится")
    check(len(app._protection_route(link)) == 2,
          "после удаления изломов связь снова прямая")

    # Перетаскивание маркера
    link["points"] = [[350.0, 200.0]]
    app.selected_protection = link
    app.redraw_all()
    sx, sy = app.world_to_screen(350.0, 200.0)
    app.on_left_click(_event(sx, sy))
    check(app._dragging_point == ("link", link, 0),
          "нажатие на маркер начинает перетаскивание")
    nx, ny = app.world_to_screen(360.0, 240.0)
    app.on_drag(_event(nx, ny))
    check(not close(link["points"][0], [350.0, 200.0]),
          "точка следует за курсором")
    app.on_release(_event(nx, ny))
    check(app._dragging_point is None, "перетаскивание завершено")
    moved = [list(point) for point in link["points"]]

    app.undo_last_action()
    restored = app.protection_links[0]
    check(close(restored["points"][0], [350.0, 200.0]),
          "отмена возвращает точку на место")
    check(not close(restored["points"][0], moved[0]),
          "отмена отличается от перемещённого положения")


def test_round_trip(app):
    print("5. сохранение, загрузка и совместимость")
    _reset(app)
    cabinet, device, link = _pair(app)
    link["points"] = [[350.0, 200.0]]
    link["note"] = "защита ввода линии"

    folder = tempfile.mkdtemp(prefix="prot-")
    path = os.path.join(folder, "scheme.json")
    app.current_path = path
    check(app._write_scheme() is True, "схема сохранена")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    record = data["protection_links"][0]
    check(record.get("points") == [[350.0, 200.0]],
          "изломы записаны в JSON")
    check(record.get("note") == "защита ввода линии",
          "примечание записано в JSON")
    check(record.get("komplekt") == cabinet + "#0"
          and record.get("element") == device,
          "топология связи не изменилась")

    built = app._build_protection_links(data["protection_links"])
    check(built[0]["points"] == [[350.0, 200.0]],
          "изломы читаются обратно")
    check(built[0].get("note") == "защита ввода линии",
          "примечание читается обратно")

    # Старый файл: поля points/notes нет — связь прямая, без сбоя
    old = {"elements": data["elements"],
           "protection_links": [{"komplekt": link["komplekt"],
                                  "element": link["element"]}]}
    built_old = app._build_protection_links(old["protection_links"])
    check(len(built_old) == 1
          and app._clean_points(built_old[0].get("points")) == [],
          "старый файл без изломов читается")

    # Мусор в points отбрасывается
    broken = {"elements": data["elements"],
              "protection_links": [{"komplekt": link["komplekt"],
                                    "element": link["element"],
                                    "points": [[10, 20], [30]]}]}
    built_broken = app._build_protection_links(broken["protection_links"])
    check(built_broken[0]["points"] == [[10.0, 20.0]],
          "битые изломы при загрузке отбрасываются")


def test_paste(app):
    print("6. вставка из файла — переназначение и сдвиг")
    _reset(app)
    cabinet, device, link = _pair(app)
    link["points"] = [[350.0, 200.0]]
    folder = tempfile.mkdtemp(prefix="prot-paste-")
    path = os.path.join(folder, "scheme.json")
    app.current_path = path
    app._write_scheme()

    # Свежая схема — вставляем сохранённый файл поверх неё
    _reset(app)
    _add(app, "container", 800, 600)

    import main
    saved = path
    main.filedialog.askopenfilename = lambda **kw: saved
    before = len(app.protection_links)
    app.insert_from_json()
    check(len(app.protection_links) == before + 1,
          "связь защиты добавлена при вставке")

    new_link = app.protection_links[-1]
    check(self_ref(new_link).endswith("#0"),
          "ссылка на комплект сохранена (с новым id шкафа)")
    cabinet_id = self_ref(new_link).partition("#")[0]
    check(cabinet_id in app.elements, "шкаф привязан к существующему элементу")
    check(len(new_link.get("points") or []) == 1,
          "излом перенесён вместе со связью")
    # сдвиг относительно оригинала: новый излом не совпадает со старым
    check(not close(new_link["points"][0], [350.0, 200.0]),
          "излом сдвинут на вектор вставки")


def self_ref(link):
    return link["komplekt"]


def test_draw(app):
    print("7. отрисовка полилинии и маркеров")
    _reset(app)
    _, _, link = _pair(app)
    link["points"] = [[350.0, 200.0]]
    app.selected_protection = link
    app.redraw_all()

    lines = app.canvas.find_withtag("protection_link")
    check(len(lines) == 1, "линия связи защиты нарисована")
    coords = app.canvas.coords(lines[0])
    check(len(coords) == 6, "линия построена по трём точкам")
    route = app._protection_route(link)
    check(close(coords[:2], app.world_to_screen(*route[0]))
          and close(coords[-2:], app.world_to_screen(*route[-1])),
          "концы линии совпадают с маршрутом")

    markers = app.canvas.find_withtag("protection_point")
    check(len(markers) == 1, "маркер излома нарисован")
    check(all(app.canvas.type(item) == "rectangle" for item in markers),
          "маркер — квадрат")


def test_right_click(app):
    print("8. правый клик — окно данных связи")
    _reset(app)
    _, _, link = _bent(app)
    app.redraw_all()

    sx, sy = app.world_to_screen(300.0, 200.0)
    hit = app._link_at(sx, sy)
    check(hit is not None and hit[0] == "protection"
          and hit[1] is link,
          "_link_at возвращает вид 'protection'")

    # перехватываем открытие диалога, проверяем диспетчеризацию
    called = {}

    def fake_edit(target):
        called["link"] = target
        called["selected"] = app.selected_protection

    app.edit_protection_link = fake_edit
    app.edit_link_data("protection", link)
    check(called.get("link") is link,
          "edit_link_data вызывает редактор связи защиты")
    check(called.get("selected") is link,
          "перед редактированием связь выделяется")


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
        app.show_protection = True
        app.show_cabinets = True
        app.show_containers = True
        test_route(app)
        test_hit(app)
        test_edit(app)
        test_round_trip(app)
        test_paste(app)
        test_draw(app)
        test_right_click(app)
    finally:
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Опорные точки связей защиты")
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
