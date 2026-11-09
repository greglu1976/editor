# -*- coding: utf-8 -*-
"""Проверка сверки стандартов СТО с каталогом и структурой.

Запуск:
    python3 tests/test_standards_sync.py           # с GUI-частью (нужен tkinter)
    python3 tests/test_standards_sync.py --no-gui  # только данные

Проверяет:

1. сверку ``standards_sync.diff()``: 13 шкафов стандартов, у каждой карточки
   состав, поля, записи «только в структуре» и число отличающихся таблиц,
   «всего» — сумма этих групп;
2. синхронность каталога: после ``standards_sync.py --apply`` и пересборки
   различий нет (иначе тест подсказывает команду);
3. семантику ссылок: значение-ссылка («Таблица 5.2.13») не считается
   полем каталога и подлежит замене, а настоящее значение каталога — нет;
4. ``kits_from_standard``: недостающий комплект берётся из стандарта вместе
   с именем ИЭУ и функциями;
5. ``apply``: пишет в каталог только изменившиеся поля и новые комплекты,
   повторный вызов на тех же данных ничего не меняет;
6. ``import_missing``: шкафы standards_base, которых нет в каталоге, получают
   запись каталога (ключ, стандарт, комплекты, ИЭУ) и добавляются один раз;
7. построчный перенос: ``row_changes`` и ``apply_change`` двигают поле в
   каталог и обратно в JSON стандарта, таблицы — только из стандарта;
8. ``structure_tools``: пересборка во временный файл, проверка и текст отчёта;
9. окна «Сверка…» и «Проверка…»: открываются, показывают списки и отчёт.
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cabs                # noqa: E402
import standards_base      # noqa: E402
import standards_sync      # noqa: E402
import structure           # noqa: E402
import structure_tools     # noqa: E402

try:                        # GUI-часть необязательна
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


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        for item in _walk(child):
            yield item


#: действующие стандарты: их сверка с каталогом — константа
#: (13 шкафов СТО + 2 шкафа редакции 280-XXXX «Изменение 1»)
ACTIVE = "СТО 56947007-"
ACTIVE_CABINETS = 15


def active_items(items):
    """Только карточки действующих стандартов (проекты adding не меняют базу)."""
    return [item for item in items if str(item["стандарт"]).startswith(ACTIVE)]


def test_diff():
    print("1. сверка каталога со стандартами")
    items = standards_sync.diff()
    check(len(active_items(items)) == ACTIVE_CABINETS,
          "шкафов действующих стандартов в сверке: %d (всего %d)"
          % (len(active_items(items)), len(items)))
    check(all(item["ключ"] for item in items), "у каждого шкафа есть ключ")
    check(all(item["стандарт"].startswith("СТО") for item in items),
          "у каждого шкафа указан стандарт")
    bad = []
    for item in items:
        expected = (len(item["состав"]) + len(item["каталог_поля"])
                    + len(item["структура"]) + item["таблицы"])
        if item["всего"] != expected:
            bad.append("%s: %d ≠ %d" % (item["шифр"], item["всего"], expected))
    check(not bad, "«всего» равно сумме групп по всем шкафам %s"
          % ("; ".join(bad[:2]) if bad else ""))
    stats = standards_sync.summary(items)
    check(stats["всего"] == sum(item["всего"] for item in items),
          "сводка сходится с суммой по шкафам: %d" % stats["всего"])
    check(stats["поля"] == sum(len(item["каталог_поля"]) for item in items),
          "поля каталога посчитаны: %d" % stats["поля"])
    check(stats["в_структуру"] == sum(len(item["структура"]) for item in items),
          "поля «в структуру» посчитаны: %d" % stats["в_структуру"])
    text = standards_sync.plan_text(items)
    check(text.splitlines()[0].startswith("Шкафов в стандартах:"),
          "план начинается со сводки")
    detail = standards_sync.detail_text(items[0])
    check("СОСТАВ" in detail and "ПОЛЯ КАТАЛОГА" in detail
          and "ТАБЛИЦЫ ИЭУ" in detail,
          "подробности шкафа содержат все разделы")
    check(standards_sync.detail_text(None) == "",
          "пустой выбор → пустой текст")


def test_synced():
    print("2. каталог синхронизирован со стандартом")
    stats = standards_sync.summary(active_items(standards_sync.diff()))
    if stats["всего"]:
        print("       (различий %d — примените: python standards_sync.py "
              "--apply и python tools/build_structure.py)" % stats["всего"])
    check(stats["всего"] == 0,
          "различий по действующим стандартам нет: состав %d, поля %d, "
          "в структуру %d, таблицы %d"
          % (stats["состав"], stats["поля"], stats["в_структуру"],
             stats["таблицы"]))
    check(stats["с_различиями"] == 0,
          "шкафов действующих стандартов с различиями нет (%d)"
          % stats["с_различиями"])


def test_reference_values():
    print("3. ссылки на таблицы не считаются значениями каталога")
    card = standards_base.cabinet("ШЭТ 430.01-0")
    fake = {"key": "shet-430-01-0", "code": "ШЭТ 430.01-0",
            "komplets": [{"key": "", "name": "Комплект 1",
                          "ieds": [{"name": "ИЭУ"}]}],
            "its_functions": "Таблица 5.2.5",
            "mp_functions": "ДТЗ, МТЗ"}
    item = standards_sync.cabinet_diff(card, fake, records={})
    its = [row for row in item["поля"] if row["поле"] == "функции ИТС"]
    check(its and not its[0]["каталог"],
          "ссылка «Таблица 5.2.5» → поле «только в структуру»")
    functions = [row for row in item["поля"] if row["поле"] == "функции МП ИЭУ"]
    check(functions and functions[0]["каталог"],
          "настоящее значение каталога считается полем каталога")
    fields = {row["поле"] for row in item["поля"]}
    check(not fields & set(standards_sync.TABLE_FIELDS),
          "поля-таблицы в построчную сверку не попадают")
    check(item["комплектов_каталог"] == 1 and item["комплектов_стандарт"] == 1,
          "состав комплектов сопоставлен")


def test_kits_from_standard():
    print("4. недостающие комплекты из стандарта")
    card = standards_base.cabinet("ШЭТ 431.02-0")
    fake = {"key": "shet-431-02-0", "code": "ШЭТ 431.02-0",
            "komplets": [{"key": "", "name": "Комплект 1",
                          "ieds": [{"name": "ИЭУ1"}]}]}
    item = standards_sync.cabinet_diff(card, fake, records={})
    kits = standards_sync.kits_from_standard(item)
    check(len(kits) == 1, "недостающих комплектов: %d" % len(kits))
    kit = kits[0]
    check(kit["name"] == "Комплект 2", "имя: %s" % kit["name"])
    check([ied["name"] for ied in kit["ieds"]] == ["ИЭУ2"],
          "ИЭУ второго комплекта: %s"
          % ", ".join(ied["name"] for ied in kit["ieds"]))
    check(kit["functions"] == ["УРОВ", "ЗНФ", "АУВ", "РАС"],
          "функции второго комплекта: %s" % ", ".join(kit["functions"]))
    check(kit["has_ied"] is True and kit["type"] == "МП РЗА",
          "признак ИЭУ и тип комплекта по умолчанию")
    one = standards_sync.cabinet_diff(
        standards_base.cabinet("ШЭТ 430.01-0"),
        {"key": "shet-430-01-0", "code": "ШЭТ 430.01-0",
         "komplets": [{"key": "", "name": "Комплект 1",
                       "ieds": [{"name": "ИЭУ"}]}]}, records={})
    check(standards_sync.kits_from_standard(one) == [],
          "при совпадении состава новых комплектов нет")


def test_apply():
    print("5. перенос в каталог")
    card = standards_base.cabinet("ШЭТ 431.02-0")
    fake = {"key": "shet-431-02-0", "code": "ШЭТ 431.02-0",
            "komplets": [{"key": "", "name": "Комплект 1",
                          "ieds": [{"name": "ИЭУ1"}]}],
            "mp_functions": "ДТЗ, МТЗ"}
    item = standards_sync.cabinet_diff(card, fake, records={})
    saved = []
    original = cabs.save_cabinet

    def fake_save(definition, original_key=None):
        saved.append((copy.deepcopy(definition), original_key))

    cabs.save_cabinet = fake_save
    try:
        result = standards_sync.apply(item)
        check(result["изменено"] > 0,
              "перенесено изменений: %d" % result["изменено"])
        check(len(saved) == 1, "каталог сохранён один раз")
        definition = saved[0][0]
        check(len(definition["komplets"]) == 2,
              "в каталоге стало комплектов: %d" % len(definition["komplets"]))
        check(saved[0][1] == "shet-431-02-0", "передан исходный ключ шкафа")
        check(definition["mp_functions"] != "ДТЗ, МТЗ",
              "поле каталога обновлено значением стандарта")
        check("ИЭУ2" in str(definition["komplets"][1]),
              "у нового комплекта есть ИЭУ2")
        saved.clear()
        check(standards_sync.apply({"шифр": "x", "каталог": None,
                                    "запись": {}})["изменено"] == 0,
              "без записи каталога ничего не пишется")
        check(standards_sync.apply({"шифр": "x", "каталог": fake,
                                    "запись": {}, "поля": [],
                                    "состав": [], "всего": 0})["изменено"] == 0,
              "без различий каталог не переписывается")
        check(not saved, "лишних сохранений нет")
    finally:
        cabs.save_cabinet = original


def test_import_missing():
    print("6. шкафы стандартов, которых нет в каталоге")
    tmp = tempfile.mkdtemp()
    original = cabs.USER_CATALOG_PATH
    cabs.USER_CATALOG_PATH = os.path.join(tmp, "cabinets.json")
    try:
        missing = standards_sync.missing_cabinets()
        check(bool(missing), "во временном каталоге нет шкафов: %d" % len(missing))
        card = next(card for card in missing if card["шифр"] == "ШЭТ 431.21-1")
        entry = standards_sync.catalog_entry(card)
        check(entry["key"] == "shet-431-21-1",
              "ключ из шифра: %s" % entry["key"])
        check(entry["standard_key"] == "skrm" and entry["group"] == "СКРМ",
              "редакция 280-XXXX попала в стандарт skrm (СКРМ)")
        check(entry["name"] == "Шкаф защит батареи статических конденсаторов "
                               "110-330 кВ, УРОВ, АУВ",
              "наименование из карточки: %s" % entry.get("name"))
        check(len(entry["komplets"]) == 2,
              "комплектов в записи: %d" % len(entry["komplets"]))
        check([ied["name"] for ied in entry["komplets"][0]["ieds"]] == ["ИЭУ1"]
              and [ied["name"] for ied in entry["komplets"][1]["ieds"]]
              == ["ИЭУ2"],
              "ИЭУ комплектов перенесены из стандарта")
        check("ДТЗ" in entry["komplets"][0]["functions"],
              "функции комплекта перенесены")
        check(entry["goose"] is True, "признак GOOSE определён по таблицам ИЭУ")

        result = standards_sync.import_missing([card])
        check([item["шифр"] for item in result["добавлено"]] == ["ШЭТ 431.21-1"]
              and not result["ошибки"],
              "шкаф добавлен: %s" % result["добавлено"])
        saved = cabs.find_cabinet("shet-431-21-1")
        check(saved is not None and saved.get("code") == "ШЭТ 431.21-1",
              "шкаф появился в каталоге")
        check(card["шифр"] not in
              [item["шифр"] for item in standards_sync.missing_cabinets()],
              "повторно шкаф в отсутствующие не попадает")
        again = standards_sync.import_missing([card])
        check(not again["добавлено"] and again["ошибки"],
              "повторное добавление отклонено: %s" % again["ошибки"])
    finally:
        cabs.USER_CATALOG_PATH = original
    result = structure_tools.add_missing_standards()
    check(result["ok"] and not result["добавлено"],
          "в рабочем каталоге новых шкафов нет: %s"
          % result["текст"].splitlines()[0])


def test_change_rows():
    print("7. построчный перенос изменений")
    # Шкаф с различием выбираем по данным, а не по шифру: после переноса
    # значений в стандарт конкретный шкаф может перестать различаться.
    pairs = [(item, change)
             for item in standards_sync.diff()
             for change in standards_sync.row_changes(item)
             if change["поле"] == "применимость"
             and change["можно_в_структуру"] and change["можно_в_стандарт"]]
    check(bool(pairs), "есть поле «применимость» с различием в обе стороны")
    if not pairs:
        return
    item, applicability = pairs[0]
    changes = standards_sync.row_changes(item)
    check(len(changes) == item["всего"],
          "строк изменений: %d = всего %d" % (len(changes), item["всего"]))
    check(all(change["группа"] in ("Поле", "Состав", "Таблица")
              for change in changes), "у каждой строки есть группа")
    check(applicability["можно_в_структуру"]
          and applicability["можно_в_стандарт"],
          "поле с обеими сторонами переносится в обе стороны")

    saved = []
    original_save = cabs.save_cabinet
    cabs.save_cabinet = lambda definition, key=None: saved.append(
        (copy.deepcopy(definition), key))
    try:
        result = standards_sync.apply_change(item, applicability,
                                            "в структуру")
        check(result["ok"] and result.get("пересобрать"),
              "перенос в структуру: %s" % result["текст"])
        check(len(saved) == 1
              and saved[0][0]["applicability"]
              == applicability["значение_стандарт"],
              "поле каталога получило значение стандарта")
        check(saved[0][1] == item["ключ"], "передан ключ шкафа")
    finally:
        cabs.save_cabinet = original_save

    tmp = tempfile.mkdtemp()
    code = item["шифр"]
    card = standards_base.cabinet(code)
    source = os.path.join(standards_base.STANDARDS_DIR, card["файл"])
    shutil.copy(source, os.path.join(tmp, card["файл"]))
    original_dir = standards_base.STANDARDS_DIR
    standards_base.STANDARDS_DIR = tmp
    standards_base.reload()
    try:
        fresh = next(item for item in standards_sync.diff()
                     if item["шифр"] == code)
        change = next(change for change in standards_sync.row_changes(fresh)
                      if change["поле"] == "применимость")
        result = standards_sync.apply_change(fresh, change, "в стандарт")
        check(result["ok"] and not result.get("пересобрать"),
              "перенос в стандарт: %s" % result["текст"])
        after = next(item for item in standards_sync.diff()
                     if item["шифр"] == code)
        check(not [row for row in standards_sync.row_changes(after)
                   if row["поле"] == "применимость"],
              "после переноса строка различия исчезла")
        check(standards_base.record(standards_base.cabinet(code))
              .get("применимость") == change["значение_структура"],
              "значение записано в JSON стандарта")
    finally:
        standards_base.STANDARDS_DIR = original_dir
        standards_base.reload()

    table = {"группа": "Таблица", "поле": "ИЭУ1 · входные GOOSE",
             "причина": "таблицы ИЭУ переносятся только из стандарта"}
    result = standards_sync.apply_change(item, table, "в стандарт")
    check(not result["ok"] and "только из стандарта" in result["текст"],
          "обратный перенос таблицы отклонён с причиной")


def test_structure_tools():
    print("8. пересборка и проверка структуры")
    target_dir = os.path.join(ROOT, "output", "_sync_test")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "structure.json")
    result = structure_tools.rebuild(target)
    check(result["ok"], "пересборка выполнена (%s)" % (result["ошибка"] or "ok"))
    check(os.path.exists(target), "файл собран: %s" % target)
    text = result["текст"] or ""
    check("structure.json v3" in text, "сводка сборщика получена")
    check("standards_base: " in text,
          "в сводке есть данные standards_base")
    check("таблиц ИЭУ" in text, "таблицы ИЭУ перенесены")
    report = structure_tools.check(target)
    check(report.get("загружено"), "структура прочитана проверкой")
    check(not report.get("проблемы"),
          "проблем нет (%d)" % len(report.get("проблемы") or []))
    check(report.get("шкафы") == len(cabs.all_cabinets()),
          "шкафов в структуре: %d" % report.get("шкафы"))
    body = structure_tools.check_text(report, target)
    check("ОШИБКИ (0)" in body, "в отчёте нет ошибок")
    check("ЗАПОЛНЕНИЕ" in body, "в отчёте есть заполнение полей")
    broken = structure_tools.check_text({}, target)
    check(broken.startswith("structure.json не прочитан"),
          "отчёт без данных сообщает об ошибке")
    structure.load(force=True, path=structure.DEFAULT_PATH)


def test_gui():
    print("9. окна сверки и проверки")
    import main
    root = tk.Tk()
    try:
        app = main.CircuitEditor(root)
        root.update()
        before = len(root.winfo_children())
        app.show_standards_sync()
        root.update()
        windows = [widget for widget in root.winfo_children()
                   if isinstance(widget, tk.Toplevel)]
        check(len(root.winfo_children()) == before + 1, "окно сверки открыто")
        window = windows[0]
        trees = [widget for widget in _walk(window)
                 if widget.winfo_class() == "Treeview"]
        check(len(trees) == 1, "в окне сверки есть список шкафов")
        rows = trees[0].get_children() if trees else ()
        # Флажок «Только с различиями» включён, если различия вообще есть.
        items = standards_sync.diff()
        expected = len([item for item in items if item["всего"]]) \
            if standards_sync.summary(items)["всего"] else len(items)
        check(len(rows) == expected,
              "шкафов в списке: %d (ожидалось %d)" % (len(rows), expected))
        texts = [widget for widget in _walk(window)
                 if widget.winfo_class() == "Text"]
        content = texts[0].get("1.0", "end") if texts else ""
        check("СОСТАВ" in content or "ТАБЛИЦЫ ИЭУ" in content,
              "подробности выбранного шкафа показаны")

        check(bool(trees[0].bind("<Double-1>")),
              "двойной щелчок по шкафу привязан")
        target = next(item for item in standards_sync.diff()
                      if any(change["можно_в_структуру"]
                             and change["можно_в_стандарт"]
                             for change in standards_sync.row_changes(item)))
        app.show_sync_changes(target["шифр"])
        root.update()
        detail = next(widget for widget in root.winfo_children()
                      if isinstance(widget, tk.Toplevel)
                      and widget.title().startswith("Изменения шкафа"))
        detail_trees = [widget for widget in _walk(detail)
                        if widget.winfo_class() == "Treeview"]
        check(bool(detail_trees)
              and len(detail_trees[0].get_children())
              == target["всего"],
              "в окне изменений: %d строк"
              % (len(detail_trees[0].get_children()) if detail_trees else 0))
        buttons = {str(widget.cget("text")): widget for widget in _walk(detail)
                   if widget.winfo_class() == "Button"}
        check("→ В структуру" in buttons and "→ В стандарт" in buttons,
              "в окне есть перенос в обе стороны")
        changes = standards_sync.row_changes(target)
        index = next(number for number, change in enumerate(changes)
                     if change["можно_в_структуру"]
                     and change["можно_в_стандарт"])
        detail_trees[0].selection_set(detail_trees[0].get_children()[index])
        detail_trees[0].event_generate("<<TreeviewSelect>>")
        root.update()
        check(str(buttons["→ В структуру"].cget("state")) == "normal"
              and str(buttons["→ В стандарт"].cget("state")) == "normal",
              "для поля с двумя значениями доступны обе кнопки")
        detail.destroy()
        window.destroy()
        root.update()

        app.show_structure_check()
        root.update()
        windows = [widget for widget in root.winfo_children()
                   if isinstance(widget, tk.Toplevel)]
        check(len(windows) == 1, "окно проверки открыто")
        texts = [widget for widget in _walk(windows[0])
                 if widget.winfo_class() == "Text"]
        body = texts[0].get("1.0", "end") if texts else ""
        check("ОШИБКИ (0)" in body, "отчёт проверки показан в окне")
        windows[0].destroy()
        root.update()

        # карточка выбора шкафа: поля-ссылки скрыты, содержательные остались
        picked = {}

        def probe():
            window = next((widget for widget in root.winfo_children()
                           if isinstance(widget, tk.Toplevel)
                           and widget.title() == "Шкаф РЗА"), None)
            if window is None:
                return
            boxes = [widget for widget in _walk(window)
                     if widget.winfo_class() == "Listbox"]
            labels = [widget for widget in _walk(window)
                      if widget.winfo_class() == "Label"]
            if boxes:
                box = boxes[0]
                entries = [str(box.get(index)) for index in range(box.size())]
                index = next((number for number, text in enumerate(entries)
                              if "430.01" in text), 0)
                box.selection_clear(0, "end")
                box.selection_set(index)
                box.event_generate("<<ListboxSelect>>")
                root.update_idletasks()
            picked["text"] = "\n".join(str(widget.cget("text"))
                                       for widget in labels)
            window.destroy()

        root.after(200, probe)
        app._choose_cabinet()
        root.update()
        text = picked.get("text") or ""
        check("Таблица 5." not in text and "Рисунок 5." not in text,
              "в карточке выбора шкафа нет ссылок на таблицы и рисунки")
        check("Функции ИТС" in text and "Применимость" in text,
              "в карточке выбора остались функции, применимость и питания")
    finally:
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-gui", action="store_true",
                        help="не открывать окна редактора")
    args = parser.parse_args(argv)

    print("Проверка сверки стандартов\n")
    test_diff()
    test_synced()
    test_reference_values()
    test_kits_from_standard()
    test_apply()
    test_import_missing()
    test_change_rows()
    test_structure_tools()
    if not args.no_gui and tk is not None:
        test_gui()
    print()
    if FAILURES:
        print("ПРОВАЛЕНО: %d" % len(FAILURES))
        for message in FAILURES:
            print("  - %s" % message)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
