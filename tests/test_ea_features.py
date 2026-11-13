# -*- coding: utf-8 -*-
"""Проверка новых возможностей ветки EA: размещение, новый стандарт, DOCX.

Запуск:
    python tests/test_ea_features.py           # с окном (нужен tkinter)
    python tests/test_ea_features.py --no-gui  # без окна

Проверяет:

1. мост «стандарт EA → каталог редактора» (``ea_catalog``);
2. создание нового стандарта на базе выбранного (``ea_new_standard``);
3. выгрузку в DOCX (``ea_docx``);
4. архив неиспользуемых файлов старой ветки;
5. кнопки и узлы окна «СТО (EA)…».
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cabs                    # noqa: E402
import ea_catalog              # noqa: E402
import ea_docx                 # noqa: E402
import ea_new_standard as ns   # noqa: E402
import ea_standard as es       # noqa: E402

try:
    import tkinter as tk
except ImportError:            # pragma: no cover
    tk = None

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


# ---------------------------------------------------------------------------
# 1. Каталог
# ---------------------------------------------------------------------------
def test_catalog(data):
    print("1. мост в каталог редактора")
    check(ea_catalog.standard_key(data) == "skrm2",
          "стандарт EA → ключ каталога skrm2")
    item = es.cabinet(data, "ШЭТ 431.11-1")
    found = ea_catalog.find_catalog_cabinet(data, item)
    check(found is not None and found.get("key") == "draft-шэт-431-11-1",
          "шкаф находится в каталоге по шифру")
    check(bool((found.get("komplets") or [{}])[0].get("test_blocks")),
          "существующая запись не перезаписывается (БИ на месте)")

    record = ea_catalog.catalog_record(data, item)
    check(record["code"] == "ШЭТ 431.11-1", "шифр перенесён")
    check(record["standard_key"] == "skrm2", "стандарт перенесён")
    check(record["voltage"] == "110–330 кВ", "напряжение из области применения")
    check(record["source"] == "табл. 5.2", "источник — первая таблица шкафа")
    check(len(record["komplets"]) == 1, "комплектов: %d"
          % len(record["komplets"]))
    kit = record["komplets"][0]
    check(kit["kind"] == "typical", "комплект типовой")
    check(kit["has_ied"] and kit["ieds"][0]["name"] == "ИЭУ1",
          "ИЭУ комплекта перенесён")
    check("ДТЗ" in kit["functions"], "функции комплекта перенесены")
    check(kit["analog_inputs"][0]["block"] == "SG1",
          "аналоговые измерения перенесены")

    entry = ea_catalog.kit_entry(data, item, item["kits"][0])
    check(entry["cabinet_key"] == "draft-шэт-431-11-1",
          "комплект ссылается на шкаф каталога")
    check(entry["name"] == "Комплект 1", "имя комплекта: %s" % entry["name"])
    check(entry["source"] == "cabinet_entry",
          "комплект готов для шкафа на схеме")


def test_catalog_new(data):
    """Новый шкаф (нет в каталоге) создаётся без привязки к «tat»."""
    item = {
        "cypher": "ШЭТ 999.99-9",
        "name": "Тестовый шкаф",
        "architecture": "II тип",
        "description": "Описание тестового шкафа",
        "protected_element": "Элемент",
        "controllable_element": "Выключатель",
        "scope": "РУ 110–330 кВ",
        "kits": [{
            "number": 1, "description": "Комплект", "type": "ИЭУ",
            "ieds": [{
                "number": 1, "analog_inputs": [],
                "functions": [{"name": "X", "russian_path": "ЗХ",
                               "isMainFunction": True, "isInITS": True,
                               "parameters": []}],
            }],
        }],
    }
    payload = {"code": data.get("code"), "name": data.get("name"),
               "sections": [], "cabinets": [item], "containers": []}
    old_path = cabs.USER_CATALOG_PATH
    folder = tempfile.mkdtemp()
    cabs.USER_CATALOG_PATH = os.path.join(folder, "cabinets.json")
    try:
        record = ea_catalog.ensure_catalog(payload, item)
        check(record.get("code") == "ШЭТ 999.99-9", "новый шкаф сохранён")
        check(record.get("standard_key") == "skrm2",
              "стандарт не подменён на «tat»")
        check(record.get("group") == "СКРМ", "группа из стандарта: %s"
              % record.get("group"))
        check(os.path.isfile(cabs.USER_CATALOG_PATH),
              "запись попала в пользовательский каталог")
        again = ea_catalog.ensure_catalog(payload, item)
        check(again.get("key") == record.get("key"),
              "повторное обращение не создаёт дубль")
    finally:
        cabs.USER_CATALOG_PATH = old_path


# ---------------------------------------------------------------------------
# 2. Новый стандарт
# ---------------------------------------------------------------------------
def test_new_standard(data):
    print("2. новый стандарт на базе выбранного")
    result = ns.build(data, meta={"code": "СТО (проект, ред. 3)",
                                  "date": "01.01.2027"})
    check(result["data"]["code"] == "СТО (проект, ред. 3)", "шифр заменён")
    check(result["data"]["date"] == "01.01.2027", "дата заменена")
    check(result["stats"]["шкафы"] == 4, "шкафов без отбора: 4")
    check(not result["problems"], "проверка без отбора: %s"
          % (result["problems"] or "OK"))
    check(result["data"]["sections"] is not data["sections"],
          "исходный стандарт не изменён")

    one = ns.build(data, meta={"code": "СТО (проект, ред. 3)",
                               "date": "01.01.2027"},
                   keep=["ШЭТ 431.12-1"])
    check([cab["cypher"] for cab in one["data"]["cabinets"]] == ["ШЭТ 431.12-1"],
          "оставлен один шкаф")
    check(one["stats"]["формы"] == 14, "таблиц-форм: %d"
          % one["stats"]["формы"])
    subs = [sub for section in one["data"]["sections"]
            for sub in section.get("subsections") or []
            if any(table.get("cabinet") for table in sub.get("tables") or [])]
    check([sub["number"] for sub in subs] == ["5.3"],
          "подраздел перенумерован в 5.3")
    tables = [table["number"] for table in es.iter_tables(one["data"])
              if table.get("cabinet")]
    check(tables == ["5.%d" % index for index in range(2, 16)],
          "таблицы перенумерованы 5.2…5.15")
    figures = [figure["number"] for sub in subs
               for figure in sub.get("figures") or []]
    check(figures == ["5.1", "5.2"], "рисунки перенумерованы: %s" % figures)
    clauses = [clause["number"] for clause in subs[0].get("clauses") or []]
    check(clauses == ["5.3.1", "5.3.2"], "пункты следуют за подразделом")
    check(len(es.table_by_number(one["data"], "5.1")["rows"]) == 2,
          "общий перечень шкафов сокращён")
    check(len(es.table_by_number(one["data"], "В.1")["rows"]) == 3,
          "таблица применимости сокращена")

    replaced = ns.build(data, meta={"code": "X", "date": "01.01.2027"},
                        replacements=["431.12-1 => 431.99-1"])
    check("ШЭТ 431.99-1" in [cab["cypher"] for cab in
                             replaced["data"]["cabinets"]],
          "замена шифра применена")

    path = os.path.join(tempfile.mkdtemp(), "new.json")
    ns.write_standard(one["data"], path)
    check(os.path.isfile(path) and es.load(path)["code"] == "СТО (проект, ред. 3)",
          "новый стандарт записан и читается")

    broken = dict(data)
    broken = {key: value for key, value in data.items() if key != "code"}
    check(any("Шифр стандарта" in item for item in ns.validate(broken)),
          "проверка замечает пустой шифр")


# ---------------------------------------------------------------------------
# 3. DOCX
# ---------------------------------------------------------------------------
def test_docx(data):
    print("3. выгрузка в DOCX")
    try:
        from docx import Document
    except ImportError:
        print("  --   python-docx нет: проверка пропущена")
        return
    path = os.path.join(tempfile.mkdtemp(), "report.docx")
    counters = ea_docx.build(data, path, max_rows=3)
    check(os.path.isfile(path) and counters["размер"] > 10000,
          "файл собран: %.1f КБ" % (counters["размер"] / 1024.0))
    check(counters["разделы"] == 10, "разделов: %d" % counters["разделы"])
    check(counters["таблицы"] == 65, "таблиц: %d" % counters["таблицы"])

    doc = Document(path)
    headings = [paragraph.text for paragraph in doc.paragraphs
                if paragraph.style.name.startswith("Heading")]
    check(any(text.startswith("5.3 Шкаф защит") for text in headings),
          "заголовок подраздела шкафа на месте")
    check(any(text.startswith("Приложение. Шкафы") for text in headings),
          "приложение со шкафами на месте")

    headers, rows = es.table_view(data, es.table_by_number(data, "5.2"))
    match = None
    for table in doc.tables:
        values = [cell.text for cell in table.rows[0].cells]
        if values == headers:
            match = table
            break
    check(match is not None, "таблица 5.2 найдена в документе")
    if match is not None:
        check(len(match.rows) - 1 == min(3, len(rows)),
              "строк в таблице 5.2: %d" % (len(match.rows) - 1))
        first = [cell.text for cell in match.rows[1].cells]
        check(first == [str(value) for value in rows[0]],
              "строки взяты из шкафа")


# ---------------------------------------------------------------------------
# 4. Архив
# ---------------------------------------------------------------------------
def test_archive():
    print("4. архив старой ветки")
    archive = os.path.join(ROOT, "archive", "legacy_standards")
    for name in ("_parse", "cat", "example.json", "run_changes_gui.bat",
                 "README.md"):
        check(os.path.exists(os.path.join(archive, name)),
              "в архиве: %s" % name)
    for name in ("standard_editor/_parse", "standard_editor/example.json",
                 "standard_editor/run_changes_gui.bat", "cat"):
        check(not os.path.exists(os.path.join(ROOT, name)),
              "убрано с прежнего места: %s" % name)
    check(os.path.isfile(os.path.join(ROOT, "standard_editor",
                                      "make_standard.py")),
          "редактор изменений старой ветки на месте")


# ---------------------------------------------------------------------------
# 5. Окно
# ---------------------------------------------------------------------------
def test_gui(data):
    print("5. окно «СТО (EA)…»")
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
            self.placed = []
            self.kits = []

        def _place_cabinet(self, record):
            self.placed.append(record)

        def add_komplekt_to_cabinet(self, entry):
            self.kits.append(entry)

    app = App(root)
    window = None
    try:
        window = ea_ui.show(app)
        root.update()
        kits = [iid for iid, node in window._nodes.items()
                if node[0] == "kit"]
        ieds = [iid for iid, node in window._nodes.items()
                if node[0] == "ied"]
        check(len(kits) == 4, "узлов-комплектов: %d" % len(kits))
        check(len(ieds) == 4, "узлов-ИЭУ: %d" % len(ieds))

        cabinets = [iid for iid, node in window._nodes.items()
                    if node[0] == "cabinet"]
        window.tree.selection_set(cabinets[0])
        window._show()
        root.update()
        check(str(window.btn_place["state"]) == "normal",
              "«На схему» доступна для шкафа")
        check(str(window.btn_kit["state"]) == "disabled",
              "«Комплект → в шкаф» закрыта для шкафа")
        window.place_cabinet()
        check(len(app.placed) == 1
              and app.placed[0].get("code") == "ШЭТ 431.11-1",
              "шкаф размещён на схеме")

        window.tree.selection_set(kits[0])
        window._show()
        root.update()
        check(str(window.btn_kit["state"]) == "normal",
              "«Комплект → в шкаф» доступна для комплекта")
        check(len(window.table.get_children()) > 0,
              "карточка комплекта заполнена")
        window.add_kit()
        check(len(app.kits) == 1
              and app.kits[0].get("cabinet_key") == "draft-шэт-431-11-1",
              "комплект передан шкафу на схеме")

        window.tree.selection_set(ieds[0])
        window._show()
        root.update()
        check(len(window.table["columns"]) == 5,
              "функции ИЭУ в таблице: %d колонок"
              % len(window.table["columns"]))
        check(hasattr(window, "export_docx"), "в окне есть выгрузка DOCX")
        check(hasattr(window, "new_standard"), "в окне есть новый стандарт")

        dialog = ea_ui.NewStandardDialog(window)
        root.update()
        check(len(dialog.cyphers) == 4, "в диалоге все шкафы")
        check(dialog.vars["date"].get().count(".") == 2,
              "дата заполнена по умолчанию")
        dialog.grab_release()
        dialog.destroy()
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
    data = es.load()
    test_catalog(data)
    test_catalog_new(data)
    test_new_standard(data)
    test_docx(data)
    test_archive()
    if not args.no_gui:
        test_gui(data)
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
