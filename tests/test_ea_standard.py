# -*- coding: utf-8 -*-
"""Проверка нового формата стандарта СТО (структура EA) в редакторе.

Запуск:
    python tests/test_ea_standard.py           # с окном (нужен tkinter)
    python tests/test_ea_standard.py --no-gui  # только данные

Проверяет:

1. папку ``EA``, список стандартов и счётчики;
2. что таблицы шкафов в документе — только форма, а данные лежат в шкафах;
3. сборку строк таблиц из шкафа по каждому виду данных;
4. целостность ссылок «таблица → шкаф» и полноту сигналов;
5. CLI модуля;
6. окно «СТО (EA)…» и проводку в ленте редактора.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ea_standard as es   # noqa: E402

try:
    import tkinter as tk
except ImportError:        # pragma: no cover
    tk = None

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def test_files():
    print("1. файлы и карточки")
    check(es.available(), "папка EA найдена: %s" % es.folder())
    rows = es.standards()
    check(len(rows) == 1, "стандартов в папке: %d" % len(rows))
    item = rows[0]
    check(item["шкафы"] == 4, "шкафов: %d" % item["шкафы"])
    check(item["таблицы"] == 65, "таблиц: %d" % item["таблицы"])
    data = es.load(item["путь"])
    stats = es.stats(data)
    check(stats["формы"] == 56, "таблиц-форм: %d" % stats["формы"])
    check(stats["таблицы_документа"] == 9,
          "таблиц документа с данными: %d" % stats["таблицы_документа"])


def test_forms():
    print("2. таблицы в документе — только форма")
    data = es.load()
    forms = [table for table in es.iter_tables(data) if table.get("cabinet")]
    check(len(forms) == 56, "форм со ссылкой на шкаф: %d" % len(forms))
    bad = []
    for table in forms:
        if "Описание ШЭТ" in table["name"]:
            for row in table["rows"]:
                if any(cell for cell in row["content"][1:]):
                    bad.append(table["number"])
                    break
        elif len(table["rows"]) > 2:
            bad.append(table["number"])
    check(not bad, "в формах нет строк данных%s"
          % ("" if not bad else ": %s" % ", ".join(bad)))
    check(all(es.table_kind(table["name"]) for table in forms),
          "вид данных определён у всех форм")


def test_views():
    print("3. строки таблиц собираются из шкафа")
    data = es.load()
    expected = {
        "Входные аналоговые измерения": ("analog_inputs", 9),
        "Внутренние дискретные цепи": ("inner_discrete_circuits", 11),
        "входящих сообщений": ("incoming_goose_signals", 22),
        "Функциональные клавиши": ("functional_buttons", 7),
        "Светодиодная сигнализация": ("leds", 16),
        "Сообщения и отчеты": ("datasets", 7),
        "исходящих сообщений": ("goose_signals", 32),
        "исходящих отчетов": ("report_signals", 354),
        "Осциллографируемые": ("osc_analog_signals", 31),
        "Команды управления": ("control_commands", 7),
        "Ряды зажимов": ("terminal_blocks", 53),
        "Основные компоненты": ("components", 11),
    }
    for needle, (kind, count) in expected.items():
        table = next((t for t in es.iter_tables(data)
                      if t.get("cabinet") and needle in t["name"]), None)
        check(table is not None and es.table_kind(table["name"]) == kind,
              "вид %s найден" % kind)
        if table is None:
            continue
        headers, rows = es.table_view(data, table)
        check(len(headers) == max((len(row) for row in rows), default=0)
              or len(headers) > 0, "%s: шапка %d колонок" % (kind, len(headers)))
        check(len(rows) == count, "%s: строк %d (ожидалось %d)"
              % (kind, len(rows), count))
    functions = next(t for t in es.iter_tables(data)
                     if t.get("cabinet") and "Основные параметры функций" in t["name"])
    _headers, rows = es.table_view(data, functions)
    check(len(rows) == 77, "functions: строк с группами %d" % len(rows))
    description = next(t for t in es.iter_tables(data)
                       if t.get("cabinet") and "Описание ШЭТ" in t["name"])
    _headers, rows = es.table_view(data, description)
    values = dict(rows)
    check(values.get("Шифр шкафа") == "ШЭТ 431.11-1", "шифр подставлен")
    check(values.get("Входные аналоговые измерения") == "Таблица 5.3",
          "ссылка на таблицу подставлена")
    check(values.get("Поясняющая схема подключения") == "Рисунок 5.1",
          "ссылка на рисунок подставлена")


def test_integrity():
    print("4. целостность")
    data = es.load()
    check(not es.validate(data), "проверка структуры без замечаний")
    codes = {cabinet["cypher"] for cabinet in es.cabinets(data)}
    check(len(codes) == 4, "шифры шкафов уникальны: %d" % len(codes))
    for table in es.iter_tables(data):
        if table.get("cabinet"):
            check(table["cabinet"] in codes,
                  "таблица %s ссылается на шкаф" % table["number"])
            break
    item = es.cabinet(data, "ШЭТ 431.11-1")
    check(item is not None, "шкаф ищется по шифру")
    card = dict(es.cabinet_card(item))
    check(card.get("Шифр шкафа") == "ШЭТ 431.11-1", "карточка шкафа заполнена")
    check(card.get("Сигналов в наборах") == "386",
          "сигналов в наборах: %s" % card.get("Сигналов в наборах"))


def test_cli():
    print("5. CLI")
    check(es.main(["--check"]) == 0, "--check завершается без ошибок")
    check(es.main(["--table", "5.3", "--limit", "1"]) == 0,
          "--table печатает таблицу")
    check(es.main(["--cabinet", "ШЭТ 431.11-1"]) == 0, "--cabinet печатает карточку")


def test_gui():
    print("6. окно")
    if tk is None:
        print("  --   tkinter нет: окно не проверяется")
        return
    try:
        import ea_ui
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        print("  --   окно не открыть: %s" % exc)
        return
    root.withdraw()

    class App:
        def __init__(self, root):
            self.root = root

    window = None
    try:
        window = ea_ui.show(App(root))
        root.update()
        check(len(window.tree.get_children()) == 2,
              "в дереве разделы и шкафы")
        tables = [iid for iid, node in window._nodes.items()
                  if node[0] == "table"]
        check(len(tables) == 65, "узлов-таблиц: %d" % len(tables))
        window.tree.selection_set(tables[0])
        window._show()
        root.update()
        check(len(window.table["columns"]) > 0,
              "таблица показывает колонки: %d" % len(window.table["columns"]))
        cabinets = [iid for iid, node in window._nodes.items()
                    if node[0] == "cabinet"]
        window.tree.selection_set(cabinets[0])
        window._show()
        root.update()
        check(len(window.table.get_children()) > 0,
              "карточка шкафа заполнена")
        texts = [iid for iid, node in window._nodes.items()
                 if node[0] == "text"]
        window.tree.selection_set(texts[0])
        window._show()
        root.update()
        check(window.text.winfo_manager() == "pack"
              and window.table.winfo_manager() == "",
              "текст раздела показывается вместо таблицы")
        import main
        check(hasattr(main.CircuitEditor, "show_ea_standards"),
              "в редакторе есть метод show_ea_standards")
    except Exception as exc:                      # noqa: BLE001
        check(False, "окно работает: %s" % exc)
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args(argv)
    test_files()
    test_forms()
    test_views()
    test_integrity()
    test_cli()
    if not args.no_gui:
        test_gui()
    print("")
    if FAILURES:
        print("ПРОВАЛЕНО: %d" % len(FAILURES))
        for item in FAILURES:
            print("  - %s" % item)
        return 1
    print("все проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
