# -*- coding: utf-8 -*-
"""Тесты нормализованной модели каталога РЗА."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rza_catalog.export import catalog_counts, catalog_to_dict
from rza_catalog.migrate import (
    MigrationError,
    load_catalog,
    repair_functions,
)
from rza_catalog.models import ContainerOrigin
from rza_catalog.to_sqlite import export_sqlite
from rza_catalog.validate import CatalogValidationError, validate_catalog


def _kit(
    name: str,
    *,
    cabinet_key: str | None = "cab1",
    functions: list[str] | None = None,
    with_ied: bool = True,
    **extra,
) -> dict:
    result = {
        "key": "",
        "kind": "typical",
        "name": name,
        "type": "МП РЗА",
        "functions": functions or ["ДЗТ"],
        "desc": f"{name}: описание",
        "has_ied": with_ied,
        "ieds": (
            [{"name": "ИЭУ1", "type": "МП РЗА", "desc": "описание ИЭУ"}]
            if with_ied else []
        ),
        "test_blocks": {
            "voltage": {"count": 0, "circuits": []},
            "current": {"count": 0, "circuits": []},
        },
        "source": "user",
    }
    if cabinet_key:
        result.update({
            "cabinet_key": cabinet_key,
            "cabinet_index": 0,
            "cabinet_code": cabinet_key.upper(),
            "cabinet_name": f"Шкаф {cabinet_key}",
            "cabinet_group": "Т/АТ",
        })
    result.update(extra)
    return result


def sample_source() -> dict:
    return {
        "custom": [
            {
                "key": "cont-1",
                "standard_key": "tat",
                "standard_title": "СТО 56947007-33.040.20.277-2019",
                "edition": "Редакция 1",
                "document": "doc.pdf",
                "standard": "СТО кратко",
                "code": "C-1",
                "name": "Контейнер 1",
                "title": "Контейнер 1 (полное)",
                "description": "Описание контейнера",
                "group": "Т/АТ",
                "voltage": "110 кВ",
                "protected": "Автотрансформатор",
                "controlled": ["Q1", "Q2"],
                "its_functions": ["ДЗТ", "СЗ ВН (ДЗ", "ТНЗНП", "БК)"],
                "applicability": "применимо",
                "architecture": "II тип",
                "source": "разд. 1",
                "goose": True,
                "tags": ["tag1", "tag1"],
                "unknown_container_field": {"a": 1},
                "komplets": [
                    _kit(
                        "Комплект 1",
                        functions=["СЗ ВН (ДЗ", "ТНЗНП", "БК)", "ДЗТ"],
                        tags=["kit-tag"],
                        test_blocks={
                            "voltage": {"count": 2,
                                        "circuits": ["Ua", "Ub"]},
                            "current": {"count": 1,
                                        "circuits": ["Ia"]},
                        },
                        test_block_list=[
                            {"name": "SG1", "circuits": "Ia",
                             "count": "6+1", "note": "примечание"}
                        ],
                        analog_inputs=[
                            {"block": "SG1", "signals": "Ia",
                             "contacts": "6+1", "note": "вход"}
                        ],
                        io_in=[{"name": "Пуск", "code": "PTRC.Str",
                                "details": "цепь 1"}],
                        io_out=[{"name": "Отключить", "code": "PTRC.Op",
                                 "details": "цепь 2"}],
                        mp_functions="основные функции",
                        notes="примечание комплекта",
                    ),
                    _kit(
                        "Комплект 2",
                        functions=["ДЗТ", "ДЗТ"],
                        with_ied=False,
                    ),
                    _kit("Комплект 3", cabinet_key="cab2",
                         functions=["РАС"], with_ied=False),
                    _kit("Комплект 4", cabinet_key=None,
                         functions=["АПВ"], with_ied=False),
                ],
            },
            {
                "key": "cont-2",
                "code": "C-2",
                "name": "Удаляемый",
                "komplets": [],
            },
        ],
        "overrides": {
            "cont-1": {
                "title": "Контейнер 1 (override)",
                "goose": False,
                "unknown_container_field": {"b": 2},
            }
        },
        "deleted": ["cont-2"],
    }


class RepairFunctionsTest(unittest.TestCase):
    def test_fragments_are_glued(self) -> None:
        raw = ["СЗ ВН (ДЗ", "ТНЗНП", "МТЗ", "ОУ", "АУ", "БНН", "БК)"]
        self.assertEqual(
            repair_functions(raw),
            ["СЗ ВН (ДЗ, ТНЗНП, МТЗ, ОУ, АУ, БНН, БК)"],
        )

    def test_balanced_and_unclosed(self) -> None:
        self.assertEqual(
            repair_functions(["ДЗТ", "СЗ (ДЗ", "ТНЗНП", "БК)", "РАС"]),
            ["ДЗТ", "СЗ (ДЗ, ТНЗНП, БК)", "РАС"],
        )
        self.assertEqual(
            repair_functions(["СЗ (ДЗ", "ТНЗНП"]),
            ["СЗ (ДЗ, ТНЗНП"],
        )

    def test_empty_and_duplicates(self) -> None:
        self.assertEqual(repair_functions(["", "ДЗТ", "ДЗТ", None]), ["ДЗТ"])


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report: list[str] = []
        self.catalog = load_catalog(sample_source(), report=self.report)

    def test_container_and_override(self) -> None:
        self.assertEqual(list(self.catalog.containers), ["cont-1"])
        self.assertEqual(self.catalog.deleted, {"cont-2"})

        container = self.catalog.containers["cont-1"]
        self.assertEqual(container.origin, ContainerOrigin.OVERRIDE.value)
        self.assertEqual(container.title, "Контейнер 1 (override)")
        self.assertEqual(container.description, "Описание контейнера")
        self.assertFalse(container.goose)
        self.assertEqual(container.standard.label, "СТО кратко")
        self.assertEqual(container.standard.key, "tat")
        self.assertEqual(container.standard_key, "tat")
        self.assertEqual(container.tags[0].code, "tag1")
        self.assertEqual(len(container.tags), 1)
        self.assertEqual(
            container.extensions["unknown_container_field"],
            {"a": 1, "b": 2},
        )
        self.assertEqual(
            [function.code for function in container.its_functions],
            ["ДЗТ", "СЗ ВН (ДЗ, ТНЗНП, БК)"],
        )

    def test_cabinets_and_kits(self) -> None:
        container = self.catalog.containers["cont-1"]
        self.assertEqual(len(container.cabinets), 3)
        self.assertEqual(
            [cabinet.key for cabinet in container.cabinets],
            ["cab1", "cab2", "cont-1:inline-cabinet:3"],
        )
        self.assertEqual([len(cabinet.kits) for cabinet in container.cabinets],
                         [2, 1, 1])

        first = container.cabinets[0]
        self.assertEqual(first.code, "CAB1")
        self.assertEqual(first.name, "Шкаф cab1")
        self.assertEqual(first.group, "Т/АТ")
        self.assertEqual(first.source, "user")
        self.assertEqual(first.kits[0].name, "Комплект 1")
        self.assertEqual(first.kits[1].name, "Комплект 2")
        self.assertEqual(first.kits[0].cabinet_id, "cab1")
        self.assertEqual(first.kits[0].ieds[0].kit_id, first.kits[0].id)

    def test_kit_fields(self) -> None:
        kit = self.catalog.containers["cont-1"].cabinets[0].kits[0]
        self.assertEqual(
            [function.code for function in kit.functions],
            ["СЗ ВН (ДЗ, ТНЗНП, БК)", "ДЗТ"],
        )
        self.assertTrue(kit.has_ied)
        self.assertEqual(kit.source, "user")
        self.assertEqual(kit.tags[0].code, "kit-tag")
        self.assertEqual(kit.extensions["mp_functions"], "основные функции")
        self.assertEqual(kit.extensions["notes"], "примечание комплекта")

        blocks = kit.test_blocks
        self.assertEqual(blocks.voltage.count, 2)
        self.assertEqual(blocks.voltage.circuits, ["Ua", "Ub"])
        self.assertEqual(blocks.current.count, 1)
        self.assertEqual(blocks.current.circuits, ["Ia"])
        self.assertEqual(len(blocks.blocks), 1)
        self.assertEqual(blocks.blocks[0].name, "SG1")
        self.assertEqual(blocks.blocks[0].count, "6+1")
        self.assertEqual(blocks.blocks[0].note, "примечание")
        self.assertEqual(len(kit.analog_inputs), 1)
        self.assertEqual(kit.analog_inputs[0].block, "SG1")
        self.assertEqual(kit.io_in[0].name, "Пуск")
        self.assertEqual(kit.io_in[0].code, "PTRC.Str")
        self.assertEqual(kit.io_out[0].name, "Отключить")

        second = self.catalog.containers["cont-1"].cabinets[0].kits[1]
        self.assertEqual([f.code for f in second.functions], ["ДЗТ"])
        self.assertFalse(second.has_ied)

    def test_counts(self) -> None:
        self.assertEqual(catalog_counts(self.catalog), {
            "containers": 1,
            "cabinets": 3,
            "kits": 4,
            "kits_with_ied": 1,
            "ieds": 1,
            "functions": 4,
            "standards": 1,
            "test_blocks": 3,
            "analog_inputs": 1,
            "signals": 2,
            "deleted": 1,
            "deleted_containers": 0,
            "builtin_cabinets": 0,
            "builtin_kets": 0,
        })

    def test_roundtrip(self) -> None:
        first = catalog_to_dict(self.catalog)
        second_catalog = load_catalog(first)
        second = catalog_to_dict(second_catalog)
        self.assertEqual(first, second)
        self.assertEqual(catalog_counts(second_catalog),
                         catalog_counts(self.catalog))

    def test_no_duplicate_ids_after_override(self) -> None:
        container = self.catalog.containers["cont-1"]
        cabinet_ids = [cabinet.id for cabinet in container.cabinets]
        kit_ids = [kit.id for cabinet in container.cabinets
                   for kit in cabinet.kits]
        self.assertEqual(len(cabinet_ids), len(set(cabinet_ids)))
        self.assertEqual(len(kit_ids), len(set(kit_ids)))
        self.assertNotIn(":dup", " ".join(cabinet_ids + kit_ids))


class DuplicateKeysTest(unittest.TestCase):
    def test_duplicate_container_key_is_renamed(self) -> None:
        report: list[str] = []
        source = {
            "custom": [
                {"key": "dup", "code": "first", "name": "first"},
                {"key": "dup", "code": "second", "name": "second"},
            ]
        }
        catalog = load_catalog(source, report=report)
        self.assertEqual(list(catalog.containers), ["dup", "dup:dup2"])
        self.assertTrue(report)

    def test_strict_mode_raises(self) -> None:
        source = {
            "custom": [
                {"key": "dup"},
                {"key": "dup"},
            ]
        }
        with self.assertRaises(MigrationError):
            load_catalog(source, strict=True)

    def test_duplicate_ied_ids_are_renamed_globally(self) -> None:
        source = {
            "custom": [{
                "key": "c",
                "komplets": [
                    _kit("К1", cabinet_key="cab1", ieds=[
                        {"id": "same", "name": "A", "type": "МП РЗА"}
                    ]),
                    _kit("К2", cabinet_key="cab2", ieds=[
                        {"id": "same", "name": "B", "type": "МП РЗА"}
                    ]),
                ],
            }]
        }
        report: list[str] = []
        catalog = load_catalog(source, report=report)
        ids = [ied.id for container in catalog.containers.values()
               for cabinet in container.cabinets
               for kit in cabinet.kits for ied in kit.ieds]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertIn("same", ids)
        self.assertTrue(any(":dup" in ied_id for ied_id in ids))
        self.assertTrue(report)
        validate_catalog(catalog)


class ValidationTest(unittest.TestCase):
    def test_valid_catalog_has_no_problems(self) -> None:
        catalog = load_catalog(sample_source())
        self.assertEqual(validate_catalog(catalog), [])

    def test_broken_backref_is_reported(self) -> None:
        catalog = load_catalog(sample_source())
        kit = catalog.containers["cont-1"].cabinets[0].kits[0]
        kit.cabinet_id = "missing"
        with self.assertRaises(CatalogValidationError):
            validate_catalog(catalog)
        problems = validate_catalog(catalog, raise_error=False)
        self.assertTrue(any("cabinet_id" in problem for problem in problems))

    def test_container_reference_list_is_preserved(self) -> None:
        source = {
            "custom": [{
                "key": "ket",
                "code": "КЭТ",
                "name": "Контейнер",
                "cabinets": ["a", "b"],
                "size": "40dc",
            }]
        }
        catalog = load_catalog(source)
        container = catalog.containers["ket"]
        self.assertEqual(container.cabinets, [])
        self.assertEqual(container.extensions["cabinet_keys"], ["a", "b"])
        self.assertEqual(container.extensions["size"], "40dc")


class SqliteTest(unittest.TestCase):
    def test_export_and_integrity(self) -> None:
        catalog = load_catalog(sample_source())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            export_sqlite(catalog, path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM containers"
                    ).fetchone()[0], 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM cabinets"
                    ).fetchone()[0], 3)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM kits"
                    ).fetchone()[0], 4)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM ieds"
                    ).fetchone()[0], 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM deleted"
                    ).fetchone()[0], 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT standard_key FROM containers"
                    ).fetchone()[0], "tat")
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM test_block_circuits"
                    ).fetchone()[0], 3)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM kit_signals"
                    ).fetchone()[0], 2)
                self.assertEqual(
                    connection.execute(
                        "SELECT count_value FROM test_blocks "
                        "WHERE kind = 'block' AND name = 'SG1'"
                    ).fetchone()[0], "6+1")
                self.assertEqual(
                    connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall(), [])
            finally:
                connection.close()

    def test_sqlite_is_atomic_and_repeatable(self) -> None:
        catalog = load_catalog(sample_source())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            export_sqlite(catalog, path)
            first_size = path.stat().st_size
            export_sqlite(catalog, path)
            self.assertEqual(path.stat().st_size, first_size)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


class NormalizedInputTest(unittest.TestCase):
    def test_single_container_root(self) -> None:
        source = {
            "key": "solo",
            "code": "S",
            "name": "Один",
            "komplets": [_kit("Комплект 1")],
        }
        catalog = load_catalog(source)
        self.assertEqual(list(catalog.containers), ["solo"])
        self.assertEqual(len(catalog.containers["solo"].cabinets), 1)

    def test_container_functions_fallback(self) -> None:
        catalog = load_catalog({
            "key": "c",
            "functions": ["ДЗТ", "РАС"],
        })
        functions = [
            function.code
            for function in catalog.containers["c"].its_functions
        ]
        self.assertEqual(functions, ["ДЗТ", "РАС"])

    def test_json_dump_is_utf8_and_readable(self) -> None:
        catalog = load_catalog(sample_source())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            from rza_catalog.export import dump_catalog
            dump_catalog(catalog, path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Контейнер 1", text)
            self.assertEqual(json.loads(text)["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
