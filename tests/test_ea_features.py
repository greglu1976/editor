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
7. добавление/удаление узлов стандарта (``ea_structure``);
8. схему ФЛС в составе ИЭУ: поле ``IED.scheme``, генерацию из функций,
   рендер в PNG и вставку в DOCX (``logic_scheme_render``);
9. перекрёстные ссылки по меткам ``\\ref{…}`` (пункт 31): поле ``ref``,
   REF-поля в DOCX и пункт меню редактора.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cabs                    # noqa: E402
import ea_catalog              # noqa: E402
import ea_docx                 # noqa: E402
import ea_new_standard as ns   # noqa: E402
import ea_schema as sc         # noqa: E402
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


def style_font_size(style):
    """Кегль стиля с учётом ``basedOn``: у «ДОК …» он наследуется от Normal."""
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        if style.font.size is not None:
            return style.font.size.pt
        style = style.base_style
    return None


def heading_texts(doc):
    """Тексты заголовков: стили с уровнем структуры (``outlineLvl``).

    В отчёте по стандарту заголовки получают стиль из поля ``header_style``
    («ДОК Текст …», «ДОК ПРИЛ …»), а не «Heading N», поэтому определять их по
    имени стиля нельзя.
    """
    from docx.oxml.ns import qn

    def is_heading(style):
        seen = set()
        while style is not None and style.style_id not in seen:
            seen.add(style.style_id)
            props = style.element.find(qn("w:pPr"))
            if props is not None and props.find(qn("w:outlineLvl")) is not None:
                return True
            style = style.base_style
        return False

    return [paragraph.text for paragraph in doc.paragraphs
            if paragraph.style is not None and is_heading(paragraph.style)]


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
    check(one["data"].get("description_split") is True,
          "новый стандарт помечен как разделённый")
    check(one["stats"]["формы"] == 15, "таблиц-форм: %d"
          % one["stats"]["формы"])
    subs = [sub for section in one["data"]["sections"]
            for sub in section.get("subsections") or []
            if any(table.get("cabinet") for table in sub.get("tables") or [])]
    check([sub["number"] for sub in subs] == ["5.3"],
          "подраздел перенумерован в 5.3")
    tables = [table["number"] for table in es.iter_tables(one["data"])
              if table.get("cabinet")]
    check(tables == ["5.%d" % index for index in range(2, 17)],
          "таблицы перенумерованы 5.2…5.16")
    description = next(table for table in es.iter_tables(one["data"])
                       if table.get("description_part") == "cabinet")
    kit_table = next(table for table in es.iter_tables(one["data"])
                     if table.get("description_part") == "kit")
    check(len(description["rows"]) == 8,
          "в таблице шкафа остались только поля шкафа")
    check(es.table_kind(kit_table["name"]) == "description_kit"
          and "Описание ИЭУ1 в составе" in kit_table["name"],
          "описание ИЭУ вынесено в отдельную таблицу")
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


def test_split_descriptions(data):
    """Пункт 33: описание шкафа и описания ИЭУ в новом стандарте."""
    print("2б. разделённое описание шкафа и ИЭУ")
    import ea_structure as st

    legacy = ns.build(data, meta={"code": "OLD", "date": "01.01.2027",
                                  "description_split": False})
    check(legacy["data"].get("description_split") is False,
          "флаг позволяет оставить старый формат")
    legacy_description = [table for table in es.iter_tables(legacy["data"])
                          if es.table_kind(table.get("name")) == "description"]
    check(len(legacy_description) == len(es.cabinets(legacy["data"]))
          and not [table for table in es.iter_tables(legacy["data"])
                   if table.get("description_part")],
          "старый стандарт сохраняет одну таблицу описания на шкаф")

    new = ns.build(data, meta={"code": "NEW", "date": "01.01.2027"})["data"]
    cabinets = es.cabinets(new)
    cabinet_tables = [table for table in es.iter_tables(new)
                      if table.get("description_part") == "cabinet"]
    kit_tables = [table for table in es.iter_tables(new)
                  if table.get("description_part") == "kit"]
    check(len(cabinet_tables) == len(cabinets)
          and len(kit_tables) == len(cabinets),
          "на каждый шкаф — описание шкафа и описание ИЭУ")
    check(all(es.table_kind(table["name"]) == "description_kit"
              for table in kit_tables),
          "описание ИЭУ распознаётся как вид таблицы")
    check(all(len(table["rows"]) == 8 for table in cabinet_tables)
          and all(len(table["rows"]) == 19 for table in kit_tables),
          "поля разделены по документации: 8 и 19")

    header, rows = es.table_view(new, cabinet_tables[0])
    values = dict(rows)
    check(header == ["Параметр", "Значение"]
          and values.get("Шифр шкафа") == cabinets[0]["cypher"]
          and "Наименование комплекта" not in values,
          "таблица шкафа берёт значения из карточки шкафа")
    kit = cabinets[0]["kits"][0]
    _header, kit_rows = es.table_view(new, kit_tables[0])
    kit_values = dict(kit_rows)
    check(kit_values.get("Наименование комплекта") == kit.get("description")
          and bool(kit_values.get("Основные функции")),
          "таблица ИЭУ берёт значения из комплекта и его ИЭУ")

    # Идентичные комплекты дают одну таблицу «ИЭУ1(2)».
    second = copy.deepcopy(cabinets[0]["kits"][0])
    second["number"] = 2
    second["identical"] = "группа 33"
    cabinets[0]["kits"][0]["identical"] = "группа 33"
    cabinets[0]["kits"].append(second)
    before = len([table for table in es.iter_tables(new)
                  if table.get("description_part") == "kit"])
    created = st.split_description_tables(new)
    after = [table for table in es.iter_tables(new)
             if table.get("description_part") == "kit"]
    check(created == before and len(after) == before,
          "повторная генерация не дублирует таблицы")
    check(any("ИЭУ1(2)" in table["name"] for table in after),
          "идентичные ИЭУ описаны одной таблицей")


# ---------------------------------------------------------------------------
# 3. DOCX
# ---------------------------------------------------------------------------
def test_docx(data):
    print("3. выгрузка в DOCX")
    try:
        from docx import Document
        from docx.oxml.ns import qn
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
    check(len(doc.sections) == 1,
          "рисунки без формата не меняют параметры страницы")
    headings = heading_texts(doc)
    check(any(text.startswith("Шкаф защит батареи") for text in headings),
          "заголовок подраздела шкафа на месте")
    check(not any(text[:1].isdigit() for text in headings),
          "номера разделов и подразделов не вписаны в заголовки")
    check(not any(text.startswith("Приложение. Шкафы") for text in headings),
          "приложения со шкафами нет")

    # Пункт 42: «Содержание» оформляется стилем «Заголовок оглавления»,
    # а не «Заголовок 1»; стиль вынесен в реквизит toc_style.
    toc_heading = next(paragraph for paragraph in doc.paragraphs
                       if paragraph.text.strip() == "Содержание")
    check(toc_heading.style.name == "TOC Heading",
          "«Содержание» оформлено стилем «Заголовок оглавления»")

    # Пункт 36: оформление берётся из стилей шаблона — заголовки по полю
    # header_style, подписи таблиц и рисунков — из стилей «ДОК … Название».
    sections = es.sections(data)
    section = next(item for item in sections
                   if item.get("header_style") and item.get("header")
                   and str(item.get("number") or "")[:1].isdigit())
    subsection = next(sub for item in sections
                      for sub in item.get("subsections") or []
                      if sub.get("header_style") and sub.get("header"))
    section_paragraph = next(paragraph for paragraph in doc.paragraphs
                             if paragraph.text.strip()
                             == str(section["header"]).strip())
    subsection_paragraph = next(paragraph for paragraph in doc.paragraphs
                                if paragraph.text.strip()
                                == str(subsection["header"]).strip())
    check(section_paragraph.style.name == section["header_style"]
          and subsection_paragraph.style.name == subsection["header_style"],
          "стили заголовков взяты из header_style")
    table_caption = next(paragraph for paragraph in doc.paragraphs
                         if paragraph.text.startswith("Таблица 5.2 —"))
    figure_caption = next(paragraph for paragraph in doc.paragraphs
                          if paragraph.text.startswith("Рисунок 5."))
    check(table_caption.style.name == ea_docx.TABLE_CAPTION_STYLE
          and figure_caption.style.name == ea_docx.FIGURE_CAPTION_STYLE,
          "подписи таблицы и рисунка оформлены стилями «ДОК … Название»")
    label_run = next((run for run in table_caption.runs
                      if run.text == "Таблица"), None)
    check(label_run is not None
          and label_run._r.find(qn("w:rPr")) is not None
          and label_run._r.find(qn("w:rPr")).find(qn("w:spacing")) is not None,
          "надпись «Таблица» разрежена отдельно от названия")
    appendix_style = next((str(item.get("header_style") or "")
                           for item in sections
                           if ea_docx._is_appendix(item)
                           and item.get("header_style")), "")
    appendix_paragraph = next(paragraph for paragraph in doc.paragraphs
                              if paragraph.text.startswith("ПРИЛОЖЕНИЕ"))
    check(bool(appendix_style)
          and appendix_paragraph.style.name == appendix_style
          and appendix_paragraph.text.startswith("ПРИЛОЖЕНИЕ А."),
          "заголовок приложения: стиль из JSON и буква из номера")
    appendix_caption = next((paragraph for paragraph in doc.paragraphs
                             if paragraph.text.startswith("Таблица Б.")), None)
    check(appendix_caption is not None
          and appendix_caption.style.name
          == ea_docx.APPENDIX_TABLE_CAPTION_STYLE,
          "подпись таблицы приложения оформлена стилем «ПРИЛ …»")

    # Перекрестные ссылки: подписи — закладки, упоминания в тексте — REF.
    body_xml = doc.element.body.xml
    check(body_xml.count("<w:bookmarkStart") > 10
          and "REF Ref" in body_xml,
          "подписи таблиц и рисунков получили закладки и поля REF")
    table_caption = next(paragraph for paragraph in doc.paragraphs
                         if paragraph.text.startswith("Таблица 5.2 —"))
    check("bookmarkStart" in table_caption._p.xml
          and "RefT_5_2" in table_caption._p.xml,
          "закладка таблицы 5.2 находится в подписи")
    mention = next(paragraph for paragraph in doc.paragraphs
                   if "В таблице Таблица 5.1" in paragraph.text)
    check("REF RefT_5_1" in mention._p.xml,
          "упоминание таблицы 5.1 превращено в поле REF")

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
        # Пункт 8: таблицы набраны кеглем 10, как основной текст.
        sizes = {run.font.size.pt for row in match.rows
                 for cell in row.cells for paragraph in cell.paragraphs
                 for run in paragraph.runs if run.font.size}
        check(sizes <= {10},
              "таблицы отчёта набраны кеглем 10 (%s)" % (sizes or "стиль"))

        # Пункт 44: кегль заголовка берётся из стиля шаблона, а не из
        # фрагмента. «ДОК Заголовок 1» наследует 14 пт от Normal шаблона —
        # отчёт не должен переопределять Normal на 10 пт.
        styled_heading = next(paragraph for paragraph in doc.paragraphs
                              if paragraph.style.name
                              == "ДОК Заголовок вкл в содержание")
        heading_size = style_font_size(styled_heading.style)
        check(all(run.font.size is None for run in styled_heading.runs)
              and heading_size is not None and heading_size > 10,
              "кегль заголовка взят из стиля (%.0f пт), а не из фрагмента"
              % (heading_size or 0))

        # Пункт 44 (продолжение): абзацы основного текста получают стиль
        # «Обычный», а кегль берут из него, а не из фрагмента.
        body_paragraph = next(paragraph for paragraph in doc.paragraphs
                              if paragraph.style.name == "Normal"
                              and len(paragraph.text.strip()) > 40
                              and all(run.font.size is None
                                      for run in paragraph.runs))
        check(style_font_size(body_paragraph.style) == 12,
              "основной текст берёт кегль из стиля «Обычный» (12 пт)")

    check("text_style" in [key for key, _kind, _default
                           in sc.fields("Standard")],
          "у стандарта есть поле «Стиль текста»")
    check("toc_style" in [key for key, _kind, _default
                          in sc.fields("Standard")],
          "у стандарта есть поле «Стиль заголовка содержания»")
    check(ea_docx._paragraph_style(doc, "Обычный") is not None
          and ea_docx._paragraph_style(doc, "Обычный").name == "Normal",
          "русское имя «Обычный» находит стиль Normal")
    styled_data = copy.deepcopy(data)
    styled_data["text_style"] = "ДОК Текст"
    styled_data["toc_style"] = "ДОК Заголовок 1"
    styled_path = os.path.join(tempfile.mkdtemp(), "styled.docx")
    ea_docx.build(styled_data, styled_path, max_rows=1)
    styled_doc = Document(styled_path)
    styled_body = next(paragraph for paragraph in styled_doc.paragraphs
                       if paragraph.style.name == "ДОК Текст"
                       and len(paragraph.text.strip()) > 40)
    check(all(run.font.size is None for run in styled_body.runs)
          and style_font_size(styled_body.style) == 14,
          "стиль текста из реквизита применён к абзацам (14 пт)")
    styled_toc = next(paragraph for paragraph in styled_doc.paragraphs
                      if paragraph.text.strip() == "Содержание")
    check(styled_toc.style.name == "ДОК Заголовок 1",
          "стиль заголовка содержания из реквизита применён")

    # Пункт 29: двухуровневая шапка выводится двумя ярусами, а одинаковые
    # ячейки объединяются по горизонтали и вертикали.
    two_level = es.table_by_number(data, "5.10")
    header_rows = es.table_header_rows(two_level)
    check(len(header_rows) == 2
          and header_rows[0][:2] == ["Информационный сигнал"] * 2
          and header_rows[1][:2] == ["Наименование", "Статус"],
          "таблица 5.10 читается как двухуровневая шапка")
    two_table = next((item for item in doc.tables
                      if item.cell(0, 0).text == "Информационный сигнал"
                      and item.cell(1, 0).text == "Наименование"), None)
    check(two_table is not None, "таблица 5.10 выведена с двумя ярусами")
    if two_table is not None:
        xml = two_table._tbl.xml
        check(xml.count("<w:gridSpan") >= 2 and "<w:vMerge" in xml,
              "одинаковые ячейки шапки объединены")
        check(all(row._tr.find(qn("w:trPr")) is not None
                  and row._tr.find(qn("w:trPr")).find(qn("w:tblHeader"))
                  is not None for row in two_table.rows[:2]),
              "оба яруса шапки повторяются на новой странице")

    # Пункт 46: одинаковые значения строк данных объединяются так же, как
    # ячейки шапки, — по горизонтали и по вертикали.
    merge_doc = Document()
    ea_docx._setup(merge_doc)
    ea_docx._table(merge_doc, ["A", "B", "C"],
                   [["1", "1", "2"], ["1", "1", "2"], ["3", "3", "3"]])
    merged = merge_doc.tables[0]
    merge_xml = merged._tbl.xml
    check(merge_xml.count("<w:gridSpan") >= 2 and "<w:vMerge" in merge_xml,
          "одинаковые значения строк объединены по горизонтали и вертикали")
    check(merged.cell(1, 0).text == "1" and merged.cell(1, 2).text == "2"
          and len(merged.cell(1, 0).paragraphs) == 1,
          "текст объединённой ячейки не дублируется")
    check(merged.cell(1, 0)._tc is merged.cell(2, 1)._tc
          and merged.cell(1, 2)._tc is merged.cell(2, 2)._tc,
          "вертикальные объединения захватывают все одинаковые строки")

    # Пункт 46: ячейки без текста («-», «>>», «»») не объединяются.
    plain_doc = Document()
    ea_docx._setup(plain_doc)
    ea_docx._table(plain_doc, ["A", "B", "C"],
                   [["-", "-", ">>"], ["-", "-", ">>"],
                    ["«»", "«»", "—"]])
    plain_xml = plain_doc.tables[0]._tbl.xml
    check("<w:gridSpan" not in plain_xml and "<w:vMerge" not in plain_xml,
          "прочерки, стрелки и кавычки не объединяются")

    # Пункт 46: объединение отключается полем таблицы merge_cells.
    off_doc = Document()
    ea_docx._setup(off_doc)
    ea_docx._table(off_doc, ["A", "B", "C"],
                   [["1", "1", "2"], ["1", "1", "2"]], merge=False)
    off_xml = off_doc.tables[0]._tbl.xml
    check("<w:gridSpan" not in off_xml and "<w:vMerge" not in off_xml,
          "поле merge_cells=False отключает объединение")

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

    # Автоматическая ширина не должна выходить за поля страницы.
    from docx.shared import Emu
    for label, report in (("основной", doc), ("с шаблоном", with_template)):
        section = report.sections[-1]
        usable = Emu(section.page_width - section.left_margin
                     - section.right_margin).cm
        check(all(sum(column.width.cm for column in table.columns
                      if column.width) <= usable + 0.05
                  for table in report.tables),
              "таблицы (%s) вписаны в ширину текста %.1f см"
              % (label, usable))

    # Поле «Ширина колонок» задаёт жёсткую ширину в миллиметрах.
    fixed_data = copy.deepcopy(data)
    fixed_table = es.table_by_number(fixed_data, "5.2")
    fixed_headers = es.table_view(fixed_data, fixed_table)[0]
    fixed_table["colums_width"] = [25] * len(fixed_headers)
    fixed_path = os.path.join(tempfile.mkdtemp(), "fixed.docx")
    ea_docx.build(fixed_data, fixed_path, max_rows=1, toc=False)
    fixed_doc = Document(fixed_path)
    widths_table = next((item for item in fixed_doc.tables
                         if [cell.text for cell in item.rows[0].cells]
                         == fixed_headers), None)
    check(widths_table is not None
          and all(abs(column.width.cm - 2.5) < 0.01
                  for column in widths_table.columns)
          and all(abs(cell.width.cm - 2.5) < 0.01
                  for cell in widths_table.rows[0].cells),
          "заданные ширины колонок применены к колонкам и ячейкам")
    if widths_table is not None:
        props = widths_table._tbl.tblPr
        total = props.find(qn("w:tblW"))
        layout = props.find(qn("w:tblLayout"))
        expected = round(25 * len(fixed_headers) * 1440.0 / 25.4)
        check(total is not None and total.get(qn("w:type")) == "dxa"
              and abs(int(total.get(qn("w:w"))) - expected) <= 1
              and layout is not None
              and layout.get(qn("w:type")) == "fixed",
              "общая ширина таблицы зафиксирована в XML")

    # Формат и ориентация рисунка создают отдельную секцию и восстанавливают
    # параметры страницы после подписи.
    from docx.enum.section import WD_ORIENT
    page_data = copy.deepcopy(data)
    figure = next(es.iter_figures(page_data))
    figure["format"] = "A3"
    figure["orientation"] = "альбомная"
    page_path = os.path.join(tempfile.mkdtemp(), "page.docx")
    ea_docx.build(page_data, page_path, max_rows=1, toc=False)
    page_doc = Document(page_path)
    check(len(page_doc.sections) >= 3, "рисунок с форматом получил секцию")
    if len(page_doc.sections) >= 3:
        middle = page_doc.sections[1]
        last = page_doc.sections[-1]
        check(abs(middle.page_width.cm - 42.0) < 0.1
              and abs(middle.page_height.cm - 29.7) < 0.1
              and middle.orientation == WD_ORIENT.LANDSCAPE,
              "секция рисунка: A3 альбомная")
        check(last.orientation != WD_ORIENT.LANDSCAPE
              and last.page_width.cm < middle.page_width.cm,
              "после рисунка параметры страницы восстановлены")

    # Готовый PNG вставляется без рендера схемы.
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        image_data = copy.deepcopy(data)
        for figure in es.iter_figures(image_data):
            figure["scheme"] = ""
        png_dir = tempfile.mkdtemp()
        png_path = os.path.join(png_dir, "figure.png")
        Image.new("RGB", (120, 60), "white").save(png_path)
        next(es.iter_figures(image_data))["scheme"] = png_path
        image_path = os.path.join(png_dir, "image.docx")
        ea_docx.build(image_data, image_path, toc=False, max_rows=1)
        image_doc = Document(image_path)
        check(len(image_doc.inline_shapes) == 1,
              "рисунок PNG вставлен в документ")

    # Причины неудачи больше не пропадают молча.
    bad_data = copy.deepcopy(data)
    for figure in es.iter_figures(bad_data):
        figure["scheme"] = ""
    bad_figure = next(es.iter_figures(bad_data))
    bad_figure["scheme"] = "нет-такого-файла.json"
    bad_path = os.path.join(tempfile.mkdtemp(), "bad.docx")
    bad_counters = ea_docx.build(bad_data, bad_path, toc=False, max_rows=1)
    check(bad_counters["рисунки"] == 0
          and any("файл не найден" in item
                  for item in bad_counters["ошибки_рисунков"]),
          "ошибка вставки рисунка сообщается вызывающей стороне")


def test_table_style():
    """Пункт 37: поле «Стиль таблицы» и его применение при выгрузке."""
    print("3е. стиль таблицы из поля table_style")
    try:
        from docx import Document
    except ImportError:
        print("  --   python-docx нет: проверка пропущена")
        return
    keys = [key for key, _kind, _default in sc.fields("Table")]
    check("table_style" in keys, "у таблицы есть поле «Стиль таблицы»")
    check("merge_cells" in keys, "у таблицы есть поле «Объединять ячейки»")
    check(ea_docx._merge_enabled({}) is True
          and ea_docx._merge_enabled({"merge_cells": False}) is False
          and ea_docx._merge_enabled({"merge_cells": "0"}) is False,
          "объединение включено по умолчанию и выключается полем")
    template = ea_docx.template_path(os.path.dirname(REFERENCE))
    if not template:
        print("  --   template.docx нет: проверка стиля пропущена")
        return
    doc = Document(template)
    ea_docx._table(doc, ["Параметр", "Значение"], [["а", "б"]],
                   style="Таблица_ГОСТ")
    check(doc.tables[-1].style.name == "Таблица_ГОСТ",
          "стиль таблицы из поля применён")
    ea_docx._table(doc, ["Параметр", "Значение"], [["а", "б"]],
                   style="Нет такого стиля")
    check(doc.tables[-1].style.name == "Table Grid",
          "неизвестный стиль заменён на «Table Grid»")


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
        dialog.vars["title_page"].set("title_page.docx")
        dialog.vars["text_style"].set("ДОК Текст")
        dialog.vars["toc_style"].set("Заголовок оглавления")
        dialog.split_var.set(True)
        dialog.save()
        saved = es.load(path)
        check(saved["code"] == "НОВЫЙ ШИФР", "шифр сохранён")
        check(saved["name"] == "Новое наименование",
              "наименование сохранено")
        check(saved["property"] == "ПАО «Тест»", "принадлежность сохранена")
        check(saved["date"] == "01.01.2027", "дата сохранена")
        check(saved["title_page"] == "title_page.docx",
              "ссылка на титульный DOCX сохранена")
        check(saved["text_style"] == "ДОК Текст",
              "стиль текста сохранён в реквизитах")
        check(saved["toc_style"] == "Заголовок оглавления",
              "стиль заголовка содержания сохранён в реквизитах")
        check(saved.get("description_split") is True,
              "флаг разделённого описания сохранён в реквизитах")
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
            self.blocks = []
            self.kits = []

        def _place_cabinet(self, record):
            self.placed.append(record)

        def _place_functional_block(self, entry):
            self.blocks.append(entry)

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

        fbs = [iid for iid, node in window._nodes.items()
               if node[0] == "fb_entry"]
        check(len(fbs) > 0, "записей ФБ в окне стандарта: %d" % len(fbs))
        if fbs:
            window.tree.selection_set(fbs[0])
            window._show()
            root.update()
            check(str(window.btn_fb["state"]) == "normal",
                  "«ФБ → на схему» доступна для записи каталога")
            window.place_functional_block()
            check(len(app.blocks) == 1
                  and app.blocks[0].get("cabinet"),
                  "функциональный блок размещён на схеме")

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
        #-structure2: в таблице функций есть колонка «Параметров».
        check(len(window.table["columns"]) == 6,
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
        check(dialog.split_descriptions.get(),
              "в диалоге включено разделение описания ИЭУ")
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

        # Пункт 9: у таблиц в дереве видны их колонки.
        table_node = next(key for key, node in window._nodes.items()
                          if node[0] == "table"
                          and window.tree.get_children(key))
        columns = window.tree.get_children(table_node)
        check(all(window._nodes[column][0] == "table_column"
                  for column in columns),
              "у таблицы в дереве показаны колонки (%d)" % len(columns))
        table_item = window._nodes[table_node][1]
        headers = es.table_headers(window.data, table_item)
        expected = ["• %s" % (str(header or "").strip()
                              or "колонка %d" % (index + 1))
                    for index, header in enumerate(headers)]
        check([window.tree.item(column, "text") for column in columns]
              == expected,
              "подписи колонок совпадают с шапкой таблицы")
        window.tree.selection_set(columns[0])
        root.update()
        check("колонка" in window.caption.cget("text").lower()
              and len(window._grid_rows) > 0,
              "выбор колонки открывает сетку таблицы")
        window.tree.selection_set(table_node)
        root.update()

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
        check("text_style" in window.vars,
              "в реквизитах есть поле «Стиль текста»")
        check("toc_style" in window.vars,
              "в реквизитах есть поле «Стиль заголовка содержания»")
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
        labels = [entry[0] for entry in items if entry]
        check("Добавить раздел…" in labels
              and any("Сформировать отчёт" in label for label in labels),
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

        # Пункт 15: рисунок добавляется из контекстного меню раздела.
        original_ask = ea_editor.simpledialog.askstring
        ea_editor.simpledialog.askstring = lambda *a, **k: "Рисунок из редактора"
        try:
            window._add_figure(section_iid)
        finally:
            ea_editor.simpledialog.askstring = original_ask
        root.update()
        check(len(section["figures"]) == 1
              and section["figures"][-1]["name"] == "Рисунок из редактора",
              "рисунок добавлен в раздел")
        check(window._find_iid(section["figures"][-1]) is not None,
              "новый рисунок отображается в дереве")
        section_iid = window._find_iid(section)

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
        check("table_style" in window.vars,
              "в панели таблицы есть поле «Стиль таблицы»")
        window.vars["table_style"].set("Таблица_ГОСТ")
        window._apply_pending()
        check(target_table.get("table_style") == "Таблица_ГОСТ",
              "стиль таблицы сохраняется в поле")
        window.vars["table_style"].set("")
        window._apply_pending()
        check("table_style" not in target_table,
              "пустой стиль убирает поле из таблицы")
        check("merge_cells" in window.vars,
              "в панели таблицы есть флажок объединения ячеек")
        window.vars["merge_cells"].set(False)
        window._apply_pending()
        check(target_table.get("merge_cells") is False,
              "флажок объединения сохраняется в таблице")
        window.vars["merge_cells"].set(True)
        window._apply_pending()
        check(target_table.get("merge_cells") is True,
              "объединение включается обратно")

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
        labels = [entry[0] for entry in menu if entry]
        check(any("типовой комплект" in label for label in labels),
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
        labels = [entry[0] for entry in menu if entry]
        check(any("типовой шкаф" in label for label in labels),
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


def test_editor_drag_reorder():
    """Перетаскивание мышью меняет порядок разделов, таблиц и рисунков."""
    print("10б. перенос узлов мышью в редакторе стандарта")
    if tk is None:
        print("  --   tkinter нет: редактор не проверяется")
        return
    try:
        from types import SimpleNamespace
        import ea_editor
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    window = None
    try:
        window = ea_editor.show(path, root)
        # Bbox узлов дерева доступен только для реально видимых строк.
        root.deiconify()
        root.geometry("1600x1200")
        window.geometry("1500x1100")
        root.update()

        def expand_all(parent=""):
            for iid in window.tree.get_children(parent):
                window.tree.item(iid, open=True)
                expand_all(iid)

        def by_kind(kind):
            return [iid for iid, node in window._nodes.items()
                    if window._node_kind(iid) == kind]

        def children_of_kind(iid, kind):
            return [child for child in window.tree.get_children(iid)
                    if window._node_kind(child) == kind]

        def drag(source, target, where="before"):
            expand_all()
            window.tree.see(source)
            window.tree.see(target)
            root.update()
            sbox = window.tree.bbox(source)
            box = window.tree.bbox(target)
            if not sbox or not box:
                raise ValueError("узел не виден для перетаскивания")
            start = SimpleNamespace(x=sbox[0] + sbox[2] / 2.0,
                                    y=sbox[1] + sbox[3] / 2.0)
            part = 0.2 if where == "before" else 0.8
            event = SimpleNamespace(x=box[0] + box[2] / 2.0,
                                    y=box[1] + box[3] * part)
            window._on_drag_start(start)
            window._on_drag_motion(event)
            window._on_drag_end(event)
            root.update()
            expand_all()

        sections = by_kind("section")
        check(len(sections) > 1, "в стандарте несколько разделов для переноса")
        before = list(window.data["sections"])
        drag(sections[1], sections[0])
        after = window.data["sections"]
        check(after[0] is before[1] and after[1] is before[0],
              "раздел передвинут мышью перед другим разделом")

        sec_iid = next(iid for iid in by_kind("section")
                       if len(children_of_kind(iid, "subsection")) > 1)
        subs = children_of_kind(sec_iid, "subsection")
        container = window._nodes[sec_iid][2]
        before = list(container["subsections"])
        drag(subs[1], subs[0])
        after = container["subsections"]
        check(after[0] is before[1] and after[1] is before[0],
              "подраздел передвинут мышью внутри раздела")

        for kind, key, word in (("table", "tables", "таблица"),
                                ("figure", "figures", "рисунок")):
            parent = next(iid for iid in list(window._nodes)
                          if len(children_of_kind(iid, kind)) > 1)
            items = children_of_kind(parent, kind)
            container = window._container_for_iid(items[0])
            before = list(container[key])
            drag(items[1], items[0])
            after = container[key]
            check(after[0] is before[1] and after[1] is before[0],
                  "%s передвинут мышью внутри контейнера" % word)

        # Пункт 21: рисунок можно поставить над таблицей и наоборот.
        import ea_structure as st

        def containers(data):
            for section in data.get("sections") or []:
                yield section
                for sub in section.get("subsections") or []:
                    yield sub
                    for clause in sub.get("clauses") or []:
                        yield clause
                for clause in section.get("clauses") or []:
                    yield clause

        compact = next(item for item in containers(window.data)
                       if len(item.get("tables") or []) == 1
                       and not (item.get("figures") or []))
        figure_item = st.new_figure(window.data, compact, name="Схема")
        st.add(compact.setdefault("figures", []), figure_item)
        window._fill_tree()
        root.update()
        table_item = compact["tables"][0]
        drag(window._find_iid(figure_item), window._find_iid(table_item))
        parent_iid = window._find_iid(compact)
        order = window.tree.get_children(parent_iid)
        check(order.index(window._find_iid(figure_item))
              < order.index(window._find_iid(table_item)),
              "рисунок перенесён мышью над таблицей")
        check(all("order" in item for item in
                  list(compact.get("tables") or [])
                  + list(compact.get("figures") or [])),
              "у блоков контейнера появился общий порядок")
        drag(window._find_iid(table_item), window._find_iid(figure_item))
        parent_iid = window._find_iid(compact)
        order = window.tree.get_children(parent_iid)
        check(order.index(window._find_iid(table_item))
              < order.index(window._find_iid(figure_item)),
              "таблица перенесена мышью над рисунком")

        # Пункт 26: пункты и подпункты в общем порядке с блоками.
        mixed_section = st.new_section(window.data, header="Тест 26")
        st.add(window.data.setdefault("sections", []), mixed_section)
        mixed_table = st.new_table(window.data,
                                   {"name": "Тест 26", "headers": ["П"]})
        mixed_clause = st.new_clause(window.data, mixed_section, number="99.1")
        mixed_clause["content"] = "Тестовый пункт"
        st.add(mixed_section.setdefault("tables", []), mixed_table)
        st.add(mixed_section.setdefault("clauses", []), mixed_clause)
        window._fill_tree()
        root.update()
        drag(window._find_iid(mixed_clause), window._find_iid(mixed_table))
        parent_iid = window._find_iid(mixed_section)
        order = window.tree.get_children(parent_iid)
        check(order.index(window._find_iid(mixed_clause))
              < order.index(window._find_iid(mixed_table)),
              "пункт перенесён мышью над таблицей")
        check(all("order" in item for item in
                  list(mixed_section.get("clauses") or [])
                  + list(mixed_section.get("tables") or [])
                  + list(mixed_section.get("figures") or [])),
              "у пунктов и блоков контейнера общий порядок")
        drag(window._find_iid(mixed_table), window._find_iid(mixed_clause))
        parent_iid = window._find_iid(mixed_section)
        order = window.tree.get_children(parent_iid)
        check(order.index(window._find_iid(mixed_table))
              < order.index(window._find_iid(mixed_clause)),
              "таблица перенесена мышью над пунктом")

        mixed_sub = {"number": "99.1.1", "content": "Тестовый подпункт",
                     "tables": [], "figures": []}
        mixed_clause.setdefault("subclauses", []).append(mixed_sub)
        sub_table = st.new_table(window.data,
                                 {"name": "Тест 26.1", "headers": ["П"]})
        st.add(mixed_clause.setdefault("tables", []), sub_table)
        window._fill_tree()
        root.update()
        check(window._find_iid(mixed_sub) is not None,
              "подпункт показан в дереве редактора")
        drag(window._find_iid(mixed_sub), window._find_iid(sub_table))
        order = window.tree.get_children(window._find_iid(mixed_clause))
        check(order.index(window._find_iid(mixed_sub))
              < order.index(window._find_iid(sub_table)),
              "подпункт перенесён мышью над таблицей")
    except Exception as exc:                      # noqa: BLE001
        check(False, "перетаскивание мышью: %s" % exc)
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


def test_kit_identity():
    """Пункт 28: идентичные комплекты, перенос и замена у шкафа."""
    print("10в. идентичные комплекты и перепривязка таблиц")
    if tk is None:
        print("  --   tkinter нет: проверка пропущена")
        return
    try:
        import ea_editor
        import ea_structure as st
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    window = None
    try:
        window = ea_editor.show(path, root)
        data = window.data
        cab_a = st.new_cabinet(data, cypher="ШЭТ 900-1", name="Шкаф A")
        cab_b = st.new_cabinet(data, cypher="ШЭТ 900-2", name="Шкаф B")
        st.add(data.setdefault("cabinets", []), cab_a)
        st.add(data["cabinets"], cab_b)
        kit_a1 = st.new_kit(data, cab_a)
        kit_a2 = st.new_kit(data, cab_a)
        kit_a1["identical"] = "группа 900"
        kit_a2["identical"] = "группа 900"
        st.add(cab_a["kits"], kit_a1)
        st.add(cab_a["kits"], kit_a2)
        table = st.new_table(data, {
            "name": "Входные аналоговые измерения шкафа ШЭТ 900-1",
            "cabinet": "ШЭТ 900-1", "kind": "analog_inputs"})
        st.add(data["sections"][0].setdefault("tables", []), table)
        window._fill_tree()
        root.update()

        original_confirm = ea_editor.messagebox.askyesno
        original_warning = ea_editor.messagebox.showwarning
        warnings = []
        ea_editor.messagebox.askyesno = lambda *args, **kwargs: True
        ea_editor.messagebox.showwarning = lambda *args, **kwargs: \
            warnings.append(args)
        try:
            # Удаление первого комплекта: заменяет идентичный того же шкафа.
            window._delete_node(window._find_iid(kit_a1))
            root.update()
        finally:
            ea_editor.messagebox.askyesno = original_confirm
            ea_editor.messagebox.showwarning = original_warning
        check(not warnings
              and not any(value is kit_a1 for value in cab_a["kits"])
              and cab_a["kits"][0] is kit_a2
              and table["cabinet"] == "ШЭТ 900-1",
              "первый комплект удалён, таблицы остались на шкафу")

        # Перенос первого комплекта в другой шкаф с перепривязкой таблиц.
        original_choose = window._choose_cabinet
        window._choose_cabinet = lambda *args, **kwargs: cab_b
        ea_editor.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            window._move_kit(window._find_iid(kit_a2))
            root.update()
        finally:
            window._choose_cabinet = original_choose
            ea_editor.messagebox.askyesno = original_confirm
        check(cab_a["kits"] == [] and cab_b["kits"] == [kit_a2]
              and table["cabinet"] == "ШЭТ 900-2",
              "комплект перенесён, таблицы привязаны к новому шкафу")

        # Копия комплекта сохраняет группу «Идентичны».
        window._duplicate_kit(window._find_iid(kit_a2))
        root.update()
        copy = cab_b["kits"][-1]
        check(copy is not kit_a2 and copy["identical"] == "группа 900"
              and copy["number"] == 2,
              "копия комплекта сохранила группу «Идентичны»")
    except Exception as exc:                      # noqa: BLE001
        check(False, "идентичные комплекты: %s" % exc)
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


def test_editor_report():
    """Пункт 30: пункт «Сформировать отчёт» в дереве редактора."""
    print("10г. отчёт из дерева стандарта")
    if tk is None:
        print("  --   tkinter нет: проверка пропущена")
        return
    try:
        import time
        import ea_editor
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    window = None
    try:
        window = ea_editor.show(path, root)
        root.update()
        cabinet_iid = next(iid for iid, node in window._nodes.items()
                           if node[0] == "cabinet")
        labels = [entry[0] for entry in
                  window._menu_items(cabinet_iid,
                                     window._nodes[cabinet_iid]) if entry]
        check("Сформировать отчёт (DOCX)…" in labels,
              "в меню шкафа есть формирование отчёта")
        check([item["class"] for item in
               window._report_targets([cabinet_iid])] == ["Cabinet"],
              "шкаф превращается в элемент отчёта")

        table_iid = next(iid for iid, node in window._nodes.items()
                         if node[0] == "table")
        check([item["class"] for item in
               window._report_targets([table_iid])] == ["Table"],
              "таблица превращается в элемент отчёта")
        function_iid = next(iid for iid, node in window._nodes.items()
                            if node[0] == "function")
        check([item["class"] for item in
               window._report_targets([function_iid])] == ["Function"],
              "функция превращается в элемент отчёта")

        cabinets = [iid for iid, node in window._nodes.items()
                    if node[0] == "cabinet"][:2]
        group = [entry[0] for entry in window._group_menu(cabinets)
                 if entry]
        check(any("Сформировать отчёт по выделенному" in label
                  for label in group),
              "у выделенной группы есть общий отчёт")
        check(len(window._report_targets(cabinets)) == 2,
              "в групповой отчёт попадают оба элемента")

        out = os.path.join(folder, "element.docx")
        original_save = ea_editor.filedialog.asksaveasfilename
        original_info = ea_editor.messagebox.showinfo
        original_error = ea_editor.messagebox.showerror
        errors = []
        finished = []
        ea_editor.filedialog.asksaveasfilename = lambda *a, **k: out
        # Отчёт строится в фоне: файл появляется раньше, чем дописан, поэтому
        # ждём не файла, а итогового сообщения «Отчёт сохранён».
        ea_editor.messagebox.showinfo = lambda *a, **k: finished.append(a)
        ea_editor.messagebox.showerror = lambda *a, **k: errors.append(a)
        try:
            window._report_nodes([function_iid])
            deadline = time.time() + 60
            while not finished and not errors and time.time() < deadline:
                root.update()
                time.sleep(0.05)
            root.update()
        finally:
            ea_editor.filedialog.asksaveasfilename = original_save
            ea_editor.messagebox.showinfo = original_info
            ea_editor.messagebox.showerror = original_error
        if errors:
            print("   ошибки отчёта: %s" % (errors,))
        check(bool(finished) and not errors and os.path.isfile(out)
              and os.path.getsize(out) > 10000,
              "отчёт из редактора записан в DOCX")
    except Exception as exc:                      # noqa: BLE001
        check(False, "отчёт из редактора: %s" % exc)
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


def test_editor_reference():
    """Пункт 31: метка ссылки из контекстного меню дерева редактора."""
    print("10д. метки перекрёстных ссылок в редакторе")
    if tk is None:
        print("  --   tkinter нет: редактор не проверяется")
        return
    try:
        import ea_editor
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    window = None
    original_ask = ea_editor.simpledialog.askstring
    original_info = ea_editor.messagebox.showinfo
    original_error = ea_editor.messagebox.showerror
    try:
        window = ea_editor.show(path, root)
        root.update()
        nodes = {}
        for iid, node in window._nodes.items():
            if node[0] == "text" and node[1] in ("section", "subsection"):
                nodes.setdefault(node[1], (iid, node[2]))
            elif node[0] in ("table", "figure"):
                nodes.setdefault(node[0], (iid, node[1]))
        for kind in ("section", "subsection", "table", "figure"):
            iid = nodes[kind][0]
            labels = [entry[0] for entry in
                      window._menu_items(iid, window._nodes[iid]) if entry]
            check("Вставить ссылку…" in labels,
                  "в меню %s есть вставка ссылки" % kind)

        iid, item = nodes["table"]
        entry = next(entry for entry in
                     window._menu_items(iid, window._nodes[iid])
                     if entry and entry[0] == "Вставить ссылку…")
        ea_editor.simpledialog.askstring = lambda *a, **k: "метка таблицы"
        ea_editor.messagebox.showinfo = lambda *a, **k: None
        entry[1]()
        root.update()
        check(item.get("ref") == "метка таблицы",
              "метка записана в поле ref таблицы")
        window.save()
        saved = es.load(path)
        check(es.table_by_number(saved, item["number"]).get("ref")
              == "метка таблицы",
              "метка сохранилась в JSON")

        # Та же метка у другого объекта не перезаписывает первую.
        figure_iid, figure = nodes["figure"]
        figure_iid = window._find_iid(figure)
        errors = []
        ea_editor.simpledialog.askstring = lambda *a, **k: "метка таблицы"
        ea_editor.messagebox.showerror = lambda *a, **k: errors.append(a)
        window._insert_reference(figure_iid)
        root.update()
        check(not figure.get("ref") and bool(errors),
              "повторная метка отклонена")

        # Пустой ввод снимает метку.
        table_iid = window._find_iid(item)
        ea_editor.simpledialog.askstring = lambda *a, **k: ""
        window._insert_reference(table_iid)
        root.update()
        check("ref" not in item, "пустой ввод удаляет метку")
    except Exception as exc:                      # noqa: BLE001
        check(False, "метки в редакторе: %s" % exc)
    finally:
        ea_editor.simpledialog.askstring = original_ask
        ea_editor.messagebox.showinfo = original_info
        ea_editor.messagebox.showerror = original_error
        if window is not None:
            window.destroy()
        root.destroy()


def test_editor_update_standard():
    """Пункт 33: флаг в реквизитах и кнопка обновления стандарта."""
    print("10е. обновление стандарта в редакторе")
    if tk is None:
        print("  --   tkinter нет: редактор не проверяется")
        return
    try:
        import ea_editor
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    window = None
    original_info = ea_editor.messagebox.showinfo
    original_error = ea_editor.messagebox.showerror
    ea_editor.messagebox.showinfo = lambda *a, **k: None
    ea_editor.messagebox.showerror = lambda *a, **k: None
    try:
        window = ea_editor.show(path, root)
        root.update()
        check(hasattr(window, "update_standard")
              and hasattr(window, "split_var"),
              "в редакторе есть обновление и флаг в реквизитах")
        check(not window.split_var.get(),
              "старый стандарт открыт без разделения описания")
        window.split_var.set(True)
        window.update_standard()
        root.update()
        kits = [table for table in es.iter_tables(window.data)
                if table.get("description_part") == "kit"]
        check(window.data.get("description_split") is True and len(kits) == 4,
              "обновление создало описания ИЭУ: %d" % len(kits))
        # Переименование копии в «Описание ИЭУ…» больше не блокируется.
        kit_iid = window._find_iid(kits[0])
        window.tree.selection_set(kit_iid)
        root.update()
        window.vars["name"].set("Описание ИЭУ1 (проверка) в составе шкафа")
        check(window._apply_pending()
              and "Описание ИЭУ1" in kits[0]["name"],
              "таблица описания ИЭУ переименовывается и сохраняется")
        window.save()
        saved = es.load(path)
        check(saved.get("description_split") is True
              and len([table for table in es.iter_tables(saved)
                       if table.get("description_part") == "kit"]) == 4,
              "обновлённый стандарт записан в JSON")
        before = len([table for table in es.iter_tables(saved)
                      if table.get("description_part") == "kit"])
        window.update_standard()
        root.update()
        after = len([table for table in es.iter_tables(window.data)
                     if table.get("description_part") == "kit"])
        check(after == before, "повторное обновление не дублирует таблицы")
    except Exception as exc:                      # noqa: BLE001
        check(False, "обновление стандарта: %s" % exc)
    finally:
        ea_editor.messagebox.showinfo = original_info
        ea_editor.messagebox.showerror = original_error
        if window is not None:
            window.destroy()
        root.destroy()


def test_editor_renumber():
    """Пункт 35: кнопка «Перенумеровать» в редакторе стандарта."""
    print("10ж. перенумерация структуры в редакторе")
    if tk is None:
        print("  --   tkinter нет: редактор не проверяется")
        return
    try:
        import ea_editor
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(es.load(REFERENCE), path)
    window = None
    original_error = ea_editor.messagebox.showerror
    ea_editor.messagebox.showerror = lambda *a, **k: None
    try:
        window = ea_editor.show(path, root)
        root.update()
        check(hasattr(window, "renumber_structure"),
              "в редакторе есть перенумерация структуры")
        section = next(item for item in window.data["sections"]
                       if any(sub.get("clauses")
                              for sub in item.get("subsections") or []))
        sub = next(item for item in section["subsections"]
                   if item.get("clauses"))
        clause = sub["clauses"][0]
        section["number"] = "99"
        sub["number"] = "99.9"
        clause["number"] = "99.9.9"
        window.renumber_structure()
        root.update()
        position = (section["subsections"].index(sub)
                    + len(section.get("clauses") or []) + 1)
        expected_sub = "%s.%d" % (section["number"], position)
        check(section["number"].isdigit()
              and sub["number"] == expected_sub
              and clause["number"] == expected_sub + ".1",
              "номера приведены к структуре дерева")
        table = next(item for item in es.iter_tables(window.data)
                     if str(item.get("number") or "").startswith("5."))
        table["number"] = "99.99"
        table["reference"] = "Таблица 99.99"
        window.renumber_structure()
        root.update()
        check(str(table["number"]).startswith("5.")
              and table["reference"] == "Таблица %s" % table["number"],
              "кнопка перенумерует таблицы и их ссылки")
        iid = window._find_iid(section)
        check(iid is not None
              and window.tree.item(iid, "text").startswith(
                  section["number"] + " "),
              "дерево показывает новый номер раздела")
        check("Перенумеровано" in window.status.cget("text"),
              "в статусе отчёта о перенумерации")
    except Exception as exc:                      # noqa: BLE001
        check(False, "перенумерация в редакторе: %s" % exc)
    finally:
        ea_editor.messagebox.showerror = original_error
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
          and ied.get("description") == "" and ied.get("scheme") == ""
          and len(ied) == 13,
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

    # Пункт 19: дублирование узлов функциональной модели.
    import ea_schema as sc
    block = sc.new_node("FunctionBlock", name="Блок")
    function = sc.new_node("Function", name="Функция")
    slot = sc.new_node("Input", name="Вход", id="in1")
    setting = sc.new_node("Setting", name="Уставка")
    parameter = sc.new_node("Parameter", name="Параметр")
    st.add(block["functions"], function)
    st.add(function["inputs"], slot)
    st.add(function["settings"], setting)
    st.add(function["parameters"], parameter)
    st.add(ied["function_blocks"], block)

    block_copy = st.duplicate_node(block, ied["function_blocks"])
    check(block_copy is not block and block_copy["name"] == "Блок (копия)"
          and len(block_copy["functions"]) == 1
          and block_copy["functions"][0] is not function,
          "блок функций скопирован вместе с функциями")
    function_copy = st.duplicate_node(function, block["functions"])
    check(function_copy["name"] == "Функция (копия)"
          and function_copy["inputs"][0]["name"] == "Вход",
          "функция скопирована со своими слотами")
    slot_copy = st.duplicate_node(slot, function["inputs"])
    check(slot_copy["name"] == "Вход (копия)" and slot_copy["id"] != "in1",
          "вход скопирован с новым id")
    setting_copy = st.duplicate_node(setting, function["settings"])
    parameter_copy = st.duplicate_node(parameter, function["parameters"])
    check(setting_copy["name"] == "Уставка (копия)"
          and parameter_copy["name"] == "Параметр (копия)",
          "уставка и параметр скопированы")
    second_copy = st.duplicate_node(block, ied["function_blocks"])
    check(second_copy["name"] == "Блок (копия 2)",
          "повторная копия получает номер")

    # Пункт 21: общий порядок таблиц и рисунков в контейнере.
    blocks = {"tables": [], "figures": []}
    table_one = st.new_table(clone, {"name": "Первая", "headers": ["П"]})
    table_two = st.new_table(clone, {"name": "Вторая", "headers": ["П"]})
    figure = st.new_figure(clone, blocks, name="Схема")
    st.add(blocks["tables"], table_one)
    st.add(blocks["tables"], table_two)
    st.add(blocks["figures"], figure)
    check([kind for kind, _item in st.ordered_blocks(blocks)]
          == ["table", "table", "figure"],
          "без order порядок прежний: таблицы, затем рисунки")
    st.move_block("figure", figure, blocks["figures"], blocks,
                  anchor=table_one, after=False)
    check([item for _kind, item in st.ordered_blocks(blocks)]
          == [figure, table_one, table_two],
          "рисунок перенесён над таблицей")
    st.move_block("table", table_two, blocks["tables"], blocks,
                  anchor=figure, after=False)
    check([item for _kind, item in st.ordered_blocks(blocks)]
          == [table_two, figure, table_one],
          "таблица перенесена над рисунком")
    check(blocks["tables"] == [table_two, table_one]
          and blocks["figures"] == [figure],
          "списки таблиц и рисунков переписаны в общем порядке")

    # Пункт 26: пункты и подпункты в общем порядке с таблицами/рисунками.
    mixed = {"tables": [], "figures": [], "clauses": []}
    first_table = st.new_table(clone, {"name": "Т1", "headers": ["П"]})
    mixed_figure = st.new_figure(clone, mixed, name="Рисунок")
    mixed_clause = st.new_clause(clone, mixed, number="1.1")
    mixed_clause["content"] = "Пункт"
    mixed_sub = {"number": "1.1.1", "content": "Подпункт",
                 "tables": [], "figures": []}
    clause_table = st.new_table(clone, {"name": "Т2", "headers": ["П"]})
    mixed_clause["subclauses"].append(mixed_sub)
    st.add(mixed_clause["tables"], clause_table)
    st.add(mixed["tables"], first_table)
    st.add(mixed["figures"], mixed_figure)
    st.add(mixed["clauses"], mixed_clause)
    check([kind for kind, _item in st.ordered_items(mixed)]
          == ["table", "figure", "clause"],
          "без order пункты идут после таблиц и рисунков")
    st.move_item("clause", mixed_clause, mixed["clauses"], mixed,
                 anchor=first_table, after=False)
    check([item for _kind, item in st.ordered_items(mixed)]
          == [mixed_clause, first_table, mixed_figure],
          "пункт перенесён над таблицей и рисунком")
    st.move_item("table", first_table, mixed["tables"], mixed,
                 anchor=mixed_figure, after=True)
    check([item for _kind, item in st.ordered_items(mixed)]
          == [mixed_clause, mixed_figure, first_table],
          "таблица перенесена под рисунок")
    st.move_item("subclause", mixed_sub, mixed_clause["subclauses"],
                 mixed_clause, anchor=clause_table, after=False)
    check([item for _kind, item in st.ordered_items(mixed_clause)]
          == [mixed_sub, clause_table],
          "подпункт перенесён над таблицей пункта")
    try:
        st.move_item("clause", mixed_clause, mixed["clauses"], mixed_clause)
    except st.StructureError:
        check(True, "пункт нельзя вложить в пункт")
    else:
        check(False, "пункт нельзя вложить в пункт")

    # Пункт 28: идентичные комплекты и перенос между шкафами.
    cab_a = st.new_cabinet(clone, cypher="ШЭТ 900-1", name="Шкаф A")
    cab_b = st.new_cabinet(clone, cypher="ШЭТ 900-2", name="Шкаф B")
    st.add(clone["cabinets"], cab_a)
    st.add(clone["cabinets"], cab_b)
    kit_a1 = st.new_kit(clone, cab_a)
    kit_a2 = st.new_kit(clone, cab_a)
    kit_a1["identical"] = "группа 900"
    kit_a2["identical"] = "группа 900"
    st.add(cab_a["kits"], kit_a1)
    st.add(cab_a["kits"], kit_a2)
    check(kit_a1["identical"] == kit_a2["identical"],
          "комплекты можно пометить одной группой «Идентичны»")
    table = st.new_table(clone, {
        "name": "Входные аналоговые измерения шкафа ШЭТ 900-1",
        "cabinet": "ШЭТ 900-1", "kind": "analog_inputs"})
    st.add(section["tables"], table)
    check(st.kit_feeds_tables(clone, kit_a1, cab_a),
          "первый комплект шкафа питает таблицы")
    check(not st.kit_feeds_tables(clone, kit_a2, cab_a),
          "второй комплект таблицы не питает")
    repl_cabinet, repl_kit = st.identical_replacement(clone, kit_a1, cab_a)
    check(repl_cabinet is cab_a and repl_kit is kit_a2,
          "найдена замена того же шкафа")
    st.promote_kit(cab_a, kit_a2)
    check(cab_a["kits"][0] is kit_a2, "идентичный комплект стал первым")
    st.move_kit(kit_a1, cab_a, cab_b)
    check(cab_a["kits"] == [kit_a2] and cab_b["kits"] == [kit_a1]
          and kit_a1["number"] == 1,
          "комплект перенесён в другой шкаф с новым номером")
    check(kit_a1["identical"] == "группа 900",
          "группа «Идентичны» сохранена при переносе")
    copy = st.copy_kit(kit_a1, cab_b)
    check(copy is not kit_a1 and copy["identical"] == kit_a1["identical"]
          and copy["number"] == 2 and "копия" in copy["description"],
          "копия комплекта сохраняет группу «Идентичны»")


def test_renumber_document():
    """Пункт 35: перенумерация разделов, подразделов, пунктов, подпунктов."""
    print("11а. перенумерация структуры документа")
    import ea_new_standard as ns

    doc = {"sections": [
        {"number": "", "header": "Введение", "clauses": [],
         "tables": [{"number": "9.9", "reference": "Таблица 9.9",
                     "name": "Без номера раздела"}],
         "subsections": []},
        {"number": "7", "header": "Область применения",
         "header_style": "ДОК Текст 3/4уров 1-раздел", "clauses": [],
         "subsections": [
             {"number": "7.9", "header": "Термины", "clauses": [
                 {"number": "7.9.4", "content": "текст", "subclauses": [
                     {"number": "7.9.4.8", "content": "подпункт"}]}]},
             {"number": "7.3", "header": "Сокращения", "clauses": []}]},
        {"number": "3", "header": "Общие положения",
         "tables": [{"number": "3.9", "reference": "Таблица 3.9",
                     "name": "Таблица"}],
         "clauses": [
             {"number": "3.9", "content": "пункт, см. таблицу 3.9 и "
                                          "рисунок 3.8", "subclauses": []},
             {"number": "3.1", "content": "пункт", "subclauses": []}],
         "subsections": [
             {"number": "3.5", "header": "Подраздел",
              "figures": [{"number": "3.8", "reference": "Рисунок 3.8",
                           "name": "Рисунок"}],
              "clauses": [
                 {"number": "3.5.7", "content": "пункт",
                  "subclauses": []}]}]},
        {"number": "Ж", "header": "Приложение Ж",
         "header_style": "ДОК ПРИЛ ур1 Заголовок",
         "tables": [{"number": "Ж.9", "reference": "Таблица Ж.9",
                     "name": "Таблица приложения"}],
         "clauses": [{"number": "Ж.9", "content": "пункт",
                      "subclauses": []}], "subsections": []},
        {"number": "Д", "header": "Приложение Д",
         "header_style": "ПРИЛ Заголовок",
         "clauses": [{"number": "Д.2", "content": "пункт",
                      "subclauses": []}], "subsections": []},
        {"number": "", "header": "Библиография", "clauses": [],
         "subsections": []},
    ]}
    counts = ns.renumber_document(doc)
    sections = doc["sections"]
    check([section["number"] for section in sections]
          == ["", "1", "2", "А", "Б", ""],
          "разделы: 1, 2, приложения А, Б, без номера — как было")
    check(counts["sections"] == 4, "перенумеровано разделов: %d"
          % counts["sections"])
    check([sub["number"] for sub in sections[1]["subsections"]]
          == ["1.1", "1.2"], "подразделы идут подряд")
    check(sections[1]["subsections"][0]["clauses"][0]["number"] == "1.1.1"
          and sections[1]["subsections"][0]["clauses"][0]["subclauses"][0]
          ["number"] == "1.1.1.1",
          "пункт и подпункт получили номера родителя")
    check([clause["number"] for clause in sections[2]["clauses"]]
          == ["2.1", "2.2"]
          and sections[2]["subsections"][0]["number"] == "2.3"
          and sections[2]["subsections"][0]["clauses"][0]["number"] == "2.3.1",
          "пункты и подраздел делят общую последовательность")
    check(sections[3]["clauses"][0]["number"] == "А.1"
          and sections[4]["clauses"][0]["number"] == "Б.1",
          "пункты приложений нумеруются буквой приложения")
    check(sections[2]["tables"][0]["number"] == "2.1"
          and sections[2]["tables"][0]["reference"] == "Таблица 2.1",
          "таблица получила номер раздела")
    check(sections[2]["subsections"][0]["figures"][0]["number"] == "2.1",
          "рисунок получил номер раздела")
    check("таблицу 2.1 и рисунок 2.1"
          in sections[2]["clauses"][0]["content"],
          "ссылки на таблицу и рисунок обновлены")
    check(sections[3]["tables"][0]["number"] == "А.1",
          "таблица приложения нумеруется буквой приложения")
    check(sections[0]["tables"][0]["number"] == "9.9",
          "в разделе без номера таблица не меняется")
    check(counts["tables"] == 2 and counts["figures"] == 1,
          "счётчики таблиц и рисунков: %d, %d"
          % (counts["tables"], counts["figures"]))
    again = ns.renumber_document(doc)
    check(sum(again.values()) == 0, "повторная перенумерация ничего не меняет")


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
    check(len(result["subsection"]["tables"]) == len(em._FORM_NAMES),
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


def test_functional_blocks(data):
    """Отдельный каталог ФБ: принадлежность, signals/уставки, размещение."""
    print("14a. каталог функциональных блоков")
    import ea_schema as sc
    import ea_structure as st
    import logic_library as ll

    entries = es.collect_functional_blocks(data)
    check(len(entries) > 0, "собрано функциональных блоков: %d" % len(entries))
    check(all({"cabinet", "kit", "ied", "name", "functions"} <= set(entry)
              for entry in entries),
          "у каждой записи есть принадлежность и функции")
    function = next((fn for entry in entries for fn in entry["functions"]), {})
    check(all(key in function for key in (
            "name", "iec_name", "inputs", "outputs", "settings",
            "parameters")),
          "функция несёт МЭК, сигналы, уставки и параметры")

    clone = copy.deepcopy(data)
    clone.pop("functional_blocks", None)
    check(len(es.all_functional_blocks(clone)) == len(entries),
          "каталог собирается на лету, если его нет в JSON")
    count = es.rebuild_functional_blocks(clone)
    check(count == len(entries)
          and len(clone["functional_blocks"]) == count,
          "пересборка записывает каталог в стандарт")

    check(sc.child_class("Standard", "functional_blocks")
          == "FunctionalBlockEntry",
          "схема: FunctionalBlocks — отдельный модуль Standard")
    fields = {key for key, _kind, _default
              in sc.fields("FunctionalBlockEntry")}
    check({"cabinet", "kit", "ied", "name", "iec_name", "russian_path"}
          <= fields, "в схеме есть принадлежность и имена по МЭК")

    entry = st.new_functional_block_entry(
        clone,
        {"name": "Тест", "functions": [
            {"name": "Ф", "iec_name": "Ph", "settings": [
                {"name": "U", "default_value": "0,2"}]}]},
        "Шкаф 1", 2, 3)
    check(entry["cabinet"] == "Шкаф 1" and entry["kit"] == "2"
          and entry["ied"] == "3",
          "фабрика записи сохраняет шкаф/комплект/ИЭУ")
    check(entry["functions"][0]["settings"][0]["name"] == "U",
          "фабрика копирует уставки функции")

    block = ll.block_from_standard(entry, "Btest", 0, 0)
    check(block.type == "logic_block" and block.cabinet == "Шкаф 1"
          and block.ied == "3" and len(block.functions) == 1,
          "блок стандарта превращается в элемент схемы ФЛС")
    check(block.functions[0]["title"] == "Ф"
          and block.functions[0]["iec"] == "Ph"
          and len(block.functions[0]["settings"]) == 1,
          "на схеме сохранены русское имя, МЭК и уставка")
    payload = ll.element_payload(block)
    check(payload["cabinet"] == "Шкаф 1"
          and payload["functions"][0]["settings"][0]["name"] == "U",
          "принадлежность и уставки попадают в JSON схемы")
    restored = ll.block_from_standard({}, "B2", 0, 0)
    ll.restore_element(restored, payload)
    check(restored.cabinet == "Шкаф 1"
          and restored.functions[0]["settings"][0]["name"] == "U",
          "принадлежность и уставки восстанавливаются из JSON")

    mark_entry = st.new_functional_block_entry(
        clone, {"name": "ЗП", "functions": [
            {"name": "1 ступень",
             "outputs": [{"name": "Срабатывание"}]}]})
    mark_block = ll.block_from_standard(mark_entry, "Bmark", 0, 0)
    label, _signal = ll.link_full_label(
        {mark_block.id: mark_block},
        {"from": "Bmark#fn0_out0", "to": "K1#left"},
        ll._default_split_ref)
    check(label == "ЗП / 1 ступень: Срабатывание",
          "полная маркировка связи из каталога ФБ: %s" % label)

    # Данные берутся из таблиц «Информационные сигналы в составе
    # отчетов/исходящих сообщений»: там есть и русская, и МЭК-привязка.
    real_entry = next((entry for entry in es.all_functional_blocks(data)
                       if entry.get("cabinet") == "ШЭТ 431.14-1"
                       and entry.get("name") == "ЗП"), None)
    check(real_entry is not None, "блок ЗП найден в каталоге шкафа 431.14-1")
    if real_entry is not None:
        outputs = [out for fn in real_entry["functions"]
                   for out in fn.get("outputs") or []]
        check(any(out.get("description") == "ЗП / ЗП: Срабатывание"
                  and out.get("iec_name") == "CMROVCTOC/PTOC1.Op.general"
                  for out in outputs),
              "выход функции дополнен из информационных сигналов")
        first_fn = real_entry["functions"][0]
        first_out = first_fn["outputs"][0]
        check(real_entry.get("LD") == "CMROVCTOC"
              and first_fn.get("LN") == "PTOC1"
              and first_out.get("DO") == "Op"
              and first_out.get("DA") == "general",
              "МЭК-путь разделён на LD/LN/DO/DA")
        schema_fields = {
            cls: {key for key, _kind, _default in sc.fields(cls)}
            for cls in ("FunctionalBlockEntry", "Function", "Output")}
        check(all(part in schema_fields["FunctionalBlockEntry"]
                  and part in schema_fields["Function"]
                  and part in schema_fields["Output"]
                  for part in ("LD", "LN", "DO", "DA")),
              "схема structure2 содержит поля LD/LN/DO/DA")
        real_block = ll.block_from_standard(real_entry, "Breal", 0, 0)
        check(real_block.LD == "CMROVCTOC"
              and real_block.functions[0]["outputs"][0]["DA"] == "general",
              "структурные поля доходят до блока на схеме")
        real_label, _signal = ll.link_full_label(
            {"Breal": real_block},
            {"from": "Breal#fn0_out0", "to": "K1#left"},
            ll._default_split_ref)
        check(real_label == "ЗП / ЗП: Срабатывание",
              "полная маркировка из таблицы информационных сигналов: %s"
              % real_label)
    import main
    check(hasattr(main.CircuitEditor, "_place_functional_block"),
          "в редакторе есть размещение ФБ на схеме")


def test_structure2_schema():
    """Схема structure2 и миграция JSON: поля есть, перезапись идемпотентна."""
    print("14. схема structure2")
    import ea_schema as sc

    check(sc.child_class("Function", "settings") == "Setting",
          "схема знает вложенные коллекции функции")
    check(sc.kind_of("Setting", "min_value") == "s",
          "уставки хранят числовые поля строками")
    node = {"name": "F", "Location": "ряд 1"}
    check(sc.normalize("TerminalRow", node) and node["location"] == "ряд 1"
          and "Location" not in node,
          "старое имя Location переименовано в location")
    sample = {"number": "1"}
    check(sc.normalize("TerminalRow", sample)
          and "assembly_unit" in sample,
          "новое поле TerminalRow.assembly_unit добавлено")
    fresh = sc.new_node("Function")
    check(all(key in fresh for key, _cls in sc.children("Function")),
          "новый узел Function содержит все коллекции схемы")

    for path in es.files():
        data = es.load(path)
        check(all("description" in ied
                  for cabinet in es.cabinets(data)
                  for kit in cabinet.get("kits") or []
                  for ied in kit.get("ieds") or []),
              "%s: у всех ИЭУ есть description"
              % os.path.basename(path))
        check(all("colums_width" in table for table in es.iter_tables(data)),
              "%s: у всех таблиц есть colums_width"
              % os.path.basename(path))
        check(not sc.normalize_document(data),
              "%s: схема ничего не добавляет повторно"
              % os.path.basename(path))


def test_editor_fields():
    """Редактор правит, добавляет и удаляет любое поле; дерево функций."""
    print("15. произвольные поля в редакторе")
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
    window = None
    original_ask = ea_editor.simpledialog.askstring
    original_yes = ea_editor.messagebox.askyesno
    try:
        window = ea_editor.show(path, root)
        root.update()
        kinds = {node[0] for node in window._nodes.values()}
        check({"block", "function", "parameter"} <= kinds,
              "в дереве есть блоки, функции и параметры ИЭУ")

        function_iid = next(iid for iid, node in window._nodes.items()
                            if node[0] == "function")
        window.tree.selection_set(function_iid)
        root.update()
        item = window._field_item
        check(window._field_keys == ["name", "iec_name", "LNclass",
                                     "inputs", "outputs", "settings",
                                     "parameters"],
              "панель показывает все поля функции")

        window.field_list.selection_set(1)
        ea_editor.simpledialog.askstring = lambda *a, **k: "PDIFX"
        window._edit_field()
        root.update()
        check(item["iec_name"] == "PDIFX",
              "произвольное поле функции отредактировано")

        answers = iter(["custom_field", "42"])
        ea_editor.simpledialog.askstring = lambda *a, **k: next(answers)
        window._add_field()
        root.update()
        check(item.get("custom_field") == 42,
              "добавлено новое поле с приведением типа")

        window.field_list.selection_clear(0, "end")
        window.field_list.selection_set(
            window._field_keys.index("custom_field"))
        ea_editor.messagebox.askyesno = lambda *a, **k: True
        window._delete_field()
        root.update()
        check("custom_field" not in item, "поле удалено")

        # Пункт 12: уставка и параметр добавляются в функцию, а не в ключ None.
        before = len(item.get("settings") or [])
        ea_editor.simpledialog.askstring = lambda *a, **k: "Новая уставка"
        window._add_generic_child(window._find_iid(item), "setting")
        root.update()
        check(len(item["settings"]) == before + 1
              and item["settings"][-1]["name"] == "Новая уставка",
              "уставка добавлена в функцию")
        check(None not in item, "уставка не попала в ключ None")

        before = len(item.get("parameters") or [])
        ea_editor.simpledialog.askstring = lambda *a, **k: "Новый параметр"
        window._add_generic_child(window._find_iid(item), "parameter")
        root.update()
        check(len(item["parameters"]) == before + 1
              and item["parameters"][-1]["name"] == "Новый параметр",
              "параметр добавлен в функцию")
        check(None not in item, "параметр не попал в ключ None")

        # Пункт 19: дублирование функции из меню.
        function_iid = window._find_iid(item)
        functions = window._owners[function_iid][0]
        before = len(functions)
        window.tree.selection_set(function_iid)
        root.update()
        labels = [entry[0] for entry in
                  window._menu_items(function_iid,
                                     window._nodes[function_iid]) if entry]
        check(any("Дублировать функцию" in label for label in labels),
              "в меню функции есть дублирование")
        window._duplicate_node(function_iid)
        root.update()
        index = next(position for position, value in enumerate(functions)
                     if value is item)
        clone = functions[index + 1]
        check(len(functions) == before + 1 and clone is not item
              and clone["name"].endswith("(копия)")
              and len(clone["settings"]) == len(item["settings"]),
              "функция продублирована копией рядом с оригиналом")

        window.tree.selection_set(window._find_iid(item))
        root.update()
        window._copy_node()
        window._paste_node()
        root.update()
        check(len(functions) == before + 2,
              "Ctrl+C и Ctrl+V вставляют копию узла")

        block_iid = next(iid for iid, node in window._nodes.items()
                         if node[0] == "block")
        ied_iid = window._owners[block_iid][2]
        window.tree.selection_set(ied_iid)
        root.update()
        ied = window._owners[ied_iid][1]
        before = len(ied["function_blocks"])
        ea_editor.simpledialog.askstring = lambda *a, **k: "Новый блок"
        window._add_generic_child(ied_iid, "block")
        root.update()
        after = len(ied["function_blocks"])
        check(after == before + 1, "блок функций добавлен в ИЭУ")

        fresh = ied["function_blocks"][-1]
        fresh_iid = window._find_iid(fresh)
        ea_editor.messagebox.askyesno = lambda *a, **k: True
        window._delete_node(fresh_iid)
        root.update()
        check(fresh not in ied["function_blocks"], "блок функций удалён")

        window.save()
        root.update()
        check(es.load(path)["cabinets"] == window.data["cabinets"]
              or len(es.validate(es.load(path))) == 0,
              "структура после правок записывается и проходит проверку")
    finally:
        ea_editor.simpledialog.askstring = original_ask
        ea_editor.messagebox.askyesno = original_yes
        if window is not None:
            window.destroy()
        root.destroy()


# ---------------------------------------------------------------------------
# 16. Схема ФЛС в составе ИЭУ
# ---------------------------------------------------------------------------
def test_ied_scheme(data):
    """Поле IED.scheme, рендер схемы и вставка в DOCX."""
    print("16. схема ФЛС в составе ИЭУ")
    import zipfile

    import logic_scheme_render as lsr
    import ea_structure as st

    check(sc_missing("IED", "scheme") is False,
          "поле IED.scheme есть в схеме structure2")
    fresh = st.new_ied(data, {"ieds": []})
    check(fresh.get("scheme") == "", "новое ИЭУ создаётся с полем scheme")

    cabinet = es.cabinets(data)[0]
    kit = next(k for k in cabinet.get("kits") or [] if k.get("ieds"))
    ied = kit["ieds"][0]

    # Генерация схемы из функциональной модели ИЭУ.
    scheme = lsr.scheme_from_ied(ied)
    blocks = [el for el in scheme["elements"]
              if el["type"] == "logic_block"]
    check(len(blocks) == len(ied.get("function_blocks") or []),
          "блоки схемы соответствуют блокам функций ИЭУ")
    if blocks and (ied.get("function_blocks") or []):
        functions = blocks[0]["logic"]["functions"]
        check(bool(functions)
              and len(functions)
              == len(ied["function_blocks"][0].get("functions") or []),
              "функции блока перенесены в схему")

    # Рендер схемы в PNG.
    folder = tempfile.mkdtemp()
    scheme_path = os.path.join(folder, "scheme.json")
    with open(scheme_path, "w", encoding="utf-8") as handle:
        import json
        json.dump(scheme, handle, ensure_ascii=False)
    image_path = os.path.join(folder, "scheme.png")
    try:
        width, height = lsr.export_png_file(scheme_path, image_path)
        check(width > 0 and height > 0 and os.path.getsize(image_path) > 0,
              "схема рендерится в PNG (%dx%d)" % (width, height))

        # DOCX: рисунок со схемой вставляется картинкой.
        clone = es.load(REFERENCE)
        figure = _first_figure(clone)
        check(figure is not None, "в стандарте есть рисунки")
        figure["scheme"] = scheme_path
        out = os.path.join(folder, "doc.docx")
        ea_docx.build(clone, out, toc=False)
        with zipfile.ZipFile(out) as archive:
            media = [name for name in archive.namelist()
                     if name.startswith("word/media/")
                     and name.endswith(".png")]
        check(bool(media), "DOCX содержит вставленную схему (PNG)")

        # Миграция: поле scheme появляется у ИЭУ и рисунков.
        sample = {"cabinets": [{"kits": [{"ieds": [{}]}]}],
                  "sections": [{"figures": []}]}
        import ea_schema as sc2
        sc2.normalize_document(sample)
        ied2 = sample["cabinets"][0]["kits"][0]["ieds"][0]
        check("scheme" in ied2, "миграция добавляет IED.scheme")
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)

    # GUI: панель ИЭУ с файлом схемы, предпросмотром и применением.
    if tk is None:
        print("  --   tkinter нет: панель ИЭУ не проверяется")
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
    window = None
    try:
        window = ea_editor.show(path, root)
        root.update()
        ied_iid = next(iid for iid, node in window._nodes.items()
                       if node[0] == "ied")
        window.tree.selection_set(ied_iid)
        root.update()
        ied = window._panel_item
        check("scheme" in window.vars, "панель ИЭУ содержит поле схемы")

        code = window._ied_cabinet_code()
        check(code == str(cabinet.get("cypher") or ""),
              "шифр шкафа для имени файла схемы найден: %s" % code)

        # Файл схемы (абсолютный путь) и предпросмотр.
        scheme_path = os.path.join(folder, "ied-scheme.json")
        with open(scheme_path, "w", encoding="utf-8") as handle:
            import json
            json.dump(lsr.scheme_from_ied(ied), handle,
                      ensure_ascii=False)
        window.vars["scheme"].set(scheme_path)
        window._apply_pending()
        root.update()
        window._ied_scheme_file = window._ied_scheme_path(
            window._panel_item)
        window._refresh_ied_scheme_preview()
        root.update()
        check(window._ied_scheme_file == scheme_path,
              "файл схемы найден по полю ИЭУ")
        check(len(window._scheme_preview.find_all()) > 0,
              "предпросмотр схемы нарисован")
        check(ied.get("scheme") == scheme_path,
              "файл схемы сохраняется в ИЭУ")

        # Убрать схему.
        window._clear_ied_scheme()
        window._apply_pending()
        root.update()
        check(ied.get("scheme") == "", "схема убирается из ИЭУ")

        # Панель рисунка тоже работает со схемой.
        figure_iid = next(iid for iid, node in window._nodes.items()
                          if node[0] == "figure")
        window.tree.selection_set(figure_iid)
        root.update()
        check("scheme" in window.vars, "панель рисунка содержит поле схемы")
        figure = window._panel_item
        window.vars["scheme"].set(scheme_path)
        window._apply_pending()
        root.update()
        check(figure.get("scheme") == scheme_path,
              "файл схемы сохраняется в рисунке")
    finally:
        if window is not None:
            window.destroy()
        root.destroy()
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def test_analog_links_in_report():
    """Пункт 20: аналоговые цепи в JSON-рисунке отчёта (PNG и DOCX)."""
    print("17. аналоговые цепи в рисунках отчёта")
    import io
    import json
    import zipfile

    import pdfexport
    import logic_scheme_render as lsr

    try:
        from PIL import Image
    except ImportError:                          # pragma: no cover
        Image = None

    scheme = {
        "elements": [
            {"id": "CA1", "type": "cabinet", "x": 300, "y": 300,
             "cabinet": {"key": "", "title": "Шкаф", "info": {},
                         "komplets": [{"name": "Комплект 1"},
                                      {"name": "Комплект 2"}]}},
            {"id": "CT1", "type": "current_transformer", "x": 700, "y": 220},
        ],
        "connections": [],
        "analog_links": [
            {"from": "CT1", "to": "CA1#0", "voltage": "Ua, Ub",
             "current": "Ia", "points": [[500, 220]]},
        ],
    }
    recorder = pdfexport.SceneRecorder()
    lsr.render_scene(recorder, scheme)
    lines = [call for call in recorder.calls
             if call[0] == "create_line"
             and call[2].get("fill") == lsr.ANALOG_COLOR]
    check(bool(lines), "аналоговая связь нарисована в сцене отчёта")
    check(any(call[2].get("dash") for call in lines),
          "аналоговая связь нарисована пунктиром")
    arrows = [call for call in recorder.calls
              if call[0] == "create_polygon"
              and call[2].get("fill") == lsr.ANALOG_COLOR]
    check(bool(arrows), "стрелка аналоговой связи нарисована")
    texts = [call[2].get("text") for call in recorder.calls
             if call[0] == "create_text"]
    check(any("Ua, Ub / Ia" in str(text) for text in texts),
          "подпись цепей напряжения и тока нарисована")

    folder = tempfile.mkdtemp()
    try:
        scheme_path = os.path.join(folder, "analog.json")
        with open(scheme_path, "w", encoding="utf-8") as handle:
            json.dump(scheme, handle, ensure_ascii=False)
        image_path = os.path.join(folder, "analog.png")
        lsr.export_png_file(scheme_path, image_path)
        check(os.path.getsize(image_path) > 0,
              "схема с аналоговыми цепями рендерится в PNG")
        if Image is not None:
            image = Image.open(image_path).convert("RGB")
            purple = sum(1 for r, g, b in image.getdata()
                         if abs(r - 123) <= 24 and abs(g - 31) <= 24
                         and abs(b - 162) <= 24)
            check(purple > 0, "в PNG есть пиксели аналоговых цепей")

        # DOCX отчёта: рисунок с этой JSON-схемой.
        clone = es.load(REFERENCE)
        figure = _first_figure(clone)
        check(figure is not None, "в стандарте есть рисунок для отчёта")
        figure["scheme"] = scheme_path
        out = os.path.join(folder, "report.docx")
        ea_docx.build(clone, out, toc=False)
        with zipfile.ZipFile(out) as archive:
            media = [archive.read(name) for name in archive.namelist()
                     if name.startswith("word/media/")
                     and name.endswith(".png")]
        check(bool(media), "DOCX содержит изображение схемы")
        if Image is not None:
            purple = 0
            for payload in media:
                try:
                    image = Image.open(io.BytesIO(payload)).convert("RGB")
                except Exception:                # noqa: BLE001
                    continue
                purple += sum(1 for r, g, b in image.getdata()
                              if abs(r - 123) <= 24 and abs(g - 31) <= 24
                              and abs(b - 162) <= 24)
            check(purple > 0,
                  "в изображении отчёта есть аналоговые цепи")
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def test_block_order_in_report():
    """Пункты 21 и 26: отчёт выводит элементы в общем порядке."""
    print("18. порядок пунктов, таблиц и рисунков в отчёте")
    import ea_docx
    import ea_structure as st

    clause_table = {"name": "В пункте", "reference": "Таблица 3"}
    sub_table = {"name": "В подпункте", "reference": "Таблица 4"}
    sub = {"number": "1.1.1", "content": "Подпункт",
           "tables": [sub_table], "figures": []}
    clause = {"number": "1.1", "content": "Пункт",
              "tables": [clause_table], "figures": [],
              "subclauses": [sub]}
    container = {
        "tables": [{"name": "Первая", "reference": "Таблица 1"},
                   {"name": "Вторая", "reference": "Таблица 2"}],
        "figures": [{"name": "Схема", "reference": "Рисунок 1"}],
        "clauses": [clause],
    }
    st.move_item("clause", clause, container["clauses"], container,
                 anchor=container["tables"][0], after=False)
    st.move_item("subclause", sub, clause["subclauses"], clause,
                 anchor=clause_table, after=False)
    calls = []
    originals = (ea_docx._render_table, ea_docx._render_figure_block,
                 ea_docx._text_block, ea_docx._body)
    ea_docx._render_table = lambda doc, data, table, *a: calls.append(
        ("table", table["name"]))
    ea_docx._render_figure_block = lambda doc, figure, *a: calls.append(
        ("figure", figure["name"]))
    ea_docx._text_block = lambda *a: None
    ea_docx._body = lambda doc, text, style=None: calls.append(
        ("text", text))
    try:
        ea_docx._render_container(None, {}, container, 2, 50, {}, {}, [])
    finally:
        (ea_docx._render_table, ea_docx._render_figure_block,
         ea_docx._text_block, ea_docx._body) = originals
    check(calls == [("text", "1.1 Пункт"), ("text", "1.1.1 Подпункт"),
                    ("table", "В подпункте"), ("table", "В пункте"),
                    ("table", "Первая"), ("table", "Вторая"),
                    ("figure", "Схема")],
          "отчёт выводит пункт и подпункт над таблицами и рисунком")


def test_block_order_in_viewer():
    """Пункт 34: просмотрщик повторяет общий порядок редактора."""
    print("34. порядок пунктов, таблиц и рисунков в просмотрщике")
    if tk is None:
        print("  --   tkinter нет: проверка пропущена")
        return
    import ea_ui
    import ea_structure as st

    class App:
        def __init__(self, root):
            self.root = root

    root = tk.Tk()
    root.withdraw()
    window = None
    try:
        window = ea_ui.show(App(root), REFERENCE)
        root.update()

        sub_table = {"name": "В подпункте", "reference": "Таблица 4"}
        sub = {"number": "1.1.1", "content": "Подпункт",
               "tables": [sub_table], "figures": []}
        clause_table = {"name": "В пункте", "reference": "Таблица 3"}
        clause = {"number": "1.1", "content": "Пункт",
                  "tables": [clause_table], "figures": [],
                  "subclauses": [sub]}
        section = {"number": "1", "header": "Раздел", "content": "",
                   "subsections": [], "clauses": [clause],
                   "tables": [{"name": "Первая", "reference": "Таблица 1"},
                              {"name": "Вторая", "reference": "Таблица 2"}],
                   "figures": []}
        figure = st.new_figure({"sections": [section]}, section,
                               number="1", name="Схема")
        section["figures"] = [figure]
        data = {"code": "Проверка", "sections": [section],
                "cabinets": [], "functional_blocks": []}
        st.move_item("clause", clause, section["clauses"], section,
                     anchor=section["tables"][0], after=False)
        st.move_item("subclause", sub, clause["subclauses"], clause,
                     anchor=clause_table, after=False)

        window._data = data
        window._fill_tree()
        root.update()
        document = next(
            iid for iid in window.tree.get_children("")
            if window.tree.item(iid, "text") == "Проверка")
        section_iid = window.tree.get_children(document)[0]
        labels = [window.tree.item(iid, "text").strip()
                  for iid in window.tree.get_children(section_iid)]
        check(labels == ["1.1 Пункт", "Таблица 1 Первая",
                         "Таблица 2 Вторая", "Рисунок 1 Схема"],
              "пункт, таблицы и рисунок идут в общем порядке: %s" % labels)
        clause_iid = window.tree.get_children(section_iid)[0]
        nested = [window.tree.item(iid, "text").strip()
                  for iid in window.tree.get_children(clause_iid)]
        check(nested == ["1.1.1 Подпункт", "Таблица 3 В пункте"],
              "внутри пункта подпункт идёт перед таблицей: %s" % nested)
        sub_iid = window.tree.get_children(clause_iid)[0]
        check([window.tree.item(iid, "text").strip()
               for iid in window.tree.get_children(sub_iid)]
              == ["Таблица 4 В подпункте"],
              "таблица подпункта показана внутри подпункта")

        figure_iid = next(
            iid for iid, node in window._nodes.items()
            if node[0] == "figure" and node[1] is figure)
        window.tree.selection_set(figure_iid)
        window._show()
        root.update()
        check(window.caption.cget("text") == "Рисунок 1 — Схема",
              "рисунок открывается карточкой в просмотрщике")
        check(len(window.table.get_children()) >= 6,
              "карточка рисунка заполнена")
    finally:
        if window is not None:
            window.destroy()
        root.destroy()


def sc_missing(cls, key):
    """Есть ли поле ``key`` у класса ``cls`` в схеме structure2?"""
    import ea_schema as sc
    return key not in [name for name, _t, _v in sc.fields(cls)]


def _first_figure(data):
    """Первый рисунок стандарта (обход разделов и подразделов)."""
    for section in data.get("sections") or []:
        for figure in section.get("figures") or []:
            return figure
        for sub in section.get("subsections") or []:
            for figure in sub.get("figures") or []:
                return figure
    return None


def test_element_report(data):
    """Пункт 30: отчёт по любому элементу стандарта в DOCX."""
    print("3в. отчёт по элементу стандарта")
    try:
        from docx import Document
    except ImportError:
        print("  --   python-docx нет: проверка пропущена")
        return
    import ea_report as er

    folder = tempfile.mkdtemp()
    cabinet = es.cabinet(data, "ШЭТ 431.11-1")
    function = next(
        function
        for cab in data["cabinets"]
        for kit in cab.get("kits") or []
        for ied in kit.get("ieds") or []
        for block in ied.get("function_blocks") or []
        for function in block.get("functions") or []
        if function.get("parameters"))

    # Шкаф: поля карточки, комплекты, ИЭУ и коллекции листовых элементов.
    path = os.path.join(folder, "cabinet.docx")
    counters = er.build(data, [er.target("Cabinet", cabinet)], path)
    check(os.path.isfile(path) and counters["поля"] > 100,
          "отчёт по шкафу собран: %d полей" % counters["поля"])
    doc = Document(path)
    headings = heading_texts(doc)
    check(any(cabinet["cypher"] in text for text in headings),
          "в отчёте есть заголовок шкафа")
    check("Комплекты (1)" in headings and "ИЭУ (1)" in headings,
          "в отчёте перечислены комплекты и ИЭУ шкафа")
    fields = next(table for table in doc.tables
                  if [cell.text for cell in table.rows[0].cells]
                  == ["Поле", "Значение"])
    values = {row.cells[0].text: row.cells[1].text
              for row in fields.rows[1:]}
    check(values.get("Шифр шкафа") == cabinet["cypher"]
          and values.get("Архитектура") == cabinet.get("architecture"),
          "поля шкафа выведены со значениями")
    check(any([cell.text for cell in table.rows[0].cells]
              == ["Элемент", "Поле", "Значение"] for table in doc.tables),
          "входы/выходы и параметры собраны в таблицы коллекций")

    # Функция: поля, параметры и подписи вложенных элементов.
    path = os.path.join(folder, "function.docx")
    er.build(data, [er.target("Function", function)], path)
    doc = Document(path)
    headings = heading_texts(doc)
    check(any(text.startswith("Функция — ") for text in headings),
          "в отчёте есть заголовок функции")
    fields = next(table for table in doc.tables
                  if [cell.text for cell in table.rows[0].cells]
                  == ["Поле", "Значение"])
    values = {row.cells[0].text: row.cells[1].text
              for row in fields.rows[1:]}
    check(values.get("Наименование") == function["name"],
          "поля функции выведены со значениями")
    check(any(text.startswith("Параметры (") for text in headings),
          "параметры функции выведены отдельной коллекцией")

    # Таблица: двухуровневая шапка и строки из шкафа.
    table = es.table_by_number(data, "5.10")
    path = os.path.join(folder, "table.docx")
    counters = er.build(data, [er.target("Table", table)], path,
                        max_rows=3)
    doc = Document(path)
    check(counters["таблицы"] == 1, "таблица данных посчитана")
    headings = heading_texts(doc)
    check(any(table["reference"] in text for text in headings),
          "в отчёте есть заголовок таблицы")
    data_table = doc.tables[1]
    check(data_table.cell(0, 0).text == "Информационный сигнал"
          and data_table.cell(1, 0).text == "Наименование"
          and len(data_table.rows) == 2 + 3,
          "таблица выведена с двумя ярусами шапки и строками из шкафа")
    xml = data_table._tbl.xml
    check("<w:gridSpan" in xml and "<w:vMerge" in xml,
          "объединения шапки сохранены в отчёте по таблице")

    # Выделенная группа: общий заголовок и главы по каждому элементу.
    path = os.path.join(folder, "group.docx")
    er.build(data, [er.target("Cabinet", cabinet),
                    er.target("Table", es.table_by_number(data, "5.2"))],
             path, max_rows=1)
    doc = Document(path)
    texts = [paragraph.text for paragraph in doc.paragraphs]
    headings = heading_texts(doc)
    check("Элементов в отчёте: 2." in texts,
          "в отчёте указано число элементов группы")
    check(any(text.startswith("Шкаф — ") for text in headings)
          and any(text.startswith("Таблица 5.2") for text in headings),
          "в групповом отчёте есть главы обоих элементов")

    try:
        er.build(data, [], path)
        empty = False
    except er.DocxError:
        empty = True
    check(empty, "пустой список элементов — ошибка отчёта")


def test_reference_number_switch():
    """Суффикс /#/0: REF-поле показывает только номер, метка убрана."""
    print("3б. ссылка только на номер (/#/0)")
    try:
        from docx import Document
    except ImportError:            # pragma: no cover
        print("  --   python-docx нет: проверка пропущена")
        return
    doc = Document()
    doc.add_paragraph("См. Таблица 5.1/#/0 и Рисунок 4.1, также Таблица 5.2")
    references = {
        ("T", "5.1"): "RefT_5_1",
        ("F", "4.1"): "RefF_4_1",
        ("T", "5.2"): "RefT_5_2",
    }
    ea_docx._link_references(doc, references)
    xml = doc.element.body.xml
    check('REF RefT_5_1 \\h ' in xml and '\\#' not in xml,
          "REF без числового переключателя: закладка и так содержит номер")
    check('REF RefF_4_1 \\h ' in xml,
          "обычная ссылка осталась ссылкой на подпись")
    text = doc.paragraphs[0].text
    check(text == "См. 5.1 и Рисунок 4.1, также Таблица 5.2",
          "виден только номер: %s" % text)
    check("/#/0" not in text, "суффикс /#/0 убран из текста")


def test_reference_labels():
    """Пункт 31: метки поля ref читаются, повторы и скобки отбрасываются."""
    print("3г. разбор меток перекрёстных ссылок")
    import ea_schema as sc

    check(sc.reference_labels(
        r"\ref{ссылка на рис.1}; МЕТКА ;ссылка на рис.1")
        == ["ссылка на рис.1", "МЕТКА"],
        "метки читаются из ref, готовый вид \\ref{...} снимается")
    check(sc.normalize_ref_label("  Ссылка   На Рис.1 ")
          == "ссылка на рис.1",
          "пробелы и регистр не важны при поиске метки")
    check(sc.reference_labels(" ; {плохая} ; ") == [],
          "метка со скобками не создаётся")


def test_named_references(data):
    """Пункт 31: \\ref{метка} превращается в REF с одним номером."""
    print("3д. перекрёстные ссылки по меткам")
    try:
        from docx import Document
    except ImportError:            # pragma: no cover
        print("  --   python-docx нет: проверка пропущена")
        return
    clone = copy.deepcopy(data)
    table = es.table_by_number(clone, "5.2")
    table["ref"] = "ссылка на рис.1; вторая метка"
    figure = next(es.iter_figures(clone))
    figure["ref"] = "метка рисунка"
    section = clone["sections"][1]
    section["ref"] = "метка раздела"
    sub = next(item["subsections"][0] for item in clone["sections"]
               if item.get("subsections"))
    sub["ref"] = "метка подраздела"
    section["content"] = (
        "Смотри \\ref{ссылка на рис.1}, \\ref{метка рисунка}, "
        "\\ref{МЕТКА РАЗДЕЛА} и \\ref{метка подраздела}. "
        "Нет \\ref{неизвестная метка}.")

    path = os.path.join(tempfile.mkdtemp(), "refs.docx")
    ea_docx.build(clone, path, toc=False, max_rows=1)
    doc = Document(path)
    mention = next(paragraph for paragraph in doc.paragraphs
                   if paragraph.text.startswith("Смотри "))
    check(mention.text == "Смотри 5.2, 4.1, 1 и 3.1. "
          "Нет неизвестная метка.",
          "метки заменены номерами: %s" % mention.text)
    xml = mention._p.xml
    check(xml.count(" REF ") == 4 and '\\#' not in xml,
          "ссылки по меткам — поля REF без числового переключателя")
    names = re.findall(r"REF (\S+)", xml)
    check(len(names) == 4 and len(set(names)) == 4,
          "метки указывают на четыре разные закладки")

    caption = next(paragraph for paragraph in doc.paragraphs
                   if paragraph.text.startswith("Таблица 5.2 —"))
    caption_xml = caption._p.xml
    start = caption_xml.find("<w:bookmarkStart")
    start = caption_xml.find(">", start) + 1 if start >= 0 else -1
    end = caption_xml.find("<w:bookmarkEnd")
    check(start > 0 and end > start, "подпись таблицы держит закладку")
    marked = re.sub(r"<[^>]+>", "", caption_xml[start:end]).strip()
    check(marked == "5.2",
          "закладка подписи содержит только номер: %r" % marked)

    body_xml = doc.element.body.xml
    check(' SET RefS_1 "1" ' in body_xml,
          "номер раздела объявлен полем SET")
    targets = set(re.findall(r" REF (\S+)", body_xml))
    bookmarks = set(re.findall(
        r'<w:bookmarkStart[^>]*w:name="([^"]*)"', body_xml))
    declared = set(re.findall(
        r'<w:instrText[^>]*> SET (\S+) "', body_xml))
    check(targets and targets <= bookmarks | declared,
          "все REF указывают на существующие закладки: %s"
          % ", ".join(sorted(targets - bookmarks - declared)))

    # Пункт 43: в обычном отчёте таблицы меток нет — она выводится
    # отдельным отчётом.
    index = next((paragraph for paragraph in doc.paragraphs
                  if paragraph.text == "Метки перекрёстных ссылок"), None)
    index_table = next((item for item in doc.tables
                        if [cell.text for cell in item.rows[0].cells]
                        == ["Метка", "Объект", "Номер"]), None)
    check(index is None and index_table is None,
          "в обычном отчёте нет таблицы меток")

    labels_path = os.path.join(tempfile.mkdtemp(), "labels.docx")
    counters = ea_docx.build_labels(clone, labels_path)
    labels_doc = Document(labels_path)
    labels_table = next((item for item in labels_doc.tables
                         if [cell.text for cell in item.rows[0].cells]
                         == ["Метка", "Объект", "Номер"]), None)
    check(counters["метки"] == 5 and labels_table is not None
          and len(labels_table.rows) == 6,
          "отчёт по меткам: пять меток четырёх объектов")
    import ea_editor
    import ea_ui
    check(hasattr(ea_editor.StandardEditorWindow, "labels_report")
          and hasattr(ea_ui.EAStandardWindow, "export_labels"),
          "кнопки отчёта по меткам есть в редакторе и просмотрщике")


def test_title_page_before_report(data):
    """Реквизит title_page: готовый DOCX открывает сгенерированный отчёт."""
    print("3в. титульный DOCX перед отчётом")
    try:
        from docx import Document
    except ImportError:            # pragma: no cover
        print("  --   python-docx нет: проверка пропущена")
        return
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    folder = tempfile.mkdtemp()
    title = os.path.join(folder, "my_title.docx")
    source = Document()
    source.add_paragraph("ТИТУЛЬНЫЙ ЛИСТ")
    source.add_paragraph("Титул: Таблица 5.1")
    # Колонтитулы титула не должны попасть в отчёт.
    title_section = source.sections[0]
    title_section.header.is_linked_to_previous = False
    title_section.header.paragraphs[0].text = "КОЛОНТИТУЛ ТИТУЛА"
    title_section.footer.is_linked_to_previous = False
    title_section.footer.paragraphs[0].text = "ПОДПИСЬ ТИТУЛА"
    # Титул может сбрасывать нумерацию — отчёт всё равно её продолжает.
    pg_num = OxmlElement("w:pgNumType")
    pg_num.set(qn("w:start"), "1")
    title_section._sectPr.insert_element_before(
        pg_num, "w:cols", "w:formProt", "w:vAlign", "w:noEndnote",
        "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter",
        "w:docGrid", "w:printerSettings", "w:sectPrChange")
    source.save(title)

    clone = copy.deepcopy(data)
    clone["title_page"] = title
    out = os.path.join(folder, "with_title.docx")
    counters = ea_docx.build(clone, out, toc=False, max_rows=1)
    check(counters["титульный_лист"] == title,
          "в счётчике указан использованный титульный DOCX")

    doc = Document(out)
    texts = [paragraph.text for paragraph in doc.paragraphs]
    title_at = next(index for index, text in enumerate(texts)
                    if text == "ТИТУЛЬНЫЙ ЛИСТ")
    report_at = next(index for index, text in enumerate(texts)
                     if text == "Введение")
    check(title_at < report_at, "готовый титул идёт перед отчётом")
    check(not any(text.startswith("Разделов:") for text in texts),
          "встроенный титул не дублируется")
    check(len(doc.sections) >= 2,
          "отчёт отделён от титула новой секцией")
    check("REF RefT_5_1" in doc.element.body.xml,
          "перекрёстные ссылки отчёта сохранились")
    title_mention = next(paragraph for paragraph in doc.paragraphs
                         if paragraph.text.startswith("Титул:"))
    check("REF" not in title_mention._p.xml,
          "текст готового титула не переписывается")

    report = doc.sections[-1]
    title_section = doc.sections[-2]
    check(report.orientation == WD_ORIENT.PORTRAIT,
          "отчёт после титула идёт в книжной ориентации")
    check(abs(report.page_width.cm - 21.0) < 0.01
          and abs(report.page_height.cm - 29.7) < 0.01,
          "отчёт после титула — A4: %.1f×%.1f см"
          % (report.page_width.cm, report.page_height.cm))
    # Пункт 47: поля отчёта продолжают поля титула, а не сбрасываются.
    check(all(abs(getattr(report, name).cm - getattr(title_section, name).cm)
              < 0.01
              for name in ("left_margin", "right_margin",
                           "top_margin", "bottom_margin")),
          "поля отчёта продолжают поля титула")
    check(report._sectPr.find(qn("w:titlePg")) is None,
          "у отчёта нет особого колонтитула первой страницы титула")
    check(not report.header.is_linked_to_previous,
          "верхний колонтитул отчёта не наследуется от титула")
    check(not report.footer.is_linked_to_previous,
          "нижний колонтитул отчёта не наследуется от титула")
    header_xml = report.header._element.xml
    check("PAGE" in header_xml, "в верхнем колонтитуле отчёта поле PAGE")
    check("Обновите поле" not in header_xml,
          "поле PAGE не показывает заглушку вместо номера")
    check("КОЛОНТИТУЛ ТИТУЛА" not in header_xml,
          "логотип и текст титула не попали в верхний колонтитул")
    footer_text = "\n".join(paragraph.text
                            for paragraph in report.footer.paragraphs)
    check("ПОДПИСЬ ТИТУЛА" not in footer_text,
          "подпись титула не попала в нижний колонтитул")
    check(report._sectPr.find(qn("w:pgNumType")) is None,
          "нумерация страниц отчёта продолжается от титула")


def test_report_tables_font():
    print("3a. шрифт таблиц отчётов")
    import docxreport
    builder = docxreport.DocxBuilder()
    builder.table(header=["Показатель", "Значение"], rows=[["А", "1"]])
    xml = "".join(builder.body)
    check('<w:sz w:val="20"/>' in xml,
          "таблицы отчёта по НИР набраны кеглем 10")


def _exchange_sample():
    """Небольшой стандарт для проверки выгрузки/загрузки объектов."""
    return {
        "code": "ТЕСТ", "name": "Стандарт для обмена",
        "sections": [],
        "cabinets": [
            {"cypher": "ШЭТ 1", "name": "Шкаф 1", "kits": [
                {"number": 1, "description": "Комплект 1", "ieds": [
                    {"number": 1, "description": "ИЭУ1", "function_blocks": [
                        {"name": "Блок A", "russian_path": "Блок A",
                         "functions": [{"name": "Функция A"}]}
                    ]}
                ]}
            ]},
            {"cypher": "ШЭТ 2", "name": "Шкаф 2", "kits": [
                {"number": 1, "description": "Комплект 2", "ieds": [
                    {"number": 1, "description": "ИЭУ2", "function_blocks": [
                        {"name": "Блок B", "russian_path": "Блок B",
                         "functions": [{"name": "Функция B"}]}
                    ]}
                ]}
            ]},
            {"cypher": "ШЭТ 3", "name": "Шкаф 3", "kits": [
                {"number": 1, "description": "Комплект 3", "ieds": [
                    {"number": 1, "description": "ИЭУ3", "function_blocks": [
                        {"name": "Блок C", "russian_path": "Блок C",
                         "functions": [{"name": "Функция C"}]}
                    ]}
                ]}
            ]},
        ],
        "functional_blocks": [
            {"name": "Каталог X", "russian_path": "Каталог X",
             "functions": [{"name": "Функция X"}],
             "cabinet": "ШЭТ 1", "kit": "1", "ied": "1"},
        ],
    }


def test_exchange():
    """Пункт 38: отдельный JSON со шкафами, комплектами, блоками, функциями."""
    print("10д. выгрузка и загрузка объектов в отдельный JSON")
    import ea_exchange as ex
    import ea_structure as st
    data = _exchange_sample()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "objects.json")
    cab1 = data["cabinets"][0]
    kit2 = data["cabinets"][1]["kits"][0]
    entry = data["functional_blocks"][0]
    func2 = data["cabinets"][2]["kits"][0]["ieds"][0] \
        ["function_blocks"][0]["functions"][0]
    nodes = [("cabinet", cab1), ("kit", kit2), ("fb_entry", entry),
             ("function", func2)]

    records = ex.collect(nodes)
    check([item["kind"] for item in records] == [
        "cabinet", "kit", "functional_block", "function"],
        "выгружаются все четыре вида объектов")
    check(ex.collect([("cabinet", cab1), ("kit", cab1["kits"][0])])
          == [ex.collect([("cabinet", cab1)])[0]],
          "вложенный комплект не дублируется при выгрузке шкафа")

    ex.save(path, records, source="standard.json")
    loaded = ex.load(path)
    check(len(loaded) == 4
          and loaded[0]["data"]["cypher"] == "ШЭТ 1"
          and loaded[3]["data"]["name"] == "Функция C",
          "файл обмена записан и прочитан без потери данных")
    bad = os.path.join(folder, "bad.json")
    with open(bad, "w", encoding="utf-8") as handle:
        json.dump({"format": "standard", "version": 1,
                   "objects": loaded}, handle)
    try:
        ex.load(bad)
        check(False, "чужой формат файла отклонён")
    except ex.ExchangeError:
        check(True, "чужой формат файла отклонён")

    target = {"sections": [], "cabinets": [], "functional_blocks": []}
    target_cab = st.new_cabinet(target, cypher="ШЭТ 3")
    st.add(target["cabinets"], target_cab)
    st.add(target_cab["kits"], st.new_kit(target, target_cab))
    target_block = {"name": "БлокПриёмник", "russian_path": "БлокПриёмник",
                    "functions": []}
    result = ex.apply(target, loaded, cabinet=target_cab,
                      function_owner=target_block)
    check(result["counts"] == {"cabinet": 1, "kit": 1,
                               "functional_block": 1, "function": 1},
          "все объекты загружены в целевой стандарт")
    check(len(target["cabinets"]) == 2
          and target["cabinets"][1]["cypher"] == "ШЭТ 1"
          and len(target["cabinets"][1]["kits"][0]["ieds"][0]
                  ["function_blocks"][0]["functions"]) == 1,
          "шкаф загружен вместе с комплектом, ИЭУ и функцией")
    check(target_cab["kits"][1]["number"] == 2,
          "номер комплекта при конфликте заменён следующим")
    check(target["functional_blocks"][0]["cabinet"] == "ШЭТ 1"
          and target_block["functions"][0]["name"] == "Функция C",
          "блок и функция попали в нужные владельцы")

    before = copy.deepcopy(target)
    try:
        ex.apply(target, [loaded[0]], cabinet=target_cab,
                 function_owner=target_block)
        check(False, "повторная загрузка шкафа отклонена")
    except ex.ExchangeError:
        check(True, "повторная загрузка шкафа отклонена")
    check(target == before, "при ошибке стандарт остался без изменений")


def test_editor_exchange():
    """Пункт 38: пункты меню и выгрузка/загрузка из редактора."""
    print("10е. обмен объектами через контекстное меню редактора")
    if tk is None:
        print("  --   tkinter нет: проверка пропущена")
        return
    try:
        import ea_editor
        import ea_exchange as ex
        root = tk.Tk()
    except Exception as exc:                      # noqa: BLE001
        check(False, "редактор стандарта: %s" % exc)
        return
    root.withdraw()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "standard.json")
    es.save(_exchange_sample(), path)
    window = second = None
    try:
        window = ea_editor.show(path, root)
        root.update()
        cab_iid = next(iid for iid, node in window._nodes.items()
                       if node[0] == "cabinet")
        labels = [entry[0] for entry in
                  window._menu_items(cab_iid, window._nodes[cab_iid])
                  if entry]
        check("Выгрузить шкаф в JSON…" in labels
              and "Загрузить в шкаф из JSON…" in labels,
              "в меню шкафа есть выгрузка и загрузка")
        fb_iid = next(iid for iid, node in window._nodes.items()
                      if node[0] == "root" and node[1] == "fb")
        labels = [entry[0] for entry in
                  window._menu_items(fb_iid, window._nodes[fb_iid]) if entry]
        check("Загрузить из JSON…" in labels,
              "в меню каталога ФБ есть загрузка из JSON")
        function_iid = next(iid for iid, node in window._nodes.items()
                            if node[0] == "function")
        labels = [entry[0] for entry in
                  window._menu_items(function_iid,
                                     window._nodes[function_iid]) if entry]
        check("Выгрузить функцию в JSON…" in labels,
              "в меню функции есть выгрузка в JSON")

        out = os.path.join(folder, "cabinet.json")
        original_save = ea_editor.filedialog.asksaveasfilename
        ea_editor.filedialog.asksaveasfilename = lambda *a, **k: out
        try:
            window._export_nodes([cab_iid])
            root.update()
        finally:
            ea_editor.filedialog.asksaveasfilename = original_save
        check(os.path.isfile(out)
              and [item["kind"] for item in ex.load(out)] == ["cabinet"],
              "шкаф выгружен из редактора в отдельный JSON")

        empty = os.path.join(folder, "empty.json")
        es.save({"code": "ПУСТОЙ", "name": "Пустой стандарт",
                 "sections": [], "cabinets": [], "functional_blocks": []},
                empty)
        second = ea_editor.show(empty, root)
        root.update()
        cabs_iid = next(iid for iid, node in second._nodes.items()
                        if node[0] == "root" and node[1] == "cabs")
        original_open = ea_editor.filedialog.askopenfilename
        ea_editor.filedialog.askopenfilename = lambda *a, **k: out
        try:
            second._import_json(cabs_iid)
            root.update()
        finally:
            ea_editor.filedialog.askopenfilename = original_open
        check(len(second.data["cabinets"]) == 1
              and second.data["cabinets"][0]["cypher"] == "ШЭТ 1",
              "шкаф загружен из JSON в другой стандарт")
    except Exception as exc:                      # noqa: BLE001
        check(False, "обмен объектами в редакторе: %s" % exc)
    finally:
        if second is not None:
            second.destroy()
        if window is not None:
            window.destroy()
        root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args(argv)
    data = es.load(REFERENCE)
    test_catalog(data)
    test_catalog_new(data)
    test_catalog_sync(data)
    test_new_standard(data)
    test_split_descriptions(data)
    test_docx(data)
    test_table_style()
    test_element_report(data)
    test_reference_number_switch()
    test_reference_labels()
    test_named_references(data)
    test_title_page_before_report(data)
    test_report_tables_font()
    test_archive()
    test_rebuild_from_standards()
    test_main_method_exists()
    test_edit_model()
    test_structure_ops(data)
    test_renumber_document()
    test_merge_all_cabinets()
    test_typical_transfer()
    test_functional_blocks(data)
    test_structure2_schema()
    test_ied_scheme(data)
    test_analog_links_in_report()
    test_block_order_in_report()
    test_exchange()
    if not args.no_gui:
        test_gui(data)
        test_block_order_in_viewer()
        test_fields()
        test_editor()
        test_editor_drag_reorder()
        test_editor_fields()
        test_kit_identity()
        test_editor_report()
        test_editor_reference()
        test_editor_update_standard()
        test_editor_renumber()
        test_editor_exchange()
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
