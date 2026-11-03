# -*- coding: utf-8 -*-
"""Выгрузка «Назначение шкафа» и «Основные компоненты шкафа» из PDF стандартов.

Каталог редактора хранит для этих полей только ссылки на таблицы стандарта
(«Таблица 5.2.21»), а сам текст — в PDF из ``standards/``. Скрипт читает
текст страниц, находит раздел шкафа по шифру и вытаскивает:

* «Назначение шкафа» — пункт ``5.N.1`` раздела (абзац до пункта ``5.N.2``);
* «Основные компоненты шкафа» — строки таблицы «Основные компоненты …»:
  №, наименование (полный текст строки) и количество, если оно стоит в конце.

Результат — ``standards/extracted.json`` вида::

    {"shet-211-01-1": {"Назначение шкафа": "…",
                      "Основные компоненты шкафа": [{"Наименование": "…",
                                                     "Количество": "1"}]},
     "ШЭТ 211.01-1": {…}}            # дубль по шифру — ключи/шифры эквивалентны

Текст страниц кэшируется в ``standards/text_cache.json`` — чтение PDF долгое.

Запуск:
    python3 tools/extract_standards.py                 # все PDF из standards/
    python3 tools/extract_standards.py --only 277 283  # выборочные документы
    python3 tools/extract_standards.py --workers 4
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STD_DIR = os.path.join(ROOT, "standards")
CACHE_DIR = os.path.join(STD_DIR, "text_cache")   # по файлу на документ
OUT = os.path.join(STD_DIR, "extracted.json")
#: модули проекта (sto_extract с таблицей раскодировки) лежат в корне
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CODE_RE = re.compile(r"(ШЭТ|ОЭТ|ШСО|ШСК|ШПДС|ШИП|ШКП|УПАСК|ПДС|ВК|АРНТ|ПА)"
                     r"[\s\-]*([0-9A-Za-z\u0410-\u042f().\-]{2,})", re.U)
SECTION_RE = re.compile(r"^\s*(\d+\.\d+)\s+(Шкаф|Комплект|Типовой шкаф)\b", re.U)
PURPOSE_RE = re.compile(r"^\s*(\d+\.\d+)\.1\s", re.U)
NEXT_ITEM_RE = re.compile(r"^\s*(\d+\.\d+)\.2\s|^\s*Таблица\s|^\s*Рисунок\s", re.U)
COMPONENTS_RE = re.compile(r"^\s*Таблица\s+[\d.]+\s*[-–—]\s*Основные компоненты",
                           re.U)
TABLE_BREAK_RE = re.compile(r"^\s*(Таблица|Рисунок)\s+[\d.]+", re.U)
ROW_RE = re.compile(r"^\s*(\d{1,3})\s+(\S.*)$")
COUNT_TAIL_RE = re.compile(r"^(.*?)[\s,]+(≥?\s?\d{1,4}(?:\s*шт\.?)?)\s*$")


def cache_file(stamp):
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", stamp)
    return os.path.join(CACHE_DIR, safe + ".json")


CYR_RE = re.compile(r"[\u0400-\u04FF]")
LAT_RE = re.compile(r"[A-Za-z]")


def garbled(pages):
    """True, если текста почти нет или вместо кириллицы — «глифовая» каша."""
    text = "".join(pages)
    cyr = len(CYR_RE.findall(text))
    lat = len(LAT_RE.findall(text))
    if len(text) < 2000:
        return False
    return cyr / max(1, cyr + lat) < 0.5


def pages_text(path):
    """Текст всех страниц PDF; кэш — отдельный файл на документ."""
    stamp = "%s:%d" % (os.path.basename(path), os.path.getsize(path))
    try:
        with open(cache_file(stamp), encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        pass
    pages = pypdf_pages(path) if FORCE_PYPDF else (mutool_pages(path) or
                                                   pypdf_pages(path))
    if garbled(pages):
        # в некоторых СТО шрифты без нормальной ToUnicode: читаем pypdf и
        # раскодируем таблицей подстановки из sto_extract.py
        try:
            import sto_extract
            fixed = [sto_extract.decode_text(page) for page in pypdf_pages(path)]
            if not garbled(fixed):
                pages = fixed
        except Exception as exc:
            print("  ! не раскодирован %s: %s" % (os.path.basename(path), exc),
                  file=sys.stderr)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_file(stamp), "w", encoding="utf-8") as handle:
            json.dump(pages, handle, ensure_ascii=False)
    except Exception:
        pass
    return pages


SUFFIX_RE = re.compile(r"^\s*[-\u2013]\s*(\d{1,2})\b")


MUTOOL = shutil.which("mutool")
FORCE_PYPDF = False


def mutool_pages(path):
    """Страницы текста через mupdf (быстрее pypdf в разы), либо None."""
    if not MUTOOL:
        return None
    handle, tmp = tempfile.mkstemp(suffix=".txt", dir=HERE)
    os.close(handle)
    try:
        subprocess.run([MUTOOL, "draw", "-F", "text", "-o", tmp, path],
                       check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=1800)
        with open(tmp, encoding="utf-8", errors="replace") as stream:
            raw = stream.read()
    except Exception as exc:
        print("mutool не справился (%s), пробую pypdf" % exc, file=sys.stderr)
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    pages = raw.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def pypdf_pages(path):
    """Страницы текста через pypdf (запасной вариант)."""
    from pypdf import PdfReader                       # локальный импорт
    reader = PdfReader(path)
    return [(page.extract_text() or "") for page in reader.pages]


def find_codes(text):
    """Шифры, упомянутые в тексте (для привязки раздела к шкафу каталога)."""
    codes = []
    for match in CODE_RE.finditer(text):
        code = re.sub(r"\s+", " ", match.group(0)).strip()
        # в PDF концовка шифра иногда уезжает за пробел: «ШЭТ 400.01 -1»
        tail = SUFFIX_RE.match(text[match.end():])
        if tail:
            code = "%s-%s" % (code, tail.group(1))
        if code not in codes:
            codes.append(code)
    return codes


def clean_paragraph(lines):
    """Собрать абзац: склеить переносы, убрать нумерацию пунктов."""
    text = " ".join(line.strip() for line in lines)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def code_key(code):
    """Ключ шифра для сопоставления: без пробелов, дефисы приведены к «-»."""
    text = re.sub(r"\s+", "", str(code or ""))
    text = text.replace("\u0415", "E").replace("\u2013", "-").replace("\u2014", "-")
    return text.upper()


TOC_LINE_RE = re.compile(r"\.{6,}")  # строки содержания с точками-отточками


def _body_pages(pages):
    """Страницы основного текста: без содержания (строки с точками-отточками)."""
    for page in pages:
        lines = page.split("\n")
        leaders = sum(1 for line in lines if TOC_LINE_RE.search(line))
        if leaders >= 3:
            continue
        yield lines


def _section_purpose(lines, index, section):
    """Абзац «5.N.1 …» — назначение шкафа раздела section (например «5.2»)."""
    start = None
    for offset in range(index, min(index + 8, len(lines))):
        line = lines[offset]
        if re.match(r"^\s*%s\.1\s" % re.escape(section), line):
            start = offset
            break
        if SECTION_RE.match(line) and not re.match(
                r"^\s*%s\s" % re.escape(section), line):
            return ""
    if start is None:
        return ""
    collected = []
    for offset in range(start, len(lines)):
        line = lines[offset]
        stripped = re.sub(r"^\s*%s\.1\s*" % re.escape(section), "", line).strip()
        if offset == start:
            if stripped:
                collected.append(stripped)
            continue
        if (NEXT_ITEM_RE.match(line) or SECTION_RE.match(line)
                or re.match(r"^\s*%s\." % re.escape(section), line)):
            break
        if stripped:
            collected.append(stripped)
    return clean_paragraph(collected)


def extract_sections(pages, source=""):
    """{шифр: {назначение, компоненты, документ}} по страницам документа."""
    found = {}
    last_code = ""
    for lines in _body_pages(pages):
        for index, line in enumerate(lines):
            head = SECTION_RE.match(line)
            if not head:
                continue
            section = head.group(1)
            heading_lines = [line]
            for offset in range(index + 1, min(index + 6, len(lines))):
                nxt = lines[offset]
                if (re.match(r"^\s*%s\.1\s" % re.escape(section), nxt)
                        or SECTION_RE.match(nxt) or NEXT_ITEM_RE.match(nxt)
                        or not nxt.strip()):
                    break
                heading_lines.append(nxt)
            heading = clean_paragraph(heading_lines)
            prefixes = ("ШЭТ", "ОЭТ", "ШСО", "ШСК", "ШПДС", "ПДС", "ШИП",
                        "ШКП", "ВК", "АРНТ", "ПА", "УПАСК")
            codes = [c for c in find_codes(heading) if c.upper().startswith(prefixes)]
            if not codes:
                continue
            last_code = codes[0]
            purpose = _section_purpose(lines, index, section)
            if purpose:
                entry = found.setdefault(code_key(codes[0]), {
                    "Назначение шкафа": "", "Основные компоненты шкафа": [],
                    "Документ": "", "Код": codes[0]})
                if len(purpose) > len(entry["Назначение шкафа"]):
                    entry["Назначение шкафа"] = purpose
                    entry["Документ"] = os.path.basename(source)

        for index, line in enumerate(lines):
            if not COMPONENTS_RE.match(line):
                continue
            codes = find_codes(clean_paragraph([line]))
            if not codes:
                # в шапке таблицы шифра нет — ищем в ближайших строках
                tail = clean_paragraph(lines[index:index + 6])
                codes = find_codes(tail)
            if not codes:
                codes = [last_code] if last_code else []
            rows = (_cells_rows(lines, index) if _is_cell_layout(lines, index)
                     else _line_rows(lines, index))
            if rows:
                entry = found.setdefault(code_key(codes[0]), {
                    "Назначение шкафа": "", "Основные компоненты шкафа": [],
                    "Документ": "", "Код": codes[0]})
                if len(rows) > len(entry["Основные компоненты шкафа"]):
                    entry["Основные компоненты шкафа"] = [_row_to_item(row)
                                                           for row in rows]
                    entry["Документ"] = os.path.basename(source)
    return found


CELL_START_RE = re.compile(r"^\d{1,3}$")


def _is_cell_layout(lines, index):
    """Раскладка mupdf: шапка таблицы стоит по одной ячейке на строку."""
    window = [line.strip() for line in lines[index + 1:index + 8]]
    return "№" in window and any(w == "Наименование" for w in window)


def _line_rows(lines, index):
    """Раскладка pypdf: строка таблицы — одна текстовая строка."""
    rows = []
    cursor = index + 1
    while cursor < len(lines) and not TABLE_BREAK_RE.match(lines[cursor]):
        text = lines[cursor].strip()
        if text and not text.startswith("№"):
            match = ROW_RE.match(text)
            if match:
                rows.append(match.group(2))
            elif rows:
                rows[-1] = clean_paragraph([rows[-1], text])
        cursor += 1
    return rows


def _cells_rows(lines, index):
    """Раскладка mupdf: номер строки отдельной строкой, ячейки построчно."""
    rows = []
    cells = []
    cursor = index + 1
    while cursor < len(lines) and not TABLE_BREAK_RE.match(lines[cursor]):
        text = lines[cursor].strip()
        cursor += 1
        if not text or text in ("№", "Наименование", "Характеристика",
                               "Количество, шт.", "Количество,шт."):
            continue
        if CELL_START_RE.match(text):
            if cells:
                rows.append(clean_paragraph(cells))
            cells = []
            continue
        cells.append(text)
    if cells:
        rows.append(clean_paragraph(cells))
    return rows


def _row_to_item(row):
    row = re.sub(r"\s+", " ", row).strip()
    match = COUNT_TAIL_RE.match(row)
    if match and match.group(2).strip():
        return {"Наименование": match.group(1).strip(),
                "Количество": match.group(2).strip()}
    return {"Наименование": row}


def process(path):
    pages = pages_text(path)
    return extract_sections(pages, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=[],
                        help="фрагменты шифра СТО (277, 283 …)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pypdf", action="store_true",
                        help="не использовать mutool (битые шрифты, ToUnicode)")
    parser.add_argument("--from-cache", action="store_true",
                        help="обработать только документы, чей текст уже в кэше")
    args = parser.parse_args(argv)

    files = sorted(f for f in os.listdir(STD_DIR) if f.lower().endswith(".pdf"))
    global FORCE_PYPDF
    FORCE_PYPDF = args.pypdf
    if args.from_cache:
        files = [f for f in files
                 if os.path.exists(cache_file(
                     "%s:%d" % (f, os.path.getsize(os.path.join(STD_DIR, f)))))]
    if args.only:
        files = [f for f in files if any(tag in f for tag in args.only)]
    if not files:
        print("нет PDF в standards/", file=sys.stderr)
        return 1

    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, os.path.join(STD_DIR, name)): name
                   for name in files}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                found = future.result()
            except Exception as exc:
                print("  ! %s: %s" % (name, exc), file=sys.stderr)
                continue
            for code, entry in found.items():
                target = result.setdefault(code, {
                    "Назначение шкафа": "",
                    "Основные компоненты шкафа": [],
                    "Документ": "",
                    "Код": ""})
                if len(entry["Назначение шкафа"]) > len(target["Назначение шкафа"]):
                    target["Назначение шкафа"] = entry["Назначение шкафа"]
                if len(entry["Основные компоненты шкафа"]) > \
                        len(target["Основные компоненты шкафа"]):
                    target["Основные компоненты шкафа"] = \
                        entry["Основные компоненты шкафа"]
                target["Документ"] = entry.get("Документ") or target["Документ"]
                target["Код"] = entry.get("Код") or target["Код"]
            print("  %s: %d шкафов" % (name, len(found)))

    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    purposes = sum(1 for v in result.values() if v["Назначение шкафа"])
    comps = sum(1 for v in result.values() if v["Основные компоненты шкафа"])
    print("\n%s: %d шифров, назначение — %d, компоненты — %d" % (
        OUT, len(result), purposes, comps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
