# -*- coding: utf-8 -*-
"""Преобразование JSON-описания стандарта СТО 56947007-... в отчёт DOCX.

Скрипт читает итоговый JSON, полученный парсерами `_parse/*.py`, и строит
полноценный отчёт Word: титул, общие сведения, перечень шкафов, описание
каждого шкафа и его комплектов, все таблицы стандарта. Если JSON собран
через apply_changes.py, добавляется раздел «Сведения о редакции», а
отменённые строки таблиц получают видимые столбцы «Статус»/«Основание».

Установка:
    python -m pip install python-docx

Примеры:
    python json_to_docx.py "СТО 56947007-33.040.20.279-2019.json"
    python json_to_docx.py "СТО 56947007-33.040.20.279-2019.json" --out "Отчет.docx" --toc
    python json_to_docx.py "СТО 56947007-33.040.20.279-2019.json" --scope brief
    python json_to_docx.py "СТО 56947007-33.040.20.279-2019.json" --only 431.02-0
    python json_to_docx.py "СТО 56947007-33.040.20.279-2019.json" --max-rows 25
    python json_to_docx.py "СТО 56947007-*.json" --toc --out-dir "Отчеты"

Опции:
    --out PATH         путь к DOCX (только для одного входного файла)
    --out-dir PATH     каталог для отчётов при пакетной обработке
    --scope            full     - все таблицы (по умолчанию)
                       cabinets - только таблицы шкафов
                       brief    - только описания и комплекты, без таблиц разделов
    --max-rows N       не более N строк в каждой таблице, 0 = все строки
    --only CODE        только указанный шкаф (код ШЭТ или номер раздела),
                       можно повторять; по умолчанию все шкафы
    --toc              вставить поле оглавления (Word: Ctrl+A, затем F9)
    --no-title-page    не добавлять титульный лист
    --portrait         книжная ориентация (по умолчанию альбомная - удобнее
                       для широких таблиц)
    --font-size PT     базовый размер шрифта, по умолчанию 10
    --tables-5x1       дублировать таблицу 5.x.1 в разделе таблиц
                       (по умолчанию она уже выведена как «Описание шкафа»)

Скрипт можно использовать и как модуль:
    from json_to_docx import build_report
    build_report(data, "report.docx", scope="full")
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import date

try:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError:
    sys.exit("Не установлен python-docx. Выполните: python -m pip install python-docx")

FONT = "Times New Roman"
HEADER_FILL = "DCE6F1"          # заливка шапки таблицы
ACCENT = RGBColor(0x1F, 0x3B, 0x63)
GRAY = RGBColor(0x60, 0x60, 0x60)
BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
COMPLECT_RE = re.compile(r"^Комплект(?: [123])?$")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def s(value) -> str:
    """Любое значение JSON -> плоский текст для ячейки Word."""
    if value is None:
        return ""
    if isinstance(value, str):
        return BAD_XML.sub("", value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(s(x) for x in value if x not in (None, "", []))
    if isinstance(value, dict):
        return "; ".join("%s: %s" % (s(k), s(v)) for k, v in value.items())
    return BAD_XML.sub("", str(value))


def set_run_font(run, size=None, bold=None, color=None, italic=None):
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def fill_cell(cell, text, size=9, bold=False, color=None, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    if align is not None:
        p.alignment = align
    run = p.add_run(s(text))
    set_run_font(run, size, bold, color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def shade(cell, color=HEADER_FILL):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def no_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def set_widths(table, widths_cm):
    table.autofit = False
    for col, width in zip(table.columns, widths_cm):
        col.width = Cm(width)
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Cm(width)


def calc_widths(headers, rows, available_cm, min_cm=1.7, max_cm=8.0):
    """Ширины столбцов по длине содержимого, с ограничениями."""
    weights = []
    for i, h in enumerate(headers):
        longest = len(s(h))
        for r in rows[:200]:
            if i < len(r):
                longest = max(longest, len(s(r[i])))
        weights.append(max(4.0, min(float(longest), 42.0)) ** 0.65)
    total = sum(weights) or 1.0
    widths = [min(max_cm, max(min_cm, available_cm * w / total)) for w in weights]
    scale = available_cm / (sum(widths) or 1.0)
    return [w * scale for w in widths]


def add_grid(doc, headers, rows, font_size=8, available_cm=26.0):
    """Таблица с шапкой, повторяющейся на каждой странице."""
    if not headers:
        return None
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        fill_cell(table.rows[0].cells[i], h, size=font_size, bold=True, color=ACCENT)
        shade(table.rows[0].cells[i])
    repeat_header(table.rows[0])
    no_split(table.rows[0])
    for row in rows:
        cells = table.add_row().cells
        no_split(table.rows[-1])
        for i, value in enumerate(row[:len(headers)]):
            fill_cell(cells[i], value, size=font_size)
    set_widths(table, calc_widths(headers, rows, available_cm))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def add_caption(doc, num, title, meta=""):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    r1 = p.add_run("%s — %s" % (num, s(title)))
    set_run_font(r1, 10, bold=True, color=ACCENT)
    if meta:
        r2 = p.add_run("  " + s(meta))
        set_run_font(r2, 8, color=GRAY, italic=True)


def add_kv_table(doc, mapping, font_size=9, available_cm=26.0, col1=7.0):
    """Таблица «Параметр | Значение» для описаний."""
    rows = [[s(k), s(v)] for k, v in mapping.items()]
    table = add_grid(doc, ["Параметр", "Значение"], rows,
                     font_size=font_size, available_cm=available_cm)
    if table is not None:
        set_widths(table, [col1, available_cm - col1])
        for row in table.rows[1:]:
            fill_cell(row.cells[0], row.cells[0].text, size=font_size, bold=True)
    return table


def add_heading(doc, text, level):
    h = doc.add_heading(s(text), level=level)
    for run in h.runs:
        set_run_font(run, {0: 20, 1: 16, 2: 13, 3: 11}.get(level, 11),
                     bold=True, color=ACCENT)
    return h


def add_page_number_footer(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Стр. ")
    set_run_font(run, 8, color=GRAY)
    fld = p.add_run()
    set_run_font(fld, 8, color=GRAY)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, end):
        fld._r.append(el)


def add_toc(doc):
    add_heading(doc, "Оглавление", 1)
    p = doc.add_paragraph()
    run = p.add_run()
    set_run_font(run, 10)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = r'TOC \o "1-3" \h \z \u'
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    hint = OxmlElement("w:t")
    hint.text = "Обновите оглавление: выделите документ (Ctrl+A) и нажмите F9"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, sep, hint, end):
        run._r.append(el)
    doc.add_page_break()


def setup_document(doc, base_size, landscape):
    section = doc.sections[0]
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(1.6)
    section.top_margin = section.bottom_margin = Cm(1.6)
    add_page_number_footer(section)
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(base_size)
    normal.paragraph_format.space_after = Pt(4)
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        try:
            st = doc.styles[name]
            st.font.name = FONT
            st.font.color.rgb = ACCENT
        except KeyError:
            pass
    return section


def title_page(doc, data, stats):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(70)
    r = p.add_run(s(data.get("Принадлежность стандарта", "")))
    set_run_font(r, 14, color=GRAY)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(24)
    r = p.add_run(s(data.get("Обозначение стандарта", "")))
    set_run_font(r, 20, bold=True, color=ACCENT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("ОТЧЁТ ПО ТИПОВЫМ ШКАФАМ РЗА")
    set_run_font(r, 16, bold=True, color=ACCENT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(36)
    r = p.add_run(s(data.get("Шифр стандарта", "")))
    set_run_font(r, 14, bold=True)
    doc.add_paragraph()
    add_kv_table(doc, OrderedDict([
        ("Дата введения", data.get("Дата введения", "")),
        ("Принадлежность стандарта", data.get("Принадлежность стандарта", "")),
        ("Шкафов в стандарте", stats["cabinets"]),
        ("Комплектов", stats["complects"]),
        ("Таблиц", stats["tables"]),
        ("Строк данных в таблицах", stats["rows"]),
        ("Отчёт сформирован", date.today().strftime("%d.%m.%Y")),
    ]), font_size=10, col1=8.0)
    doc.add_page_break()


# ---------------------------------------------------------------------------
# Содержательная часть
# ---------------------------------------------------------------------------
def table_records(table):
    """(заголовки, строки) из объекта таблицы JSON.

    Если в строках появились служебные поля редакции («Статус»,
    «Основание», «Изменение»), они автоматически становятся дополнительными столбцами,
    чтобы отменённые элементы были видны в отчёте.
    """
    cols = list(table.get("Столбцы") or [])
    recs = table.get("Строки", [])
    for rec in recs:
        if isinstance(rec, dict):
            for k in ("Статус", "Основание", "Изменение", "Действует до"):
                if k in rec and k not in cols:
                    cols.append(k)
    rows = []
    for rec in recs:
        if isinstance(rec, dict):
            rows.append([s(rec.get(c, "")) for c in cols] or [s(v) for v in rec.values()])
        else:
            rows.append([s(v) for v in rec])
    return [s(c) for c in cols], rows


def render_table(doc, num, table, max_rows, font_size=8, available_cm=26.0):
    headers, rows = table_records(table)
    total = len(rows)
    shown = rows if max_rows <= 0 else rows[:max_rows]
    meta = "строк: %d" % total
    if table.get("Страницы"):
        meta += "; стр. %s" % s(table["Страницы"])
    if len(shown) < total:
        meta += "; выведено первые %d" % len(shown)
    add_caption(doc, num, table.get("Наименование", ""), meta)
    if not headers:
        headers = ["Столбец %d" % (i + 1) for i in range(max(len(r) for r in shown))]
    add_grid(doc, headers, shown, font_size=font_size, available_cm=available_cm)


def render_edition(doc, edition, small, available_cm):
    """Сведения о редакции: какие изменения применены и что отменено."""
    applied = edition.get("Применённые изменения") or []
    deprecated = edition.get("Отменённые элементы") or []
    excluded = edition.get("Исключённые изменения") or []
    add_heading(doc, "Сведения о редакции", 2)
    add_kv_table(doc, OrderedDict([
        ("Формат", edition.get("Формат", "")),
        ("Базовый стандарт", edition.get("Базовый стандарт", "")),
        ("SHA-256 базы", edition.get("SHA-256 базы", "")),
        ("Дата сборки", edition.get("Собрано", "")),
        ("Применено изменений", len(applied)),
        ("Всего операций", edition.get("Всего операций", 0)),
        ("Отменённых элементов", len(deprecated)),
        ("Исключено файлов изменений", len(excluded)),
    ]), font_size=9, available_cm=available_cm, col1=8.0)
    if applied:
        add_caption(doc, "Редакция", "Применённые изменения",
                    "штук: %d" % len(applied))
        headers = ["Идентификатор", "Версия", "Дата", "Наименование",
                   "Основание", "Операций", "Заменяет"]
        add_grid(doc, headers,
                 [[s(r.get(h, "")) for h in headers] for r in applied],
                 font_size=small, available_cm=available_cm)
    if deprecated:
        add_caption(doc, "Редакция", "Отменённые элементы (сохранены в документе)",
                    "штук: %d" % len(deprecated))
        headers = list(deprecated[0].keys())
        add_grid(doc, headers,
                 [[s(r.get(h, "")) for h in headers] for r in deprecated],
                 font_size=small, available_cm=available_cm)
    if excluded:
        add_caption(doc, "Редакция", "Исключённые изменения")
        add_grid(doc, ["Причина"], [[s(x)] for x in excluded],
                 font_size=small, available_cm=available_cm)
    doc.add_page_break()


def render_complect(doc, name, obj, font_size=8, available_cm=26.0):
    add_heading(doc, name, 4)
    scalars = OrderedDict()
    for k, v in obj.items():
        if k in ("Входные аналоговые измерения", "Таблицы комплекта"):
            continue
        scalars[k] = v
    if scalars:
        add_kv_table(doc, scalars, font_size=9, available_cm=available_cm, col1=7.0)
    analog = obj.get("Входные аналоговые измерения")
    if isinstance(analog, dict):
        analog = [analog]
    if analog:
        add_caption(doc, name, "Входные аналоговые измерения", "строк: %d" % len(analog))
        headers = []
        for row in analog:
            for k in row:
                if k not in headers:
                    headers.append(k)
        add_grid(doc, headers,
                 [[s(row.get(h, "")) for h in headers] for row in analog],
                 font_size=font_size, available_cm=available_cm)
    refs = obj.get("Таблицы комплекта")
    if refs:
        add_caption(doc, name, "Таблицы комплекта")
        add_kv_table(doc, refs, font_size=9, available_cm=available_cm, col1=12.0)


def collect_stats(content):
    tables = 0
    rows = 0
    complects = 0
    cabinets = 0
    for key, value in content.items():
        if isinstance(value, dict) and "Таблицы" in value:
            cabinets += 1
            for t in value["Таблицы"].values():
                tables += 1
                rows += t.get("Количество строк", len(t.get("Строки", [])))
            complects += sum(1 for k in value.get("Описание шкафа", {})
                             if COMPLECT_RE.match(k))
        elif isinstance(value, dict):
            for t in value.values():
                if isinstance(t, dict) and "Строки" in t:
                    tables += 1
                    rows += t.get("Количество строк", len(t.get("Строки", [])))
    return dict(cabinets=cabinets, complects=complects, tables=tables, rows=rows)


def cabinet_matches(cab, filters):
    if not filters:
        return True
    hay = "%s %s" % (cab.get("Шифр шкафа", ""), cab.get("Раздел стандарта", ""))
    return any(f.lower() in hay.lower() for f in filters)


def build_report(data, out_path, scope="full", max_rows=0, only=None,
                 toc=False, title=True, portrait=False, base_size=10,
                 tables_5x1=False):
    """Построить DOCX из разобранного JSON и сохранить в out_path."""
    content = data["Содержимое стандарта"]
    stats = collect_stats(content)
    doc = Document()
    setup_document(doc, base_size, landscape=not portrait)
    available_cm = 26.5 if not portrait else 17.5
    small = max(7, base_size - 2)

    if title:
        title_page(doc, data, stats)
    if toc:
        add_toc(doc)

    # 1. Общие сведения
    add_heading(doc, "1. Общие сведения", 1)
    add_kv_table(doc, OrderedDict([
        ("Обозначение стандарта", data.get("Обозначение стандарта", "")),
        ("Шифр стандарта", data.get("Шифр стандарта", "")),
        ("Дата введения", data.get("Дата введения", "")),
        ("Принадлежность стандарта", data.get("Принадлежность стандарта", "")),
    ]), font_size=10, available_cm=available_cm, col1=7.0)
    add_heading(doc, "Область применения стандарта", 3)
    p = doc.add_paragraph(s(data.get("Область применения стандарта", "")))
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for run in p.runs:
        set_run_font(run, base_size)
    add_heading(doc, "Сводка по стандарту", 3)
    in_report = sum(1 for cab in content.values()
                    if isinstance(cab, dict) and "Описание шкафа" in cab
                    and cabinet_matches(cab, only))
    summary = OrderedDict([
        ("Шкафов", stats["cabinets"]),
        ("Комплектов (всего)", stats["complects"]),
        ("Таблиц", stats["tables"]),
        ("Строк данных", stats["rows"]),
    ])
    if in_report != stats["cabinets"]:
        summary["Шкафов в отчёте"] = in_report
    add_kv_table(doc, summary, font_size=10, available_cm=available_cm, col1=7.0)
    edition = data.get("Редакция")
    if isinstance(edition, dict) and edition:
        render_edition(doc, edition, small, available_cm)

    # 2. Общий перечень шкафов
    listing = content.get("Общий перечень шкафов стандарта", [])
    if listing:
        add_heading(doc, "2. Общий перечень шкафов стандарта", 1)
        headers = list(listing[0].keys())
        rows = [[s(rec.get(h, "")) for h in headers] for rec in listing]
        add_grid(doc, headers, rows, font_size=small, available_cm=available_cm)

    # 3. Шкафы
    add_heading(doc, "3. Описание шкафов", 1)
    idx = 0
    for key, cab in content.items():
        if not isinstance(cab, dict) or "Описание шкафа" not in cab:
            continue
        if not cabinet_matches(cab, only):
            continue
        idx += 1
        if idx > 1:
            doc.add_page_break()
        add_heading(doc, "3.%d %s" % (idx, key), 2)
        add_kv_table(doc, OrderedDict([
            ("Раздел стандарта", cab.get("Раздел стандарта", "")),
            ("Шифр шкафа", cab.get("Шифр шкафа", "")),
            ("Назначение шкафа", cab.get("Назначение шкафа", "")),
        ]), font_size=10, available_cm=available_cm, col1=6.0)

        desc = cab["Описание шкафа"]
        add_heading(doc, "Описание шкафа", 3)
        plain = OrderedDict((k, v) for k, v in desc.items()
                            if not COMPLECT_RE.match(k))
        add_kv_table(doc, plain, font_size=9, available_cm=available_cm, col1=8.0)
        comp_names = [k for k in desc if COMPLECT_RE.match(k)]
        if comp_names:
            add_heading(doc, "Комплекты (%d)" % len(comp_names), 3)
            for cname in comp_names:
                render_complect(doc, cname, desc[cname],
                                font_size=small, available_cm=available_cm)

        if scope == "brief":
            continue
        own = cab.get("Таблицы", {})
        if own:
            add_heading(doc, "Таблицы раздела %s" % cab.get("Раздел стандарта", ""), 3)
            for num, table in own.items():
                if not tables_5x1 and re.search(r"\.1$", num):
                    continue       # уже выведено как «Описание шкафа»
                render_table(doc, num, table, max_rows,
                             font_size=small, available_cm=available_cm)

    if scope != "full":
        doc.save(out_path)
        return stats

    # 4. Прочие таблицы и приложение
    section_no = 4
    for group_name in ("Прочие таблицы стандарта (разделы 4 и 5.1)", "Приложение А"):
        group = content.get(group_name)
        if not isinstance(group, dict) or not group:
            continue
        add_heading(doc, "%d. %s" % (section_no, group_name), 1)
        section_no += 1
        for num, table in group.items():
            render_table(doc, num, table, max_rows,
                         font_size=small, available_cm=available_cm)

    doc.save(out_path)
    return stats


def main():
    ap = argparse.ArgumentParser(
        description="Преобразование JSON-описания стандарта в отчёт DOCX")
    ap.add_argument("json", nargs="+",
                    help="путь(и) к JSON стандарта; допускаются маски *.json")
    ap.add_argument("--out", help="путь к DOCX (только для одного входного файла)")
    ap.add_argument("--out-dir", help="каталог для отчётов при пакетной обработке")
    ap.add_argument("--scope", choices=("full", "cabinets", "brief"), default="full")
    ap.add_argument("--max-rows", type=int, default=0,
                    help="максимум строк в каждой таблице, 0 = все")
    ap.add_argument("--only", action="append", default=[],
                    help="только шкаф с данным кодом/номером раздела (повторяемо)")
    ap.add_argument("--toc", action="store_true", help="поле оглавления")
    ap.add_argument("--no-title-page", action="store_true")
    ap.add_argument("--portrait", action="store_true")
    ap.add_argument("--font-size", type=float, default=10)
    ap.add_argument("--tables-5x1", action="store_true",
                    help="дублировать таблицы 5.x.1 в разделе таблиц")
    args = ap.parse_args()

    # Разворачиваем маски и убираем повторы, сохраняя порядок.
    sources = []
    for pattern in args.json:
        matches = (sorted(glob.glob(pattern))
                   if any(ch in pattern for ch in "*?[") else [pattern])
        if not matches:
            sys.exit("Файл не найден: %s" % pattern)
        for m in matches:
            m = os.path.abspath(m)
            if m not in sources:
                sources.append(m)
    if args.out and len(sources) != 1:
        sys.exit("--out допустим только при одном входном файле")
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    failed = 0
    for src in sources:
        if not os.path.exists(src):
            print("ПРОПУЩЕН (нет файла): %s" % src, file=sys.stderr)
            failed += 1
            continue
        if args.out:
            dst = os.path.abspath(args.out)
        elif args.out_dir:
            dst = os.path.join(os.path.abspath(args.out_dir),
                               os.path.splitext(os.path.basename(src))[0] + "_отчет.docx")
        else:
            dst = os.path.splitext(src)[0] + "_отчет.docx"
        try:
            with open(src, encoding="utf-8") as f:
                data = json.load(f, object_pairs_hook=OrderedDict)
            if "Содержимое стандарта" not in data:
                raise ValueError("нет ключа «Содержимое стандарта»")
            stats = build_report(
                data, dst, scope=args.scope, max_rows=args.max_rows,
                only=args.only, toc=args.toc, title=not args.no_title_page,
                portrait=args.portrait, base_size=args.font_size,
                tables_5x1=args.tables_5x1)
            print("Отчёт: %s" % dst)
            print("  %s: шкафов %d, комплектов %d, таблиц %d, строк %d, %.1f КБ" % (
                os.path.basename(src), stats["cabinets"], stats["complects"],
                stats["tables"], stats["rows"], os.path.getsize(dst) / 1024.0))
        except Exception as exc:
            print("ОШИБКА %s: %s" % (src, exc), file=sys.stderr)
            failed += 1
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
