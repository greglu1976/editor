#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка стандарта EA в DOCX.

Строит документ Word по JSON стандарта (см. :mod:`ea_standard`): титул,
оглавление, разделы с текстом и таблицами, приложение с карточками шкафов.
Строки таблиц берутся из шкафов через :func:`ea_standard.table_view` — ровно
то же, что показывает окно «СТО (EA)…», поэтому документ и окно не расходятся.

Рисунки в JSON хранят только номер и название (сами изображения остаются в
исходном документе), поэтому в DOCX выводится подпись рисунка.

    python ea_docx.py --out "Отчет.docx"
    python ea_docx.py --file "EA/....json" --out "Отчет.docx" --max-rows 50
    python ea_docx.py --out "Отчет.docx" --no-cabinets --no-toc
"""

from __future__ import annotations

import argparse
import os
import sys

import ea_standard as es

try:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError:                                   # pragma: no cover
    Document = None

FONT = "Times New Roman"
HEADER_FILL = "DCE6F1"
USABLE_CM = 26.7          # А4 в альбомной ориентации минус поля 1,5 см


class DocxError(Exception):
    """Ошибка выгрузки (нет python-docx, некуда писать)."""


# ---------------------------------------------------------------------------
# Оформление
# ---------------------------------------------------------------------------
def _font(run, size=None, bold=None, italic=None):
    """Оформление фрагмента; шрифт и кегль 10 уже заданы стилем."""
    if size and size != 10:
        run.font.size = Pt(size)
    if bold:
        run.bold = True
    if italic:
        run.italic = True


def _cell(cell, text, size=8, bold=False, align=None):
    paragraph = cell.paragraphs[0]
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    run = paragraph.add_run(str(text or ""))
    _font(run, size, bold)


def _shade(cell, color=HEADER_FILL):
    props = cell._element.get_or_add_tcPr()
    fill = OxmlElement("w:shd")
    fill.set(qn("w:val"), "clear")
    fill.set(qn("w:color"), "auto")
    fill.set(qn("w:fill"), color)
    props.append(fill)


def _repeat_header(row):
    props = row._tr.get_or_add_trPr()
    flag = OxmlElement("w:tblHeader")
    flag.set(qn("w:val"), "true")
    props.append(flag)


def _widths(headers, rows, available=USABLE_CM):
    """Ширина колонок по содержимому, но с разумными пределами."""
    widths = []
    for index, header in enumerate(headers):
        length = max([len(str(header))] + [
            len(str(row[index])) for row in rows[:120] if index < len(row)])
        widths.append(min(9.0, max(1.6, length * 0.18 + 0.6)))
    scale = available / sum(widths)
    return [width * scale for width in widths]


def _table(doc, headers, rows, size=8, max_rows=0):
    """Таблица с шапкой; возвращает число выведенных строк данных."""
    if not headers:
        return 0
    shown = rows[:max_rows] if max_rows else rows
    table = doc.add_table(rows=len(shown) + 1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = _widths(headers, shown)
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        _cell(cell, header, size, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _shade(cell)
    _repeat_header(table.rows[0])
    for row, values in zip(table.rows[1:], shown):
        for index in range(len(headers)):
            _cell(row.cells[index],
                  values[index] if index < len(values) else "", size)
    for index, width in enumerate(widths):
        table.columns[index].width = Cm(width)
    return len(shown)


def _caption(doc, text):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    _font(run, 9, bold=True)


def _body(doc, text):
    """Абзац основного текста: по ширине, с красной строкой."""
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    _font(run, 10)


def _text_block(doc, content):
    for line in str(content or "").split("\n"):
        line = line.strip()
        if line:
            _body(doc, line)


def _clause_lines(content):
    """Строки пункта: переносы внутри абзаца склеиваются, список — нет.

    В JSON строки пришли из PDF: часть — настоящие абзацы и пункты списка,
    часть — жёсткие переносы. Строка, начинающаяся со строчной буквы или
    скобки, продолжает предыдущую; строка с ««» или тире — новый элемент.
    """
    lines = [line.strip() for line in str(content or "").split("\n")
             if line.strip()]
    result = []
    for line in lines:
        continues = line[:1].islower() or line[:1] in "(,;:»"
        if result and continues and not result[-1].endswith(":"):
            result[-1] = result[-1] + " " + line
        else:
            result.append(line)
    return result


def _heading(doc, text, level):
    heading = doc.add_heading(level=level)
    run = heading.add_run(text)
    _font(run, {1: 14, 2: 12, 3: 11}.get(level, 11), bold=True)
    heading.paragraph_format.space_before = Pt(10)
    heading.paragraph_format.space_after = Pt(4)
    heading.paragraph_format.keep_with_next = True
    return heading


def _field(paragraph, instruction):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "Обновите поле (F9)"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instr, separate, text, end):
        run._r.append(element)


def _toc(doc):
    _heading(doc, "Содержание", 1)
    paragraph = doc.add_paragraph()
    _field(paragraph, r'TOC \o "1-2" \h \z \u')


def _page_number(section):
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _field(paragraph, "PAGE")


def _setup(doc):
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Cm(29.7)
    section.page_height = Cm(21.0)
    for name in ("left_margin", "right_margin"):
        setattr(section, name, Cm(1.5))
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10)
    for level, size in ((1, 14), (2, 12), (3, 11)):
        style = doc.styles["Heading %d" % level]
        style.font.name = FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
    _page_number(section)


# ---------------------------------------------------------------------------
# Содержимое
# ---------------------------------------------------------------------------
def _title_page(doc, data, stats):
    for _ in range(6):
        doc.add_paragraph()
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(paragraph.add_run(data.get("name", "")), 18, bold=True)
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(paragraph.add_run(data.get("code", "")), 14)
    doc.add_paragraph()
    for label, value in (("Организация", data.get("property")),
                         ("Дата введения", data.get("date"))):
        if not value:
            continue
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font(paragraph.add_run("%s: %s" % (label, value)), 12)
    doc.add_paragraph()
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(paragraph.add_run(
        "Разделов: %d · таблиц: %d · шкафов: %d"
        % (stats["разделы"], stats["таблицы"], stats["шкафы"])), 10,
        italic=True)
    doc.add_page_break()


def _render_table(doc, data, table, max_rows, counters):
    headers, rows = es.table_view(data, table)
    reference = table.get("reference") or ""
    name = table.get("name") or ""
    if not headers:
        return
    _caption(doc, ("%s — %s" % (reference, name)).strip(" —"))
    counters["таблицы"] += 1
    counters["строки"] += _table(doc, headers, rows, max_rows=max_rows)


def _render_container(doc, data, container, level, max_rows, counters):
    _text_block(doc, container.get("content"))
    for table in container.get("tables") or []:
        _render_table(doc, data, table, max_rows, counters)
    for figure in container.get("figures") or []:
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font(paragraph.add_run(
            "%s — %s" % (figure.get("reference") or "Рисунок",
                         figure.get("name") or "")), 9, italic=True)
    for clause in container.get("clauses") or []:
        number = clause.get("number") or ""
        lines = _clause_lines(clause.get("content"))
        if lines:
            lines[0] = ("%s %s" % (number, lines[0])).strip()
        elif number:
            lines = [number]
        for line in lines:
            _body(doc, line)
        for table in clause.get("tables") or []:
            _render_table(doc, data, table, max_rows, counters)


def _render_sections(doc, data, max_rows, counters):
    for section in es.sections(data):
        number = str(section.get("number") or "").strip()
        header = str(section.get("header") or "").strip()
        if not header and not number:
            continue
        _heading(doc, ("%s %s" % (number, header)).strip(), 1)
        counters["разделы"] += 1
        _render_container(doc, data, section, 2, max_rows, counters)
        for sub in section.get("subsections") or []:
            title = ("%s %s" % (sub.get("number") or "",
                                sub.get("header") or "")).strip()
            if title:
                _heading(doc, title, 2)
            _render_container(doc, data, sub, 3, max_rows, counters)


def _render_cabinets(doc, data):
    items = es.cabinets(data)
    if not items:
        return
    doc.add_page_break()
    _heading(doc, "Приложение. Шкафы стандарта", 1)
    for item in items:
        _heading(doc, "%s — %s" % (item.get("cypher", ""),
                                   item.get("name", "")), 2)
        _table(doc, ["Параметр", "Значение"], es.cabinet_card(item), size=9)
        kits = item.get("kits") or []
        if not kits:
            continue
        _caption(doc, "Комплекты шкафа")
        rows = []
        for kit in kits:
            ieds = kit.get("ieds") or []
            functions = []
            for ied in ieds:
                for function in ied.get("functions") or []:
                    name = (function.get("russian_path")
                            or function.get("name") or "")
                    if function.get("isMainFunction") and name \
                            and name not in functions:
                        functions.append(name)
            rows.append([kit.get("number", ""), kit.get("type", ""),
                         kit.get("description", ""),
                         ", ".join("ИЭУ %s" % ied.get("number", "")
                                   for ied in ieds) or "—",
                         ", ".join(functions) or "—"])
        _table(doc, ["№", "Тип", "Описание", "ИЭУ", "Основные функции"],
               rows, size=8)


def build(data, path, toc=True, cabinets=True, max_rows=0):
    """Записать стандарт в DOCX. Возвращает счётчики выведенного."""
    if Document is None:
        raise DocxError("не установлен python-docx: "
                        "python -m pip install python-docx")
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        raise DocxError("нет папки: %s" % folder)
    doc = Document()
    _setup(doc)
    stats = es.stats(data)
    counters = {"разделы": 0, "таблицы": 0, "строки": 0}
    _title_page(doc, data, stats)
    if toc:
        _toc(doc)
        doc.add_page_break()
    _render_sections(doc, data, max_rows, counters)
    if cabinets:
        _render_cabinets(doc, data)
    doc.save(path)
    counters["размер"] = os.path.getsize(path)
    return counters


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Выгрузка стандарта EA в DOCX")
    parser.add_argument("--file", help="JSON стандарта (по умолчанию первый)")
    parser.add_argument("--out", required=True, help="куда записать DOCX")
    parser.add_argument("--max-rows", type=int, default=0,
                        help="не более N строк в таблице (0 — все)")
    parser.add_argument("--no-toc", action="store_true",
                        help="без оглавления")
    parser.add_argument("--no-cabinets", action="store_true",
                        help="без приложения со шкафами")
    args = parser.parse_args(argv)

    path = args.file or es.default_base()
    if not path:
        print("Нет стандартов в папке %s" % es.folder())
        return 1
    try:
        data = es.load(path)
        counters = build(data, args.out, toc=not args.no_toc,
                         cabinets=not args.no_cabinets,
                         max_rows=args.max_rows)
    except (DocxError, OSError, ValueError) as exc:
        print("Ошибка: %s" % exc)
        return 1
    print("Стандарт: %s" % path)
    print("Файл: %s (%.1f КБ)" % (args.out, counters["размер"] / 1024.0))
    print("Разделов: %d, таблиц: %d, строк: %d"
          % (counters["разделы"], counters["таблицы"], counters["строки"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
