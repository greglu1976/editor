# -*- coding: utf-8 -*-
"""Сквозной конвейер разбора стандарта: PDF -> JSON -> отчёт DOCX.

Скрипт объединяет уже написанные этапы:

    _parse/extract_pdf.py        PDF -> черновая выгрузка таблиц (raw_tables_*.json)
    _parse/build_json_XXX.py     выгрузка -> итоговый JSON стандарта
    _parse/build_complects.py    JSON -> JSON со структурой «Комплект / Комплект 1 / ...»
    json_to_docx.py              JSON -> отчёт Word (используется как модуль)

По умолчанию готовая выгрузка и готовый JSON не пересчитываются: если JSON
уже есть, сразу строится DOCX. Это быстро и не меняет проверенные файлы.

Примеры:
    # один стандарт, готовый JSON -> DOCX
    python standard_to_docx.py "СТО 56947007-33.040.20.279-2019.json" --toc

    # все три стандарта в папке -> три отчёта
    python standard_to_docx.py --all --toc --out-dir "Отчеты"

    # пересобрать JSON из имеющейся черновой выгрузки, затем DOCX
    python standard_to_docx.py "СТО 56947007-33.040.20.279-2019.json" --rebuild

    # полный цикл от PDF: перечитать таблицы, собрать JSON, сделать DOCX
    python standard_to_docx.py "СТО 56947007-33.040.20.279-2019.pdf" --reextract --toc

    # PDF, для которого ещё нет JSON: полный цикл включается автоматически
    python standard_to_docx.py "СТО 56947007-33.040.20.279-2019.pdf" --toc

Новый стандарт: добавьте запись в STANDARDS (сборщик, имя выгрузки) и,
если нужно, настройку COMPLECTS в _parse/build_complects.py.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict

BASE = os.path.dirname(os.path.abspath(__file__))
PARSE = os.path.join(BASE, "_parse")
sys.path.insert(0, BASE)

from json_to_docx import build_report  # noqa: E402

# Код стандарта -> файлы конвейера.
STANDARDS = OrderedDict([
    ("279", {"builder": "build_json_279.py", "raw": "raw_tables_279.json",
             "text": "full_text_279.txt"}),
    ("280", {"builder": "build_json.py", "raw": "raw_tables.json",
             "text": None}),
    ("281", {"builder": "build_json_281.py", "raw": "raw_tables_281.json",
             "text": "full_text_281.txt"}),
])
CODE_RE = re.compile(r"33\.040\.20\.(\d{3})-2019", re.I)


def detect_code(path):
    m = CODE_RE.search(os.path.basename(path))
    if not m:
        sys.exit("Не удалось определить номер стандарта из имени: %s" % path)
    if m.group(1) not in STANDARDS:
        sys.exit("Стандарт %s не настроен. Добавьте его в STANDARDS." % m.group(1))
    return m.group(1)


def run(script, args=(), env=None):
    cmd = [sys.executable, script] + [str(a) for a in args]
    print("  > " + " ".join('"%s"' % c if " " in c else c for c in cmd[1:]),
          flush=True)
    subprocess.run(cmd, cwd=BASE, env=env, check=True)


def dump_text(pdf, dst):
    """Полнотекстовый дамп нужен сборщику 281, когда PDF недоступен."""
    try:
        import pymupdf
    except ImportError:
        print("  (pymupdf не установлен, текстовый дамп пропущен)", file=sys.stderr)
        return
    doc = pymupdf.open(pdf)
    with open(dst, "w", encoding="utf-8") as f:
        for i, page in enumerate(doc):
            f.write("\n\n========== PDF PAGE %d ==========\n" % (i + 1))
            f.write(page.get_text(sort=True))
    doc.close()


def rebuild(code, pdf, json_path, reextract=False):
    """Пересобрать итоговый JSON (при необходимости - из PDF)."""
    conf = STANDARDS[code]
    raw = os.path.join(PARSE, conf["raw"])
    if reextract:
        if not pdf or not os.path.exists(pdf):
            sys.exit("Для --reextract нужен PDF: %s" % pdf)
        print("[1/4] Извлечение таблиц из PDF")
        run(os.path.join(PARSE, "extract_pdf.py"), ["--pdf", pdf, "--out", raw])
        if conf["text"]:
            dump_text(pdf, os.path.join(PARSE, conf["text"]))
    elif not os.path.exists(raw):
        sys.exit("Нет черновой выгрузки %s. Запустите с PDF и --reextract." % raw)

    # Сборщики 279/280 читают 4-ю страницу PDF для «Области применения»;
    # у 281 есть резервный текстовый дамп full_text_281.txt.
    if code != "281" and (not pdf or not os.path.exists(pdf)):
        sys.exit("Для пересборки стандарта %s нужен PDF (область применения)." % code)
    if code == "281" and (not pdf or not os.path.exists(pdf)) \
            and not os.path.exists(os.path.join(PARSE, conf["text"])):
        sys.exit("Для 281 нужен PDF или _parse/full_text_281.txt")

    env = os.environ.copy()
    env["STO_PDF"] = pdf if pdf and os.path.exists(pdf) else ""
    env["STO_RAW"] = raw
    env["STO_OUT"] = json_path
    print("[2/4] Сборка JSON: %s" % conf["builder"])
    run(os.path.join(PARSE, conf["builder"]), env=env)
    print("[3/4] Разделение на комплекты")
    run(os.path.join(PARSE, "build_complects.py"),
        ["--json", json_path,
         "--report", os.path.join(PARSE, "complects_%s.txt" % code)], env=env)


def make_docx(json_path, docx_path, args, full_chain=False):
    print("[%s] Отчёт DOCX" % ("4/4" if full_chain else "1/1"))
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=OrderedDict)
    if "Содержимое стандарта" not in data:
        sys.exit("Не похоже на JSON стандарта: %s" % json_path)
    stats = build_report(
        data, docx_path, scope=args.scope, max_rows=args.max_rows,
        only=args.only, toc=args.toc, title=not args.no_title_page,
        portrait=args.portrait, base_size=args.font_size,
        tables_5x1=args.tables_5x1)
    print("Готово: %s" % docx_path)
    print("  шкафов %d, комплектов %d, таблиц %d, строк %d, %.1f КБ" %
          (stats["cabinets"], stats["complects"], stats["tables"],
           stats["rows"], os.path.getsize(docx_path) / 1024.0))
    return stats


def main():
    ap = argparse.ArgumentParser(
        description="PDF -> JSON -> DOCX для стандартов СТО 56947007-33.040.20.xxx-2019")
    ap.add_argument("inputs", nargs="*", help="PDF или JSON (допускаются маски)")
    ap.add_argument("--all", action="store_true",
                    help="все JSON стандартов в каталоге скрипта")
    ap.add_argument("--rebuild", action="store_true",
                    help="пересобрать JSON из готовой черновой выгрузки")
    ap.add_argument("--reextract", action="store_true",
                    help="перечитать таблицы из PDF, затем пересобрать JSON")
    ap.add_argument("--out", help="путь к DOCX (только для одного входа)")
    ap.add_argument("--out-dir", help="каталог для отчётов")
    ap.add_argument("--json-out",
                    help="куда записать пересобранный JSON (только для одного входа)")
    ap.add_argument("--scope", choices=("full", "cabinets", "brief"), default="full")
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--toc", action="store_true")
    ap.add_argument("--no-title-page", action="store_true")
    ap.add_argument("--portrait", action="store_true")
    ap.add_argument("--font-size", type=float, default=10)
    ap.add_argument("--tables-5x1", action="store_true")
    args = ap.parse_args()

    patterns = list(args.inputs)
    if args.all:
        patterns += [os.path.join(BASE, "СТО 56947007-*.json")]
    if not patterns:
        ap.error("укажите PDF/JSON или --all")

    inputs = []
    for pattern in patterns:
        found = (sorted(glob.glob(pattern))
                 if any(c in pattern for c in "*?[") else [pattern])
        if not found:
            sys.exit("Файл не найден: %s" % pattern)
        for path in found:
            path = os.path.abspath(path)
            if path not in inputs:
                inputs.append(path)
    if len(inputs) != 1 and (args.out or args.json_out):
        sys.exit("--out/--json-out допустимы только при одном входном файле")
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    for path in inputs:
        code = detect_code(path)
        ext = os.path.splitext(path)[1].lower()
        stem = os.path.splitext(path)[0]
        if ext == ".pdf":
            pdf, json_path = path, os.path.join(BASE, os.path.basename(stem) + ".json")
        elif ext == ".json":
            json_path = path
            pdf = os.path.join(BASE, os.path.basename(stem) + ".pdf")
        else:
            sys.exit("Ожидается .pdf или .json: %s" % path)
        if args.json_out:
            json_path = os.path.abspath(args.json_out)

        reextract = args.reextract or (ext == ".pdf" and not os.path.exists(json_path))
        need_rebuild = reextract or args.rebuild
        print("\n=== %s (%s) ===" % (os.path.basename(path), code))
        if need_rebuild:
            rebuild(code, pdf, json_path, reextract=reextract)
        if not os.path.exists(json_path):
            sys.exit("Нет JSON: %s" % json_path)

        if args.out:
            docx_path = os.path.abspath(args.out)
        elif args.out_dir:
            docx_path = os.path.join(
                os.path.abspath(args.out_dir),
                "Отчет_" + os.path.basename(stem) + ".docx")
        else:
            docx_path = "Отчет_" + os.path.basename(stem) + ".docx"
        make_docx(json_path, os.path.abspath(docx_path), args,
                  full_chain=need_rebuild)


if __name__ == "__main__":
    main()
