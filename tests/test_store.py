# -*- coding: utf-8 -*-
"""Интеграция нормализованного хранилища с каталогами приложения."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from rza_catalog import store


class BuiltinStoreTest(unittest.TestCase):
    def test_root_store_contains_builtin_cabinets_and_kets(self) -> None:
        catalog = store.read_store()
        self.assertEqual(len(store.builtin_cabinet_entries(catalog)), 282)
        self.assertEqual(len(store.builtin_ket_entries(catalog)), 16)
        self.assertEqual(len(catalog.deleted), 6)

    def test_builtin_cabinet_is_converted_to_app_dict(self) -> None:
        catalog = store.read_store()
        container = store.builtin_cabinet_entries(catalog)[0]
        definition = store.container_to_cabinet_dict(container)
        self.assertEqual(definition["key"], container.key)
        self.assertIn("komplets", definition)
        self.assertIn("kind", definition)

    def test_full_store_roundtrip_keeps_builtins(self) -> None:
        first = store.read_store()
        second = store.load_catalog(store.catalog_to_dict(first))
        self.assertEqual(len(second.builtin_cabinets),
                         len(first.builtin_cabinets))
        self.assertEqual(len(second.builtin_kets), len(first.builtin_kets))
        self.assertEqual(
            [container.key for container in second.builtin_cabinets.values()],
            [container.key for container in first.builtin_cabinets.values()],
        )


class StoreIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "catalog.normalized.json"
        self._old_path = store.DEFAULT_STORE_PATH
        store.DEFAULT_STORE_PATH = self.path
        store._cache.clear()

    def tearDown(self) -> None:
        store.DEFAULT_STORE_PATH = self._old_path
        store._cache.clear()
        self._directory.cleanup()

    def test_bootstrap_has_both_entry_types(self) -> None:
        catalog = store.ensure_store()
        self.assertEqual(len(store.cabinet_entries(catalog)), 33)
        self.assertEqual(len(store.ket_entries(catalog)), 1)
        self.assertEqual(len(catalog.deleted), 6)
        self.assertTrue(self.path.exists())

    def test_catalog_adapters_keep_counts(self) -> None:
        import cabs
        import containers
        import komplekts

        self.assertEqual(len(cabs.all_cabinets()), 308)
        self.assertEqual(len(containers.all_containers()), 17)
        self.assertEqual(len(komplekts.all_komplekts()), 339)
        self.assertTrue(any(not cabs.is_builtin(cabinet["key"])
                            for cabinet in cabs.all_cabinets()))
        self.assertTrue(any(not containers.is_builtin(container["key"])
                            for container in containers.all_containers()))

    def test_cabinet_and_ket_edits_are_isolated(self) -> None:
        import cabs
        import containers

        store.ensure_store()
        builtin_key = "shet-311-01-1"
        original_name = cabs.find_cabinet(builtin_key)["name"]

        definition = {
            "key": "",
            "code": "TEST.01-1",
            "name": "Тестовый шкаф",
            "description": "Тест",
            "standard_key": "",
            "group": "Прочие",
            "komplets": [{
                "name": "Комплект 1",
                "type": "МП РЗА",
                "functions": ["ДЗТ"],
                "desc": "тест",
                "ieds": [{"name": "ИЭУ1", "type": "МП РЗА",
                          "desc": "тест"}],
            }],
        }
        cabinet_key = cabs.save_cabinet(definition)

        ket_key = containers.save_container({
            "key": "",
            "code": "КЭТ ТЕСТ",
            "name": "Тестовый КЭТ",
            "group": "Прочие",
            "size": "20dc",
            "slots": 7,
            "cabinets": [builtin_key],
            "composition": ["тест"],
            "functions": ["ДЗТ"],
        })

        self.assertTrue(cabs.find_cabinet(cabinet_key))
        self.assertTrue(containers.find_container(ket_key))

        # Правка встроенного шкафа — это override, а не новый шкаф.
        base = copy.deepcopy(cabs.find_cabinet(builtin_key))
        base["name"] = "Переопределённый шкаф"
        cabs.save_cabinet(base, builtin_key)
        self.assertEqual(cabs.find_cabinet(builtin_key)["name"],
                         "Переопределённый шкаф")

        catalog = store.read_store()
        self.assertEqual(catalog.containers[builtin_key].origin, "override")
        self.assertEqual(len(store.cabinet_entries(catalog)), 35)
        self.assertEqual(len(store.ket_entries(catalog)), 2)

        # Сброс каталога шкафов не должен удалять пользовательский КЭТ.
        cabs.reset_user_catalog()
        self.assertTrue(containers.find_container(ket_key))
        self.assertEqual(cabs.find_cabinet(builtin_key)["name"], original_name)

        # И наоборот: сброс КЭТ не удаляет пользовательский шкаф.
        cabinet_key = cabs.save_cabinet(definition)
        containers.reset_user_catalog()
        self.assertTrue(cabs.find_cabinet(cabinet_key))
        self.assertFalse(containers.find_container(ket_key))

    def test_user_kit_catalog_is_stored_normalized(self) -> None:
        import komplekts

        store.ensure_store()
        key = komplekts.save_komplekt({
            "name": "Пользовательский комплект",
            "kind": "custom",
            "type": "МП РЗА",
            "functions": ["ДЗТ"],
            "desc": "тест",
            "ieds": [{"name": "ИЭУ1", "type": "МП РЗА",
                      "desc": "тест"}],
            "test_blocks": {
                "voltage": {"count": 1, "circuits": ["Ua"]},
                "current": {"count": 0, "circuits": []},
            },
        })
        self.assertTrue(komplekts.find_komplekt(key))
        catalog = store.read_store()
        self.assertIn(store.KIT_CATALOG_KEY, catalog.containers)
        self.assertFalse(Path(komplekts.USER_CATALOG_PATH).exists())
        self.assertEqual(len(komplekts.all_komplekts()), 340)

        komplekts.reset_user_catalog()
        self.assertFalse(komplekts.find_komplekt(key))
        self.assertNotIn(store.KIT_CATALOG_KEY,
                         store.read_store().containers)
        self.assertEqual(len(komplekts.all_komplekts()), 339)

    def test_typical_kit_override_is_stored_normalized(self) -> None:
        import komplekts

        store.ensure_store()
        kit = next(item for item in komplekts.all_komplekts()
                   if item.get("source") == "cabinet")
        edited = copy.deepcopy(kit)
        edited["name"] = "Изменённый комплект"
        key = komplekts.save_komplekt(edited, kit["key"])
        self.assertEqual(komplekts.find_komplekt(key)["name"],
                         "Изменённый комплект")
        data = store.kit_catalog_data(store.read_store())
        self.assertIn(key, data["overrides"])
        self.assertFalse(Path(komplekts.USER_CATALOG_PATH).exists())
        komplekts.reset_user_catalog()
        self.assertNotEqual(komplekts.find_komplekt(key)["name"],
                            "Изменённый комплект")

    def test_store_survives_roundtrip(self) -> None:
        first = store.ensure_store()
        second = store.read_store()
        self.assertEqual(
            [container.key for container in first.containers.values()],
            [container.key for container in second.containers.values()],
        )
        self.assertEqual(first.deleted_containers,
                         second.deleted_containers)
        self.assertEqual(len(first.functions), len(second.functions))


if __name__ == "__main__":
    unittest.main()
