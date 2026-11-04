# -*- coding: utf-8 -*-
"""Проверка структуры РЗА v3 и её стыковки с редактором схем.

Запуск:
    python3 tests/test_structure_docking.py          # нужен tkinter для GUI-части
    python3 tests/test_structure_docking.py --no-gui # только данные

Проверяет:

1. ``structure.json`` — иерархию «КЭТ → шкафы → комплекты → ИЭУ»:
   шкаф состоит минимум из одного комплекта, у комплекта обязательный
   признак «есть ИЭУ», вложенные «иэу» есть только у комплекта с ИЭУ;
2. модуль ``structure``: поиск по ключу/шифру, комплекты, ИЭУ, КЭТ,
   текстовые представления «с ИЭУ / без ИЭУ»;
3. миграцию описаний шкафов (``cabs.normalize_cabinet``): единственное ИЭУ
   из старого поля ``ieds`` уходит в комплект и поле удаляется, повторный
   вызов ничего не меняет;
4. ключи элементов реальных схем (``schemes/*.json``) разрешаются в записи
   структуры — шкафы и комплекты по номеру;
5. окна редактора: проводник с деревом, карточка, фильтр «С ИЭУ / Без ИЭУ»,
   структура выделенного шкафа/КЭТ, каталоги шкафов и комплектов.
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cabs                # noqa: E402
import containers          # noqa: E402
import komplekts           # noqa: E402
import structure           # noqa: E402

try:                        # GUI-часть необязательна (например, в CI)
    import tkinter as tk
    from tkinter import ttk
except ImportError:         # pragma: no cover - зависит от сборки Python
    tk = ttk = None

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def all_sections():
    document = structure.load(force=True)
    assert document is not None, structure.error()
    cabinets = document.get(structure.CABINET_SECTION) or []
    containers_list = document.get(structure.CONTAINER_SECTION) or []
    kits = [kit for cabinet in cabinets
            for kit in cabinet.get(structure.KITS_FIELD) or []]
    ieds = [ied for kit in kits for ied in structure.ieds_of(kit)]
    return document, containers_list, cabinets, kits, ieds


def test_document():
    print("1. structure.json — иерархия и комплекты")
    document, containers_list, cabinets, kits, ieds = all_sections()
    check(document.get("версия") == 3, "версия файла 3")
    check(structure.available(), "structure.json загружается")
    check(len(containers_list) == len(containers.all_containers()),
          "все КЭТ каталога на месте (%d)" % len(containers_list))
    check(len(cabinets) == len(cabs.all_cabinets()),
          "все шкафы каталога на месте (%d)" % len(cabinets))
    check(len(kits) == len(komplekts.cabinet_komplekts(cabs.all_cabinets())),
          "все комплекты каталога на месте (%d)" % len(kits))

    check(all(cabinet.get(structure.KITS_FIELD) for cabinet in cabinets),
          "каждый шкаф состоит минимум из одного комплекта")
    check(not any("ieds" in cabinet or structure.IEDS_FIELD in cabinet
                  for cabinet in cabinets),
          "ИЭУ не хранится на уровне шкафа")
    check(all(isinstance(kit.get(structure.HAS_IED_FIELD), bool)
              for kit in kits),
          "у каждого комплекта есть булевый признак «есть ИЭУ»")
    with_ied = [kit for kit in kits if structure.has_ied(kit)]
    without_ied = [kit for kit in kits if not structure.has_ied(kit)]
    check(bool(with_ied) and bool(without_ied),
          "есть комплекты и с ИЭУ (%d), и без ИЭУ (%d)"
          % (len(with_ied), len(without_ied)))
    check(all(structure.ieds_of(kit) for kit in with_ied),
          "у каждого комплекта с ИЭУ есть вложенные «иэу»")
    check(all(structure.IEDS_FIELD not in kit and not structure.ieds_of(kit)
              for kit in without_ied),
          "у комплекта без ИЭУ нет вложенных «иэу»")
    check(len(ieds) == sum(len(structure.ieds_of(kit)) for kit in kits),
          "все ИЭУ принадлежат комплектам (%d)" % len(ieds))
    check(all(ied.get("обозначение") and ied.get("тип") for ied in ieds),
          "у каждого ИЭУ есть обозначение и тип")
    check(len({c.get("id") for c in cabinets}) == len(cabinets)
          and len({k.get("id") for k in kits}) == len(kits),
          "id шкафов и комплектов уникальны")

    cabinet_ids = {c.get("id") for c in cabinets}
    container_ids = {c.get("id") for c in containers_list}
    refs = [(c.get("id"), ref) for c in containers_list
            for ref in c.get(structure.CABINETS_FIELD) or []]
    check(all(ref in cabinet_ids for _, ref in refs),
          "ссылки КЭТ → шкафы замкнуты (%d)" % len(refs))
    check(all(cid in container_ids
              for cabinet in cabinets
              for cid in cabinet.get(structure.CONTAINERS_FIELD) or []),
          "обратные ссылки шкаф → КЭТ замкнуты")


def test_module():
    print("2. модуль structure")
    entry = structure.cabinet("shet-211-01-1")
    check(bool(entry), "шкаф находится по ключу каталога")
    check(entry.get("шифр") == "ШЭТ 211.01-1", "шифр шкафа читается")
    check(structure.cabinet("ШЭТ 211.01-1") is entry,
          "шкаф находится и по шифру")
    kits = structure.kits_of("shet-211-01-1")
    check(len(kits) == 2, "у шкафа два комплекта (%d)" % len(kits))
    kit = structure.kit_for("shet-211-01-1", 0)
    check(kit and kit.get(structure.HAS_IED_FIELD) is True,
          "комплект №1 — с ИЭУ")
    ieds = structure.ieds_of(kit)
    check(bool(ieds) and ieds[0].get("обозначение") == "ИЭУ1",
          "ИЭУ1 входит в комплект, а не в шкаф")
    check(structure.cabinet_of_kit(kit.get("id")) is entry,
          "комплект ссылается на свой шкаф")
    check(bool(structure.format_record(kit)), "запись печатается в текст")
    printed = structure.format_cabinet_full("shet-211-01-1")
    check("Шкаф состоит из" in printed and "КОМПЛЕКТ" in printed
          and "есть ИЭУ" in printed,
          "печать шкафа показывает все его комплекты с признаком ИЭУ")

    empty = next(k for k in structure.kits() if not structure.has_ied(k))
    check("без ИЭУ" in structure.kit_label(empty),
          "подпись комплекта без ИЭУ явная")
    full = structure.format_kit_full(empty.get("id"))
    check("без ИЭУ" in full and "вложенных устройств нет" in full,
          "карточка комплекта без ИЭУ объясняет отсутствие устройств")
    check(bool(structure.format_container(
        (structure.containers()[0] or {}).get("id"))),
        "контейнер КЭТ печатается со шкафами")
    check(len(structure.containers_of("shet-211-01-1")) >= 0
          and len(structure.cabinets_of([])) == 0,
          "списки КЭТ и шкафов работают")
    summary = structure.summary()
    check("версия 3" in summary and "без ИЭУ" in summary
          and "Шкафов без комплектов: 0" in summary,
          "сводка отражает модель v3")
    check(structure.cabinet("нет-такого-шкафа") is None
          and structure.kit("typ:нет:0") is None
          and structure.container("нет") is None,
          "несуществующие ключи дают None")


def test_migration():
    print("3. миграция описания шкафа")
    raw = next((record for record in cabs.CABINETS
                if komplekts.cabinet_single_ied(record)
                and cabs.find_cabinet(record.get("key"))), None)
    check(raw is not None, "в каталоге есть шкаф с одним ИЭУ в описании")
    if raw is None:
        return
    source = copy.deepcopy(raw)
    single = komplekts.cabinet_single_ied(source)
    name = single.get("name")
    check(bool(source.get("ieds")), "в исходном описании ИЭУ лежит в шкафу")
    normalized = cabs.normalize_cabinet(source)
    check("ieds" not in normalized, "поле ieds удалено из шкафа")
    check(len(normalized.get("komplets") or []) >= 1,
          "шкаф состоит из комплектов")
    moved = [ied.get("name") for kit in normalized["komplets"]
             for ied in komplekts.effective_ieds(kit)]
    check(name in moved, "ИЭУ «%s» перенесено в комплект" % name)
    before = copy.deepcopy(normalized["komplets"])
    komplekts.ensure_cabinet_kits(normalized)
    check(normalized["komplets"] == before,
          "повторная нормализация идемпотентна")
    check("ieds" not in normalized, "ИЭУ не вернулось на уровень шкафа")

    no_ied = komplekts.normalize_komplekt(
        {"name": "Комплект 1", "has_ied": False, "ieds": []})
    check(no_ied.get("has_ied") is False
          and not komplekts.effective_ieds(no_ied),
          "комплект без ИЭУ — полноценная запись каталога")


def test_schemes():
    print("4. элементы схем")
    cabinets = kits = resolved = kits_resolved = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "schemes", "*.json"))):
        with open(path, encoding="utf-8") as handle:
            scheme = json.load(handle)
        for element in scheme.get("elements") or []:
            if element.get("type") != "cabinet":
                continue
            data = element.get("cabinet") or {}
            key = element.get("cabinet_key") or data.get("key") or ""
            if not key:
                continue
            cabinets += 1
            if structure.cabinet(key):
                resolved += 1
            for index in range(len(data.get("komplets") or [])):
                kits += 1
                if structure.kit_for(key, index):
                    kits_resolved += 1
    check(cabinets > 0 and resolved == cabinets,
          "шкафы со схем находят записи (%d/%d)" % (resolved, cabinets))
    check(kits > 0 and kits_resolved == kits,
          "комплекты со схем находятся по номеру (%d/%d)"
          % (kits_resolved, kits))


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def widgets(widget, predicate, found=None):
    """Все подчинённые виджеты, удовлетворяющие predicate."""
    found = found if found is not None else []
    for child in widget.winfo_children():
        if predicate(child):
            found.append(child)
        widgets(child, predicate, found)
    return found


def find_text(window):
    texts = widgets(window, lambda w: isinstance(w, tk.Text))
    return texts[0] if texts else None


def find_tree(window):
    trees = widgets(window, lambda w: isinstance(w, ttk.Treeview))
    return trees[0] if trees else None


def nodes(tree, parent=""):
    result = []
    for child in tree.get_children(parent):
        result.append(child)
        result.extend(nodes(tree, child))
    return result


def tag_of(tree, item):
    value = tree.item(item, "tags") or ()
    return value if isinstance(value, (tuple, list)) else (value,)


def count_tag(tree, tag):
    return sum(1 for item in nodes(tree) if tag in tag_of(tree, item))


def composition_option(root, window):
    """Переключатель «Все / С ИЭУ / Без ИЭУ» в окне."""
    if window is None:
        return None
    for option in widgets(window, lambda w: isinstance(w, tk.Menubutton)):
        name = str(option.cget("textvariable") or "")
        if name and root.getvar(name) == "Все":
            return name
    return None


def window_by_title(root, title):
    """Окно по заголовку (методы каталогов не возвращают Toplevel)."""
    return next((w for w in root.winfo_children()
                 if isinstance(w, tk.Toplevel) and w.title() == title), None)


def test_gui():
    print("5. окна редактора")
    if tk is None:
        print("  пропуск: tkinter недоступен в этом Python")
        return
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print("  пропуск: нет дисплея (%s)" % error)
        return
    try:
        import main
    except ImportError as error:
        print("  пропуск: не удалось импортировать редактор (%s)" % error)
        root.destroy()
        return
    root.withdraw()
    app = main.CircuitEditor(root)
    windows = []

    try:
        cab_window = app.show_cabinet_structure("shet-211-01-1")
        windows.append(cab_window)
        overview = app.show_structure_overview()
        windows.append(overview)
        plain_kit = next(k for k in structure.kits()
                         if not structure.has_ied(k))
        kit_window = app.show_komplekt_structure({"key": plain_kit.get("id")})
        windows.append(kit_window)
        with_kit = structure.kit_for("shet-211-01-1", 0)
        kit_with_ied = app.show_komplekt_structure(
            {"key": with_kit.get("id")})
        windows.append(kit_with_ied)
        root.update_idletasks()
        root.update()

        check(all(isinstance(w, tk.Toplevel) for w in windows),
              "открыто 4 окна структуры")
        check(all(find_tree(w) is not None and find_text(w) is not None
                  for w in windows),
              "в каждом окне есть дерево и карточка")
        check(all((find_text(w).get("1.0", "end") or "").strip()
                  for w in windows),
              "во всех карточках есть текст")
        check("Состав шкафа" in find_text(cab_window).get("1.0", "end"),
              "карточка шкафа показывает состав из комплектов")
        check("без ИЭУ" in find_text(kit_window).get("1.0", "end")
              and "вложенных устройств нет" in find_text(kit_window).get(
                  "1.0", "end"),
              "карточка комплекта без ИЭУ явно это показывает")
        check("с ИЭУ" in find_text(kit_with_ied).get("1.0", "end"),
              "карточка комплекта с ИЭУ показывает ИЭУ")

        tree = find_tree(overview)
        check(len(nodes(tree)) > 100,
              "дерево обзора заполнено (%d узлов)" % len(nodes(tree)))
        check(all(count_tag(tree, tag) > 0 for tag in
                  ("container", "cabinet", "kit", "kit_empty", "ied")),
              "в дереве есть КЭТ, шкафы, комплекты с/без ИЭУ и ИЭУ")
        empty_labels = [tree.item(item, "text") for item in nodes(tree)
                        if "kit_empty" in tag_of(tree, item)]
        check(any("без ИЭУ" in text for text in empty_labels),
              "узлы комплектов без ИЭУ подписаны явно")

        variable = composition_option(root, overview)
        check(variable is not None, "в окне есть фильтр по составу")
        if variable:
            root.setvar(variable, "Без ИЭУ")
            root.update_idletasks()
            check(count_tag(tree, "kit") == 0
                  and count_tag(tree, "ied") == 0
                  and count_tag(tree, "kit_empty") > 0,
                  "фильтр «Без ИЭУ» оставляет только комплекты без ИЭУ")
            root.setvar(variable, "С ИЭУ")
            root.update_idletasks()
            check(count_tag(tree, "kit_empty") == 0
                  and count_tag(tree, "kit") > 0
                  and count_tag(tree, "ied") > 0,
                  "фильтр «С ИЭУ» скрывает пустые комплекты")
            root.setvar(variable, "Все")
            root.update_idletasks()

        # Ctrl+E: выделенный на схеме шкаф и выделенный КЭТ
        cabinet_element = SimpleNamespace(
            type="cabinet", name="ШЭТ 211.01-1",
            cabinet_key="shet-211-01-1")
        app.selected_elements = ["el-1"]
        app.elements = {"el-1": cabinet_element}
        selected = app.show_selected_structure()
        windows.append(selected)
        check("Структура шкафа" in selected.title(),
              "Ctrl+E по шкафу открывает структуру шкафа")
        container_key = structure.containers()[0].get("id")
        app.selected_elements = ["el-2"]
        app.elements = {"el-2": SimpleNamespace(
            type="container", name="КЭТ", container_key=container_key)}
        selected_container = app.show_selected_structure()
        windows.append(selected_container)
        check("Структура контейнера" in selected_container.title(),
              "Ctrl+E по КЭТ открывает структуру контейнера")
        check(count_tag(find_tree(selected_container), "container") > 0
              and count_tag(find_tree(selected_container), "cabinet") > 0,
              "в структуре КЭТ есть шкафы")

        # каталоги: счётчики комплектов с ИЭУ / без ИЭУ и фильтр
        app.open_cabinet_catalog()
        cabinet_catalog = window_by_title(root, "Каталог шкафов РЗА")
        root.update_idletasks()
        check(cabinet_catalog is not None, "каталог шкафов открыт")
        if cabinet_catalog:
            headers = [w.cget("text") for w in widgets(
                cabinet_catalog, lambda w: isinstance(w, tk.Label))]
            check(any("без ИЭУ" in str(text) for text in headers),
                  "каталог шкафов показывает состав комплектов")

        app.open_komplekt_catalog()
        kit_catalog = window_by_title(root, "Каталог комплектов РЗА")
        root.update_idletasks()
        check(kit_catalog is not None, "каталог комплектов открыт")
        if kit_catalog:
            headers = [w.cget("text") for w in widgets(
                kit_catalog, lambda w: isinstance(w, tk.Label))]
            check(any("Состав:" in str(text) for text in headers),
                  "в каталоге комплектов есть фильтр «Состав»")
            listboxes = widgets(kit_catalog,
                                lambda w: isinstance(w, tk.Listbox))
            check(bool(listboxes), "список комплектов отрисован")
            variable = composition_option(root, kit_catalog)
            if variable and listboxes:
                expected = sum(1 for kit in komplekts.all_komplekts()
                               if not komplekts.effective_ieds(kit))
                root.setvar(variable, "Без ИЭУ")
                root.update_idletasks()
                check(listboxes[0].size() == expected,
                      "фильтр «Без ИЭУ» в каталоге: %d/%d"
                      % (listboxes[0].size(), expected))
                root.setvar(variable, "Все")
                root.update_idletasks()

        # диалог выбора комплекта: тот же фильтр, окно закрываем извне
        title = "Тест выбора комплекта"

        def inspect_dialog():
            dialog = next((w for w in root.winfo_children()
                           if isinstance(w, tk.Toplevel)
                           and w.title() == title), None)
            check(dialog is not None, "диалог выбора комплекта открыт")
            if dialog is None:
                return
            variable = composition_option(root, dialog)
            check(variable is not None,
                  "в диалоге выбора есть фильтр «С ИЭУ / Без ИЭУ»")
            dialog.destroy()

        root.after(30, inspect_dialog)
        app._choose_komplekt(title)
    finally:
        for window in root.winfo_children():
            if isinstance(window, tk.Toplevel):
                try:
                    window.destroy()
                except tk.TclError:
                    pass
        root.destroy()


def main_test(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args(argv)
    test_document()
    test_module()
    test_migration()
    test_schemes()
    if not args.no_gui:
        test_gui()
    print()
    if FAILURES:
        print("ПРОВАЛОВ: %d" % len(FAILURES))
        for failure in FAILURES:
            print("  - %s" % failure)
        return 1
    print("Всё в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
