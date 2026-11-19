#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевод JSON стандартов на модель ``EA/structure2.xml``.

Что делает:

1. Старый плоский список ``functions`` превращает в ``function_blocks``
   (:func:`ea_model.migrate_document`) — groupby по ``russian_path``.
2. Добавляет отсутствующие поля всех классов модели: ``IED.description``,
   ``Table.colums_width``, ``TerminalRow.assembly_unit``, поля ``Input``,
   ``Output``, ``Setting`` и т. д. Старые имена (``Location``, ``conditions``)
   переименовываются.
3. Ничего не удаляет: дополнительные поля редактора сохраняются.

Повторный запуск ничего не меняет.

    python3 tools/migrate_standards_structure2.py --check
    python3 tools/migrate_standards_structure2.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ea_model          # noqa: E402
import ea_schema as sc   # noqa: E402
import ea_standard as es  # noqa: E402


def report(data):
    """Счётчик отсутствующих полей по классам схемы."""
    found = Counter()

    def walk(node, cls):
        if not isinstance(node, dict):
            return
        for key in sc.missing_fields(cls, node):
            found["%s.%s" % (cls, key)] += 1
        for key, child in sc.children(cls):
            values = node.get(key)
            if isinstance(values, list):
                for value in values:
                    walk(value, child)

    walk(data, "Standard")
    return found


def migrate_file(path, write=True, add_children=False):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    missing = report(data)
    _data, legacy = ea_model.migrate_document(data)
    normalized = sc.normalize_document(data, add_children=add_children)
    changed = legacy or normalized
    if changed and write:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return changed, missing, legacy


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Стандарты EA → модель structure2")
    parser.add_argument("paths", nargs="*", help="JSON стандартов (по умолчанию все)")
    parser.add_argument("--check", action="store_true",
                        help="только показать, что будет изменено")
    parser.add_argument("--add-children", action="store_true",
                        help="создавать пустые коллекции для всех классов")
    args = parser.parse_args(argv)

    paths = args.paths or es.files()
    changed = 0
    for path in paths:
        try:
            updated, missing, legacy = migrate_file(
                path, write=not args.check, add_children=args.add_children)
        except (OSError, ValueError) as exc:
            print("ошибка %s: %s" % (os.path.basename(path), exc))
            return 1
        print("%s: %s" % (os.path.basename(path),
                          "обновлён" if updated else "без изменений"))
        if missing:
            for name, count in sorted(missing.items()):
                print("    %-42s %d" % (name, count))
        if legacy:
            print("    плоский functions → function_blocks")
        if updated:
            changed += 1
    print("файлов обновлено: %d" % changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
