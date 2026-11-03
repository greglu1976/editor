# -*- coding: utf-8 -*-
"""CLI миграции: cabinets.json → нормализованный JSON (+ SQLite)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .export import catalog_counts, dump_catalog
from .migrate import MigrationError, load_catalog
from .to_sqlite import export_sqlite
from .validate import CatalogValidationError, validate_catalog

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "cabinets.json"
DEFAULT_JSON = ROOT / "output" / "catalog.normalized.json"
DEFAULT_SQLITE = ROOT / "output" / "catalog.sqlite"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rza_catalog",
        description=(
            "Перекладывает исходный JSON каталога (custom/overrides/deleted) "
            "в нормализованную модель container → cabinet → kit → ied."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"исходный JSON (по умолчанию: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON,
        help=f"куда писать нормализованный JSON (по умолчанию: {DEFAULT_JSON})",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=DEFAULT_SQLITE,
        help=f"куда писать SQLite (по умолчанию: {DEFAULT_SQLITE})",
    )
    parser.add_argument(
        "--no-sqlite",
        action="store_true",
        help="не выгружать SQLite",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="падать на повторах ключей и ошибках формата",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="rza_catalog 1",
    )
    return parser


def _human_size(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} КиБ"
    return f"{size / (1024 * 1024):.1f} МиБ"


def _print_report(counts: dict[str, int], *, json_path: Path,
                  sqlite_path: Optional[Path]) -> None:
    print(f"Контейнеров:        {counts['containers']}")
    print(f"Шкафов:             {counts['cabinets']}")
    print(f"Комплектов:         {counts['kits']} "
          f"(с ИЭУ: {counts['kits_with_ied']})")
    print(f"ИЭУ:                {counts['ieds']}")
    print(f"Функций:            {counts['functions']}")
    print(f"Стандартов:         {counts['standards']}")
    print(f"Испытательных блоков: {counts['test_blocks']}")
    print(f"Аналоговых входов:  {counts['analog_inputs']}")
    print(f"Удалённых ключей:   {counts['deleted']}")
    print()
    print(f"JSON:   {json_path} ({_human_size(json_path)})")
    if sqlite_path is not None:
        print(f"SQLite: {sqlite_path} ({_human_size(sqlite_path)})")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    source: Path = args.source
    if not source.exists():
        print(f"Источник не найден: {source}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Не удалось прочитать {source}: {exc}", file=sys.stderr)
        return 2

    report: list[str] = []
    try:
        catalog = load_catalog(raw, report=report, strict=args.strict)
    except MigrationError as exc:
        print(f"Ошибка миграции: {exc}", file=sys.stderr)
        return 2

    try:
        validate_catalog(catalog)
    except CatalogValidationError as exc:
        print("Каталог не прошёл проверку целостности:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    try:
        dump_catalog(catalog, args.json)
        sqlite_path: Optional[Path] = None
        if not args.no_sqlite:
            export_sqlite(catalog, args.sqlite)
            sqlite_path = args.sqlite
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Не удалось записать результат: {exc}", file=sys.stderr)
        return 1

    print(f"Источник: {source}")
    print()
    _print_report(catalog_counts(catalog), json_path=args.json,
                  sqlite_path=sqlite_path)

    if report:
        print()
        print(f"Предупреждения ({len(report)}):")
        for warning in report:
            print(f"  - {warning}")

    return 0
