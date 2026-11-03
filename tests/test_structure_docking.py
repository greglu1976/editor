# -*- coding: utf-8 -*-
"""Проверка стыковки structure.json с редактором схем (без mainloop человека).

Запуск:
    python3 tests/test_structure_docking.py

Проверяет:
1. модуль structure: поиск по ключу, по шифру, комплекты шкафа, id из схем;
2. ключи элементов реальных схем (schemes/*.json) разрешаются в записи структуры;
3. окно редактора открывается и рисует текст (нужен X11-дисплей; без него
   GUI-часть пропускается).
"""

import glob
import json
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main                # noqa: E402  (импортирует cabs, komplekts, structure)
import structure           # noqa: E402

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def test_module():
    print("1. модуль structure")
    check(structure.available(), "structure.json загружается")
    entry = structure.cabinet("shet-211-01-1")
    check(bool(entry), "шкаф находится по ключу каталога")
    check(entry.get("Шифр шкафа") == "ШЭТ 211.01-1", "шифр шкафа читается")
    by_code = structure.cabinet("ШЭТ 211.01-1")
    check(by_code is entry, "шкаф находится и по шифру")
    kits = structure.kits_of("shet-211-01-1")
    check(len(kits) == 2, "у шкафа два комплекта (%d)" % len(kits))
    kit = structure.kit_for("shet-211-01-1", 0)
    check(kit and kit.get("Обозначение ИЭУ") == "ИЭУ1",
          "комплект №1 — ИЭУ1")
    table = kit.get("Входные аналоговые измерения") or {}
    check(len(table) == 11, "входные аналоговые измерения: %d строк" % len(table))
    check(bool(kit.get("Функциональные клавиши со светодиодной индикацией")),
          "функциональные клавиши заполнены")
    check(bool(structure.format_record(kit)), "запись печатается в текст")
    missing = structure.cabinet("нет-такого-шкафа")
    check(missing is None, "несуществующий ключ даёт None")


def test_schemes():
    print("2. элементы схем")
    total = resolved = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "schemes", "*.json"))):
        with open(path, encoding="utf-8") as handle:
            scheme = json.load(handle)
        for element in scheme.get("elements") or []:
            if element.get("type") != "cabinet":
                continue
            key = (element.get("cabinet_key")
                   or (element.get("cabinet") or {}).get("key") or "")
            if not key:
                continue
            total += 1
            if structure.cabinet(key):
                resolved += 1
    check(total > 0, "на схеме есть %d шкафов каталога" % total)
    check(resolved == total,
          "все элементы схем находят запись структуры (%d/%d)" % (resolved, total))


def test_gui():
    print("3. окна редактора")
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print("  пропуск: нет дисплея (%s)" % error)
        return
    root.withdraw()
    app = main.CircuitEditor(root)
    app.show_cabinet_structure("shet-211-01-1")
    app.show_structure_overview()
    kit = structure.kit_for("shet-211-01-1", 1)
    app.show_komplekt_structure({"key": kit.get("id"),
                                 "cabinet_key": "shet-211-01-1",
                                 "cabinet_index": 1,
                                 "name": "Комплект 2"})
    windows = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)]
    root.update_idletasks()
    root.update()
    check(len(windows) >= 3, "открыто окон структуры: %d" % len(windows))
    def find_text(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Text):
                return child
            found = find_text(child)
            if found is not None:
                return found
        return None

    filled = sum(1 for window in windows
                 if (find_text(window) or tk.Text(root)).get("1.0", "end").strip())
    check(filled == len(windows), "во всех окнах есть текст (%d)" % filled)
    for window in windows:
        window.destroy()
    root.destroy()


def main_test():
    test_module()
    test_schemes()
    test_gui()
    print()
    if FAILURES:
        print("ПРОВАЛОВ: %d" % len(FAILURES))
        return 1
    print("Всё в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
