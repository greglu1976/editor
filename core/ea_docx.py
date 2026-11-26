#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Выгрузка стандарта EA в DOCX.

Строит документ Word по JSON стандарта (см. :mod:`ea_standard`): титул,
оглавление, разделы с текстом и таблицами. Строки таблиц берутся из шкафов
через :func:`ea_standard.table_view` — ровно то же, что показывает окно
«СТО (EA)…», поэтому документ и окно не расходятся. Двухуровневая шапка
таблицы выводится двумя строками с объединением одинаковых ячеек
(:func:`ea_standard.table_header_rows`).

Рисунок, у которого заполнено поле ``scheme`` (файл ФЛС редактора),
вставляется в документ картинкой: схема рендерится в PNG тем же кодом,
что и экспорт редактора (:mod:`logic_scheme_render`). Остальные рисунки
выводятся подписью (сами изображения остаются в исходном документе).

Если в папке стандартов (рядом с JSON или в ``EA/``) лежит ``template.docx``,
он берётся за основу: сохраняются его стили, колонтитулы и параметры
страницы, а содержимое строится заново. Оформление основного текста берётся
из поля ``text_style`` (по умолчанию «Обычный»), заголовка содержания — из
поля ``toc_style`` (по умолчанию «Заголовок оглавления»), заголовков — из
поля ``header_style`` раздела/подраздела, подписей — из стилей «ДОК Таблица
Название», «ДОК Рисунок Название» и их приложенческих вариантов; номер
проставляет нумерация стиля, а если её нет — нумерация заголовков шаблона
(1, 1.1, …).

Перекрёстные ссылки: упоминания «Таблица 5.2/#/0» и метки ``\ref{метка}``
(поле ``ref`` таблицы, рисунка, раздела или подраздела) превращаются в поля
Word `REF … \h`. Метки разбирает :mod:`ea_schema`. У подписи
таблицы/рисунка закладка охватывает только номер (ссылка ещё и кликабельна),
у раздела номер объявляет поле SET в начале отчёта — поэтому REF возвращает
один номер, а не весь текст подписи или заголовка. Числовой переключатель
``\#"0"`` не ставится: Word применяет его к значению закладки как к числу и
при обновлении полей (F9) портит номер («5.1» → «1»).

Если в реквизите ``title_page`` указан DOCX титульного листа, он берётся
за основу без очистки: готовое содержимое остаётся первым, а сгенерированный
отчёт добавляется после него новой секцией (книжная A4, поля наследуются от
последней секции титула).
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

import ea_schema as sc
import ea_standard as es
import ea_structure as st

try:
    from docx import Document
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.oxml.table import ST_Merge
    from docx.shared import Cm, Emu, Mm, Pt, RGBColor
    from docx.table import _Cell
    from docx.text.paragraph import Paragraph
except ImportError:                                   # pragma: no cover
    Document = None

FONT = "Times New Roman"
HEADER_FILL = "DCE6F1"
USABLE_CM = 26.7          # А4 в альбомной ориентации минус поля 1,5 см
TEMPLATE_NAME = "template.docx"
#: Нумерация заголовков шаблона (numId 49): 1, 1.1, 1.1.1.
HEADING_NUM_ID = 49
#: Стили подписей таблиц и рисунков из template.docx.
TABLE_CAPTION_STYLE = "ДОК Таблица Название"
FIGURE_CAPTION_STYLE = "ДОК Рисунок Название"
APPENDIX_TABLE_CAPTION_STYLE = "ДОК ПРИЛ Таблица Название"
APPENDIX_FIGURE_CAPTION_STYLE = "ДОК ПРИЛ Рисунок Название"
#: Разрежение надписи «Таблица»/«Рисунок» в подписи, twips (1 пт).
CAPTION_LABEL_SPACING = 20
_CAPTION_LABEL = re.compile(r"^(Таблица|Рисунок)\b")
#: Реквизит стандарта с путём к DOCX, который должен открывать отчёт.
TITLE_PAGE_FIELD = "title_page"
#: Реквизит со стилем основного текста (по умолчанию — «Обычный»).
TEXT_STYLE_FIELD = "text_style"
#: Реквизит со стилем заголовка «Содержание».
TOC_STYLE_FIELD = "toc_style"
#: Стиль заголовка оглавления по умолчанию (в Word — «Заголовок оглавления»).
TOC_STYLE = "Заголовок оглавления"
#: Русские имена стилей Word, которые python-docx знает по-английски.
STYLE_ALIASES = {"обычный": "Normal", "normal": "Normal",
                 "заголовок оглавления": "TOC Heading",
                 "toc heading": "TOC Heading",
                 "заголовок 1": "Heading 1", "заголовок 2": "Heading 2",
                 "заголовок 3": "Heading 3"}


class DocxError(Exception):
    """Ошибка выгрузки (нет python-docx, некуда писать)."""


# ---------------------------------------------------------------------------
# Оформление
# ---------------------------------------------------------------------------
def _font(run, size=None, bold=None, italic=None):
    """Оформление фрагмента; кегль задаётся явно, стиль абзаца не меняется."""
    if size:
        run.font.size = Pt(size)
    if bold:
        run.bold = True
    if italic:
        run.italic = True


def _letter_spacing(run, twips):
    """Разрежение символов фрагмента (``w:spacing``), в twips."""
    if not twips:
        return
    props = run._r.get_or_add_rPr()
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:val"), str(int(twips)))
    # В rPr порядок элементов задан схемой: spacing идёт после color и
    # перед w/kern/sz, иначе Word может проигнорировать разрежение.
    props.insert_element_before(
        spacing, "w:w", "w:kern", "w:position", "w:sz", "w:szCs",
        "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText",
        "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
        "w:eastAsianLayout", "w:specVanish", "w:oMath")


def _paragraph_style(doc, name):
    """Стиль абзаца из шаблона по имени; None, если стиля нет.

    Русское имя «Обычный» python-docx не находит: стиль называется
    ``Normal``. Алиасы из :data:`STYLE_ALIASES` переводят такие имена, а
    поиск без учёта регистра — варианты написания.
    """
    name = str(name or "").strip()
    if not name:
        return None
    candidates = [name, STYLE_ALIASES.get(name.casefold(), "")]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            style = doc.styles[candidate]
        except KeyError:
            continue
        try:
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                return style
        except AttributeError:                      # pragma: no cover
            continue
    for style in doc.styles:
        try:
            if (style.type == WD_STYLE_TYPE.PARAGRAPH
                    and str(style.name or "").casefold() == name.casefold()):
                return style
        except AttributeError:                      # pragma: no cover
            continue
    return None


def _style_numbering(style):
    """(numId, ilvl) из стиля или его basedOn; None, если нумерации нет."""
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        props = style.element.find(qn("w:pPr"))
        num = props.find(qn("w:numPr")) if props is not None else None
        if num is not None:
            num_id = num.find(qn("w:numId"))
            level = num.find(qn("w:ilvl"))
            value = num_id.get(qn("w:val")) if num_id is not None else None
            if value not in (None, "0"):
                return value, (level.get(qn("w:val"))
                               if level is not None else "0")
        style = style.base_style
    return None


def _set_numbering(paragraph, num_id, level="0"):
    """Задать нумерацию абзаца явно, поверх стиля."""
    num = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num.get_or_add_ilvl().val = int(level)
    num.get_or_add_numId().val = int(num_id)


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


def _min_widths(headers):
    """Минимальная ширина колонки, чтобы не рвать слова в шапке."""
    widths = []
    for header in headers:
        words = re.split(r"[\s/]+", str(header or ""))
        longest = max((len(word) for word in words), default=1)
        widths.append(min(2.5, max(0.9, longest * 0.24 + 0.55)))
    return widths


def _fit_minimums(widths, minimums):
    """Подтянуть узкие колонки до минимума за счёт широких."""
    deficit = sum(max(0.0, low - value)
                  for value, low in zip(widths, minimums))
    excess = sum(max(0.0, value - low)
                 for value, low in zip(widths, minimums))
    if deficit <= 0.0 or excess <= 0.0:
        return widths
    if deficit >= excess:
        # Минимумы не помещаются в ширину текста — сжимаем их пропорционально.
        total = sum(widths)
        minimum_total = sum(minimums)
        return [low * total / minimum_total for low in minimums]
    factor = max(0.0, (excess - deficit) / excess)
    return [low if value <= low else low + (value - low) * factor
            for value, low in zip(widths, minimums)]


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


def _body_cell(cell, text, size=10):
    """Текст объединённой ячейки — один раз, без повторов."""
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    paragraph = cell.paragraphs[0]
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    _font(paragraph.add_run(str(text or "")), size)


def _has_text(text):
    """В значении есть буквы или цифры — только такие ячейки объединяем."""
    return any(char.isalnum() for char in str(text or ""))


def _merge_enabled(table):
    """Поле таблицы ``merge_cells``: по умолчанию объединение включено."""
    value = (table or {}).get("merge_cells", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "нет", "false", "no")
    return bool(value)


def _body_merges(rows, columns):
    """Прямоугольники одинаковых соседних ячеек строк данных.

    Одинаковые значения сливаются по горизонтали, а если та же группа
    повторяется в следующей строке — и по вертикали. Объединяются только
    ячейки с текстом: прочерки, стрелки и кавычки («-», «>>», «»») остаются
    отдельными, иначе пропадает сетка таблицы. Возвращает
    ``(r1, c1, r2, c2, текст)`` — границы областей и их значение.
    """
    matrix = []
    for values in rows:
        matrix.append([str(values[index] or "").strip()
                       if index < len(values) else ""
                       for index in range(columns)])
    regions = []
    previous = {}
    for row_index, values in enumerate(matrix):
        current = {}
        for start, end, text in _header_groups(values):
            if not _has_text(text):
                continue
            key = (start, end, text)
            region = previous.get(key)
            if region is not None:
                regions[region][2] = row_index
                current[key] = region
            else:
                current[key] = len(regions)
                regions.append([row_index, start, row_index, end, text])
        previous = current
    return [tuple(region) for region in regions]


def _merge_region(table, top, left, bottom, right, text, size=10):
    """Слить прямоугольник ячеек прямо в XML.

    ``_Cell.merge`` строит объединение через ``_grow_to`` и на больших
    таблицах работает квадратично, поэтому ``gridSpan`` и ``vMerge``
    проставляются на месте: лишние ячейки строки удаляются, у нижних
    остаётся пустой абзац.
    """
    span = right - left + 1
    top_tc = None
    for row_index in range(top, bottom + 1):
        tc = table.rows[row_index]._tr.tc_at_grid_offset(left)
        if row_index == top:
            top_tc = tc
        while tc.grid_span < span:
            following = tc._next_tc
            if following is None:
                break
            tc.grid_span = tc.grid_span + following.grid_span
            following._remove()
        if bottom > top:
            tc.vMerge = (ST_Merge.RESTART if row_index == top
                         else ST_Merge.CONTINUE)
        if row_index > top:
            tc.clear_content()
            tc.add_p()
    # Обёртка над уже найденной ячейкой: table.cell() пересобирает всю
    # сетку таблицы и на тысячах объединений заметно тормозит.
    _body_cell(_Cell(top_tc, table), text, size)


def _merge_body(table, offset, rows, columns, size=10):
    """Объединить одинаковые ячейки строк данных (пункт 46)."""
    for r1, c1, r2, c2, text in _body_merges(rows, columns):
        if (r1, c1) == (r2, c2):
            continue
        _merge_region(table, offset + r1, c1, offset + r2, c2, text, size)


def _header_cell(cell, text, size=10):
    """Подпись шапки в (возможно, объединённой) ячейке."""
    paragraphs = cell.paragraphs
    for extra in paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    paragraph = cell.paragraphs[0]
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    _cell(cell, text, size, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)


def _header_groups(row):
    """Соседние одинаковые ячейки шапки: ``[начало, конец, текст]``."""
    groups = []
    index = 0
    while index < len(row):
        text = str(row[index] or "").strip()
        end = index + 1
        while text and end < len(row) \
                and str(row[end] or "").strip() == text:
            end += 1
        groups.append([index, end - 1, text])
        index = end
    return groups


def _header_merges(header_rows):
    """Объединения двухуровневой шапки: ``(r1, c1, r2, c2, текст)``.

    Одинаковые соседние подписи верхнего яруса объединяются по горизонтали.
    Если подпись повторяется и во втором ярусе, ячейки сливаются по
    вертикали (подпись занимает оба яруса).
    """
    top, bottom = header_rows
    top_groups = _header_groups(top)
    bottom_groups = _header_groups(bottom)
    bottom_by_start = {group[0]: group for group in bottom_groups}
    used = set()
    merges = []
    for start, end, text in top_groups:
        match = bottom_by_start.get(start)
        if text and match is not None \
                and match[1] == end and match[2] == text:
            merges.append((0, start, 1, end, text))
            used.add(start)
        else:
            merges.append((0, start, 0, end, text))
    for start, end, text in bottom_groups:
        if start not in used:
            merges.append((1, start, 1, end, text))
    return merges


def _two_level_header(table, header_rows, size=10):
    """Собрать двухуровневую шапку с объединением одинаковых ячеек."""
    width = len(table.columns)
    top = [str(header_rows[0][index])
           if index < len(header_rows[0]) else "" for index in range(width)]
    bottom = [str(header_rows[1][index])
              if index < len(header_rows[1]) else "" for index in range(width)]
    merges = _header_merges([top, bottom])
    for r1, c1, r2, c2, _text in merges:
        if (r1, c1) != (r2, c2):
            table.cell(r1, c1).merge(table.cell(r2, c2))
    for r1, c1, _r2, _c2, text in merges:
        cell = table.cell(r1, c1)
        _header_cell(cell, text, size)
        _shade(cell)


def _header_widths(header_rows, headers):
    """Подписи для расчёта ширины: самая длинная ячейка каждого столбца."""
    if len(header_rows) < 2:
        return headers
    result = []
    for index, header in enumerate(headers):
        parts = [str(row[index]).strip() for row in header_rows
                 if index < len(row) and str(row[index]).strip()]
        result.append(max(parts, key=len) if parts else str(header))
    return result


def _table_style(doc, name):
    """Стиль таблицы из шаблона по имени; None, если стиля нет."""
    name = str(name or "").strip()
    if not name:
        return None
    try:
        style = doc.styles[name]
    except KeyError:
        return None
    try:
        return name if style.type == WD_STYLE_TYPE.TABLE else None
    except AttributeError:                          # pragma: no cover
        return None


def _table(doc, headers, rows, size=10, max_rows=0, widths_mm=None,
           header_rows=None, style=None, merge=True):
    """Таблица с шапкой; возвращает число выведенных строк данных."""
    if not headers:
        return 0
    header_rows = [list(row) for row in (header_rows or [headers])]
    shown = rows[:max_rows] if max_rows else rows
    table = doc.add_table(rows=len(shown) + len(header_rows),
                          cols=len(headers))
    table.style = _table_style(doc, style) or "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    available = _available_cm(doc)
    widths = _fixed_widths(headers, widths_mm, available)
    fixed = widths is not None
    if not fixed:
        width_headers = _header_widths(header_rows, headers)
        widths = _fit_minimums(
            _widths(width_headers, shown, available),
            _min_widths(width_headers))
    if len(header_rows) > 1:
        _two_level_header(table, header_rows, size)
        for row in table.rows[:len(header_rows)]:
            _repeat_header(row)
    else:
        for index, header in enumerate(headers):
            cell = table.rows[0].cells[index]
            _cell(cell, header, size, bold=True,
                  align=WD_ALIGN_PARAGRAPH.CENTER)
            _shade(cell)
        _repeat_header(table.rows[0])
    for row, values in zip(table.rows[len(header_rows):], shown):
        for index in range(len(headers)):
            _cell(row.cells[index],
                  values[index] if index < len(values) else "", size)
    # Пункт 46: одинаковые значения по горизонтали и вертикали сливаются.
    if merge:
        _merge_body(table, len(header_rows), shown, len(headers), size)
    for index, width in enumerate(widths):
        unit = Mm if fixed else Cm
        table.columns[index].width = unit(width)
    # Колонки Liberty/Word всё равно пересчитывают ширину ячеек,
    # поэтому жёсткую ширину проставляем и на каждой ячейке. Обходим сетку
    # один раз: `row.cells` пересобирает её целиком и на больших таблицах
    # работает квадратично.
    columns = len(widths)
    cells = table._cells
    for position, cell in enumerate(cells):
        index = position % columns
        if index and cells[position - 1]._tc is cell._tc:
            continue
        # У объединённой ячейки ширина — сумма её колонок.
        cell.width = unit(sum(widths[index:index + cell.grid_span]))
    if fixed:
        _hard_width(table, widths)
    return len(shown)


def _caption_run(paragraph, text, size, bold, italic):
    """Фрагмент подписи; слова «Таблица»/«Рисунок» — с разрежением."""
    if not text:
        return
    match = _CAPTION_LABEL.match(text)
    if match:
        run = paragraph.add_run(match.group(1))
        _font(run, size, bold=bold, italic=italic)
        _letter_spacing(run, CAPTION_LABEL_SPACING)
        text = text[match.end():]
        if not text:
            return
    _font(paragraph.add_run(text), size, bold=bold, italic=italic)


def _caption(doc, text, bookmark=None, bookmark_id=0,
             bold=True, italic=False, number="", style=None):
    """Подпись таблицы или рисунка.

    Закладка охватывает только номер в заголовке подписи, а не весь текст:
    тогда поле REF возвращает ровно номер («5.2»). Имя и остальная подпись
    остаются вне закладки.

    ``style`` — стиль подписи из шаблона (поле таблицы/рисунка). У этих
    стилей своя автонумерация «Таблица N —»; она выключена, потому что номер
    уже входит в текст подписи и должен совпадать с JSON и закладкой.
    """
    paragraph = doc.add_paragraph()
    custom = _paragraph_style(doc, style)
    if custom is not None:
        paragraph.style = custom
        _set_numbering(paragraph, 0)
        size = bold = italic = None
    else:
        paragraph.paragraph_format.space_before = Pt(6)
        paragraph.paragraph_format.space_after = Pt(2)
        size = 9
    paragraph.paragraph_format.keep_with_next = True
    head, separator, tail = str(text).partition(" — ")
    pattern = (re.compile(r"(?<![\d.])%s(?![\d.])" % re.escape(number))
               if bookmark and number else None)
    match = pattern.search(head) if pattern is not None else None
    if match is None:
        finish = (_bookmark(paragraph, bookmark, bookmark_id)
                  if bookmark else None)
        _caption_run(paragraph, text, size, bold, italic)
        if finish is not None:
            finish()
        return
    _caption_run(paragraph, head[:match.start()], size, bold, italic)
    finish = _bookmark(paragraph, bookmark, bookmark_id)
    _font(paragraph.add_run(match.group(0)), size, bold=bold, italic=italic)
    finish()
    _caption_run(paragraph, head[match.end():], size, bold, italic)
    if separator:
        _font(paragraph.add_run(separator), size, bold=bold, italic=italic)
    if tail:
        _caption_run(paragraph, tail, size, bold, italic)


def _body(doc, text, style=None):
    """Абзац основного текста: стиль из реквизита, по ширине, с красной строкой.

    Кегль фрагмента не задаётся: шрифт берётся из стиля абзаца. По умолчанию
    это «Обычный» (``Normal``), поэтому реквизит ``text_style`` позволяет
    выбрать другой стиль текста, не переопределяя шрифт вручную.
    """
    paragraph = doc.add_paragraph()
    style = str(style or "").strip()
    custom = _paragraph_style(doc, style) if style else None
    if custom is None:
        # Пустой или неизвестный стиль — «Обычный» с обычной вёрсткой отчёта.
        custom = _paragraph_style(doc, "Normal")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.first_line_indent = Cm(1.25)
        paragraph.paragraph_format.space_after = Pt(0)
    if custom is not None:
        paragraph.style = custom
    paragraph.add_run(text)


def _text_block(doc, content, style=None):
    for line in str(content or "").split("\n"):
        line = line.strip()
        if line:
            _body(doc, line, style)


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


def _heading(doc, text, level, numbered=True, style=None):
    """Заголовок уровня ``level``; номер ставит шаблон, а не текст.

    ``style`` — имя стиля абзаца из шаблона (поле ``header_style``). Тогда
    оформление берётся из стиля, а не из «Заголовок N»; если у стиля нет
    своей нумерации, абзацу явно задаётся нумерация заголовков шаблона
    (numId 49), иначе номера разделов и подразделов исчезли бы.

    ``numbered=False`` отключает автонумерацию абзаца (``numId=0``) — для
    «Содержания», разделов без номера вроде «Введения» и приложений, у
    которых номер уже вписан в текст.
    """
    custom = _paragraph_style(doc, style)
    if custom is not None:
        heading = doc.add_paragraph(style=custom)
    else:
        heading = doc.add_heading(level=level)
    run = heading.add_run(text)
    if custom is None:
        _font(run, {1: 14, 2: 12, 3: 11}.get(level, 11), bold=True)
        heading.paragraph_format.space_before = Pt(10)
        heading.paragraph_format.space_after = Pt(4)
        heading.paragraph_format.keep_with_next = True
    if not numbered:
        heading._p.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = 0
    elif custom is not None and not _style_numbering(custom):
        _set_numbering(heading, HEADING_NUM_ID, level - 1)
    return heading


def _field_element(instruction, result="Обновите поле (F9)"):
    """XML-элемент ``w:r`` с полем Word: begin, инструкция, результат, end."""
    run = OxmlElement("w:r")
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
        run.append(element)
    return run


def _field(paragraph, instruction, result="Обновите поле (F9)"):
    run = paragraph.add_run()
    for element in _field_element(instruction, result):
        run._r.append(element)
    return run


def _toc(doc, style=None):
    """Заголовок «Содержание» и поле оглавления.

    Стиль заголовка берётся из реквизита ``toc_style``; по умолчанию —
    «Заголовок оглавления» (``TOC Heading``), а не «Заголовок 1». Если
    стиля нет в документе, остаётся обычный заголовок первого уровня.
    """
    _heading(doc, "Содержание", 1, numbered=False,
             style=str(style or "").strip() or TOC_STYLE)
    paragraph = doc.add_paragraph()
    _field(paragraph, r'TOC \o "1-2" \h \z \u')


def _page_number_in(part):
    """Поле PAGE в колонтитуле: номер продолжает нумерацию документа.

    Кэш поля — число «1», а не текст-заглушка: Word показывает кэш до
    обновления полей, и в колонтитуле вместо номера страницы появлялась бы
    надпись «Обновите поле (F9)».
    """
    paragraph = part.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _field(paragraph, "PAGE", result="1")


def _page_number(section):
    _page_number_in(section.footer)


def _report_after_title(doc):
    """Секция отчёта после готового титульного DOCX.

    Страница — книжная A4. Поля не сбрасываются: новая секция наследует
    вёрстку последней секции титула (в ГОСТ-шаблоне — 3 / 1,25 / 2 / 2 см),
    поэтому текст отчёта не смещается относительно титула. Колонтитулы
    титула (логотип, подпись отчёта) не наследуются: в верхнем колонтитуле
    новой секции стоит поле PAGE, поэтому нумерация продолжается от титула,
    а не начинается заново. ``titlePg`` убирается — иначе первая страница
    отчёта взяла бы «особый колонтитул первой страницы» титула; ``pgNumType``
    тоже, иначе унаследованный от титула сброс нумерации начал бы её с 1.
    """
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    for tag in ("w:titlePg", "w:pgNumType"):
        element = section._sectPr.find(qn(tag))
        if element is not None:
            section._sectPr.remove(element)
    section.header.is_linked_to_previous = False
    _page_number_in(section.header)
    section.footer.is_linked_to_previous = False
    return section


# ---------------------------------------------------------------------------
# Перекрестные ссылки на таблицы, рисунки и заголовки
# ---------------------------------------------------------------------------
class ReferenceRegistry(dict):
    """Закладки документа плюс данные для меток ``\\ref{…}``.

    Обычный ``dict`` здесь тоже годится: функции умеют работать и с ним
    (например, в проверках). ``numbers`` хранит видимый номер метки для кэша
    поля, ``definitions`` — пары «закладка — номер» для полей SET, которые
    объявляют закладки заголовков (номер раздела ставит шаблон, в тексте
    заголовка его нет).
    """

    def __init__(self):
        super().__init__()
        self.numbers = {}
        self.definitions = []
        self.declared = set()


def _unique_name(references, base):
    """Свободное имя закладки: ``RefT_5_2``, ``RefS_3`` и т. п."""
    used = set(references.values())
    if base not in used:
        return base
    index = 2
    while "%s_%d" % (base, index) in used:
        index += 1
    return "%s_%d" % (base, index)


#: В имени закладки Word допускает буквы, цифры и «_»; кириллицу в номерах
#: приложений («А», «Б») заменяем, чтобы имя точно читалось Word.
_BOOKMARK_UNSAFE = re.compile(r"[^0-9A-Za-z_]")


def _bookmark_part(value):
    """ASCII-часть имени закладки: точки и недопустимые символы → «_»."""
    text = _BOOKMARK_UNSAFE.sub("_", str(value or "").replace(".", "_"))
    return text or "0"


#: «Таблица 5.2», «табл. 5.2», «Рисунок 4.1», «рис. 4.1» и т. п.
#: Суффикс ``/#/0`` (либо полевый ``\# 0``) просит вывести только номер:
#: «Таблица 5.2/#/0» → «5.2». Сам суффикс в поле REF не переходит — закладка
#: и так охватывает только номер, а числовой переключатель Word ломает номер
#: при обновлении полей.
_REFERENCE_RE = re.compile(
    r"(?P<label>таблиц\w*|табл\.?|рисун\w*|рис\.?)\s+"
    r"(?P<number>\d+(?:\.\d+)*)"
    r"(?P<only>/#/0|\\#\s*\"?0\"?)?", re.I)

#: Именованная метка: ``\ref{ссылка на рис.1}``. Такая ссылка всегда
#: показывает только номер — отдельный суффикс ``/#/0`` не нужен.
_LABEL_MENTION_RE = re.compile(
    r"\\ref\s*\{\s*(?P<name>[^{}\n]+?)\s*\}", re.I)
#: Оба вида упоминаний обрабатываются одним проходом по тексту абзаца.
_ANY_REFERENCE_RE = re.compile(
    _LABEL_MENTION_RE.pattern + "|" + _REFERENCE_RE.pattern, re.I)


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
    base = "Ref%s_%s" % (key[0], _bookmark_part(key[1]))
    name = _unique_name(references, base)
    references[key] = name
    return name, True


def _register_labels(references, item, number, bookmark):
    """Связать метки поля ``ref`` с закладкой объекта.

    Метка — простое имя: в тексте пишется ``\\ref{метка}``, в DOCX
    получается REF-поле на закладку объекта (виден только номер).
    Ссылка указывает на закладку самого объекта: на подписи таблицы/рисунка
    закладка охватывает только номер, у раздела её объявляет поле SET.
    """
    if not bookmark or not isinstance(item, dict):
        return []
    found = []
    for label in sc.reference_labels(item.get("ref")):
        key = ("R", sc.normalize_ref_label(label))
        if key in references:
            continue
        references[key] = bookmark
        numbers = getattr(references, "numbers", None)
        if numbers is not None:
            numbers[key] = str(number or "")
        found.append(label)
    return found


def _register_heading(references, number):
    """Закладка на заголовке раздела/подраздела по его номеру.

    Номер раздела проставляет шаблон, в тексте заголовка его нет, поэтому
    закладку с номером объявляет поле SET в начале отчёта. Здесь только
    резервируется имя закладки.
    """
    number = str(number or "").strip()
    if not number:
        return None
    key = ("S", number)
    if key in references:
        return references[key]
    name = _unique_name(references,
                        "RefS_%s" % _bookmark_part(number))
    references[key] = name
    definitions = getattr(references, "definitions", None)
    if definitions is not None:
        definitions.append((name, number))
    declared = getattr(references, "declared", None)
    if declared is not None:
        declared.add(name)
    return name


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
    """Заменить упоминания таблиц, рисунков и меток на поля REF.

    Поддерживаются оба вида: «Таблица 5.2[/#/0]» и ``\\ref{метка}``.
    Именованная метка всегда показывает только номер. Обрабатываются все
    абзацы тела, включая ячейки таблиц.
    ``skip`` — число первых абзацев готового титульного листа: их
    содержимое менять нельзя. Подписи с закладками пропускаются, чтобы
    ссылка не указывала сама на себя. Текст сохраняется как кэш поля —
    документ читаем и без обновления полей в Word.

    Числовой переключатель ``\\#"0"`` в REF не пишется: Word применяет его
    к тексту закладки как к числу, и после F9 номер «5.1» превращается в «1».
    Отдельный переключатель и не нужен — закладка охватывает только номер.
    """
    if not references:
        return
    used_names = set(references.values())
    numbers = getattr(references, "numbers", None) or {}
    declared = getattr(references, "declared", None) or set()
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
        matches = list(_ANY_REFERENCE_RE.finditer(text))
        if not matches:
            continue
        source_run = paragraph.runs[0] if paragraph.runs else None
        for run in list(paragraph.runs):
            run._element.getparent().remove(run._element)
        cursor = 0
        for match in matches:
            if match.start() > cursor:
                _text_run(paragraph, text[cursor:match.start()], source_run)
            named = match.group("name")
            if named is not None:
                key = ("R", sc.normalize_ref_label(named))
                name = references.get(key)
                # Метка — простая ссылка: в документе виден только номер.
                visible = numbers.get(key) or named.strip()
            else:
                key = _key_from_match(match)
                name = references.get(key)
                only_number = bool(match.group("only"))
                # Суффикс /#/0 убирается из видимого текста: остаётся номер.
                visible = match.group("number") if only_number \
                    else match.group(0)
                if name and not only_number:
                    # «Таблица 5.2» — слово остаётся текстом, поле REF
                    # подставляет только номер из закладки подписи.
                    _text_run(paragraph, match.group("label") + " ",
                              source_run)
                    visible = match.group("number")
            if name:
                # У закладки-номера раздела (SET) нет места для перехода,
                # поэтому \h не ставим: ссылка показывает номер, но не
                # уводит в начало документа.
                instruction = " REF %s" % name
                if name not in declared:
                    instruction += " \\h"
                field = _field(paragraph, instruction + " ", result=visible)
                _copy_run_props(source_run, field)
            else:
                _text_run(paragraph, visible, source_run)
            cursor = match.end()
        if cursor < len(text):
            _text_run(paragraph, text[cursor:], source_run)


def _number_bookmarks(doc, references, skip=0):
    """Объявить закладки номеров разделов полями SET в начале отчёта.

    Номер раздела проставляет шаблон, в тексте заголовка его нет, поэтому
    закладку с номером создаёт поле ``SET``: ``{ SET RefS_5_3 "5.3" }``.
    Поля стоят в первом абзаце отчёта, то есть раньше всех REF, — так
    работают и ссылки вперёд, на раздел, который идёт ниже по документу.
    """
    definitions = getattr(references, "definitions", None) or []
    if not definitions:
        return
    paragraphs = list(doc.element.body.iter(qn("w:p")))

    def is_section_break(element):
        props = element.find(qn("w:pPr"))
        return props is not None and props.find(qn("w:sectPr")) is not None

    target = next((element for index, element in enumerate(paragraphs)
                   if index >= skip and not is_section_break(element)), None)
    if target is None:
        return
    props = target.find(qn("w:pPr"))
    position = list(target).index(props) + 1 if props is not None else 0
    for offset, (name, number) in enumerate(definitions):
        target.insert(position + offset,
                      _field_element(' SET %s "%s" ' % (name, number),
                                     result=""))


def _setup(doc, layout=True, template=False):
    """Параметры страницы и стили по умолчанию.

    ``template`` — документ собран из ``template.docx`` или титульного DOCX.
    Тогда стили шаблона не переопределяются: «ДОК Заголовок 1» и другие
    стили на основе ``Normal`` сохраняют свой кегль (например, 12 пт), а не
    получают 10 пт отчёта. Для нового пустого документа ``Normal``
    настраивается явно — иначе отчёт набрался бы шрифтом Word по умолчанию.
    """
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
    if not template:
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


def _render_table(doc, data, table, max_rows, counters, references,
                  appendix=False):
    headers, rows = es.table_view(data, table)
    reference = table.get("reference") or ""
    name = table.get("name") or ""
    number = str(table.get("number") or "")
    if not headers:
        return
    # Подпись без «Таблица N» всё равно получает закладку — иначе метка
    # из поля ref некуда было бы привязать.
    caption_key = reference or ("Таблица %s" % number if number else "")
    bookmark, is_new = _register_reference(references, caption_key)
    title = ("%s — %s" % (reference, name)).strip(" —")
    _caption(doc, title, bookmark if is_new else None, 1000 + len(references),
             number=number,
             style=(APPENDIX_TABLE_CAPTION_STYLE if appendix
                    else TABLE_CAPTION_STYLE))
    _register_labels(references, table, number, bookmark)
    counters["таблицы"] += 1
    counters["строки"] += _table(doc, headers, rows, max_rows=max_rows,
                                 widths_mm=table.get("colums_width") or [],
                                 header_rows=es.table_header_rows(table),
                                 style=table.get("table_style"),
                                 merge=_merge_enabled(table))


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


def _render_figure_block(doc, figure, references, counters, errors,
                         appendix=False):
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
    number = str(figure.get("number") or "")
    bookmark, is_new = _register_reference(references, reference)
    title = "%s — %s" % (reference, figure.get("name") or "")
    _caption(doc, title, bookmark if is_new else None, 1000 + len(references),
             bold=False, italic=True, number=number,
             style=(APPENDIX_FIGURE_CAPTION_STYLE if appendix
                    else FIGURE_CAPTION_STYLE))
    _register_labels(references, figure, number, bookmark)
    paragraph = doc.paragraphs[-1]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if original is not None:
        doc.add_section(WD_SECTION.NEW_PAGE)
        _restore_page_setup(doc.sections[-1], original)


def _render_item(doc, data, kind, item, max_rows, counters, references,
                 errors, appendix=False):
    """Вывести один элемент контейнера: пункт, подпункт, таблицу, рисунок."""
    if kind == "table":
        _render_table(doc, data, item, max_rows, counters, references,
                      appendix)
    elif kind == "figure":
        _render_figure_block(doc, item, references, counters, errors,
                             appendix)
    else:
        _render_clause(doc, data, item, max_rows, counters, references,
                       errors, appendix)


def _render_clause(doc, data, clause, max_rows, counters, references, errors,
                   appendix=False):
    """Пункт или подпункт: номер с текстом и вложенные элементы по порядку."""
    number = str(clause.get("number") or "")
    lines = _clause_lines(clause.get("content"))
    if lines:
        lines[0] = ("%s %s" % (number, lines[0])).strip()
    elif number:
        lines = [number]
    for line in lines:
        _body(doc, line, data.get(TEXT_STYLE_FIELD))
    for kind, item in st.ordered_items(clause):
        _render_item(doc, data, kind, item, max_rows, counters, references,
                     errors, appendix)


def _render_container(doc, data, container, level, max_rows, counters,
                      references, errors, appendix=False):
    _text_block(doc, container.get("content"), data.get(TEXT_STYLE_FIELD))
    for kind, item in st.ordered_items(container):
        _render_item(doc, data, kind, item, max_rows, counters, references,
                     errors, appendix)


def _is_appendix(section):
    """Раздел — приложение: буквенный номер или стиль «ПРИЛ …»."""
    number = str(section.get("number") or "").strip()
    style = str(section.get("header_style") or "").casefold()
    if "прил" in style:
        return True
    return bool(number) and not number[0].isdigit() and number.isalpha()


def _appendix_title(number, title):
    """«ПРИЛОЖЕНИЕ А. Название» — номер из JSON, а не счётчик Word.

    Автонумерация стилей «ПРИЛ …» начинается заново у каждого стиля, поэтому
    два приложения с разными стилями получили бы одну и ту же букву «А».
    Текст с номером из JSON надёжнее и совпадает с полем SET/REF.
    """
    title = str(title or "").strip()
    if not number:
        return title or "ПРИЛОЖЕНИЕ"
    if title.casefold().startswith(("приложение", "прил")):
        return title
    label = "ПРИЛОЖЕНИЕ %s" % number
    return "%s. %s" % (label, title) if title else label


def _render_sections(doc, data, max_rows, counters, references, errors):
    """Разделы и подразделы: в тексте заголовка только название.

    Номер раздела и подраздела в текст не вписывается — его проставляет
    нумерация стиля (заголовков шаблона или стиля из ``header_style``).
    Исключение — приложения: их буква берётся из JSON, см.
    :func:`_appendix_title`.
    """
    for section in es.sections(data):
        number = str(section.get("number") or "").strip()
        header = str(section.get("header") or "").strip()
        if not header and not number:
            continue
        appendix = _is_appendix(section)
        text = (_appendix_title(number, header) if appendix
                else (header or number))
        _heading(doc, text, 1,
                 numbered=not appendix and bool(number) and bool(header),
                 style=section.get("header_style"))
        bookmark = _register_heading(references, number)
        _register_labels(references, section, number, bookmark)
        counters["разделы"] += 1
        _render_container(doc, data, section, 2, max_rows, counters,
                          references, errors, appendix)
        for sub in section.get("subsections") or []:
            sub_number = str(sub.get("number") or "").strip()
            title = str(sub.get("header") or "").strip()
            if not title and not sub_number:
                continue
            _heading(doc, title or sub_number, 2,
                     numbered=bool(sub_number) and bool(title),
                     style=sub.get("header_style"))
            bookmark = _register_heading(references, sub_number)
            _register_labels(references, sub, sub_number, bookmark)
            _render_container(doc, data, sub, 3, max_rows, counters,
                              references, errors, appendix)


def collect_labels(data):
    """Метки перекрёстных ссылок стандарта: (метка, объект, номер).

    Обход повторяет порядок вывода отчёта: раздел, его пункты, таблицы и
    рисунки, затем подразделы. Метка попадает в список даже без номера
    объекта — отдельный отчёт должен показывать и такие ошибки.
    """
    entries, seen = [], set()

    def add(item, title, number):
        number = str(number or "").strip()
        for label in sc.reference_labels((item or {}).get("ref")):
            key = sc.normalize_ref_label(label)
            if key in seen:
                continue
            seen.add(key)
            entries.append((label, str(title or number), number))

    def add_items(container):
        for kind, item in st.ordered_items(container):
            if kind == "table":
                title = ("%s — %s" % (item.get("reference") or "",
                                      item.get("name") or "")).strip(" —")
                add(item, title, item.get("number"))
            elif kind == "figure":
                title = "%s — %s" % (item.get("reference") or "Рисунок",
                                     item.get("name") or "")
                add(item, title, item.get("number"))
            elif kind in ("clause", "subclause"):
                add_items(item)

    for section in es.sections(data):
        number = str(section.get("number") or "").strip()
        title = str(section.get("header") or "").strip()
        add(section, title or number, number)
        add_items(section)
        for sub in section.get("subsections") or []:
            sub_number = str(sub.get("number") or "").strip()
            sub_title = str(sub.get("header") or "").strip()
            add(sub, sub_title or sub_number, sub_number)
            add_items(sub)
    return entries


def build_labels(data, path):
    """Записать отдельный DOCX со списком меток перекрёстных ссылок.

    В обычный отчёт по стандарту эта таблица больше не попадает (пункт 43):
    метки выводятся только этим отчётом.
    """
    if Document is None:
        raise DocxError("не установлен python-docx: "
                        "python -m pip install python-docx")
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        raise DocxError("нет папки: %s" % folder)
    template = template_path(folder)
    if template:
        doc = Document(template)
        _clear_body(doc)
        _setup(doc, layout=False, template=True)
    else:
        doc = Document()
        _setup(doc)
    entries = collect_labels(data)
    text_style = data.get(TEXT_STYLE_FIELD)
    _heading(doc, "Метки перекрёстных ссылок", 1, numbered=False)
    standard = " ".join(
        str(value or "").strip()
        for value in (data.get("code"), data.get("name"))
        if str(value or "").strip())
    if standard:
        _body(doc, "Стандарт: %s." % standard, text_style)
    _body(doc, r"В тексте метка пишется как \ref{имя метки}; "
               "в отчёте показывается только номер.", text_style)
    _body(doc, "Всего меток: %d." % len(entries), text_style)
    if entries:
        _table(doc, ["Метка", "Объект", "Номер"],
               [list(entry) for entry in entries], size=10,
               widths_mm=[70, 88, 32])
    else:
        _body(doc, "В стандарте нет меток перекрёстных ссылок.", text_style)
    doc.save(path)
    return {"метки": len(entries), "размер": os.path.getsize(path)}


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
        _setup(doc, layout=False, template=True)
        _report_after_title(doc)
    else:
        template = template_path(folder)
        if template:
            doc = Document(template)
            _clear_body(doc)
            _setup(doc, layout=False, template=True)
        else:
            doc = Document()
            _setup(doc)
    stats = es.stats(data)
    counters = {"разделы": 0, "таблицы": 0, "строки": 0,
                "рисунки": 0, "ошибки_рисунков": [],
                "титульный_лист": title or ""}
    references = ReferenceRegistry()
    figure_errors = counters["ошибки_рисунков"]
    if not title:
        _title_page(doc, data, stats)
    if toc:
        _toc(doc, data.get(TOC_STYLE_FIELD))
        doc.add_page_break()
    _render_sections(doc, data, max_rows, counters, references, figure_errors)
    # Таблица меток в обычный отчёт не выводится (пункт 43): для неё есть
    # отдельный отчёт build_labels(). Ссылки в тексте заменяются полями REF.
    _link_references(doc, references, skip=skip_paragraphs)
    _number_bookmarks(doc, references, skip=skip_paragraphs)
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
