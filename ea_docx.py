#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка стандарта EA в DOCX.

Строит документ Word по JSON стандарта (см. :mod:`ea_standard`): титул,
оглавление, разделы с текстом и таблицами. Строки таблиц берутся из шкафов
через :func:`ea_standard.table_view` — ровно то же, что показывает окно
«СТО (EA)…», поэтому документ и окно не расходятся.

Рисунок, у которого заполнено поле ``scheme`` (файл ФЛС редактора),
вставляется в документ картинкой: схема рендерится в PNG тем же кодом,
что и экспорт редактора (:mod:`logic_scheme_render`). Остальные рисунки
выводятся подписью (сами изображения остаются в исходном документе).

Если в папке стандартов (рядом с JSON или в ``EA/``) лежит ``template.docx``,
он берётся за основу: сохраняются его стили, колонтитулы и параметры
страницы, а содержимое строится заново. Номера разделов и подразделов в
заголовки не пишутся — их автоматически проставляет шаблон нумерацией
стилей «Заголовок 1» и «Заголовок 2».

Если в реквизите ``title_page`` указан DOCX титульного листа, он берётся
за основу без очистки: готовое содержимое остаётся первым, а сгенерированный
отчёт добавляется после него новой секцией (книжная A4, поля 1,5 см).
Колонтитулы титула в отчёт не переносятся: в верхнем колонтитуле новой
секции продолжается нумерация страниц, нижний остаётся пустым.

    python ea_docx.py --out "Отчет.docx"
    python ea_docx.py --file "EA/....json" --out "Отчет.docx" --max-rows 50
    python ea_docx.py --out "Отчет.docx" --no-toc
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import os
import re
import sys
import tempfile

import ea_standard as es
import ea_structure as st

try:
    from docx import Document
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Emu, Mm, Pt, RGBColor
    from docx.text.paragraph import Paragraph
except ImportError:                                   # pragma: no cover
    Document = None

FONT = "Times New Roman"
HEADER_FILL = "DCE6F1"
USABLE_CM = 26.7          # А4 в альбомной ориентации минус поля 1,5 см
TEMPLATE_NAME = "template.docx"
#: Реквизит стандарта с путём к DOCX, который должен открывать отчёт.
TITLE_PAGE_FIELD = "title_page"


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


def _cell(cell, text, size=10, bold=False, align=None):
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


def _available_cm(doc):
    """Ширина текста текущей секции: страница минус левое/правое поля."""
    section = doc.sections[-1]
    try:
        width = Emu(section.page_width - section.left_margin
                    - section.right_margin).cm
    except (TypeError, AttributeError):              # pragma: no cover
        return USABLE_CM
    return width if width > 1.0 else USABLE_CM


def _fixed_widths(headers, values, available=USABLE_CM):
    """Ширины из поля ``colums_width`` (мм) или None, если их нет.

    Пустой список означает «не задано» — тогда таблица ширится по
    содержимому. Число значений не обязательно равно числу колонок:
    лишние отбрасываются, недостающие дополняются расчётными.
    """
    widths = []
    for value in values or []:
        try:
            width = float(value)
        except (TypeError, ValueError):
            continue
        if width > 0:
            widths.append(width)
    if not widths:
        return None
    widths = widths[:len(headers)]
    if len(widths) < len(headers):
        rest = max(1.0, available - sum(widths))
        widths.extend(_widths(headers, [], rest)[len(widths):])
    return widths


def _hard_width(table, widths):
    """Зафиксировать общую ширину таблицы и тип разметки в XML."""
    tbl_pr = table._tbl.tblPr
    total_twips = int(round(sum(widths) * 1440.0 / 25.4))
    total = tbl_pr.find(qn("w:tblW"))
    if total is None:
        total = OxmlElement("w:tblW")
        tbl_pr.insert(0, total)
    total.set(qn("w:w"), str(total_twips))
    total.set(qn("w:type"), "dxa")
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        total.addnext(layout)
    layout.set(qn("w:type"), "fixed")


def _table(doc, headers, rows, size=10, max_rows=0, widths_mm=None):
    """Таблица с шапкой; возвращает число выведенных строк данных."""
    if not headers:
        return 0
    shown = rows[:max_rows] if max_rows else rows
    table = doc.add_table(rows=len(shown) + 1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    available = _available_cm(doc)
    widths = _fixed_widths(headers, widths_mm, available)
    fixed = widths is not None
    if not fixed:
        widths = _widths(headers, shown, available)
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
        value = Mm(width) if fixed else Cm(width)
        table.columns[index].width = value
        # Колонки Liberty/Word всё равно пересчитывают ширину ячеек,
        # поэтому жёсткую ширину проставляем и на каждой ячейке.
        for row in table.rows:
            row.cells[index].width = value
    if fixed:
        _hard_width(table, widths)
    return len(shown)


def _caption(doc, text, bookmark=None, bookmark_id=0,
             bold=True, italic=False):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.keep_with_next = True
    finish = (_bookmark(paragraph, bookmark, bookmark_id)
              if bookmark else None)
    run = paragraph.add_run(text)
    _font(run, 9, bold=bold, italic=italic)
    if finish is not None:
        finish()


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


def _heading(doc, text, level, numbered=True):
    """Заголовок уровня ``level``; номер ставит шаблон, а не текст.

    ``numbered=False`` отключает автонумерацию абзаца (``numId=0``) — для
    «Содержания» и разделов без номера вроде «Введения», иначе они сдвинули
    бы нумерацию разделов шаблона.
    """
    heading = doc.add_heading(level=level)
    run = heading.add_run(text)
    _font(run, {1: 14, 2: 12, 3: 11}.get(level, 11), bold=True)
    heading.paragraph_format.space_before = Pt(10)
    heading.paragraph_format.space_after = Pt(4)
    heading.paragraph_format.keep_with_next = True
    if not numbered:
        props = heading._p.get_or_add_pPr()
        props.get_or_add_numPr().get_or_add_numId().val = 0
    return heading


def _field(paragraph, instruction, result="Обновите поле (F9)"):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = result
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, instr, separate, text, end):
        run._r.append(element)
    return run


def _toc(doc):
    _heading(doc, "Содержание", 1, numbered=False)
    paragraph = doc.add_paragraph()
    _field(paragraph, r'TOC \o "1-2" \h \z \u')


def _page_number_in(part):
    """Поле PAGE в колонтитуле: номер продолжает нумерацию документа."""
    paragraph = part.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _field(paragraph, "PAGE")


def _page_number(section):
    _page_number_in(section.footer)


def _report_after_title(doc):
    """Секция отчёта после готового титульного DOCX.

    Страница — книжная A4 с полями 1,5 см. Колонтитулы титула (логотип,
    подпись отчёта) не наследуются: в верхнем колонтитуле новой секции
    стоит поле PAGE, поэтому нумерация продолжается от титула, а не
    начинается заново. ``titlePg`` убирается — иначе первая страница
    отчёта взяла бы «особый колонтитул первой страницы» титула; ``pgNumType``
    тоже, иначе унаследованный от титула сброс нумерации начал бы её с 1.
    """
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    for name in ("left_margin", "right_margin", "top_margin",
                 "bottom_margin"):
        setattr(section, name, Cm(1.5))
    for tag in ("w:titlePg", "w:pgNumType"):
        element = section._sectPr.find(qn(tag))
        if element is not None:
            section._sectPr.remove(element)
    section.header.is_linked_to_previous = False
    _page_number_in(section.header)
    section.footer.is_linked_to_previous = False
    return section


# ---------------------------------------------------------------------------
# Перекрестные ссылки на таблицы и рисунки
# ---------------------------------------------------------------------------
#: «Таблица 5.2», «табл. 5.2», «Рисунок 4.1», «рис. 4.1» и т. п.
#: Суффикс ``/#/0`` (либо полевый ``\# 0``) просит вывести только номер:
#: «Таблица 5.2/#/0» → «5.2»: REF-поле получает ``\#"0"``.
_REFERENCE_RE = re.compile(
    r"(?P<label>таблиц\w*|табл\.?|рисун\w*|рис\.?)\s+"
    r"(?P<number>\d+(?:\.\d+)*)"
    r"(?P<only>/#/0|\\#\s*\"?0\"?)?", re.I)


def _key_from_match(match):
    """Нормализованная ссылка из совпадения: (T|F, номер) или None."""
    if match is None:
        return None
    kind = "T" if match.group("label").lower().startswith("табл") else "F"
    return kind, match.group("number")


def _reference_key(text):
    """Нормализованная ссылка: (T|F, номер) или None."""
    return _key_from_match(_REFERENCE_RE.search(str(text or "")))


def _register_reference(references, reference):
    """Зарегистрировать подпись и вернуть (закладка, новая ли она)."""
    key = _reference_key(reference)
    if key is None:
        return None, False
    if key in references:
        return references[key], False
    base = "Ref%s_%s" % (key[0], key[1].replace(".", "_"))
    name = base
    index = 2
    while name in references.values():
        name = "%s_%d" % (base, index)
        index += 1
    references[key] = name
    return name, True


def _bookmark(paragraph, name, ident):
    """Закладка вокруг только что добавленного фрагмента абзаца."""
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(ident))
    start.set(qn("w:name"), name)
    paragraph._p.append(start)

    def finish():
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(ident))
        paragraph._p.append(end)

    return finish


def _copy_run_props(source, target):
    if source is None:
        return
    props = source._r.find(qn("w:rPr"))
    if props is not None:
        target._r.insert(0, deepcopy(props))


def _text_run(paragraph, text, template=None):
    run = paragraph.add_run(text)
    _copy_run_props(template, run)
    return run


def _link_references(doc, references, skip=0):
    """Заменить упоминания таблиц и рисунков на поля REF.

    Обрабатываются все абзацы тела документа, включая ячейки таблиц.
    ``skip`` — число первых абзацев готового титульного листа: их
    содержимое менять нельзя. Подписи с закладками пропускаются, чтобы
    ссылка не указывала сама на себя. Текст сохраняется как кэш поля —
    документ читаем и без обновления полей в Word.
    """
    if not references:
        return
    used_names = set(references.values())
    for index, element in enumerate(doc.element.body.iter(qn("w:p"))):
        if index < skip:
            continue
        markers = [item.get(qn("w:name"))
                   for item in element.findall(qn("w:bookmarkStart"))]
        if any(name in used_names for name in markers):
            continue
        paragraph = Paragraph(element, doc._body)
        text = paragraph.text
        if not text:
            continue
        matches = list(_REFERENCE_RE.finditer(text))
        if not matches:
            continue
        source_run = paragraph.runs[0] if paragraph.runs else None
        for run in list(paragraph.runs):
            run._element.getparent().remove(run._element)
        cursor = 0
        for match in matches:
            if match.start() > cursor:
                _text_run(paragraph, text[cursor:match.start()], source_run)
            name = references.get(_key_from_match(match))
            only_number = bool(match.group("only"))
            # Суффикс /#/0 убирается из видимого текста: остаётся только номер.
            visible = match.group("number") if only_number else match.group(0)
            if name:
                instruction = " REF %s \\h" % name
                if only_number:
                    instruction += r' \#"0"'
                field = _field(paragraph, instruction + " ", result=visible)
                _copy_run_props(source_run, field)
            else:
                _text_run(paragraph, visible, source_run)
            cursor = match.end()
        if cursor < len(text):
            _text_run(paragraph, text[cursor:], source_run)


def _setup(doc, layout=True):
    if layout:
        section = doc.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Cm(29.7)
        section.page_height = Cm(21.0)
        for name in ("left_margin", "right_margin"):
            setattr(section, name, Cm(1.5))
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        _page_number(section)
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(10)
    for level, size in ((1, 14), (2, 12), (3, 11)):
        try:
            style = doc.styles["Heading %d" % level]
        except KeyError:
            continue
        style.font.name = FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)


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


def _render_table(doc, data, table, max_rows, counters, references):
    headers, rows = es.table_view(data, table)
    reference = table.get("reference") or ""
    name = table.get("name") or ""
    if not headers:
        return
    bookmark, is_new = _register_reference(references, reference)
    _caption(doc, ("%s — %s" % (reference, name)).strip(" —"),
             bookmark if is_new else None, 1000 + len(references))
    counters["таблицы"] += 1
    counters["строки"] += _table(doc, headers, rows, max_rows=max_rows,
                                 widths_mm=table.get("colums_width") or [])


# ---------------------------------------------------------------------------
# Рисунки со схемами редактора
# ---------------------------------------------------------------------------
#: Максимальная ширина картинки схемы в документе, см (лист А4).
SCHEME_WIDTH_CM = 24.0
#: Форматы страницы, которые можно задать в поле «Формат» рисунка.
PAGE_FORMATS_CM = {"A5": (14.8, 21.0), "A4": (21.0, 29.7),
                   "A3": (29.7, 42.0)}
_LANDSCAPE_WORDS = {"альбомная", "альбом", "горизонтальная", "landscape", "l"}
_PORTRAIT_WORDS = {"книжная", "вертикальная", "portrait", "p"}


def _figure_page(figure):
    """Формат и ориентация рисунка из полей структуры или None."""
    page_format = str(figure.get("format") or "").strip().upper()
    orientation = str(figure.get("orientation") or "").strip().lower()
    if page_format not in PAGE_FORMATS_CM:
        page_format = ""
    if orientation in _LANDSCAPE_WORDS:
        landscape = True
    elif orientation in _PORTRAIT_WORDS:
        landscape = False
    else:
        landscape = None
    if not page_format and landscape is None:
        return None
    return page_format, landscape


def _apply_page(section, page_format, landscape):
    """Применить формат и ориентацию к секции документа."""
    width, height = PAGE_FORMATS_CM.get(page_format, (21.0, 29.7))
    if landscape is None:
        landscape = section.orientation == WD_ORIENT.LANDSCAPE
    section.orientation = (WD_ORIENT.LANDSCAPE if landscape
                           else WD_ORIENT.PORTRAIT)
    section.page_width = Cm(height if landscape else width)
    section.page_height = Cm(width if landscape else height)


def _page_snapshot(section):
    """Скопировать параметры страницы до вставки секции рисунка.

    ``Document.add_section()`` переиспользует последний ``sectPr``, поэтому
    ссылку на секцию сохранять нельзя — нужны именно атрибуты XML.
    """
    props = section._sectPr

    def attributes(element):
        return dict(element.attrib) if element is not None else None

    return attributes(props.pgSz), attributes(props.pgMar)


def _restore_page_setup(target, snapshot):
    """Восстановить параметры страницы из снимка."""
    size_attrs, margin_attrs = snapshot

    def apply(element, values):
        if values is None:
            return
        for name in list(element.attrib):
            if name not in values:
                del element.attrib[name]
        for name, value in values.items():
            element.set(name, value)

    apply(target._sectPr.get_or_add_pgSz(), size_attrs)
    if margin_attrs is not None:
        apply(target._sectPr.get_or_add_pgMar(), margin_attrs)


def _fit_picture(shape, section):
    """Вписать картинку в доступную область страницы."""
    target_width = min(int(Cm(SCHEME_WIDTH_CM)),
                       section.page_width - section.left_margin
                       - section.right_margin)
    available_height = (section.page_height - section.top_margin
                        - section.bottom_margin - int(Cm(1.5)))
    if available_height <= 0:
        available_height = shape.height
    if shape.width <= 0 or shape.height <= 0 or target_width <= 0:
        return
    scale = min(target_width / float(shape.width),
                available_height / float(shape.height))
    if scale > 0:
        shape.width = int(shape.width * scale)
        shape.height = int(shape.height * scale)


#: Готовые изображения вставляются в DOCX без рендера схемы.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _resolve_figure_file(reference):
    """Путь к файлу рисунка: относительный — от папки стандартов."""
    reference = str(reference or "").strip()
    if not reference:
        return ""
    if os.path.isabs(reference):
        return reference if os.path.isfile(reference) else ""
    path = os.path.join(es.folder(), reference)
    return path if os.path.isfile(path) else ""


def _scheme_image(doc, figure, errors=None):
    """Вставить картинку рисунка по полю ``figure["scheme"]``.

    Значение может быть готовым изображением (PNG/JPEG/BMP/GIF) или JSON-файлом
    схемы ФЛС: такой файл рендерится в PNG тем же кодом, что и экспорт
    редактора. Причины неудачи записываются в ``errors`` — раньше ошибки
    рендера молча терялись, и казалось, что JSON-схема «не вставляется».
    """
    label = str(figure.get("number") or figure.get("reference")
                or "без номера")

    def fail(reason):
        if errors is not None:
            errors.append("Рисунок %s: %s" % (label, reason))
        return False

    reference = str(figure.get("scheme") or "").strip()
    if not reference:
        return fail("поле «Файл схемы» пустое")
    path = _resolve_figure_file(reference)
    if not path:
        return fail("файл не найден: %s" % reference)
    direct = os.path.splitext(path)[1].lower() in IMAGE_SUFFIXES
    image_path, temporary = path, None
    if not direct:
        try:
            import logic_scheme_render as lsr
        except Exception as exc:
            return fail("не загружен рендер ФЛС: %s: %s"
                        % (type(exc).__name__, exc))
        handle, temporary = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        image_path = temporary
    try:
        if not direct:
            try:
                lsr.export_png_file(path, image_path)
            except Exception as exc:
                return fail("рендер JSON-схемы (%s): %s: %s"
                            % (os.path.basename(path), type(exc).__name__,
                               exc))
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        try:
            shape = run.add_picture(image_path)
            _fit_picture(shape, doc.sections[-1])
        except Exception as exc:
            paragraph._element.getparent().remove(paragraph._element)
            return fail("вставка изображения: %s: %s"
                        % (type(exc).__name__, exc))
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass
    return True


def _render_figure_block(doc, figure, references, counters, errors):
    """Картинка схемы и подпись, при необходимости на своей странице."""
    page = _figure_page(figure)
    original = _page_snapshot(doc.sections[-1]) if page else None
    if page:
        section = doc.add_section(WD_SECTION.NEW_PAGE)
        _apply_page(section, *page)
    # Сначала картинка схемы (если файл задан и читается), затем подпись.
    if _scheme_image(doc, figure, errors):
        counters["рисунки"] += 1
    reference = figure.get("reference") or "Рисунок"
    bookmark, is_new = _register_reference(references, reference)
    _caption(doc, "%s — %s" % (reference, figure.get("name") or ""),
             bookmark if is_new else None, 1000 + len(references),
             bold=False, italic=True)
    paragraph = doc.paragraphs[-1]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if original is not None:
        doc.add_section(WD_SECTION.NEW_PAGE)
        _restore_page_setup(doc.sections[-1], original)


def _render_item(doc, data, kind, item, max_rows, counters, references,
                 errors):
    """Вывести один элемент контейнера: пункт, подпункт, таблицу, рисунок."""
    if kind == "table":
        _render_table(doc, data, item, max_rows, counters, references)
    elif kind == "figure":
        _render_figure_block(doc, item, references, counters, errors)
    else:
        _render_clause(doc, data, item, max_rows, counters, references,
                       errors)


def _render_clause(doc, data, clause, max_rows, counters, references, errors):
    """Пункт или подпункт: номер с текстом и вложенные элементы по порядку."""
    number = str(clause.get("number") or "")
    lines = _clause_lines(clause.get("content"))
    if lines:
        lines[0] = ("%s %s" % (number, lines[0])).strip()
    elif number:
        lines = [number]
    for line in lines:
        _body(doc, line)
    for kind, item in st.ordered_items(clause):
        _render_item(doc, data, kind, item, max_rows, counters, references,
                     errors)


def _render_container(doc, data, container, level, max_rows, counters,
                      references, errors):
    _text_block(doc, container.get("content"))
    for kind, item in st.ordered_items(container):
        _render_item(doc, data, kind, item, max_rows, counters, references,
                     errors)


def _render_sections(doc, data, max_rows, counters, references, errors):
    """Разделы и подразделы: в тексте заголовка только название.

    Номер раздела и подраздела не выводится — его автоматически проставляет
    шаблон Word через нумерацию стилей «Заголовок 1» и «Заголовок 2».
    """
    for section in es.sections(data):
        number = str(section.get("number") or "").strip()
        header = str(section.get("header") or "").strip()
        if not header and not number:
            continue
        _heading(doc, header or number, 1,
                 numbered=bool(number) and bool(header))
        counters["разделы"] += 1
        _render_container(doc, data, section, 2, max_rows, counters,
                          references, errors)
        for sub in section.get("subsections") or []:
            sub_number = str(sub.get("number") or "").strip()
            title = str(sub.get("header") or "").strip()
            if not title and not sub_number:
                continue
            _heading(doc, title or sub_number, 2,
                     numbered=bool(sub_number) and bool(title))
            _render_container(doc, data, sub, 3, max_rows, counters,
                              references, errors)


def template_path(folder=None):
    """Путь к ``template.docx`` рядом с JSON или в папке стандартов."""
    candidates = []
    if folder:
        candidates.append(os.path.join(folder, TEMPLATE_NAME))
    candidates.append(os.path.join(es.folder(), TEMPLATE_NAME))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def title_page_path(data, folder=None):
    """Путь к DOCX титульного листа из реквизитов стандарта.

    Относительный путь ищется рядом с выходным файлом и в папке
    стандартов — так ссылка, выбранная в редакторе, переживает перенос
    проекта. Пустой реквизит означает обычную выгрузку.
    """
    raw = str((data or {}).get(TITLE_PAGE_FIELD) or "").strip()
    if not raw:
        return None
    candidates = []
    if os.path.isabs(raw):
        candidates.append(raw)
    else:
        if folder:
            candidates.append(os.path.join(folder, raw))
        candidates.append(os.path.join(es.folder(), raw))
        candidates.append(raw)
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    raise DocxError("нет файла титульного листа: %s" % raw)


def _clear_body(doc):
    """Убрать содержимое шаблона, оставив параметры последней секции."""
    body = doc.element.body
    for child in list(body.iterchildren()):
        if child.tag == qn("w:sectPr"):
            continue
        body.remove(child)


def build(data, path, toc=True, max_rows=0):
    """Записать стандарт в DOCX. Возвращает счётчики выведенного."""
    if Document is None:
        raise DocxError("не установлен python-docx: "
                        "python -m pip install python-docx")
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        raise DocxError("нет папки: %s" % folder)
    title = title_page_path(data, folder)
    skip_paragraphs = 0
    if title:
        # Готовый титульный лист остаётся как есть; сгенерированный отчёт
        # начинается новой секцией сразу после него.
        doc = Document(title)
        skip_paragraphs = sum(1 for _ in doc.element.body.iter(qn("w:p")))
        _setup(doc, layout=False)
        _report_after_title(doc)
    else:
        template = template_path(folder)
        if template:
            doc = Document(template)
            _clear_body(doc)
            _setup(doc, layout=False)
        else:
            doc = Document()
            _setup(doc)
    stats = es.stats(data)
    counters = {"разделы": 0, "таблицы": 0, "строки": 0,
                "рисунки": 0, "ошибки_рисунков": [],
                "титульный_лист": title or ""}
    references = {}
    figure_errors = counters["ошибки_рисунков"]
    if not title:
        _title_page(doc, data, stats)
    if toc:
        _toc(doc)
        doc.add_page_break()
    _render_sections(doc, data, max_rows, counters, references, figure_errors)
    _link_references(doc, references, skip=skip_paragraphs)
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
    args = parser.parse_args(argv)

    path = args.file or es.default_base()
    if not path:
        print("Нет стандартов в папке %s" % es.folder())
        return 1
    try:
        data = es.load(path)
        counters = build(data, args.out, toc=not args.no_toc,
                         max_rows=args.max_rows)
    except (DocxError, OSError, ValueError) as exc:
        print("Ошибка: %s" % exc)
        return 1
    print("Стандарт: %s" % path)
    print("Файл: %s (%.1f КБ)" % (args.out, counters["размер"] / 1024.0))
    print("Разделов: %d, таблиц: %d, строк: %d, рисунков: %d"
          % (counters["разделы"], counters["таблицы"], counters["строки"],
             counters["рисунки"]))
    for problem in counters.get("ошибки_рисунков") or []:
        print("Не вставлен: %s" % problem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
