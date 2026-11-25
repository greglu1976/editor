#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Черновик схемы из PDF в формат редактора (JSON).

Что делает:
  1. вытаскивает подписи оборудования из PDF через `pdftotext -bbox`
     (нужен poppler; в TeX Live он лежит рядом с pdftotext);
  2. склеивает слова в обозначения ("ЗН ТР В 232 В", "2 СШ 500 кВ");
  3. определяет тип элемента по обозначению (В, ЛР, ШР, ТТ, ТН, ТР, АТ, ЗН,
     ОПН, КС, ВЧЗ, ФП, АВ/САВ, предохранитель, СШ);
  4. раскладывает элементы по колонкам-присоединениям и пишет JSON редактора.

Это именно черновик: имена и типы берутся из чертежа, а координаты
схематичные (колонки присоединений), связи не восстанавливаются.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- обозначения

FIRST_TOKEN_TYPES = [
    (r"^ЗН(-\d+)?$", "grounding_switch", "ЗН"),
    (r"^В$", "breaker", "В"),
    (r"^(АВ|САВ)$", "av_breaker", "АВ"),
    (r"^(ЛР|ШР|Р1|Р2)$", "disconnector", "Р"),
    (r"^ТР$", "transformer", "Т"),
    (r"^ТСН(-\d+)?$", "transformer", "Т"),
    (r"^АТ(-\d+)?$", "autotransformer", "АТ"),
    (r"^ТТ$", "current_transformer", "ТТ"),
    (r"^ТН$", "voltage_transformer", "ТН"),
    (r"^ОПН$", "opn", "ОПН"),
    (r"^КС$", "coupling_capacitor", "КС"),
    (r"^ВЧЗ$", "line_trap", "ВЧЗ"),
    (r"^ФП$", "connection_filter", "ФП"),
    (r"^[Пп]редохранитель$", "fuse", "ПР"),
]

BUS_TYPE = "bus"
DEFAULT_BUS_LENGTH = 240


def classify(text):
    """Возвращает (тип элемента, префикс имени) или (None, None)."""
    tokens = text.split()
    if not tokens:
        return None, None

    # Сначала обозначение элемента: "ЗН-1 2 СШ 500" — это заземляющий нож на шине,
    # а не шина, поэтому якорь имеет приоритет над словом "СШ" внутри подписи.
    for pattern, etype, prefix in FIRST_TOKEN_TYPES:
        if re.match(pattern, tokens[0]):
            # "В" без номера — это, скорее, обрывок подписи, а не выключатель
            if etype == "breaker" and not any(ch.isdigit() for ch in text):
                return None, None
            return etype, prefix

    # Шина: "2 СШ 500 кВ", "1 сек. 110 кВ"
    if len(tokens) >= 2 and tokens[0].isdigit() and tokens[1] in ("СШ", "сек."):
        return BUS_TYPE, "BB"
    if tokens[0] == "СШ":
        return BUS_TYPE, "BB"

    return None, None


# ---------------------------------------------------------------- разбор PDF

def find_pdftotext(explicit=None):
    if explicit:
        return explicit
    found = shutil.which("pdftotext")
    if found:
        return found
    candidates = [
        r"F:\latex\installed\texlive\2023\bin\windows\pdftotext.exe",
        r"C:\Program Files\poppler\Library\bin\pdftotext.exe",
        r"C:\poppler\bin\pdftotext.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def extract_words(pdf_path, pdftotext):
    """Возвращает список слов с координатами в точках PDF (начало — верхний левый угол)."""
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        out_path = tmp.name
    try:
        subprocess.run([pdftotext, "-bbox", pdf_path, out_path], check=True)
        root = ET.parse(out_path).getroot()
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass

    words = []
    for node in root.iter("{http://www.w3.org/1999/xhtml}word"):
        text = (node.text or "").strip()
        if not text:
            continue
        words.append({
            "text": text,
            "x1": float(node.get("xMin")),
            "y1": float(node.get("yMin")),
            "x2": float(node.get("xMax")),
            "y2": float(node.get("yMax")),
        })
    return words


def group_labels(words, line_tolerance=4.0, gap_limit=14.0):
    """Склеивает слова в строки, затем строки — в отдельные обозначения."""
    lines = []
    for word in sorted(words, key=lambda w: ((w["y1"] + w["y2"]) / 2.0, w["x1"])):
        cy = (word["y1"] + word["y2"]) / 2.0
        target = None
        for line in lines:
            if abs(line["cy"] - cy) <= line_tolerance:
                target = line
                break
        if target is None:
            lines.append({"cy": cy, "words": [word]})
        else:
            target["words"].append(word)
            target["cy"] = sum((w["y1"] + w["y2"]) / 2.0 for w in target["words"]) / len(target["words"])

    labels = []
    for line in lines:
        ordered = sorted(line["words"], key=lambda w: w["x1"])
        current = [ordered[0]]
        for previous, word in zip(ordered, ordered[1:]):
            if word["x1"] - previous["x2"] > gap_limit:
                labels.append(current)
                current = [word]
            else:
                current.append(word)
        labels.append(current)

    result = []
    for group in labels:
        text = " ".join(w["text"] for w in group)
        text = re.sub(r"\s+", " ", text).strip()
        x1 = min(w["x1"] for w in group)
        x2 = max(w["x2"] for w in group)
        y1 = min(w["y1"] for w in group)
        y2 = max(w["y2"] for w in group)
        result.append({
            "text": text,
            "x1": x1, "x2": x2,
            "y1": y1, "y2": y2,
            "cx": (x1 + x2) / 2.0,
            "cy": (y1 + y2) / 2.0,
        })
    return result


# ---------------------------------------------------------------- раскладка

def split_columns(labels, column_gap=130.0):
    """Группирует метки в колонки-присоединения по горизонтали."""
    columns = []
    for label in sorted(labels, key=lambda l: l["x1"]):
        if columns and label["x1"] - columns[-1]["x"] <= column_gap:
            columns[-1]["labels"].append(label)
        else:
            columns.append({"x": label["x1"], "labels": [label]})
    for column in columns:
        column["labels"].sort(key=lambda l: l["cy"])
    return columns


def make_elements(labels, layout="columns", scale=1.0, pitch=90, column_width=480,
                  bus_length=DEFAULT_BUS_LENGTH, origin=(120, 120)):
    """Превращает метки в элементы схемы (схематичная раскладка)."""
    buses = [l for l in labels if classify(l["text"])[0] == BUS_TYPE]
    others = [l for l in labels if classify(l["text"])[0] not in (None, BUS_TYPE)]

    elements = []
    used_names = {}

    def unique_name(text):
        name = text.strip()
        if name[:1].islower():
            name = name[0].upper() + name[1:]
        count = used_names.get(name, 0) + 1
        used_names[name] = count
        return f"{name} ({count})" if count > 1 else name

    def make_id(etype):
        return f"{etype[:2].upper()}{uuid.uuid4().hex[:4]}"

    if layout == "faithful":
        for label in others + buses:
            etype, _prefix = classify(label["text"])
            if not etype:
                continue
            item = {
                "id": make_id(etype),
                "type": etype,
                "name": unique_name(label["text"]),
                "x": round(label["cx"] * scale / 20) * 20,
                "y": round(label["cy"] * scale / 20) * 20,
            }
            if etype == BUS_TYPE:
                item["length"] = bus_length
            elements.append(item)
        return elements

    # --- схематичная раскладка: шины сверху, присоединения колонками ---
    ox, oy = origin
    bus_per_row = 5
    for index, label in enumerate(buses):
        row, col = divmod(index, bus_per_row)
        elements.append({
            "id": make_id(BUS_TYPE),
            "type": BUS_TYPE,
            "name": unique_name(label["text"]),
            "x": ox + col * 760 + bus_length,
            "y": oy + row * 160,
            "length": bus_length,
        })

    bus_rows = (len(buses) + bus_per_row - 1) // bus_per_row
    top = oy + bus_rows * 160 + 220

    columns = split_columns(others)
    for col_index, column in enumerate(columns):
        for row_index, label in enumerate(column["labels"]):
            etype, _prefix = classify(label["text"])
            if not etype:
                continue
            elements.append({
                "id": make_id(etype),
                "type": etype,
                "name": unique_name(label["text"]),
                "x": ox + col_index * column_width,
                "y": top + row_index * pitch,
            })
    return elements


# ---------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Черновик схемы: подписи из PDF -> JSON редактора электрических схем.")
    parser.add_argument("pdf", help="исходный PDF")
    parser.add_argument("-o", "--output", help="куда сохранить JSON (по умолчанию рядом с PDF)")
    parser.add_argument("--layout", choices=["columns", "faithful"], default="columns",
                        help="columns — колонки присоединений (по умолчанию); "
                             "faithful — координаты из PDF")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="множитель координат для layout=faithful (по умолчанию 1.0)")
    parser.add_argument("--pitch", type=int, default=90,
                        help="шаг по вертикали внутри колонки, единицы редактора (по умолчанию 90)")
    parser.add_argument("--column-width", type=int, default=480,
                        help="расстояние между колонками присоединений (по умолчанию 480)")
    parser.add_argument("--pdftotext", help="путь к pdftotext.exe")
    parser.add_argument("--quiet", action="store_true", help="не печатать сводку")
    args = parser.parse_args(argv)

    tool = find_pdftotext(args.pdftotext)
    if not tool:
        parser.error("не найден pdftotext (poppler). Укажите путь через --pdftotext.")

    words = extract_words(args.pdf, tool)
    labels = group_labels(words)

    if not words:
        print("В PDF нет текстового слоя (скан или текст переведён в кривые).")
        print("Такой файл нельзя разобрать автоматически: нужен OCR (Tesseract) "
              "или разметка поверх подложки.")
        return 2

    parsed = []
    skipped = []
    for label in labels:
        etype, _prefix = classify(label["text"])
        if etype:
            parsed.append(label)
        else:
            skipped.append(label["text"])

    if not parsed:
        print("Текстовый слой есть, но обозначений оборудования не найдено "
              f"(подписей: {len(labels)}). Проверьте формат обозначений.")
        print("Первые подписи: " + "; ".join(l["text"] for l in labels[:8]))
        return 3

    elements = make_elements(parsed, layout=args.layout, scale=args.scale,
                             pitch=args.pitch, column_width=args.column_width)

    output = args.output
    if not output:
        base = os.path.splitext(os.path.basename(args.pdf))[0]
        output = os.path.join(os.path.dirname(os.path.abspath(args.pdf)), f"{base}.json")

    with open(output, "w", encoding="utf-8") as f:
        json.dump({"elements": elements, "connections": []}, f,
                  ensure_ascii=False, indent=2)

    if not args.quiet:
        counts = {}
        for item in elements:
            counts[item["type"]] = counts.get(item["type"], 0) + 1
        print(f"PDF:      {args.pdf}")
        print(f"Слов:     {len(words)}")
        print(f"Обозначений распознано: {len(parsed)}, пропущено подписей: {len(skipped)}")
        for etype, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"   {etype:24s} {count}")
        print(f"JSON:     {output}")
        if skipped:
            print("Пропущенные подписи (первые 10): " + "; ".join(skipped[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
