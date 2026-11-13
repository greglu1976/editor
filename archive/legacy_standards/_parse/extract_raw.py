# -*- coding: utf-8 -*-
"""Черновая выгрузка всех таблиц из PDF стандарта в промежуточный JSON.

Сохраняет для каждого фрагмента таблицы:
  - номер/название подписи (или None для продолжения на следующей странице),
  - очищенные строки,
  - «сырые» строки с концевыми пробелами (признак границы слов),
  - восстановленный вертикальный текст шапок.
"""
import json
import re
import sys

import pdfplumber
import pdfplumber.utils as U

PDF = r"G:/e_standards/СТО 56947007-33.040.20.280-2019.pdf"
OUT = r"G:/e_standards/_parse/raw_tables.json"

CAP_RE = re.compile(r"^Таблица\s+([0-9]+(?:\.[0-9]+)*|А\.[0-9]+)\s*[-–—]\s*(.*)$", re.I)
SPACED_LETTERS = re.compile(
    r"(?<![А-Яа-яЁёA-Za-z])(?:[А-Яа-яЁёA-Za-z]\s){3,}[А-Яа-яЁёA-Za-z](?![А-Яа-яЁёA-Za-z])"
)


def is_rotated(obj):
    if obj["object_type"] != "char":
        return False
    m = obj.get("matrix") or (1, 0, 0, 1, 0, 0)
    return abs(m[1]) > 0.5 and abs(m[2]) > 0.5


def cell_text(chars, bbox):
    """Текст ячейки с сохранением концевых пробелов (признак границы слова)."""
    x0, top, x1, bottom = bbox
    sel = [c for c in chars
           if c["x0"] >= x0 - 0.5 and c["x1"] <= x1 + 0.5
           and c["top"] >= top - 0.5 and c["bottom"] <= bottom + 0.5]
    if not sel:
        return ""
    # y_tolerance=5 удерживает подстрочные индексы (Iср, Kторм) на одной строке
    return U.extract_text(sel, x_tolerance=1.5, y_tolerance=5, keep_blank_chars=True) or ""


def vertical_text(chars, bbox):
    """Восстановить вертикальный (повёрнутый на 90 градусов) текст ячейки."""
    x0, top, x1, bottom = bbox
    sel = [c for c in chars
           if c["x0"] >= x0 - 1 and c["x1"] <= x1 + 1
           and c["top"] >= top - 1 and c["bottom"] <= bottom + 1]
    if not sel:
        return ""
    groups = {}
    for c in sel:
        groups.setdefault(round(c["x0"], 1), []).append(c)
    parts = []
    for key in sorted(groups):
        line = sorted(groups[key], key=lambda c: (c.get("matrix") or (0, 0, 0, 0, 0, c["top"]))[5])
        parts.append("".join(c["text"] for c in line).strip())
    return " ".join(p for p in parts if p)


def clean_cell(raw):
    """Склеить визуальные переносы строк, не разрывая и не сливая слова."""
    if not raw:
        return ""
    t = raw.replace("\u00ad", "").replace("\uf06a", "φ").replace("\r", "\n")
    out = ""
    prev = ""
    prev_spaced = True
    for line in t.split("\n"):
        spaced = line != line.rstrip()
        s = re.sub(r"[ \t]+", " ", line).strip()
        if not s:
            continue
        if not out:
            out = s
        else:
            # концевой пробел => была граница слов; иначе слово разорвано переносом
            joiner = "" if not prev_spaced and not re.search(r"[,;:.)\-–—]$", prev) and not s.startswith("-") else " "
            # дефис на конце строки + строчная буква = перенос по слогам
            if prev.endswith("-") and (re.match(r"^[а-яёa-z]", s)
                                       or (re.search(r"\d-$", prev) and re.match(r"^\d", s))):
                joiner = ""
            out += joiner + s
        prev, prev_spaced = s, spaced
    out = SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), out)
    return re.sub(r"\s+", " ", out).strip()


def caption_lines(page, tables_top):
    """Найти подписи таблиц на странице: (y, номер, название)."""
    res = []
    lines = page.extract_text_lines()
    for i, ln in enumerate(lines):
        m = CAP_RE.match(ln["text"].strip())
        if not m:
            continue
        num, title = m.group(1), m.group(2).strip()
        top = ln["top"]
        limit = min([t for t in tables_top if t > top] or [10 ** 6])
        for nxt in lines[i + 1:]:
            if nxt["top"] >= limit - 2 or nxt["top"] > top + 45:
                break
            s = nxt["text"].strip()
            hyphenated = title.rstrip().endswith("-")
            if not s or (not hyphenated and re.match(r"^(№|\d|Рисунок|Таблица|-|–)", s)) or len(s) > 95:
                break
            title += ("" if hyphenated and re.match(r"^\d", s) else " ") + s
            top = nxt["top"]
        res.append((ln["top"], num, re.sub(r"\s+", " ", title).strip()))
    return res


def main():
    all_tables = []
    with pdfplumber.open(PDF) as pdf:
        for pi, page in enumerate(pdf.pages):
            hpage = page.filter(lambda o: not is_rotated(o))
            vchars = page.filter(is_rotated).chars
            hchars = hpage.chars
            found = hpage.find_tables()
            if not found:
                continue
            found = sorted(found, key=lambda t: (t.bbox[1], t.bbox[0]))
            caps = caption_lines(hpage, [t.bbox[1] for t in found])
            used = set()
            for tab in found:
                top = tab.bbox[1]
                cap = None
                for ci, c in enumerate(caps):
                    if ci in used:
                        continue
                    if c[0] < top + 3 and top - c[0] < 420:
                        cap = c
                        used.add(ci)
                        break
                rows, rows_raw, vertical = [], [], {}
                for ri, row in enumerate(tab.rows):
                    r, rr = [], []
                    for ci, box in enumerate(row.cells):
                        if box is None:
                            r.append("")
                            rr.append("")
                            continue
                        raw = cell_text(hchars, box)
                        r.append(clean_cell(raw))
                        rr.append(raw)
                        if ri < 3:
                            vt = vertical_text(vchars, box)
                            if vt:
                                vertical["%d,%d" % (ri, ci)] = clean_cell(vt)
                    rows.append(r)
                    rows_raw.append(rr)
                all_tables.append({
                    "page": pi + 1,
                    "bbox": [round(x, 1) for x in tab.bbox],
                    "caption": {"num": cap[1], "title": cap[2], "y": round(cap[0], 1)} if cap else None,
                    "rows": rows,
                    "rows_raw": rows_raw,
                    "vertical": vertical,
                })
            print("page %d: %d tables, %d captions" % (pi + 1, len(found), len(caps)), file=sys.stderr)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(all_tables, f, ensure_ascii=False, indent=1)
    print("total fragments:", len(all_tables), file=sys.stderr)


if __name__ == "__main__":
    main()
