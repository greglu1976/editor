# -*- coding: utf-8 -*-
"""DOCX проекта СТО → JSON стандарта для папки ``standards_base/``.

На вход — ``Раздел 4.16_т. N_СТО …_Ред.2.docx`` (один файл = один стандарт),
на выход — JSON той же структуры, что и действующие файлы
``standards_base/СТО 56947007-…-2019.json``:

    Обозначение стандарта, Шифр стандарта, Дата введения,
    Принадлежность стандарта, Область применения стандарта,
    Содержимое стандарта {
        «Общий перечень шкафов стандарта»   — список шифров,
        «Шкаф … типа ШЭТ …»                 — по разделу на шкаф:
            Раздел стандарта, Шифр шкафа, Назначение шкафа,
            Описание шкафа (параметр → значение),
            Таблицы {"Таблица 5.3": {Наименование, Страницы, Заголовки,
                                     Столбцы, Количество строк, Строки}},
        «Прочие таблицы стандарта (разделы 4 и 5.1)»,
        «Приложение А» …
    }

Нумерация разделов, таблиц и рисунков в DOCX автоматическая (многоуровневый
список), поэтому номера воспроизводятся по ``numbering.xml``: счётчики идут по
уровням списка, а номера таблиц и рисунков (уровни 4 и 5) сбрасываются только
с новым разделом — так, как это делает Word для этого шаблона.

Ссылки в описании шкафа («Таблица 5.3 -», «Рисунок 5.1 -») приводятся к виду
«Таблица 5.3», чтобы их разыменовывал ``standards_base.table()``.

Запуск:
    python3 tools/docx_to_standards_json.py --dir standards_base --dry-run
    python3 tools/docx_to_standards_json.py --dir standards_base
    python3 tools/docx_to_standards_json.py файл.docx --cipher "Проект СТО …"
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import zipfile
from collections import OrderedDict

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: Стили заголовков основного текста: имя стиля → уровень списка.
HEADING_STYLES = {"ДОК Текст ур1 раздел": 0, "ДОК Текст ур2 подраздел": 1,
                  "ДОК Текст ур3 пункт": 2, "ДОК Текст ур4 подпункт": 3}
#: Стили заголовков приложений.
APPENDIX_STYLES = {"ДОК ПРИЛ ур1 Заголовок": 0, "ДОК ПРИЛ ур2 раздел": 1,
                   "ДОК ПРИЛ ур2 подраздел": 1, "ДОК ПРИЛ ур3 подраздел": 2,
                   "ДОК ПРИЛ ур4 подпункт": 3}
#: Стили подписей: имя стиля → «table» / «figure».
CAPTION_STYLES = {"ДОК Таблица Название": "table",
                  "ДОК ПРИЛ Таблица Название": "table",
                  "ДОК Рисунок Название": "figure",
                  "ДОК ПРИЛ Рисунок Название": "figure"}
#: Ненумерованные заголовки (Предисловие, Сведения о стандарте, Содержание).
FRONT_STYLES = ("ДОК Заголовок не вкл в содержание",
                "ДОК Заголовок не вкл в содержание по центру",
                "ДОК Заголовок вкл в содержание")

CAPTION_WORD = {"table": "Таблица", "figure": "Рисунок"}
TABLES_KEY = "Таблицы"
DESCRIPTION_KEY = "Описание шкафа"
LIST_KEY = "Общий перечень шкафов стандарта"
OTHER_KEY = "Прочие таблицы стандарта (разделы 4 и 5.1)"
CODE_FIELD = "Шифр шкафа"

#: Колонка общего перечня → поле действующих JSON.
LIST_COLUMNS = {"наименование": "Наименование шкафа",
                "наименование шкафа": "Наименование шкафа",
                "наименование шкафа рза": "Наименование шкафа",
                "наименование рза": "Наименование шкафа",
                "код шэт": "Код ШЭТ", "шифр шэт": "Код ШЭТ",
                "функции рза": "Функции РЗА",
                "примечание": "Примечание", "примечания": "Примечание"}

#: «Таблица 5.3 -» → «Таблица 5.3»; «Рисунок А.1» — тоже ссылка.
REFERENCE_RE = re.compile(
    r"^\s*(таблиц\w*|рисун\w*|приложен\w*)"
    r"[\s\u00a0]+([0-9А-Яа-я]+(?:[.\-][0-9А-Яа-я]+)*)"
    r"[\s\u00a0]*[-–—:.;]*\s*$", re.U)
#: Приписка к параметру: «Область применения … 35 кВ (ГОСТ Р 59279 и [14])».
DASHES = "\u2013\u2014\u2212"
RU_UPPER = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
#: владелец стандарта и дата введения на титуле
OWNER_RE = re.compile(r"^(ПАО|АО|ОАО|Публичное акционерное общество)\b")
DATE_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}")
#: граница обложки отчёта НИОКР — за ней начинается титул стандарта
BOUNDARY = re.compile(
    r"^(Отчёт|Отчет|Технический от|ООО|Этап|Раздел №|Договор|Москва|Том[\s№]|"
    r"Редакция|Руководитель|Работа|Инв\.|УТВЕРЖДАЮ|Приложение\s|\d{4}\s*$|"
    r"[А-Я][а-я]+\s+[А-Я]\.[А-Я]\.)")


# ---------------------------------------------------------------------------
# Текст
# ---------------------------------------------------------------------------
def space(value):
    """Один пробел вместо переводов строк, NBSP и двойных пробелов."""
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def tidy(value):
    """Значение поля: без висячего тире после номера, но «-» как знак сохраняется.

    В таблицах передачи сигналов «-» означает «не передаётся» — это данные, а
    не пунктуация, поэтому сдвигаем тире только когда оно висит после текста
    («В соответствии с таблицей 5.2.9 -»).
    """
    text = space(value).strip(" \t")
    if text.strip(DASHES + " ") != "":
        text = re.sub(r"\s+[-–—]+\s*$", "", text)
    return text.strip()


def as_reference(value):
    """Ссылка «Таблица 5.3» из значения поля (None, если это не ссылка)."""
    match = REFERENCE_RE.match(space(value))
    if not match:
        return None
    word = match.group(1).lower()
    head = ("Таблица" if word.startswith("таблиц")
            else "Рисунок" if word.startswith("рисун") else "Приложение")
    return "%s %s" % (head, match.group(2))


# ---------------------------------------------------------------------------
# Нумерация Word
# ---------------------------------------------------------------------------
def read_styles(root):
    """styleId → {name, basedOn, numId, ilvl}."""
    styles = {}
    for style in root.iter(W + "style"):
        name = style.find(W + "name")
        based = style.find(W + "basedOn")
        num_id = ilvl = None
        ppr = style.find(W + "pPr")
        if ppr is not None:
            numpr = ppr.find(W + "numPr")
            if numpr is not None:
                node = numpr.find(W + "numId")
                num_id = node.get(W + "val") if node is not None else None
                node = numpr.find(W + "ilvl")
                ilvl = node.get(W + "val") if node is not None else None
        styles[style.get(W + "styleId")] = {
            "name": name.get(W + "val") if name is not None else None,
            "basedOn": based.get(W + "val") if based is not None else None,
            "numId": num_id, "ilvl": ilvl}
    return styles


def read_numbering(root):
    """abstractNum → уровни списка; numId → abstractNum."""
    abstracts = {}
    for abstract in root.iter(W + "abstractNum"):
        levels = {}
        for level in abstract.findall(W + "lvl"):
            node = level.find(W + "lvlText")
            fmt = level.find(W + "numFmt")
            start = level.find(W + "start")
            linked = level.find(W + "pStyle")
            restart = level.find(W + "lvlRestart")
            index = int(level.get(W + "ilvl"))
            levels[index] = {
                "text": node.get(W + "val") if node is not None else "",
                "fmt": (fmt.get(W + "val") if fmt is not None else "decimal"),
                "start": int(start.get(W + "val")) if start is not None else 1,
                "pStyle": linked.get(W + "val") if linked is not None else None,
                # «restart after» в OOXML нумеруется с единицы
                "restartAfter": (int(restart.get(W + "val")) - 1
                                 if restart is not None else index - 1)}
        abstracts[abstract.get(W + "abstractNumId")] = levels
    instances = {}
    for num in root.iter(W + "num"):
        node = num.find(W + "abstractNumId")
        if node is not None:
            instances[num.get(W + "numId")] = node.get(W + "val")
    return abstracts, instances


def format_number(value, fmt):
    """Число в формате уровня: десятичное, римское, русская буква."""
    if fmt in ("russianUpper", "upperRussian"):
        return letters(value, RU_UPPER)
    if fmt in ("russianLower", "lowerRussian"):
        return letters(value, RU_UPPER.lower())
    if fmt == "lowerLetter":
        return letters(value, "abcdefghijklmnopqrstuvwxyz")
    if fmt == "upperLetter":
        return letters(value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if fmt == "lowerRoman":
        return roman(value).lower()
    if fmt == "upperRoman":
        return roman(value)
    return str(value)


def letters(value, alphabet):
    """Порядковый номер в алфавите: 1→А, 2→Б, … 33→ЯА (если дойдёт)."""
    text = ""
    index = value - 1
    while True:
        text = alphabet[index % len(alphabet)] + text
        index = index // len(alphabet) - 1
        if index < 0:
            break
    return text


def roman(value):
    signs = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
             (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
             (5, "V"), (4, "IV"), (1, "I"))
    text = ""
    for number, sign in signs:
        while value >= number:
            text += sign
            value -= number
    return text


class Counters:
    """Счётчики многоуровневых списков документа."""

    def __init__(self, abstracts, instances, styles):
        self.abstracts = abstracts
        self.instances = instances
        self.styles = styles
        self.counters = {}
        #: уровень списка, к которому привязан стиль (``w:pStyle`` в ``w:lvl``)
        self.by_style = {}
        for aid, levels in abstracts.items():
            for index, level in levels.items():
                if level.get("pStyle"):
                    self.by_style.setdefault(aid, {})[level["pStyle"]] = index
        #: списки, в которых есть уровень подписи «Таблица …» — нумеруем их
        self.owned = {aid for aid, levels in abstracts.items()
                      if any(re.search(r"таблиц|рисун",
                                       (level.get("text") or ""), re.I)
                             for level in levels.values())}

    def for_paragraph(self, style_id, direct):
        """(numId, ilvl) параграфа: прямое numPr важнее стиля."""
        num_id = ilvl = None
        if direct:
            num_id, ilvl = direct
            if num_id == "0":
                return None                     # нумерация снята явно
        if not num_id:
            seen = set()
            while style_id and style_id not in seen:
                seen.add(style_id)
                style = self.styles.get(style_id) or {}
                if style.get("numId"):
                    num_id, ilvl = style["numId"], style.get("ilvl")
                    break
                style_id = style.get("basedOn")
        if not num_id:
            return None
        aid = self.instances.get(num_id)
        if ilvl is None:
            # стиль может быть привязан к уровню списка прямо (w:pStyle)
            ilvl = (self.by_style.get(aid) or {}).get(style_id) or "0"
        return (num_id, str(ilvl))

    def render(self, num_id, ilvl):
        """Отметить параграф списка и вернуть его отформатированный номер."""
        aid = self.instances.get(num_id)
        levels = self.abstracts.get(aid) or {}
        index = int(ilvl)
        level = levels.get(index)
        if level is None:
            return None
        marks = self.counters.setdefault(aid, [0] * 9)
        marks[index] += 1
        # сброс младших уровней: по их «restart after», транзитивно
        queue = [index]
        while queue:
            head = queue.pop()
            for deeper, info in levels.items():
                if deeper > head and info.get("restartAfter") == head \
                        and deeper not in queue:
                    marks[deeper] = info.get("start", 1) - 1
                    queue.append(deeper)

        def replace(match):
            depth = int(match.group(1)) - 1
            info = levels.get(depth) or {"fmt": "decimal", "start": 1}
            value = marks[depth] + info["start"] - 1
            return format_number(value, info["fmt"])
        return re.sub(r"%(\d)", replace, level.get("text") or "")

    def classify(self, num_id, ilvl):
        """Что нумерует этот уровень: «table», «figure», «appendix», 1…4."""
        aid = self.instances.get(num_id)
        if aid is None or aid not in self.owned:
            return None
        level = (self.abstracts.get(aid) or {}).get(int(ilvl)) or {}
        text = (level.get("text") or "").strip()
        lowered = text.lower()
        if "таблиц" in lowered:
            return "table"
        if "рисун" in lowered:
            return "figure"
        if "приложен" in lowered:
            return "appendix"
        depth = len(re.findall(r"%\d", text))
        if text and depth:
            return min(depth, 4)
        if not text and level.get("fmt") in ("russianUpper", "upperLetter"):
            return "appendix"
        return None


# ---------------------------------------------------------------------------
# Разбор документа
# ---------------------------------------------------------------------------
def paragraph_node_text(par):
    """Текст параграфа без маркеров списка."""
    parts = []
    for node in par.iter():
        tag = node.tag
        if tag == W + "t":
            parts.append(node.text or "")
        elif tag == W + "sym":
            parts.append(node.get(W + "char") or "")
        elif tag in (W + "tab", W + "br", W + "cr"):
            parts.append(" ")
    return "".join(parts).replace("\u00a0", " ")


class Document:
    """DOCX: порядок блоков, номера, таблицы."""

    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as archive:
            self.body = etree.fromstring(
                archive.read("word/document.xml")).find(W + "body")
            styles = read_styles(etree.fromstring(
                archive.read("word/styles.xml")))
            abstracts, instances = read_numbering(etree.fromstring(
                archive.read("word/numbering.xml")))
        self.styles = styles
        self.counters = Counters(abstracts, instances, styles)
        #: маркерный текст уровня («–», «•») для списков внутри ячеек
        self.bullets = {}
        for aid, levels in abstracts.items():
            for index, level in levels.items():
                if level.get("fmt") == "bullet":
                    self.bullets["%s:%d" % (aid, index)] = level.get("text")

    # -- служебное ----------------------------------------------------------
    def style_id(self, par):
        ppr = par.find(W + "pPr")
        node = ppr.find(W + "pStyle") if ppr is not None else None
        return node.get(W + "val") if node is not None else None

    def style_name(self, par):
        return (self.styles.get(self.style_id(par)) or {}).get("name") or ""

    def numbering_of(self, par):
        """(numId, ilvl) параграфа или None, если параграф не из списка."""
        ppr = par.find(W + "pPr")
        direct = None
        if ppr is not None:
            numpr = ppr.find(W + "numPr")
            if numpr is not None:
                node = numpr.find(W + "numId")
                num_id = node.get(W + "val") if node is not None else None
                node = numpr.find(W + "ilvl")
                ilvl = node.get(W + "val") if node is not None else None
                direct = (num_id, ilvl)
        return self.counters.for_paragraph(self.style_id(par), direct)

    def text(self, par, with_bullets=True):
        """Текст параграфа, при необходимости — с маркером списка."""
        text = paragraph_node_text(par)
        if with_bullets:
            marker = self.marker_of(par)
            if marker:
                text = "%s %s" % (marker, text)
        return text.strip()

    def marker_of(self, par):
        resolved = self.numbering_of(par)
        if not resolved:
            return None
        num_id, ilvl = resolved
        aid = self.counters.instances.get(num_id)
        return self.bullets.get("%s:%d" % (aid, int(ilvl)))

    def number_of(self, par):
        """Автоматический номер параграфа ('', если его нет)."""
        resolved = self.numbering_of(par)
        if not resolved:
            return ""
        num_id, ilvl = resolved
        aid = self.counters.instances.get(num_id)
        if aid not in self.counters.owned:
            return ""
        return self.counters.render(num_id, ilvl) or ""

    # -- содержимое ---------------------------------------------------------
    def style_kind(self, style):
        """Вид блока по имени стиля (запас, если нумерация молчит)."""
        if style in HEADING_STYLES:
            return "h%d" % (HEADING_STYLES[style] + 1)
        if style in APPENDIX_STYLES:
            return "a%d" % (APPENDIX_STYLES[style] + 1)
        if style in CAPTION_STYLES:
            return CAPTION_STYLES[style]
        if style in FRONT_STYLES:
            return "front"
        if style == "ДОК титул":
            return "cover"
        return "text"

    def blocks(self):
        """Тело документа → блоки в порядке следования.

        Вид блока определяется нумерацией (уровень списка говорит, заголовок
        это, подраздел, таблица или рисунок), а имя стиля — только запасной
        путь: в томах 5 и 7 заголовки висят на других уровнях того же списка.
        """
        out = []
        caption = None
        for child in self.body.iterchildren():
            if child.tag == W + "p":
                style = self.style_name(child)
                resolved = self.numbering_of(child)
                kind = number = None
                if resolved:
                    kind = self.counters.classify(*resolved)
                    number = self.number_of(child)
                if kind == "table":
                    kind = "table"
                elif kind == "figure":
                    kind = "figure"
                elif kind == "appendix":
                    kind = "a1"
                elif isinstance(kind, int):
                    kind = "h%d" % kind
                else:
                    kind = self.style_kind(style)
                text = self.text(child)
                if kind == "text" and not text:
                    continue
                block = {"kind": kind, "style": style,
                         "number": number or "", "text": text}
                out.append(block)
                if kind == "table":
                    caption = block
                elif kind == "figure":
                    caption = None
            elif child.tag == W + "tbl":
                out.append({"kind": "tbl", "caption": caption,
                            "rows": self.table_rows(child)})
                caption = None
        return out

    def table_rows(self, tbl):
        """Таблица → строки {cells, header} с раскрытием объединений."""
        rows = []
        for tr in tbl.findall(W + "tr"):
            trpr = tr.find(W + "trPr")
            header = bool(trpr is not None
                          and trpr.find(W + "tblHeader") is not None)
            cells, widths = [], []
            for tc in tr.findall(W + "tc"):
                span, merged = 1, None
                tcpr = tc.find(W + "tcPr")
                if tcpr is not None:
                    node = tcpr.find(W + "gridSpan")
                    if node is not None:
                        try:
                            span = max(1, int(node.get(W + "val")))
                        except (TypeError, ValueError):
                            span = 1
                    node = tcpr.find(W + "vMerge")
                    if node is not None:
                        merged = node.get(W + "val") or "continue"
                text = self.cell_text(tc)
                if merged == "continue" and rows and len(rows[-1]["cells"]) > len(cells):
                    text = rows[-1]["cells"][len(cells)] or text
                cells.append(text)
                cells.extend([""] * (span - 1))
                widths.append(span)
                widths.extend([0] * (span - 1))
            rows.append({"cells": cells, "header": header, "widths": widths})
        return rows

    def cell_text(self, tc):
        """Текст ячейки: абзацы через «; », маркеры списков сохранены."""
        chunks = []
        for par in tc.findall(W + "p"):
            text = self.text(par).rstrip(" ;")
            if text:
                chunks.append(text)
        return "; ".join(chunks)


# ---------------------------------------------------------------------------
# Сборка JSON
# ---------------------------------------------------------------------------
class Builder:
    """Блоки DOCX → структура стандарта."""

    def __init__(self, path):
        self.doc = Document(path)
        self.name = os.path.basename(path)
        self.problems = []
        self.tables = OrderedDict()
        self.groups = []

    def warn(self, text):
        if text not in self.problems:
            self.problems.append(text)

    # -- каркас -------------------------------------------------------------
    def walk(self):
        """Блоки → группы (раздел, подраздел, приложение) + таблицы по порядку."""
        blocks = self.doc.blocks()
        self.blocks = blocks
        chapter = None
        section = None
        appendix = None
        group = {"kind": "cover", "number": "", "title": "", "blocks": []}
        self.groups = [group]
        for block in blocks:
            kind = block["kind"]
            if kind == "front":
                group = {"kind": "cover", "number": "",
                         "title": space(block["text"]), "blocks": []}
                self.groups.append(group)
                chapter = section = appendix = None
                continue
            if kind == "h1":
                group = {"kind": "chapter", "number": block["number"],
                         "title": space(block["text"]), "blocks": []}
                self.groups.append(group)
                chapter, section, appendix = group, None, None
                continue
            if kind == "a1":
                title = "%s %s" % (block["number"], space(block["text"]))
                group = {"kind": "appendix", "number": appendix_name(title),
                         "title": tidy(title), "blocks": []}
                self.groups.append(group)
                appendix, chapter, section = group, None, None
                continue
            if kind == "h2":
                group = {"kind": "section", "number": block["number"],
                         "title": space(block["text"]), "blocks": []}
                self.groups.append(group)
                section = group
                continue
            if kind in ("h3", "h4") and group["kind"] not in ("section",
                                                             "appendix"):
                group = {"kind": "section", "number": block["number"],
                         "title": space(block["text"]), "blocks": []}
                self.groups.append(group)
            group["blocks"].append(block)
        self.collect_tables()

    def collect_tables(self):
        """Таблицы с подписью → «Таблица 5.3» в своей группе."""
        for group in self.groups:
            found = OrderedDict()
            for block in group["blocks"]:
                if block["kind"] != "tbl":
                    continue
                caption = block.get("caption")
                if caption is None:
                    self.warn("%s: таблица без подписи пропущена (%s)"
                              % (group["title"] or "титул",
                                 shorten(first_words(block))))
                    continue
                key = caption_key(caption)
                table = make_table(caption, block["rows"])
                if table is None:
                    self.warn("пустая таблица %s" % key)
                    continue
                if key in self.tables:
                    self.warn("номер подписи %s встречается дважды"
                              " (группа «%s»)" % (key, group["title"]))
                found[key] = table
                self.tables[key] = table
            group["tables"] = found

    # -- реквизиты ----------------------------------------------------------
    def title_lines(self):
        """Строки титульного листа проекта (стиль «ДОК титул»)."""
        return [space(block["text"]) for block in self.blocks
                if (block.get("style") or "") == "ДОК титул"]

    def title(self):
        """Обозначение стандарта: титульные строки перед «Стандарт организации».

        Сбор назад до границы обложки НИОКР («Москва, 2023 г.», «Редакция 2»,
        подписи) — в разных томах титул отделён от обложки по-разному.
        """
        lines = [space(block["text"]) for block in self.blocks
                 if (block.get("style") or "") == "ДОК титул"]
        if "Стандарт организации" not in lines:
            return ""
        index = lines.index("Стандарт организации")
        chunk = []
        for text in reversed(lines[:index]):
            if BOUNDARY.match(text or " "):
                break
            if text:
                chunk.insert(0, text)
        return tidy(" ".join(chunk))

    def owner(self):
        """Принадлежность стандарта: владелец под строкой «Стандарт организации»."""
        lines = self.title_lines()
        start = 0
        if "Стандарт организации" in lines:
            start = lines.index("Стандарт организации")
        for text in lines[start:]:
            if OWNER_RE.match(text):
                return text
        return ""

    def date(self):
        """Дата введения: после «Дата введения:»; в проекте она пуста."""
        lines = self.title_lines()
        for index, text in enumerate(lines):
            if not text.startswith("Дата введения"):
                continue
            value = text.split(":", 1)[1].strip()
            if value:
                return value
            for following in lines[index + 1:]:
                if not following:
                    continue
                return following if DATE_RE.match(following) else ""
        return ""

    def scope(self):
        """«Область применения стандарта» — текст раздела 1."""
        for group in self.groups:
            if group["kind"] == "chapter" and group["number"].rstrip(". ") == "1":
                parts = [block["text"] for block in group["blocks"]
                         if block["kind"] in ("text", "h2", "h3", "h4")
                         and space(block["text"])]
                return tidy(" ".join(parts))
        return ""

    # -- содержимое ---------------------------------------------------------
    def listing(self):
        """«Общий перечень шкафов стандарта» — таблица с колонкой «Код ШЭТ»."""
        for key, table in self.tables.items():
            names = [norm_head(name) for name in table["Столбцы"]]
            if "код шэт" in names or "шифр шэт" in names:
                return listing_rows(table)
        self.warn("не найден общий перечень шкафов (нет колонки «Код ШЭТ»)")
        return []

    def cabinets(self):
        """Разделы-шкафы: группа с таблицей «Описание ШЭТ …»."""
        result = []
        for group in self.groups:
            if not group["number"] or group["kind"] not in ("section",
                                                           "chapter"):
                continue
            found = description_table(group["tables"])
            if found is None:
                continue
            result.append((group, found))
        return result

    def cabinet_card(self, group, found):
        """Карточка шкафа: раздел, шифр, назначение, описание, таблицы."""
        key, table = found
        fields = description(table)
        code = space(fields.get(CODE_FIELD, ""))
        card = OrderedDict()
        card["Раздел стандарта"] = group["number"].rstrip(". ")
        card[CODE_FIELD] = code
        card["Назначение шкафа"] = self.purpose(group, key)
        card[DESCRIPTION_KEY] = kits(fields)
        card[TABLES_KEY] = OrderedDict(group["tables"])
        return card, code

    def purpose(self, group, description_key):
        """«Назначение шкафа» — первый текстовый пункт раздела."""
        for block in group["blocks"]:
            if block["kind"] == "tbl":
                caption = block.get("caption")
                if caption and caption_key(caption) == description_key:
                    break
                continue
            if block["kind"] in ("table", "figure"):
                break
            if block["kind"] in ("h3", "h4", "text"):
                text = space(block["text"])
                if len(text) > 40 and not as_reference(text):
                    return tidy(text)
        return ""

    def build(self, cipher, designation=None):
        self.walk()
        content = OrderedDict()
        content[LIST_KEY] = self.listing()
        used = set()
        cards = []
        for group, described in self.cabinets():
            card, code = self.cabinet_card(group, described)
            title = group["title"]
            if title in content:
                title = "%s (%s)" % (title, code)
            content[title] = card
            used.update(card[TABLES_KEY])
            cards.append(code)
        fix_listing(content[LIST_KEY], cards)
        other = OrderedDict((key, table) for key, table in self.tables.items()
                            if key not in used and not appendix_of(key))
        if other:
            content[OTHER_KEY] = other
        for key, table in self.tables.items():
            if key in used:
                continue
            letter = appendix_of(key)
            if letter:
                name = "Приложение %s" % letter
                block = content.setdefault(name, OrderedDict())
                block[key] = table
        result = OrderedDict()
        result["Обозначение стандарта"] = (designation or self.title() or "")
        result["Шифр стандарта"] = cipher
        result["Дата введения"] = self.date() or ""
        result["Принадлежность стандарта"] = self.owner() or ""
        result["Область применения стандарта"] = self.scope()
        result["Содержимое стандарта"] = content
        self.cards = cards
        return result


# ---------------------------------------------------------------------------
# Таблицы и описания
# ---------------------------------------------------------------------------
def make_table(caption, rows):
    """Подпись + строки DOCX → объект таблицы стандарта."""
    grid = [spread(row) for row in rows]
    if not grid:
        return None
    width = max(len(row) for row in grid)
    if width == 0:
        return None
    grid = [row + [""] * (width - len(row)) for row in grid]
    name = tidy(caption["text"])
    described = is_description(name, width)
    headers, first = [], 0
    if described:
        columns = description_columns(grid, width)
    else:
        if rows and rows[0]["header"]:
            while first < len(grid) and rows[first]["header"]:
                headers.append(grid[first])
                first += 1
        else:
            headers, first = [grid[0]], 1
        columns = flatten_headers(headers)
    records = []
    for row in grid[first:]:
        if not any(space(value) for value in row):
            continue
        record = OrderedDict()
        for index, column in enumerate(columns):
            value = tidy(row[index]) if index < len(row) else ""
            if column in record and value:
                record[column] = tidy("%s %s" % (record[column], value))
            elif column not in record:
                record[column] = value
            elif value:
                record[column] = value
        records.append(record)
    table = OrderedDict()
    table["Наименование"] = name
    table["Страницы"] = []
    table["Заголовки"] = [[space(value) for value in row] for row in headers]
    table["Столбцы"] = columns
    table["Количество строк"] = len(records)
    table["Строки"] = records
    return table


def caption_key(caption):
    """Ключ таблицы/рисунка: «Таблица 5.3» (номер уже с словом)."""
    number = tidy(caption.get("number"))
    if re.match(r"^[А-Яа-яA-Za-z]", number or ""):
        return re.sub(r"\s+", " ", number)
    return "%s %s" % (CAPTION_WORD[caption["kind"]], number)


def spread(row):
    """Строка таблицы: данные — в левую ячейку слияния, шапка — во все свои.

    В действующих файлах столбцы широких таблиц называются «группа / пункт»
    («Передача на верхний уровень / АСУ»), поэтому в строках шапки текст
    объединённой ячейки раскладывается по всем покрытым столбцам.
    """
    cells = list(row["cells"])
    widths = row.get("widths") or []
    if not row["header"]:
        return cells
    start = ""
    for index, value in enumerate(cells):
        width = widths[index] if index < len(widths) else 1
        if width:
            start = value
        elif not value:
            cells[index] = start
    return cells


def is_description(name, width):
    """Таблица «Описание ШЭТ …» — параметр → значение, без строки шапки."""
    return width >= 2 and name.startswith("Описание ")


def description_columns(grid, width):
    """Столбцы описания шкафа: «Параметр», «Значение (ИЭУ1)», … как в базе."""
    names = []
    for row in grid:
        if space(row[0]).lower().startswith("мп устройство"):
            names = [space(value) for value in row[1:]]
            break
    columns = ["Параметр"]
    for index in range(1, width):
        label = names[index - 1] if index - 1 < len(names) else ""
        columns.append("Значение (%s)" % label if label
                       else ("Значение" if index == 1
                             else "Значение %d" % index))
    return columns


def flatten_headers(headers):
    """Шапка из 1…3 строк → имена столбцов «группа / подзаголовок»."""
    if not headers:
        return []
    width = max(len(row) for row in headers)
    columns = [""] * width
    for row in headers:
        for index in range(width):
            value = space(row[index]) if index < len(row) else ""
            if not value:
                continue
            if columns[index] and columns[index] != value:
                if value not in columns[index].split(" / "):
                    columns[index] = "%s / %s" % (columns[index], value)
            elif not columns[index]:
                columns[index] = value
    result, taken = [], set()
    for index, column in enumerate(columns):
        column = re.sub(r"\s*/\s*", " / ", column).strip(" /")
        column = column or "Столбец %d" % (index + 1)
        if column in taken:
            number = 2
            while "%s (%d)" % (column, number) in taken:
                number += 1
            column = "%s (%d)" % (column, number)
        taken.add(column)
        result.append(column)
    return result


def description(table):
    """Таблица «Описание ШЭТ …» → словарь полей карточки шкафа.

    Пустой параметр — продолжение предыдущего значения; повторяющийся
    параметр (две строки «Основные функции МП ИЭУ») и значения по ИЭУ —
    список, как в действующих файлах.
    """
    columns = table["Столбцы"]
    if len(columns) < 2:
        return OrderedDict()
    result = OrderedDict()
    last = None
    for row in table["Строки"]:
        key = space(row.get(columns[0]))
        values = [row.get(column, "") for column in columns[1:]]
        if not key and last is None:
            continue
        if not key:
            key = last
            merged = []
            previous = result.get(key)
            previous = previous if isinstance(previous, list) else [previous]
            for old, value in zip(previous, values):
                merged.append(tidy("%s; %s" % (old, value))
                              if space(old) and space(value)
                              else (space(old) or space(value)))
            push(result, key, merged, multi=False)
            continue
        value = values[0] if len(values) == 1 else [
            tidy(item) if not as_reference(item) else as_reference(item)
            for item in values]
        if isinstance(value, str):
            value = as_reference(value) or tidy(value)
        push(result, key, value, multi=len(values) > 1)
        last = key
    return result


def push(result, key, value, multi):
    """Занести поле описания: список по ИЭУ, повтор — тоже список."""
    empty = ("", "-", DASHES)
    if multi and isinstance(value, list):
        clean = [item for item in value if item and item not in empty]
        if len(set(clean)) <= 1:
            value = clean[0] if clean else ""
    if key in result:
        old = result[key]
        items = old if isinstance(old, list) else [old]
        items += value if isinstance(value, list) else [value]
        result[key] = [item for item in items if item]
        return
    result[key] = value


#: поле описания с именами ИЭУ и «ИЭУ1 (ИЭУ2)» в названиях параметров
IED_NAMES_RE = re.compile(r"^МП\s+устройство", re.I)
PAIRED_RE = re.compile(r"ИЭУ\s*1\s*\(\s*ИЭУ\s*2\s*\)", re.I)
KIT_PREFIX = "Комплект"


def ied_names(fields):
    """Имена ИЭУ шкафа: из «МП устройство РЗА» или из «ИЭУ1 (ИЭУ2)»."""
    for key, value in fields.items():
        if IED_NAMES_RE.match(space(key)):
            names = value if isinstance(value, list) else [value]
            names = [space(item) for item in names if space(item)]
            if names:
                return names
    for key in fields:
        if PAIRED_RE.search(space(key)):
            return ["ИЭУ1", "ИЭУ2"]
    return ["ИЭУ"]


def kits(fields):
    """Дополнить описание блоками «Комплект» / «Комплект 1, 2».

    Действующие файлы хранят комплекты явно: ``Имя ИЭУ`` плюс ``Таблицы
    комплекта`` со ссылками на таблицы этого ИЭУ. В DOCX то же самое живёт в
    таблице описания: значения по ИЭУ идут списком по колонкам, а имена ИЭУ —
    строкой «МП устройство РЗА».
    """
    names = ied_names(fields)
    result = OrderedDict(fields)
    blocks = []
    for index, name in enumerate(names):
        block = OrderedDict()
        block["Имя ИЭУ"] = name
        if len(names) > 1:
            tables, texts = OrderedDict(), OrderedDict()
            for key, value in fields.items():
                if key in (CODE_FIELD, IED_FIELD):
                    continue
                items = value if isinstance(value, list) else [value]
                if len(items) < len(names):
                    continue
                item = items[index]
                if not space(item):
                    continue
                (tables if str(item).lower().startswith("таблица")
                 else texts)[key] = item
            if tables:
                block["Таблицы комплекта"] = tables
            block.update(texts)
        blocks.append((name, block))
    if len(blocks) == 1:
        result[KIT_PREFIX] = blocks[0][1]
    else:
        for number, (_, block) in enumerate(blocks, start=1):
            result["%s %d" % (KIT_PREFIX, number)] = block
    return result


IED_FIELD = "МП устройство РЗА"


def description_table(tables):
    """Таблица «Описание …» в группе: («Таблица 5.2», объект)."""
    for key, table in tables.items():
        if table["Наименование"].startswith("Описание "):
            return key, table
    return None


SHETH_PREFIX = re.compile(r"^ШЭТ\s+", re.I)


def listing_rows(table):
    """Таблица перечня → строки с полями действующих JSON.

    Колонку «Код ШЭТ» чистят от префикса «ШЭТ » — в трёх действующих файлах
    перечень хранит голый код (``431.01-2``).
    """
    columns = table["Столбцы"]
    result = []
    for row in table["Строки"]:
        record = OrderedDict()
        for column in columns:
            value = space(row.get(column))
            field = LIST_COLUMNS.get(norm_head(column), column)
            if field == "Код ШЭТ":
                value = SHETH_PREFIX.sub("", space(value))
            if field in record and value:
                record[field] = "%s %s" % (record[field], value)
            elif value or field not in record:
                record[field] = value
        if not any(record.values()):
            continue
        for field in ("Наименование шкафа", "Код ШЭТ", "Функции РЗА",
                      "Примечание"):
            record.setdefault(field, "")          # порядок и состав, как в базе
        result.append(record)
    return result


def fix_listing(rows, codes):
    """Строка перечня → голый код шкафа, как в действующих файлах.

    В проектах колонка «Шифр ШЭТ» иногда содержит заголовок раздела целиком со
    ссылкой на его номер («…типа ШЭТ 431.11-1» + «5.3»). Шифр сверяется с
    карточками шкафов этого же стандарта и записывается коротко: «431.11-1».
    """
    for row in rows:
        value = space(row.get("Код ШЭТ"))
        plain = SHETH_PREFIX.sub("", value)
        if plain in codes:
            row["Код ШЭТ"] = plain
            continue
        found = [code for code in codes if code and code in value]
        if found:
            row["Код ШЭТ"] = max(found, key=len)


def appendix_of(key):
    """«Таблица А.12» → «А»; иначе None."""
    match = re.match(r"^Таблица\s+([А-Яа-яA-Z])\.\d+$", key)
    return match.group(1).upper() if match else None


def appendix_name(title):
    match = re.match(r"^\s*Приложение\s+([А-Яа-яA-Z])\b", title)
    return match.group(1).upper() if match else title


def norm_head(value):
    return re.sub(r"\s*[\[\(]\d+[\]\)]", "", space(value)).lower().strip(" .:")


def ref_key(name):
    """Имя таблицы для сравнения ссылок: регистр и пробелы не важны."""
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def shorten(text, limit=60):
    return text[:limit] + ("…" if len(text) > limit else "")


def first_words(block):
    """Первые слова строки таблицы — чтобы опознать пропущенную таблицу."""
    for row in block["rows"][:3]:
        for cell in row["cells"]:
            if space(cell):
                return space(cell)
    return ""


# ---------------------------------------------------------------------------
# Команда
# ---------------------------------------------------------------------------
def cipher_of(path):
    """Служебный шифр из имени файла: «Раздел 4.16_т. 3_…_Ред.2»."""
    base = os.path.splitext(os.path.basename(path))[0]
    parts = []
    section = re.search(r"[Рр]аздел\s*([\d.]+)", base)
    volume = re.search(r"[_\s][Тт]\.?\s*(\d+)", base)
    edition = re.search(r"[Рр]ед\.?\s*(\d+)", base)
    if section:
        parts.append("Раздел %s" % section.group(1))
    if volume:
        parts.append("т. %s" % volume.group(1))
    if edition:
        parts.append("ред. %s" % edition.group(1))
    parts = ["СТО (проект)"] + [", ".join(parts)]
    return " ".join(parts)


def all_tables(data):
    """Все таблицы собранного JSON: «Таблица 5.3» → объект таблицы."""
    found = {}
    for block in data["Содержимое стандарта"].values():
        if not isinstance(block, dict):
            continue
        for name, table in block.items():
            if isinstance(table, dict) and "Строки" in table:
                found[name] = table
            elif isinstance(table, dict):
                for key, item in table.items():
                    if isinstance(item, dict) and "Строки" in item:
                        found[key] = item
    return found


def verify(path, data, problems):
    """Сверка собранного JSON с ячейками DOCX: значение не должно теряться."""
    doc = Document(path)
    tables = all_tables(data)
    for block in doc.blocks():
        if block["kind"] != "tbl" or block.get("caption") is None:
            continue
        key = caption_key(block["caption"])
        table = tables.get(key)
        if table is None:
            continue
        rows = block["rows"]
        header = 0
        while header < len(rows) and rows[header]["header"]:
            header += 1
        if header == 0 and not is_description(table["Наименование"],
                                             len(rows[0]["cells"])):
            header = 1                    # первую строку считаем шапкой
        want = sum(1 for row in rows[header:] for cell in row["cells"]
                   if space(cell))
        got = sum(1 for row in table["Строки"] for value in row.values()
                  if space(value))
        if got < want:
            problems.append("%s (%s): в DOCX %d значений, в JSON %d"
                            % (key, shorten(table["Наименование"], 40),
                               want, got))
        if len(rows) - header != table["Количество строк"]:
            problems.append("%s: строк в DOCX %d, в JSON %d"
                            % (key, len(rows) - header,
                               table["Количество строк"]))


def check(data, problems):
    """Минимальная целостность собранного JSON."""
    content = data["Содержимое стандарта"]
    cards = [(name, block) for name, block in content.items()
             if isinstance(block, dict) and CODE_FIELD in block]
    codes, known = [], set()
    for name, card in cards:
        code = card[CODE_FIELD]
        if code in codes:
            problems.append("дублируется шифр шкафа %s" % code)
        codes.append(code)
        for field in ("Раздел стандарта", "Назначение шкафа",
                      DESCRIPTION_KEY, TABLES_KEY):
            if field not in card:
                problems.append("«%s»: нет поля «%s»" % (name, field))
        if not card.get("Назначение шкафа"):
            problems.append("%s: пустое «Назначение шкафа»" % code)
        known.update(ref_key(key) for key in card.get(TABLES_KEY, {}))
        for field, value in card.get(DESCRIPTION_KEY, {}).items():
            for item in (value if isinstance(value, list) else [value]):
                if isinstance(item, str) and ref_key(item).startswith("таблица") \
                        and ref_key(item) not in known:
                    problems.append("%s: ссылка «%s» (%s) никуда не ведёт"
                                    % (code, item, field))
    tables = sum(len(card.get(TABLES_KEY, {})) for _, card in cards)
    rows = 0
    for block in content.values():
        if not isinstance(block, dict):
            continue
        for value in (block.get(TABLES_KEY) or block).values() \
                if TABLES_KEY in block else block.values():
            if isinstance(value, dict) and "Строки" in value:
                rows += value["Количество строк"]
    return {"шкафов": len(cards), "таблиц шкафов": tables, "шифры": codes,
            "прочих таблиц": len(content.get(OTHER_KEY, {})),
            "строк всего": rows}


def convert(path, cipher=None, out_dir=None, dry_run=False,
            verify_flag=False):
    builder = Builder(path)
    data = builder.build(cipher or cipher_of(path))
    problems = list(builder.problems)
    stats = check(data, problems)
    if verify_flag:
        verify(path, data, problems)
    line = ("%s\n  шифр: %s\n  обозначение: %s\n  шкафов: %d · таблиц шкафов: %d"
            " · прочих таблиц: %d"
            % (os.path.basename(path), data["Шифр стандарта"],
               shorten(data["Обозначение стандарта"], 80), stats["шкафов"],
               stats["таблиц шкафов"],
               len(data["Содержимое стандарта"].get(OTHER_KEY, {}))))
    print(line)
    for name, block in data["Содержимое стандарта"].items():
        if isinstance(block, dict) and CODE_FIELD in block:
            print("    · %s %s — %d табл., %d полей описания"
                  % (block["Раздел стандарта"], block[CODE_FIELD],
                     len(block[TABLES_KEY]), len(block[DESCRIPTION_KEY])))
    for problem in problems:
        print("    !", problem)
    if dry_run:
        return data, problems
    target = os.path.join(out_dir or os.path.dirname(path),
                          data["Шифр стандарта"] + ".json")
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    print("  → %s (%.1f МБ)" % (target, os.path.getsize(target) / 1024 / 1024))
    return data, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="DOCX-файлы стандартов")
    parser.add_argument("--dir", default=None,
                        help="папка со DOCX (по умолчанию standards_base)")
    parser.add_argument("--out", help="папка для JSON (по умолчанию --dir)")
    parser.add_argument("--cipher", help="шифр стандарта (один файл)")
    parser.add_argument("--dry-run", action="store_true",
                        help="не записывать файлы")
    parser.add_argument("--verify", action="store_true",
                        help="сверить значения ячеек DOCX с собранным JSON")
    args = parser.parse_args(argv)
    target = args.dir or os.path.join(ROOT, "standards_base")
    paths = args.files or sorted(glob.glob(os.path.join(target, "*.docx")))
    if not paths:
        print("в %s нет DOCX" % target, file=sys.stderr)
        return 1
    bad = 0
    for path in paths:
        _, problems = convert(path, args.cipher if len(paths) == 1 else None,
                              args.out, args.dry_run, args.verify)
        bad += len(problems)
    return 1 if bad and args.dry_run is False and bad > 50 else 0


if __name__ == "__main__":
    sys.exit(main())
