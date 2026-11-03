# -*- coding: utf-8 -*-
"""Сценарий «комплект → шкаф → контейнер» и сигналы комплектов."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import cabs
import komplekts
from rza_catalog import store


class KitSignalsTest(unittest.TestCase):
    def test_signals_are_normalized_and_kept(self) -> None:
        kit = komplekts.normalize_komplekt({
            "name": "Комплект 1",
            "kind": "typical",
            "io_in": [
                {"name": "Пуск", "code": "PTRC.Str", "details": "цепь 1"},
                "Разрешение",
            ],
            "io_out": [{"name": "Отключить", "code": "PTRC.Op"}],
        })
        self.assertEqual(len(kit["io_in"]), 2)
        self.assertEqual(kit["io_in"][0]["code"], "PTRC.Str")
        self.assertEqual(kit["io_in"][1]["name"], "Разрешение")
        self.assertEqual(len(kit["io_out"]), 1)
        self.assertTrue(komplekts.has_signals(kit))
        self.assertIn("Входные сигналы: 2", komplekts.signals_brief(kit))

    def test_signals_survive_for_cabinet_kit(self) -> None:
        cabinet = cabs.normalize_cabinet({
            "key": "cab",
            "standard_key": "tat",
            "komplets": [{
                "name": "Комплект 1",
                "kind": "typical",
                "io_in": ["Сигнал 1"],
                "io_out": ["Сигнал 2"],
            }],
        })
        kit = komplekts.kit_from_cabinet(cabinet, 0)
        self.assertEqual(kit["io_in"][0]["name"], "Сигнал 1")
        self.assertEqual(kit["io_out"][0]["name"], "Сигнал 2")


class CabinetKindTest(unittest.TestCase):
    def test_all_typical_kits_make_typical_cabinet(self) -> None:
        cabinet = cabs.normalize_cabinet({
            "key": "cab",
            "komplets": [
                {"name": "К1", "kind": "typical"},
                {"name": "К2", "kind": "typical"},
            ],
        })
        self.assertEqual(cabinet["kind"], "typical")
        self.assertEqual(cabs.cabinet_kind_title(cabinet), "Типовой")

    def test_one_custom_kit_makes_custom_cabinet(self) -> None:
        cabinet = cabs.normalize_cabinet({
            "key": "cab",
            "komplets": [
                {"name": "К1", "kind": "typical"},
                {"name": "К2", "kind": "custom"},
            ],
        })
        self.assertEqual(cabinet["kind"], "custom")
        self.assertEqual(cabs.cabinet_kind_title(cabinet), "Нетиповой")
        # Вид самого комплекта не должен «размазываться» по шкафу.
        self.assertEqual(komplekts.kit_from_cabinet(cabinet, 0)["kind"],
                         "typical")
        self.assertEqual(komplekts.kit_from_cabinet(cabinet, 1)["kind"],
                         "custom")


class KitOverrideSignalsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "catalog.normalized.json"
        self._old_path = store.DEFAULT_STORE_PATH
        store.DEFAULT_STORE_PATH = self.path
        store._cache.clear()
        store.ensure_store()

    def tearDown(self) -> None:
        store.DEFAULT_STORE_PATH = self._old_path
        store._cache.clear()
        self._directory.cleanup()

    def test_standalone_typical_kit_makes_typical_cabinet(self) -> None:
        key = komplekts.save_komplekt({
            "name": "Типовой комплект из СТО",
            "kind": "typical",
            "type": "МП РЗА",
            "functions": ["ДЗТ"],
            "io_in": [{"name": "Пуск", "code": "PTRC.Str",
                       "details": ""}],
            "io_out": [{"name": "Отключить", "code": "PTRC.Op",
                        "details": ""}],
        })
        kit = komplekts.find_komplekt(key)
        self.assertEqual(kit["kind"], "typical")
        self.assertEqual(kit["cabinet_key"], "")
        cabinet = cabs.normalize_cabinet({
            "key": "made-from-kits",
            "code": "TEST",
            "name": "Шкаф из комплектов",
            "komplets": [copy.deepcopy(kit)],
        })
        self.assertEqual(cabinet["kind"], "typical")
        self.assertEqual(len(cabinet["komplets"]), 1)
        self.assertEqual(cabinet["komplets"][0]["kind"], "typical")

    def test_typical_kit_override_keeps_signals(self) -> None:
        kit = next(item for item in komplekts.all_komplekts()
                   if item.get("source") == "cabinet")
        edited = copy.deepcopy(kit)
        edited["io_in"] = [{"name": "Новый вход", "code": "XCBR.Pos",
                            "details": ""}]
        key = komplekts.save_komplekt(edited, kit["key"])
        saved = komplekts.find_komplekt(key)
        self.assertEqual(saved["io_in"][0]["name"], "Новый вход")
        data = store.kit_catalog_data(store.read_store())
        self.assertIn(key, data["overrides"])
        self.assertTrue(data["overrides"][key]["io_in"])


if __name__ == "__main__":
    unittest.main()
