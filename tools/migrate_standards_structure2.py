#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевод JSON стандартов на расширенную модель ``EA/structure2.xml``.

Старые файлы хранили плоский список ``functions``: запись была одновременно
блоком и функцией, а параметры лежали прямо в ней. Новый вид:

    IED → function_blocks → functions → inputs / outputs / settings / parameters

Скрипт обратим по смыслу: данные не переписываются заново, а группируются по
``russian_path`` (имя блока) и получают поля structure2. Повторный запуск
ничего не меняет.

    python3 tools/migrate_standards_structure2.py --check
    python3 tools/migrate_standards_structure2.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ea_model          # noqa: E402
import ea_standard as es  # noqa: E402


def migrate_file(path, write=True):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    _data, changed = ea_model.migrate_document(data)
    if changed and write:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Стандарты EA → расширенная модель structure2")
    parser.add_argument("paths", nargs="*", help="JSON стандартов (по умолчанию все)")
    parser.add_argument("--check", action="store_true",
                        help="только показать, что будет изменено")
    args = parser.parse_args(argv)

    paths = args.paths or es.files()
    changed = 0
    for path in paths:
        try:
            if migrate_file(path, write=not args.check):
                changed += 1
                print("обновлён: %s" % os.path.basename(path))
            else:
                print("без изменений: %s" % os.path.basename(path))
        except (OSError, ValueError) as exc:
            print("ошибка %s: %s" % (os.path.basename(path), exc))
            return 1
    print("файлов обновлено: %d" % changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
