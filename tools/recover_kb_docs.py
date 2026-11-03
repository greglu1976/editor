# -*- coding: utf-8 -*-
"""Восстановление исходных JSON-документов из базы знаний DSH.

Документы «Исходные» (T1.json, T2.json, line1.json, line2.json, bus1.json,
Bus2.json, emer1.json) в файловой системе отсутствуют — остались только
чанки в sqlite-хранилище базы знаний (окна наложения). Скрипт склеивает
чанки по перекрытиям, проверяет результат как JSON и пишет восстановленный
файл в standards/src/<имя>.json.

Запуск:
    python3 tools/recover_kb_docs.py            # все документы базы «Исходные»
    python3 tools/recover_kb_docs.py --list     # показать, что есть в хранилище
    python3 tools/recover_kb_docs.py T2.json    # только один документ
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "standards", "src")
STORE = os.path.expanduser("~/.dsh/storages/knowledge-chunks.sqlite")

#: Имя базы знаний, из которой достаём исходники.
BASE_NAME = "Исходные"

#: Отпечатки начала чанка, по которым ищем совмещение (от длинного к короткому).
HEAD_PROBES = (200, 120, 80, 60, 40, 30, 24, 20, 16, 12)


def documents(con):
    """[(doc_id, title, base)] — все документы хранилища."""
    rows = con.execute(
        "select distinct c.doc_id, c.context, c.base_id from chunk c"
    ).fetchall()
    out = []
    for doc_id, ctx, base_id in rows:
        title = (ctx or "").strip() or doc_id
        out.append((doc_id, title, base_id))
    return out


def base_names(con):
    try:
        return {r[0]: r[1] for r in con.execute(
            "select base_id, name from base")}
    except sqlite3.Error:
        return {}


def stitch(chunks):
    """Склеить упорядоченные чанки (окна наложения) в исходный текст."""
    acc = chunks[0]
    report = []
    for i, chunk in enumerate(chunks[1:], start=1):
        if not chunk:
            report.append((i, "пустой", 0))
            continue
        placed = False
        for probe in HEAD_PROBES:
            if len(chunk) < probe:
                continue
            pos = acc.rfind(chunk[:probe])
            if pos < 0:
                continue
            skip = len(acc) - pos                 # сколько чанка уже в acc
            if skip >= len(chunk):
                report.append((i, "содержится целиком", probe))
            else:
                acc += chunk[skip:]
                report.append((i, "совмещение", probe))
            placed = True
            break
        if placed:
            continue
        # хвост актуального текста == начало чанка (точное перекрытие)
        limit = min(len(acc), len(chunk), 4000)
        for length in range(limit, 15, -1):
            if acc.endswith(chunk[:length]):
                acc += chunk[length:]
                report.append((i, "перекрытие хвоста", length))
                placed = True
                break
        if not placed:
            acc += chunk
            report.append((i, "ДОПИСАНО БЕЗ СОВМЕЩЕНИЯ", 0))
    return acc, report


def main(argv):
    if not os.path.exists(STORE):
        print("хранилище базы знаний не найдено:", STORE, file=sys.stderr)
        return 2
    con = sqlite3.connect("file:%s?mode=ro" % STORE, uri=True)

    bases = base_names(con)
    #: В этом хранилище имён баз нет (только чанки), поэтому ориентируемся на
    #: расширение: исходники шкафов — .json, документация — .md и т. п.
    docs = [d for d in documents(con)
            if d[1].lower().endswith(".json")]
    wanted = [a for a in argv if not a.startswith("-")]
    if "--list" in argv:
        for doc_id, title, base_id in sorted(docs, key=lambda d: d[1]):
            n = con.execute("select count(*) from chunk where doc_id=?",
                            (doc_id,)).fetchone()[0]
            print("%-16s %-40s %s chunks" %
                  (bases.get(base_id, base_id)[:16], title, n))
        return 0

    if bases:
        target_base = next((b for b, n in bases.items() if n == BASE_NAME), None)
        docs = [d for d in docs if target_base is None or d[2] == target_base]

    if wanted:
        docs = [d for d in docs
                if os.path.basename(d[1]).lower() in
                   [w.lower() for w in wanted]]

    os.makedirs(OUT_DIR, exist_ok=True)
    failures = []
    for doc_id, title, _base in sorted(docs, key=lambda d: d[1]):
        rows = con.execute(
            "select idx, text from chunk where doc_id=? order by idx",
            (doc_id,)).fetchall()
        if not rows:
            continue
        chunks = [r[1] for r in rows]
        text, report = stitch(chunks)
        name = os.path.basename(title) if title.endswith(".json") else title + ".json"
        safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or doc_id
        out_path = os.path.join(OUT_DIR, safe)
        status = "?"
        try:
            data = json.loads(text)
            cabinets = len(data) if isinstance(data, list) else 1
            status = "OK %s записей" % cabinets
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
        except Exception as exc:
            failures.append((name, str(exc)))
            with open(out_path + ".raw", "w", encoding="utf-8") as fh:
                fh.write(text)
        rough = [r for r in report if r[1] not in ("совмещение", "перекрытие хвоста",
                                                   "содержится целиком")]
        print("%-14s %5d chunks %9d chars  %s%s" % (
            name, len(rows), len(text), status,
            ("  подозрения: %s" % rough[:4]) if rough else ""))

    if failures:
        print("\nНЕ СОБРАНО как JSON:", file=sys.stderr)
        for name, err in failures:
            print("  %s: %s" % (name, err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
