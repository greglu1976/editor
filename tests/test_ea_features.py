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
5. кнопки и узлы окна «СТО (EA)…»;
6. редактирование таблиц (``ea_edit``) и окно редактора (``ea_editor``);
7. добавление/удаление узлов стандарта (``ea_structure``).
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
import komplekts               # noqa: E402

try:
    import tkinter as tk
except ImportError:            # pragma: no cover
    tk = None

FAILURES = []

#: Эталонный стандарт для проверок — том 5.
REFERENCE = next((path for path in es.files()
                  if "т. 5" in os.path.basename(path)), None)


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

    source = next(kit for kit in komplekts.typical_komplekts()
                  if komplekts.effective_ieds(kit))
    ea_kit = ea_catalog.kit_from_catalog(source, number=7)
    check(ea_kit["number"] == 7
          and ea_kit["description"] == source["desc"],
          "типовой комплект каталога → комплект стандарта")
    check(len(ea_kit["ieds"]) == len(komplekts.effective_ieds(source))
          and es.function_blocks(ea_kit["ieds"][0]),
          "ИЭУ и функции перенесены в стандарт")
    check(set(ea_catalog.function_names(ea_kit)) <= set(source["functions"]),
          "функции сохраняются при обратном преобразовании")
    check(len(ea_kit["ieds"][0]["analog_inputs"])
          == len(source.get("analog_inputs") or []),
          "аналоговые измерения перенесены в стандарт")


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


def test_catalog_sync(data):
    """Обновление шкафов и комплектов по стандарту EA."""
    old_cabs = cabs.USER_CATALOG_PATH
    old_kits = komplekts.USER_CATALOG_PATH
    tmp_cabs = tempfile.mktemp(suffix=".json")
    tmp_kits = tempfile.mktemp(suffix=".json")
    cabs.USER_CATALOG_PATH = tmp_cabs
    komplekts.USER_CATALOG_PATH = tmp_kits
    try:
        stats = ea_catalog.update_standard_cabinets(data)
        check(stats["updated"] + stats["created"] == 4,
              "обновлено/создано 4 шкафа стандарта")
        check(stats["kits"] == 4, "в стандарте 4 комплекта")
        check(len(stats["cabinets"]) == 4, "все 4 шифра шкафов в отчёте")
        for cypher in stats["cabinets"]:
            found = ea_catalog.find_catalog_cabinet(data, {"cypher": cypher})
            check(found is not None, "шкаф %s найден в каталоге" % cypher)
            check(len(found.get("komplets") or []) >= 1,
                  "у шкафа %s есть комплекты" % cypher)
    finally:
        cabs.USER_CATALOG_PATH = old_cabs
        komplekts.USER_CATALOG_PATH = old_kits
        for p in (tmp_cabs, tmp_kits):
            if os.path.exists(p):
                os.remove(p)


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
    check(any(text.startswith("Шкаф защит батареи") for text in headings),
          "заголовок подраздела шкафа на месте")
    check(not any(text[:1].isdigit() for text in headings),
          "номера разделов и подразделов не вписаны в заголовки")
    check(not any(text.startswith("Приложение. Шкафы") for text in headings),
          "приложения со шкафами нет")

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

    # шаблон: колонтитул и параметры страницы сохраняются, тело заменяется
    template_dir = tempfile.mkdtemp()
    template = os.path.join(template_dir, ea_docx.TEMPLATE_NAME)
    tpl = Document()
    tpl.sections[0].header.paragraphs[0].text = "ШАБЛОННЫЙ КОЛОНТИТУЛ"
    tpl.add_paragraph("ТЕКСТ ШАБЛОНА")
    tpl.save(template)
    out = os.path.join(template_dir, "with_template.docx")
    ea_docx.build(data, out, max_rows=3)
    with_template = Document(out)
    check(with_template.sections[0].header.paragraphs[0].text
          == "ШАБЛОННЫЙ КОЛОНТИТУЛ", "колонтитул шаблона сохранён")
    check(not any("ТЕКСТ ШАБЛОНА" in paragraph.text
                  for paragraph in with_template.paragraphs),
          "содержимое шаблона заменено")


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
    for name in ("standard_editor", "standards_base", "cat"):
        check(not os.path.exists(os.path.join(ROOT, name)),
              "убрано с прежнего места: %s" % name)


# ---------------------------------------------------------------------------
# 5. Окно
# ---------------------------------------------------------------------------
def test_fields():
    """Диалог реквизитов сохраняет поля в JSON и в окно."""
    print("8. поля стандарта")
    if tk is None:
        print("  --   tkinter нет: диалог не проверяется")
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

    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    old_folder = es.FOLDER
    es.FOLDER = folder
    window = None
    try:
        window = ea_ui.show(App(root), path)
        dialog = ea_ui.StandardFieldsDialog(window)
        dialog.vars["code"].set("НОВЫЙ ШИФР")
        dialog.vars["name"].set("Новое наименование")
        dialog.vars["property"].set("ПАО «Тест»")
        dialog.vars["date"].set("01.01.2027")
        dialog.save()
        saved = es.load(path)
        check(saved["code"] == "НОВЫЙ ШИФР", "шифр сохранён")
        check(saved["name"] == "Новое наименование",
              "наименование сохранено")
        check(saved["property"] == "ПАО «Тест»", "принадлежность сохранена")
        check(saved["date"] == "01.01.2027", "дата сохранена")
        check(window._data["code"] == "НОВЫЙ ШИФР",
              "окно видит новый шифр")
    except Exception as exc:                      # noqa: BLE001
        check(False, "поля стандарта: %s" % exc)
    finally:
        es.FOLDER = old_folder
        if window is not None:
            window.destroy()
        root.destroy()


def test_gui(data):
    print("5. окно «СТО (EA)…»")
    if tk is None:
        print("  --   tkinter нет: окно не проверяется")
        return
    try:
        import ea_merge as em
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
        window = ea_ui.show(app, REFERENCE)
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
        check(hasattr(window, "update_cabinets_and_kits"),
              "в окне есть метод обновления шкафов и комплектов")
        check(hasattr(window, "btn_sync"),
              "в окне есть кнопка обновления шкафов и комплектов")
        check(window.btn_sync.cget("text") == "Обновить шкафы и комплекты по данному стандарту",
              "кнопка имеет текст «Обновить шкафы и комплекты по данному стандарту»")

        dialog = ea_ui.NewStandardDialog(window)
        root.update()
        total = len(dialog.entries)
        check(len(dialog.cyphers) == total,
              "в диалоге все шкафы из всех стандартов: %d" % total)
        check(dialog.listbox.size() == total,
              "в списке диалога %d записей" % total)
        first_label = dialog.listbox.get(0)
        check("[" in first_label and "]" in first_label,
              "запись списка содержит метку тома: %s" % first_label)
        check(len(dialog.listbox.curselection()) == total,
              "все шкафы выбраны по умолчанию")
        check(dialog.vars["date"].get().count(".") == 2,
              "дата заполнена по умолчанию")
        existing = {em.norm_cypher(item.get("cypher"))
                    for _kind, item in dialog.items}
        catalog_cabinet = next(
            cabinet for cabinet in komplekts.typical_cabinets()
            if cabinet.get("komplets")
            and em.norm_cypher(cabinet.get("code")) not in existing)
        original_choose = ea_ui.choose_catalog_cabinets
        ea_ui.choose_catalog_cabinets = lambda *args, **kwargs: [catalog_cabinet]
        try:
            dialog.add_catalog()
        finally:
            ea_ui.choose_catalog_cabinets = original_choose
        root.update()
        check(len(dialog.cyphers) == total + 1
              and dialog.listbox.size() == total + 1
              and "каталог" in dialog.listbox.get(total),
              "в диалог нового стандарта добавлен типовой шкаф каталога")
        check(dialog.listbox.selection_includes(total),
              "добавленный типовой шкаф выбран")
        dialog.grab_release()
        dialog.destroy()
    except Exception as exc:                      # noqa: BLE001
        check(False, "окно работает: %s" % exc)
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


# ---------------------------------------------------------------------------
# 6. Обновление всей структуры из стандартов
# ---------------------------------------------------------------------------
def test_rebuild_from_standards():
    """Метод rebuild_from_standards существует и логика синхронизации работает."""
    print("6. rebuild_from_standards — обновление каталога по всем EA-стандартам")
    old_cabs = cabs.USER_CATALOG_PATH
    old_kits = komplekts.USER_CATALOG_PATH
    tmp_cabs = tempfile.mktemp(suffix=".json")
    tmp_kits = tempfile.mktemp(suffix=".json")
    cabs.USER_CATALOG_PATH = tmp_cabs
    komplekts.USER_CATALOG_PATH = tmp_kits
    try:
        files = es.files()
        check(len(files) >= 1, "в папке EA/ есть хотя бы один стандарт")
        total_updated = 0
        total_created = 0
        total_kits = 0
        for path in files:
            data = es.load(path)
            stats = ea_catalog.update_standard_cabinets(data)
            total_updated += stats.get("updated", 0)
            total_created += stats.get("created", 0)
            total_kits += stats.get("kits", 0)
        check(total_updated + total_created >= 4,
              "обновлено/создано шкафов по всем стандартам: %d"
              % (total_updated + total_created))
        check(total_kits >= 4,
              "комплектов по всем стандартам: %d" % total_kits)
    finally:
        cabs.USER_CATALOG_PATH = old_cabs
        komplekts.USER_CATALOG_PATH = old_kits
        for p in (tmp_cabs, tmp_kits):
            if os.path.exists(p):
                os.remove(p)


def test_main_method_exists():
    """Метод rebuild_from_standards прописан в main.py."""
    print("7. метод rebuild_from_standards в CircuitEditor")
    main_path = os.path.join(ROOT, "main.py")
    with open(main_path, encoding="utf-8") as fh:
        source = fh.read()
    check("def rebuild_from_standards(self)" in source,
          "метод rebuild_from_standards определён в main.py")
    check("rebuild_from_standards" in source and
          "\"Обновить из СТО\"" in source,
          "кнопка «Обновить из СТО» зарегистрирована в ленте")
    check("\"Обновить из стандартов (EA)\"" in source,
          "кнопка «Обновить из стандартов (EA)» есть в окне структуры")


def test_edit_model():
    """ea_edit: строки таблиц читаются и записываются без потерь."""
    print("9. редактирование таблиц (ea_edit)")
    import copy
    import ea_edit as ee

    data = es.load(REFERENCE)
    problems, checked = 0, 0
    for index, table in enumerate(es.iter_tables(data)):
        if (table.get("cabinet")
                and es.table_kind(table.get("name")) == "description"):
            continue
        clone = copy.deepcopy(data)
        twin = list(es.iter_tables(clone))[index]
        before = es.table_view(data, table)
        try:
            headers, rows, note = ee.load(data, table)
            ee.save(clone, twin, rows)
        except ee.TableEditError:
            problems += 1
            continue
        if before != es.table_view(clone, twin):
            problems += 1
        else:
            checked += 1
    check(problems == 0, "таблиц прочитано и записано без потерь: %d, "
                         "с расхождениями: %d" % (checked, problems))

    clone = copy.deepcopy(data)
    table = next(item for item in es.iter_tables(clone)
                 if es.table_kind(item.get("name")) == "analog_inputs")
    headers, rows, note = ee.load(clone, table)
    rows[0][0] = "Проверочная цепь"
    ee.save(clone, table, rows)
    ied = es.cabinet(clone, table["cabinet"])["kits"][0]["ieds"][0]
    check(ied["analog_inputs"][0]["circuit_type"] == "Проверочная цепь",
          "правка ячейки доходит до шкафа")

    headers, rows, note = ee.load(clone, table)
    rows.append([""] * len(headers))
    ee.save(clone, table, rows)
    check(len(ied["analog_inputs"]) == len(rows) - 1,
          "пустая строка в шкаф не записывается")
    check(es.validate(clone) == [], "после правок структура валидна")


def test_editor():
    """Окно редактора правит таблицы, реквизиты и шкафы и пишет JSON."""
    print("10. окно редактора стандарта")
    if tk is None:
        print("  --   tkinter нет: редактор не проверяется")
        return
    try:
        import ea_editor
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        print("  --   окно не открыть: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    saved = []
    window = None
    try:
        window = ea_editor.show(path, root, on_saved=saved.append)
        root.update()
        kinds = {node[0] for node in window._nodes.values()}
        check({"meta", "text", "table", "cabinet"} <= kinds,
              "в дереве есть реквизиты, текст, таблицы и шкафы")

        errors = 0
        for iid in list(window._nodes):
            try:
                window.tree.selection_set(iid)
                root.update()
            except Exception:                      # noqa: BLE001
                errors += 1
        check(errors == 0, "все узлы дерева открываются без ошибок")

        table = next(item for item in es.iter_tables(window.data)
                     if es.table_kind(item.get("name")) == "analog_inputs")
        iid = next(key for key, node in window._nodes.items()
                   if node[0] == "table" and node[1] is table)
        window.tree.selection_set(iid)
        root.update()
        check(len(window._grid_rows) > 0, "строки таблицы показаны в сетке")
        window._grid_rows[0][0] = "Цепь из редактора"
        window._pending = window._apply_grid
        window.save()
        root.update()
        data = es.load(path)
        ied = es.cabinet(data, table["cabinet"])["kits"][0]["ieds"][0]
        check(ied["analog_inputs"][0]["circuit_type"] == "Цепь из редактора",
              "правка таблицы записана в файл")
        check(saved and saved[-1] == path, "редактор сообщил о сохранении")

        meta = next(key for key, node in window._nodes.items()
                    if node[0] == "meta")
        window.tree.selection_set(meta)
        root.update()
        window.vars["name"].set("Стандарт из редактора")
        window.save()
        root.update()
        check(es.load(path)["name"] == "Стандарт из редактора",
              "наименование записано")
        check(not window._changed, "после сохранения правок не осталось")

        # структурные операции: дерево, контекстное меню, новые узлы
        import ea_merge as em
        import ea_structure as st
        kinds = {node[0] for node in window._nodes.values()}
        check({"meta", "text", "table", "figure", "cabinet"} <= kinds,
              "в дереве есть реквизиты, текст, таблицы, рисунки и шкафы")
        doc_iid = next(key for key, node in window._nodes.items()
                       if node == ("root", "doc"))
        check(window._owners[doc_iid][0] is window.data["sections"],
              "корень документа связан со списком разделов")
        items = window._menu_items(doc_iid, window._nodes[doc_iid])
        check(bool(items) and items[0][0].startswith("Добавить"),
              "контекстное меню корня документа")

        created = []

        def add_section():
            item = st.new_section(window.data, header="Секция из меню")
            st.add(window._owners[doc_iid][0], item)
            created.append(item)
            return item

        window._mutate(add_section)
        root.update()
        section = created[0]
        check(window._current_node in window._nodes
              and window._nodes[window._current_node][-1] is section,
              "новый раздел добавлен и выбран в дереве")
        check(window._changed, "structural правка помечена как изменение")
        section_iid = window._find_iid(section)
        check(section_iid in window._owners
              and window._owners[section_iid][1] is section,
              "у нового раздела есть ссылка на контейнер")

        def add_table():
            item = st.new_table(window.data, {"name": "Новая таблица",
                                              "headers": ["П", "З"]})
            st.add(window._child_container(section_iid, "table"), item)
            return item

        window._mutate(add_table)
        root.update()
        check(len(section["tables"]) == 1 and window._grid is not None,
              "таблица документа добавлена и открыта в редакторе")

        # перенос и копирование таблицы в другой раздел
        doc_table = section["tables"][0]
        table_iid = window._find_iid(doc_table)
        source_tables = window._owners[table_iid][0]
        target_section = next(item for item in window.data["sections"]
                              if str(item.get("number")) == "4")
        target_tables = target_section.setdefault("tables", [])
        target = {"label": "Раздел 4", "hint": "Таблиц: 0",
                  "container": target_section, "tables": target_tables,
                  "section": target_section}
        original_choose = ea_editor.choose_item
        original_ask = ea_editor.simpledialog.askstring
        ea_editor.choose_item = lambda *args, **kwargs: target
        ea_editor.simpledialog.askstring = lambda *args, **kwargs: "4.99"
        try:
            window._move_table(table_iid, copy=True)
            root.update()
            clone = target_tables[-1]
            check(clone is not doc_table and clone["number"] == "4.99"
                  and clone["reference"] == "Таблица 4.99"
                  and clone["name"].endswith("(копия)"),
                  "таблица скопирована в другой раздел с новым номером")
            check(window._nodes[window._current_node][-1] is clone,
                  "копия таблицы выбрана в дереве")

            appendix = next(item for item in window.data["sections"]
                            if str(item.get("number")) == "А")
            appendix_tables = appendix.setdefault("tables", [])
            target = {"label": "Раздел А", "hint": "Таблиц: 0",
                      "container": appendix, "tables": appendix_tables,
                      "section": appendix}
            window._move_table(window._find_iid(doc_table), copy=False)
            root.update()
            check(doc_table in appendix_tables
                  and doc_table not in source_tables,
                  "таблица перенесена в другой раздел без дубля")
        finally:
            ea_editor.choose_item = original_choose
            ea_editor.simpledialog.askstring = original_ask

        # групповая работа с выделением: перенос, копирование, удаление
        extra = []
        for name in ("Групповая 1", "Групповая 2"):
            item = st.new_table(window.data, {"name": name,
                                              "headers": ["П", "З"]})
            st.add(section.setdefault("tables", []), item)
            extra.append(item)
        figure = st.new_figure(window.data, section,
                               name="Групповой рисунок")
        st.add(section.setdefault("figures", []), figure)
        window._fill_tree()
        root.update()
        group = [window._find_iid(item) for item in extra]
        window.tree.selection_set(group)
        root.update()
        check(window._selection_iids() == group,
              "выделение из нескольких узлов читается деревом")
        labels = [entry[0] for entry in
                  window._menu_items(group[0], window._nodes[group[0]])
                  if entry]
        check(any("Переместить выделенное (2)" in label for label in labels)
              and any("Копировать выделенное (2)" in label for label in labels)
              and any("Удалить выделенное (2)" in label for label in labels),
              "в меню выделенной группы есть перенос, копирование и удаление")

        group_target = {"label": "Раздел 4",
                        "hint": "Таблиц: 1, рисунков: 0",
                        "container": target_section,
                        "section": target_section}
        ea_editor.choose_item = lambda *args, **kwargs: group_target
        try:
            window._transfer(window._selection_iids(), copy=True)
            root.update()
        finally:
            ea_editor.choose_item = original_choose
        copies = [item for item in target_tables
                  if item.get("name", "").startswith("Групповая")]
        check(len(copies) == 2 and copies[0]["number"] != copies[1]["number"],
              "группа таблиц скопирована с новыми номерами")
        check(len(window.tree.selection()) == 2,
              "после группового копирования выделены все копии")

        # рисунок в группе получает новый номер в целевом разделе
        window.tree.selection_set([window._find_iid(copies[0]),
                                   window._find_iid(figure)])
        root.update()
        figures_before = len(target_section.get("figures") or [])
        ea_editor.choose_item = lambda *args, **kwargs: group_target
        try:
            window._transfer(window._selection_iids(), copy=True)
            root.update()
        finally:
            ea_editor.choose_item = original_choose
        figures_after = target_section.get("figures") or []
        check(len(figures_after) == figures_before + 1
              and figures_after[-1] is not figure,
              "рисунок скопирован в другой раздел с новым номером")

        appendix = next(item for item in window.data["sections"]
                        if str(item.get("number")) == "А")
        appendix_tables = appendix.setdefault("tables", [])
        appendix_target = {"label": "Раздел А",
                           "hint": "Таблиц: 1, рисунков: 0",
                           "container": appendix, "section": appendix}
        window.tree.selection_set([window._find_iid(item) for item in copies])
        root.update()
        ea_editor.choose_item = lambda *args, **kwargs: appendix_target
        try:
            window._transfer(window._selection_iids(), copy=False)
            root.update()
        finally:
            ea_editor.choose_item = original_choose
        check(all(item in appendix_tables for item in copies)
              and not any(item in target_tables for item in copies),
              "группа таблиц перенесена в другой раздел")

        mixed = [window._find_iid(copies[0]), window._find_iid(section)]
        window.tree.selection_set(mixed)
        root.update()
        labels = [entry[0] for entry in
                  window._menu_items(mixed[0], window._nodes[mixed[0]])
                  if entry]
        check(not any("Переместить выделенное" in label for label in labels)
              and any("Удалить выделенное" in label for label in labels),
              "в смешанной группе доступно только удаление")

        window.tree.selection_set([window._find_iid(item) for item in copies])
        root.update()
        original_confirm = ea_editor.messagebox.askyesno
        ea_editor.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            window._delete_selection()
            root.update()
        finally:
            ea_editor.messagebox.askyesno = original_confirm
        check(not any(item in appendix_tables for item in copies),
              "выделенная группа удалена одним действием")

        # привязка таблицы к другому шкафу
        bound = next(table for table in es.iter_tables(window.data)
                     if table.get("cabinet"))
        bound_iid = window._find_iid(bound)
        old_code = bound["cabinet"]
        other_cabinet = next(item for item in es.cabinets(window.data)
                             if item.get("cypher") != old_code)
        labels = [entry[0] for entry in
                  window._menu_items(bound_iid, window._nodes[bound_iid])
                  if entry]
        check(any("Привязать к другому шкафу" in label for label in labels),
              "в меню таблицы есть привязка к другому шкафу")
        original_choose_cabinet = window._choose_cabinet
        window._choose_cabinet = lambda *args, **kwargs: other_cabinet
        ea_editor.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            window._rebind_table(bound_iid)
            root.update()
        finally:
            window._choose_cabinet = original_choose_cabinet
            ea_editor.messagebox.askyesno = original_confirm
        check(bound["cabinet"] == other_cabinet["cypher"]
              and other_cabinet["cypher"] in (bound.get("name") or ""),
              "таблица перепривязана к другому шкафу")
        check(window.tree.item(window._find_iid(bound), "text")
              == "%s %s" % (bound.get("reference") or "Таблица",
                            bound.get("name") or ""),
              "подпись таблицы в дереве обновилась")

        # удаление шкафа: таблицы перепривязываются к другому шкафу
        victim = next(item for item in es.cabinets(window.data)
                      if any(table.get("cabinet") == item.get("cypher")
                             for table in es.iter_tables(window.data)))
        spare = next(item for item in es.cabinets(window.data)
                     if item is not victim)
        window._fill_tree()
        root.update()
        victim_iid = window._find_iid(victim)
        window.tree.selection_set(victim_iid)
        root.update()
        original_ask_rebind = window._ask_rebind
        window._ask_rebind = lambda item: spare
        ea_editor.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            window._delete_node(victim_iid)
            root.update()
        finally:
            window._ask_rebind = original_ask_rebind
            ea_editor.messagebox.askyesno = original_confirm
        check(not any(item is victim for item in es.cabinets(window.data))
              and all(table.get("cabinet") != victim["cypher"]
                      for table in es.iter_tables(window.data)),
              "таблицы перепривязаны, шкаф удалён")

        # правка номера и наименования таблицы в панели
        target_table = next(table for table in es.iter_tables(window.data)
                            if table.get("cabinet"))
        window._fill_tree()
        root.update()
        table_iid = window._find_iid(target_table)
        window.tree.selection_set(table_iid)
        root.update()
        old_name = target_table["name"]
        code = target_table["cabinet"]
        new_name = old_name.replace(code, "ШЭТ 999-1")
        window.vars["name"].set(new_name)
        window.vars["number"].set("99.99")
        applied = window._apply_pending()
        root.update()
        check(applied and target_table["name"] == new_name
              and target_table["number"] == "99.99"
              and target_table["reference"] == "Таблица 99.99",
              "номер и наименование таблицы правятся в панели")
        check(window.tree.item(window._find_iid(target_table), "text")
              == "Таблица 99.99 " + new_name,
              "подпись таблицы в дереве обновилась")

        # смена вида данных таблицы шкафа отклоняется
        original_error = ea_editor.messagebox.showerror
        errors = []
        ea_editor.messagebox.showerror = lambda *args, **kwargs: errors.append(
            args)
        window.vars["name"].set("Ряды зажимов шкафа " + code)
        rejected = window._apply_pending()
        ea_editor.messagebox.showerror = original_error
        check(not rejected and errors and target_table["name"] == new_name,
              "смена вида данных таблицы отклоняется")
        window.vars["name"].set(target_table["name"])
        window._apply_pending()
        root.update()

        # смена шифра шкафа перепривязывает его таблицы
        owner = next(item for item in es.cabinets(window.data)
                     if any(table.get("cabinet") == item.get("cypher")
                            for table in es.iter_tables(window.data)))
        window._fill_tree()
        root.update()
        owner_iid = window._find_iid(owner)
        window.tree.selection_set(owner_iid)
        root.update()
        old_code = owner["cypher"]
        new_code = "ШЭТ 777-1"
        linked = [table for table in es.iter_tables(window.data)
                  if table.get("cabinet") == old_code]
        named = [table for table in linked
                 if old_code in (table.get("name") or "")]
        window.vars["cypher"].set(new_code)
        window._apply_pending()
        root.update()
        check(owner["cypher"] == new_code
              and all(table.get("cabinet") == new_code for table in linked)
              and all(new_code in (table.get("name") or "")
                      for table in named),
              "смена шифра шкафа перепривязывает его таблицы")
        check(all(window.tree.item(window._find_iid(table), "text")
                  == "%s %s" % (table.get("reference") or "Таблица",
                                table.get("name") or "")
                  for table in linked),
              "подписи таблиц обновились после смены шифра")

        # шифр не может совпасть с другим шкафом
        other_code = next(item["cypher"] for item in es.cabinets(window.data)
                          if item is not owner)
        errors = []
        ea_editor.messagebox.showerror = lambda *args, **kwargs: errors.append(
            args)
        window.vars["cypher"].set(other_code)
        rejected = window._apply_pending()
        ea_editor.messagebox.showerror = original_error
        check(not rejected and errors and owner["cypher"] == new_code,
              "шифр шкафа не может совпадать с другим шкафом")
        window.vars["cypher"].set(new_code)
        window._apply_pending()
        root.update()

        # групповая привязка таблиц к другому шкафу
        group_tables = [table for table in es.iter_tables(window.data)
                        if table.get("cabinet") == new_code][:2]
        window._fill_tree()
        root.update()
        group_iids = [window._find_iid(table) for table in group_tables]
        window.tree.selection_set(group_iids)
        root.update()
        labels = [entry[0] for entry in
                  window._menu_items(group_iids[0],
                                     window._nodes[group_iids[0]]) if entry]
        check(any("Привязать выделенное (2) к другому шкафу" in label
                  for label in labels),
              "в меню группы таблиц есть привязка к шкафу")
        target_cabinet = next(item for item in es.cabinets(window.data)
                              if item is not owner)
        window._choose_cabinet = lambda *args, **kwargs: target_cabinet
        ea_editor.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            window._rebind_group(window._selection_iids())
            root.update()
        finally:
            window._choose_cabinet = original_choose_cabinet
            ea_editor.messagebox.askyesno = original_confirm
        check(all(table.get("cabinet") == target_cabinet["cypher"]
                  for table in group_tables),
              "группа таблиц привязана к другому шкафу")

        cabinet_iid = next(key for key, node in window._nodes.items()
                           if node[0] == "cabinet")
        menu = window._menu_items(cabinet_iid, window._nodes[cabinet_iid])
        check(any("типовой комплект" in label for label, _cmd in menu),
              "в меню шкафа есть «Добавить типовой комплект из каталога»")
        chosen = next(kit for kit in komplekts.typical_komplekts()
                      if komplekts.effective_ieds(kit))
        window._choose_typical_kit = lambda: chosen
        cabinet_item = window._owners[cabinet_iid][1]
        before = len(cabinet_item["kits"])
        window._add_typical_kit(cabinet_iid)
        root.update()
        added = cabinet_item["kits"]
        check(len(added) == before + 1
              and added[-1]["description"] == chosen["desc"],
              "типовой комплект добавлен в шкаф стандарта")
        check(window._nodes[window._current_node][-1] is added[-1],
              "новый комплект выбран в дереве редактора")

        ied_iid = next(key for key, node in window._nodes.items()
                       if node[0] == "ied" and node[1] is added[-1]["ieds"][0])
        window.tree.selection_set(ied_iid)
        root.update()
        window.vars["number"].set("12")
        window._apply_pending()
        root.update()
        check(added[-1]["ieds"][0]["number"] == "12"
              and window.tree.item(ied_iid, "text") == "ИЭУ 12"
              and window.caption.cget("text") == "ИЭУ 12",
              "номер ИЭУ нового комплекта меняется и виден в дереве")

        cabs_iid = next(key for key, node in window._nodes.items()
                        if node == ("root", "cabs"))
        menu = window._menu_items(cabs_iid, window._nodes[cabs_iid])
        check(any("типовой шкаф" in label for label, _cmd in menu),
              "в меню шкафов есть «Добавить типовой шкаф из каталога»")
        existing = {em.norm_cypher(item.get("cypher"))
                    for item in es.cabinets(window.data)}
        catalog_cabinet = next(
            cabinet for cabinet in komplekts.typical_cabinets()
            if cabinet.get("komplets")
            and em.norm_cypher(cabinet.get("code")) not in existing)
        window._choose_typical_cabinet = lambda: catalog_cabinet
        before_cabs = len(es.cabinets(window.data))
        window._add_typical_cabinet(cabs_iid)
        root.update()
        check(len(es.cabinets(window.data)) == before_cabs + 1
              and es.cabinet(window.data, catalog_cabinet["code"]) is not None,
              "типовой шкаф добавлен в стандарт")
        check(any(table.get("cabinet") == catalog_cabinet["code"]
                  for table in es.iter_tables(window.data)),
              "таблицы-формы типового шкафа созданы")
        del window._choose_typical_cabinet

        del window._choose_typical_kit
        original_wait = tk.Toplevel.wait_window

        def press_add(dialog, *args, **kwargs):
            dialog.update()
            frames = [child for child in dialog.winfo_children()
                      if isinstance(child, tk.Frame)]
            buttons = [button for frame in frames
                       for button in frame.winfo_children()
                       if isinstance(button, tk.Button)]
            next(button for button in buttons
                 if button.cget("text") == "Добавить").invoke()

        tk.Toplevel.wait_window = press_add
        try:
            picked = window._choose_typical_kit()
        finally:
            tk.Toplevel.wait_window = original_wait
        check(picked is not None and picked.get("kind") == "typical",
              "диалог выбора возвращает типовой комплект каталога")

        window.save()
        root.update()
        saved_sections = es.load(path)["sections"]
        check(any(s.get("header") == "Секция из меню"
                  for s in saved_sections),
              "новая структура записана в JSON")
        check(es.validate(es.load(path)) == [],
              "после добавления узлов структура валидна")
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


def test_structure_ops(data):
    """Добавление/удаление узлов без GUI (ea_structure)."""
    print("11. структурные операции (ea_structure)")
    import copy
    import ea_edit as ee
    import ea_structure as st

    clone = copy.deepcopy(data)
    section = st.new_section(clone, header="Новый раздел")
    st.add(clone["sections"], section)
    sub = st.new_subsection(clone, section)
    st.add(section["subsections"], sub)
    clause = st.new_clause(clone, sub)
    st.add(sub["clauses"], clause)
    figure = st.new_figure(clone, sub)
    st.add(sub["figures"], figure)
    check(set(("number", "header", "header_style", "content",
               "subsections", "tables", "figures")) <= set(section),
          "раздел создан с полным набором полей")
    check(clause["number"].startswith(str(sub["number"]) + ".")
          and figure["reference"] == "Рисунок %s" % figure["number"],
          "номера пункта и рисунка согласованы с родителем")

    doc_table = st.new_table(clone, {"name": "Перечень",
                                     "headers": ["Параметр", "Значение"]})
    st.add(clause["tables"], doc_table)
    check(es._stored_view(doc_table)[0] == ["Параметр", "Значение"],
          "таблица документа хранит свою шапку")

    cabinet = es.cabinets(clone)[0]
    kind = "analog_inputs"
    spec = {"name": st.kind_name(kind), "cabinet": cabinet["cypher"],
            "kind": kind}
    table = st.new_table(clone, spec)
    st.add(sub["tables"], table)
    check(es.table_kind(table["name"]) == kind,
          "имя таблицы шкафа определяет вид данных")
    check(es._form_headers(table) == list(ee._FLAT_HEADERS[kind])
          and es.table_view(clone, table)[0] == list(ee._FLAT_HEADERS[kind]),
          "шапка новой таблицы совпадает с формой данных шкафа")
    check(es.validate(clone) == [], "после добавления узлов структура валидна")

    extra = st.new_cabinet(clone, cypher="__TEST_CABINET__")
    st.add(clone["cabinets"], extra)
    kit = st.new_kit(clone, extra)
    st.add(extra["kits"], kit)
    ied = st.new_ied(clone, kit)
    st.add(kit["ieds"], ied)
    check(isinstance(kit["number"], int) and isinstance(ied["number"], int)
          and len(ied) == 11,
          "комплект и ИЭУ созданы с числовыми номерами и наборами данных")

    st.remove(sub["tables"], table)
    check(table not in sub["tables"], "таблица удалена из раздела")
    issues = st.delete_issues(clone, cabinet, "cabinet")
    check(bool(issues), "шкаф с таблицами нельзя удалить")
    issues = st.delete_issues(clone, cabinet["kits"][0], "kit")
    check(bool(issues), "первый комплект шкафа с таблицами защищён")
    issues = st.delete_issues(clone, extra["kits"][0], "kit")
    check(not issues, "пустой комплект удаляется без предупреждений")

    path = os.path.join(tempfile.mkdtemp(), "structure.json")
    es.save(clone, path)
    loaded = es.load(path)
    check(len(loaded["sections"]) == len(clone["sections"])
          and len(loaded["cabinets"]) == len(clone["cabinets"])
          and es.validate(loaded) == [],
          "круговой save/load сохраняет структуру без потерь")


def test_merge_all_cabinets():
    """Каталог и слияние шкафов всех стандартов (ea_merge)."""
    print("12. слияние шкафов всех стандартов (ea_merge)")
    import json
    import re
    import ea_merge as em

    entries = em.catalog(use_cache=False)
    check(bool(entries),
          "каталог содержит шкафы из всех стандартов: %d" % len(entries))
    volumes = {em.volume_label(entry["path"]) for entry in entries}
    check({"т. 1", "т. 3", "т. 5", "т. 7"} <= volumes,
          "каталог хранит метки томов: %s" % ", ".join(sorted(volumes)))
    check(all(entry["data"] and entry["cypher"] for entry in entries),
          "у каждой записи каталога есть данные и шифр")
    codes = [em.norm_cypher(entry["cypher"]) for entry in entries]
    check(len(codes) == len(set(codes)), "шифры в каталоге уникальны")

    target = es.load(REFERENCE)
    target_codes = {em.norm_cypher(item.get("cypher"))
                    for item in es.cabinets(target)}
    expected_cabs = len({em.norm_cypher(entry["cypher"]) for entry in entries}
                        | target_codes)
    expected_forms = sum(1 for table in es.iter_tables(target)
                         if table.get("cabinet"))
    for entry in entries:
        if em.norm_cypher(entry["cypher"]) in target_codes:
            continue
        forms = sum(1 for table in es.iter_tables(entry["data"])
                    if table.get("cabinet") == entry["cypher"])
        expected_forms += forms or len(es.KINDS)
    merged = em.merge_cabinets(target, entries)
    cabs = es.cabinets(merged)
    nums = [str(table.get("number"))
            for table in es.iter_tables(merged) if table.get("cabinet")]
    check(len(cabs) == expected_cabs,
          "после слияния %d шкафов" % expected_cabs)
    check(len(nums) == expected_forms,
          "после слияния %d форм: %d" % (expected_forms, len(nums)))
    check(em.validate_merged(merged) == [],
          "слитый стандарт проходит проверку структуры")
    check(len(set(nums)) == len(nums), "номера таблиц уникальны")
    ordered = sorted(int(number.split(".")[1]) for number in nums)
    check(ordered == list(range(2, 2 + len(nums))),
          "нумерация сквозная 5.2…5.%d" % (1 + len(nums)))
    text = json.dumps(merged, ensure_ascii=False)
    check(not re.search(r"5\.(?:1\d{3}|2\d{3})\b", text),
          "в тексте не осталось временных диапазонов нумерации")
    check(not [n for n in nums if n in
               {str(t.get("number")) for t in es.iter_tables(target)
                if not t.get("cabinet")}],
          "номера форм не схлопнулись с таблицами документа")

    clone = json.loads(json.dumps(merged, ensure_ascii=False))
    check(em.validate_merged(clone) == [],
          "круговой save/load слияния сохраняет валидность")

    subset = entries[:5]
    part = em.merge_cabinets(target, subset)
    part_nums = [str(table.get("number"))
                 for table in es.iter_tables(part) if table.get("cabinet")]
    check(em.validate_merged(part) == []
          and len(part_nums) == len(set(part_nums)),
          "слияние подмножества тоже валидно и перенумеровано")


def test_typical_transfer():
    """Типовой шкаф/комплект каталога переносится в стандарт с данными."""
    print("13. перенос данных типовых шкафов и комплектов")
    import ea_merge as em

    def rich(cabinet):
        return any(komplekts.effective_ieds(kit) and kit.get("functions")
                   and kit.get("analog_inputs")
                   for kit in cabinet.get("komplets") or [])

    target = es.load(REFERENCE)
    existing = {em.norm_cypher(item.get("cypher"))
                for item in es.cabinets(target)}
    source = next(cabinet for cabinet in komplekts.typical_cabinets()
                  if cabinet.get("komplets") and rich(cabinet)
                  and em.norm_cypher(cabinet.get("code")) not in existing)

    card = ea_catalog.cabinet_from_catalog(source)
    check(card["cypher"] == source["code"], "шифр типового шкафа перенесён")
    check(card["kits"] and card["kits"][0]["ieds"],
          "комплекты и ИЭУ типового шкафа перенесены")
    ied = next(kit["ieds"][0] for kit in card["kits"] if kit["ieds"])
    check(bool(es.function_blocks(ied)), "функции ИЭУ перенесены")
    check(bool(ied["analog_inputs"]), "аналоговые измерения перенесены")
    check(bool(card["power_supplies"]), "вводы питания перенесены")
    signals = cabs.signals_for(source)
    if signals.get("io_in") or signals.get("io_out"):
        check(bool(ied["inner_discrete_circuits"]),
              "дискретные цепи перенесены")
    if signals.get("goose_in"):
        check(bool(ied["incoming_goose_signals"]),
              "входящие GOOSE перенесены")
    if signals.get("test_blocks"):
        check(bool(card["components"]),
              "испытательные блоки перенесены в компоненты")

    result = em.add_catalog_cabinet(target, source)
    data = result["data"]
    check(es.cabinet(data, source["code"]) is not None,
          "типовой шкаф добавлен в стандарт")
    check(len(result["subsection"]["tables"]) == len(es.KINDS),
          "созданы таблицы-формы всех видов: %d"
          % len(result["subsection"]["tables"]))
    check(em.validate_merged(data) == [], "стандарт с типовым шкафом валиден")
    headers, rows = es.table_view(data, result["subsection"]["tables"][1])
    check(bool(headers) and bool(rows),
          "данные шкафа видны в таблице-форме")
    try:
        em.add_catalog_cabinet(data, source)
    except em.MergeError:
        check(True, "повторное добавление шкафа отклонено")
    else:
        check(False, "повторное добавление шкафа отклонено")

    kit_source = next(kit for kit in komplekts.typical_komplekts()
                      if kit.get("test_block_list"))
    kit = ea_catalog.kit_from_catalog(kit_source, number=3)
    check(kit["number"] == 3 and bool(kit["ieds"]),
          "типовой комплект перенесён с ИЭУ")
    cabinet = {"components": []}
    added = ea_catalog.add_test_blocks(cabinet, kit_source)
    check(bool(added) and len(cabinet["components"]) == len(added),
          "испытательные блоки комплекта добавлены в шкаф")
    check(ea_catalog.add_test_blocks(cabinet, kit_source) == [],
          "повторно блоки не добавляются")

    one = ns.build(data, meta={"code": "СТО (тест)", "name": "Тест",
                               "date": "01.01.2027"},
                   keep=["ШЭТ 431.12-1", source["code"]])
    check(not one["problems"], "новый стандарт с типовым шкафом валиден")
    check([cab["cypher"] for cab in one["data"]["cabinets"]]
          == ["ШЭТ 431.12-1", source["code"]],
          "в новый стандарт попали только выбранные шкафы")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args(argv)
    data = es.load(REFERENCE)
    test_catalog(data)
    test_catalog_new(data)
    test_catalog_sync(data)
    test_new_standard(data)
    test_docx(data)
    test_archive()
    test_rebuild_from_standards()
    test_main_method_exists()
    test_edit_model()
    test_structure_ops(data)
    test_merge_all_cabinets()
    test_typical_transfer()
    if not args.no_gui:
        test_gui(data)
        test_fields()
        test_editor()
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
