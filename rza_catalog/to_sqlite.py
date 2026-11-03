# -*- coding: utf-8 -*-
"""Опциональная выгрузка нормализованного каталога в SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .models import RzaCatalog, StandardRef, SCHEMA_VERSION

_TABLES = (
    "catalog_meta",
    "test_block_circuits",
    "test_blocks",
    "analog_inputs",
    "kit_tags",
    "kit_signals",
    "container_tags",
    "container_controlled",
    "kit_functions",
    "container_functions",
    "ieds",
    "kits",
    "cabinets",
    "functions",
    "standards",
    "containers",
    "deleted",
)

_DROP = "\n".join(f"DROP TABLE IF EXISTS {table};" for table in _TABLES)

_DDL = """
CREATE TABLE standards (
  key TEXT PRIMARY KEY,
  title TEXT,
  edition TEXT,
  document TEXT,
  label TEXT
);

CREATE TABLE functions (
  code TEXT PRIMARY KEY,
  title TEXT
);

CREATE TABLE containers (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  group_name TEXT NOT NULL,
  voltage TEXT NOT NULL,
  protected TEXT NOT NULL,
  applicability TEXT,
  architecture TEXT,
  source TEXT,
  goose INTEGER NOT NULL,
  origin TEXT NOT NULL,
  standard_key TEXT REFERENCES standards(key) ON DELETE SET NULL,
  extensions_json TEXT NOT NULL,
  ord INTEGER NOT NULL
);

CREATE TABLE cabinets (
  id TEXT PRIMARY KEY,
  container_id TEXT NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  code TEXT,
  name TEXT,
  group_name TEXT,
  source TEXT,
  extensions_json TEXT NOT NULL,
  ord INTEGER NOT NULL,
  UNIQUE (container_id, key)
);

CREATE TABLE kits (
  id TEXT PRIMARY KEY,
  cabinet_id TEXT NOT NULL REFERENCES cabinets(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  type TEXT NOT NULL,
  description TEXT,
  has_ied INTEGER NOT NULL,
  source TEXT,
  extensions_json TEXT NOT NULL,
  ord INTEGER NOT NULL
);

CREATE TABLE ieds (
  id TEXT PRIMARY KEY,
  kit_id TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  description TEXT,
  ord INTEGER NOT NULL
);

CREATE TABLE container_functions (
  container_id TEXT NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
  function_code TEXT NOT NULL REFERENCES functions(code) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  PRIMARY KEY (container_id, function_code)
);

CREATE TABLE kit_functions (
  kit_id TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
  function_code TEXT NOT NULL REFERENCES functions(code) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  PRIMARY KEY (kit_id, function_code)
);

CREATE TABLE container_controlled (
  container_id TEXT NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
  value TEXT NOT NULL,
  ord INTEGER NOT NULL
);

CREATE TABLE container_tags (
  container_id TEXT NOT NULL REFERENCES containers(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  ord INTEGER NOT NULL,
  PRIMARY KEY (container_id, code)
);

CREATE TABLE kit_tags (
  kit_id TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  ord INTEGER NOT NULL,
  PRIMARY KEY (kit_id, code)
);

CREATE TABLE test_blocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kit_id TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('voltage', 'current', 'block')),
  name TEXT,
  circuits TEXT,
  count_value TEXT,
  note TEXT,
  ord INTEGER NOT NULL
);

CREATE TABLE test_block_circuits (
  block_id INTEGER NOT NULL REFERENCES test_blocks(id) ON DELETE CASCADE,
  circuit TEXT NOT NULL,
  ord INTEGER NOT NULL
);

CREATE TABLE kit_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kit_id TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('io_in', 'io_out', 'goose_in', 'goose_out')),
  name TEXT,
  code TEXT,
  details TEXT,
  ord INTEGER NOT NULL
);

CREATE TABLE analog_inputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kit_id TEXT NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
  block TEXT,
  signals TEXT,
  contacts TEXT,
  note TEXT,
  ord INTEGER NOT NULL
);

CREATE TABLE deleted (
  key TEXT PRIMARY KEY
);

CREATE TABLE catalog_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX idx_cabinets_container ON cabinets(container_id, ord);
CREATE INDEX idx_kits_cabinet ON kits(cabinet_id, ord);
CREATE INDEX idx_ieds_kit ON ieds(kit_id, ord);
CREATE INDEX idx_test_blocks_kit ON test_blocks(kit_id, ord);
CREATE INDEX idx_analog_inputs_kit ON analog_inputs(kit_id, ord);
CREATE INDEX idx_kit_signals_kit ON kit_signals(kit_id, kind, ord);
CREATE INDEX idx_container_functions_code ON container_functions(function_code);
CREATE INDEX idx_kit_functions_code ON kit_functions(function_code);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _all_standards(catalog: RzaCatalog) -> dict[str, StandardRef]:
    """Справочник стандартов, включая ключи, встреченные у контейнеров."""

    standards = dict(catalog.standards)
    for container in catalog.containers.values():
        key = container.standard_key
        if key and key not in standards:
            standards[key] = container.standard or StandardRef(key=key)
    return standards


def _export_database(catalog: RzaCatalog, path: Path) -> None:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(_DROP + "\n" + _DDL)
        connection.execute("PRAGMA foreign_keys = ON")

        with connection:
            cursor = connection.cursor()

            cursor.execute(
                "INSERT INTO catalog_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

            standards = _all_standards(catalog)
            for key, standard in standards.items():
                cursor.execute(
                    "INSERT INTO standards(key, title, edition, document, label) "
                    "VALUES (?,?,?,?,?)",
                    (key, standard.title, standard.edition, standard.document,
                     standard.label),
                )

            for code, function in catalog.functions.items():
                cursor.execute(
                    "INSERT INTO functions(code, title) VALUES (?,?)",
                    (code, function.title),
                )

            for container_order, container in enumerate(catalog.containers.values()):
                standard_key = container.standard_key
                if standard_key not in standards:
                    standard_key = None
                cursor.execute(
                    "INSERT INTO containers("
                    "id, key, code, name, title, description, group_name, "
                    "voltage, protected, applicability, architecture, source, "
                    "goose, origin, standard_key, extensions_json, ord"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        container.id, container.key, container.code,
                        container.name, container.title, container.description,
                        container.group, container.voltage, container.protected,
                        container.applicability, container.architecture,
                        container.source, int(container.goose), container.origin,
                        standard_key, _json(container.extensions),
                        container_order,
                    ),
                )

                for index, function in enumerate(container.its_functions):
                    cursor.execute(
                        "INSERT OR IGNORE INTO container_functions("
                        "container_id, function_code, ord) VALUES (?,?,?)",
                        (container.id, function.code, index),
                    )

                for index, controlled in enumerate(container.controlled):
                    cursor.execute(
                        "INSERT INTO container_controlled("
                        "container_id, value, ord) VALUES (?,?,?)",
                        (container.id, controlled, index),
                    )

                for index, tag in enumerate(container.tags):
                    cursor.execute(
                        "INSERT OR IGNORE INTO container_tags("
                        "container_id, code, ord) VALUES (?,?,?)",
                        (container.id, tag.code, index),
                    )

                for cabinet_order, cabinet in enumerate(container.cabinets):
                    cursor.execute(
                        "INSERT INTO cabinets("
                        "id, container_id, key, code, name, group_name, source, "
                        "extensions_json, ord"
                        ") VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            cabinet.id, container.id, cabinet.key, cabinet.code,
                            cabinet.name, cabinet.group, cabinet.source,
                            _json(cabinet.extensions), cabinet_order,
                        ),
                    )

                    for kit_order, kit in enumerate(cabinet.kits):
                        cursor.execute(
                            "INSERT INTO kits("
                            "id, cabinet_id, name, kind, type, description, "
                            "has_ied, source, extensions_json, ord"
                            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (
                                kit.id, cabinet.id, kit.name, kit.kind, kit.type,
                                kit.description, int(kit.has_ied), kit.source,
                                _json(kit.extensions), kit_order,
                            ),
                        )

                        for index, function in enumerate(kit.functions):
                            cursor.execute(
                                "INSERT OR IGNORE INTO kit_functions("
                                "kit_id, function_code, ord) VALUES (?,?,?)",
                                (kit.id, function.code, index),
                            )

                        for index, tag in enumerate(kit.tags):
                            cursor.execute(
                                "INSERT OR IGNORE INTO kit_tags("
                                "kit_id, code, ord) VALUES (?,?,?)",
                                (kit.id, tag.code, index),
                            )

                        for index, ied in enumerate(kit.ieds):
                            cursor.execute(
                                "INSERT INTO ieds("
                                "id, kit_id, name, type, description, ord"
                                ") VALUES (?,?,?,?,?,?)",
                                (ied.id, kit.id, ied.name, ied.type,
                                 ied.description, index),
                            )

                        block_order = 0
                        for kind, group in (
                            ("voltage", kit.test_blocks.voltage),
                            ("current", kit.test_blocks.current),
                        ):
                            if not group.count and not group.circuits:
                                continue
                            cursor.execute(
                                "INSERT INTO test_blocks("
                                "kit_id, kind, name, circuits, count_value, "
                                "note, ord) VALUES (?,?,?,?,?,?,?)",
                                (
                                    kit.id, kind, None,
                                    ", ".join(group.circuits),
                                    str(group.count), None, block_order,
                                ),
                            )
                            block_id = cursor.lastrowid
                            block_order += 1
                            for circuit_order, circuit in enumerate(group.circuits):
                                cursor.execute(
                                    "INSERT INTO test_block_circuits("
                                    "block_id, circuit, ord) VALUES (?,?,?)",
                                    (block_id, circuit, circuit_order),
                                )

                        for entry in kit.test_blocks.blocks:
                            cursor.execute(
                                "INSERT INTO test_blocks("
                                "kit_id, kind, name, circuits, count_value, "
                                "note, ord) VALUES (?,?,?,?,?,?,?)",
                                (
                                    kit.id, "block", entry.name, entry.circuits,
                                    entry.count, entry.note, block_order,
                                ),
                            )
                            block_order += 1

                        for kind, entries in (
                            ("io_in", kit.io_in),
                            ("io_out", kit.io_out),
                            ("goose_in", kit.goose_in),
                            ("goose_out", kit.goose_out),
                        ):
                            for index, signal in enumerate(entries):
                                cursor.execute(
                                    "INSERT INTO kit_signals("
                                    "kit_id, kind, name, code, details, ord"
                                    ") VALUES (?,?,?,?,?,?)",
                                    (
                                        kit.id, kind, signal.name,
                                        signal.code, signal.details, index,
                                    ),
                                )

                        for index, analog in enumerate(kit.analog_inputs):
                            cursor.execute(
                                "INSERT INTO analog_inputs("
                                "kit_id, block, signals, contacts, note, ord"
                                ") VALUES (?,?,?,?,?,?)",
                                (
                                    kit.id, analog.block, analog.signals,
                                    analog.contacts, analog.note, index,
                                ),
                            )

            for key in sorted(catalog.deleted):
                cursor.execute(
                    "INSERT OR IGNORE INTO deleted(key) VALUES (?)", (key,)
                )

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            details = ", ".join(
                f"{row['table']}:{row['rowid']} -> {row['parent']}"
                for row in violations[:5]
            )
            raise RuntimeError(
                f"Нарушена целостность SQLite: {details}"
            )
    finally:
        connection.close()


def export_sqlite(
    catalog: RzaCatalog,
    path: str | os.PathLike[str],
) -> None:
    """Пишет SQLite-базу атомарно (через временный файл)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        _export_database(catalog, temporary)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
