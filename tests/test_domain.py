# -*- coding: utf-8 -*-
"""Классовый подход к хранению данных: доменная модель и отчёты.

Доменные классы (``Kit`` / ``Cabinet`` / ``Container``) и загрузчик
``DomainCatalog.load()`` сверяются с приложением: шкафы, комплекты и КЭТ
должны заполняться из базы так же, как их видят ``cabs`` / ``komplekts`` /
``containers``, а отчёт контейнера — совпадать с отчётом редактора.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from rza_catalog import store
from rza_catalog.domain import (
    Cabinet,
    Container,
    DomainCatalog,
    Ied,
    Kit,
    SignalEntry,
)


class DomainClassesTest(unittest.TestCase):
    def test_kit_with_ied_and_circuits(self) -> None:
        kit = Kit(id="typ:shet-x:0", name="Комплект 1", kind="typical")
        self.assertFalse(kit.has_ied)
        self.assertEqual(kit.app_key(), "typ:shet-x:0")

        kit.add_ied(Ied(id="i1", name="ИЭУ1", type="МП РЗА"))
        self.assertTrue(kit.has_ied)
        self.assertEqual(kit.ied_count(), 1)
        self.assertEqual(kit.ieds_text(), "ИЭУ1")

        kit.add_signal(SignalEntry(name="Отключить", code="CB1.Op"), "io_out")
        kit.add_signal(SignalEntry(name="Пуск"), "io_in")
        self.assertEqual(kit.signal_count("io_out"), 1)
        self.assertEqual(kit.signals_text("io_out"), "Отключить [CB1.Op]")
        with self.assertRaises(ValueError):
            kit.add_signal(SignalEntry(name="х"), "wrong")

    def test_kit_dict_roundtrip(self) -> None:
        kit = Kit(id="kit-1", name="Комплект 1", kind="typical",
                  functions=["СЗ (ДЗ, ТНЗНП, БК)", "РАС"], has_ied=True)
        kit.add_ied(Ied(id="kit-1:ied:0", name="ИЭУ1", type="МП РЗА",
                        description="защита"))
        kit.add_signal(SignalEntry(name="Пуск", code="PTRC.Str",
                                   details="цепь 1"), "io_in")
        restored = Kit.from_dict(kit.to_dict())
        self.assertEqual(restored.name, "Комплект 1")
        self.assertEqual(restored.functions, kit.functions)
        self.assertEqual(restored.ieds[0].name, "ИЭУ1")
        self.assertEqual(restored.io_in[0].details, "цепь 1")

    def test_kit_model_roundtrip(self) -> None:
        kit = DomainCatalog.load().kit("typ:shet-311-01-1:0")
        self.assertIsNotNone(kit)
        restored = Kit.from_model(kit.to_model())
        self.assertEqual(restored.to_dict(), kit.to_dict())

    def test_remove_ied_updates_flag(self) -> None:
        kit = Kit(id="k", name="К", has_ied=True)
        kit.add_ied(Ied(name="ИЭУ1"))
        self.assertTrue(kit.remove_ied("ИЭУ1"))
        self.assertFalse(kit.has_ied)
        self.assertFalse(kit.remove_ied("нет такого"))

    def test_cabinet_groups_kits(self) -> None:
        cabinet = Cabinet(id="shet-x", key="shet-x", code="ШЭТ X", name="X")
        cabinet.add_kit(Kit(name="К1"))
        cabinet.add_kit(Kit(name="К2"))
        self.assertEqual(cabinet.kit_count(), 2)
        self.assertEqual([k.cabinet_index for k in cabinet.kits], [0, 1])
        self.assertEqual(cabinet.kits[0].cabinet_id, "shet-x")

        cabinet.remove_kit("typ:shet-x:0")
        self.assertEqual(cabinet.kit_count(), 1)
        self.assertEqual(cabinet.kits[0].cabinet_index, 0)
        self.assertEqual(cabinet.kits[0].name, "К2")

    def test_cabinet_kind_follows_kits(self) -> None:
        cabinet = Cabinet(key="c1", standard_key="lep")
        self.assertTrue(cabinet.is_typical())  # пустой со стандартом — типовой
        cabinet.add_kit(Kit(name="К1", kind="typical"))
        self.assertTrue(cabinet.is_typical())
        cabinet.add_kit(Kit(name="К2", kind="custom"))
        self.assertFalse(cabinet.is_typical())
        self.assertEqual(cabinet.kind_title(), "Нетиповой")

    def test_container_holds_cabinets(self) -> None:
        container = Container(key="k", code="КЭТ", name="Контейнер")
        cabinet = Cabinet(key="cab", code="C", name="Шкаф")
        container.add_cabinet(cabinet)
        self.assertEqual(len(container.cabinets), 1)
        self.assertEqual(container.cabinet_keys, ["cab"])
        self.assertTrue(container.remove_cabinet("cab"))
        self.assertEqual(container.cabinets, [])

    def test_container_resolves_cabinets_and_finds_missing(self) -> None:
        registry = {"shet-311-01-1": Cabinet(key="shet-311-01-1")}
        container = Container(key="k",
                              cabinet_keys=["shet-311-01-1", "нет-такого"])
        container.resolve_cabinets(registry)
        self.assertEqual(len(container.cabinets), 1)
        self.assertEqual(container.missing_cabinet_keys, ["нет-такого"])

    def test_override_replaces_typical_kit_fields(self) -> None:
        kit = Kit(id="k", name="Было", functions=["ДЗТ"],
                  io_in=[SignalEntry(name="старый")])
        kit.apply_override({
            "name": "Стало",
            "functions": ["ДЗТ", "МТЗ"],
            "io_in": [{"name": "Пуск", "code": "PDS.Str", "details": "д"}],
            "mp_functions": "ДЗТ — основная",
        })
        self.assertEqual(kit.name, "Стало")
        self.assertEqual(kit.functions, ["ДЗТ", "МТЗ"])
        self.assertEqual(kit.signals_text("io_in"), "Пуск [PDS.Str] — д")
        self.assertEqual(kit.details["mp_functions"], "ДЗТ — основная")


class DomainCatalogFillTest(unittest.TestCase):
    """Заполнение комплектов и шкафов из существующей базы."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = DomainCatalog.load()

    def test_matches_app_catalog_sizes(self) -> None:
        import cabs
        import containers
        import komplekts

        stats = self.catalog.stats()
        self.assertEqual(stats["cabinets"], len(cabs.all_cabinets()))
        self.assertEqual(stats["containers"], len(containers.all_containers()))
        self.assertEqual(stats["kits"], len(komplekts.all_komplekts()))

    def test_kit_keys_match_app(self) -> None:
        import komplekts

        app_keys = {kit["key"] for kit in komplekts.all_komplekts()}
        self.assertEqual(set(self.catalog.kits), app_keys)

    def test_cabinet_keys_match_app(self) -> None:
        import cabs

        app_keys = {cabinet["key"] for cabinet in cabs.all_cabinets()}
        self.assertEqual(set(self.catalog.cabinets), app_keys)

    def test_cabinet_kits_come_from_library(self) -> None:
        for cabinet in self.catalog.cabinets.values():
            for kit in cabinet.kits:
                self.assertIs(self.catalog.kits.get(kit.app_key()), kit)
                self.assertEqual(kit.cabinet_id, cabinet.key)

    def test_kets_resolve_cabinets_from_library(self) -> None:
        import containers

        for container in self.catalog.containers.values():
            app = containers.find_container(container.key)
            app_keys = [key for key in (app.get("cabinets") or []) if key]
            self.assertEqual(container.cabinet_keys, app_keys)
            self.assertEqual(
                len(container.cabinets) + len(container.missing_cabinet_keys),
                len(app_keys))
            for cabinet in container.cabinets:
                self.assertIs(self.catalog.cabinets.get(cabinet.key), cabinet)

    def test_typical_kit_has_ieds(self) -> None:
        kit = self.catalog.kit("typ:shet-311-01-1:0")
        self.assertIsNotNone(kit)
        self.assertEqual(kit.kind, "typical")
        self.assertTrue(kit.has_ied)
        self.assertTrue(kit.ieds)

    def test_signals_filled_from_signals_file(self) -> None:
        stats = self.catalog.stats()
        self.assertGreater(stats["kits_with_io_in"], 0)
        self.assertGreater(stats["kits_with_io_out"], 0)
        self.assertGreater(stats["kits_with_analog"], 0)
        self.assertGreater(stats["kits_with_test_blocks"], 0)
        with_signals = next(kit for kit in self.catalog.kits.values()
                            if kit.io_in)
        self.assertTrue(with_signals.io_in[0].name)

    def test_kit_test_blocks_text_includes_note(self) -> None:
        kit = self.catalog.kit("typ:shet-211-01-1:0")
        self.assertIsNotNone(kit)
        if kit.has_test_blocks():
            text = kit.test_blocks_text()
            self.assertTrue(text)

    def test_dump_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.catalog.save(Path(directory) / "domain.json")
            restored = DomainCatalog.from_dump(path)
            first, second = self.catalog.stats(), restored.stats()
            for key in first:
                self.assertEqual(first[key], second[key], key)
            ket = restored.container("ket-6-1-ii")
            self.assertIsNotNone(ket)
            self.assertTrue(all(cabinet.key in restored.cabinets
                                for cabinet in ket.cabinets))
            # после загрузки контейнер ссылается на объекты библиотеки шкафов
            for cabinet in ket.cabinets:
                self.assertIs(restored.cabinets[cabinet.key], cabinet)


class DomainOverrideIntegrationTest(unittest.TestCase):
    """Каталог комплектов (custom/overrides) накладывается на базу."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "catalog.normalized.json"
        shutil.copy(store.CANONICAL_STORE_PATH, self.path)
        store._cache.clear()

    def tearDown(self) -> None:
        self._directory.cleanup()
        store._cache.clear()

    def test_overrides_and_custom(self) -> None:
        target_key = "typ:shet-311-01-1:0"

        def mutate(catalog):
            data = store.kit_catalog_data(catalog)
            data["overrides"][target_key] = {
                "name": "Комплект с правкой",
                "io_in": [{"name": "Тест", "code": "X.Y", "details": ""}],
            }
            data["custom"].append({
                "key": "domain-custom-kit",
                "kind": "other",
                "name": "Запасной комплект",
                "functions": ["МТЗ"],
                "has_ied": True,
                "ieds": [{"name": "ИЭУ99", "type": "МП РЗА", "desc": ""}],
            })
            store.write_kit_catalog(catalog, data)

        store.update_store(mutate, self.path)

        catalog = DomainCatalog.load(self.path, signals_path=Path("нет-файла"))
        kit = catalog.kit(target_key)
        self.assertEqual(kit.name, "Комплект с правкой")
        self.assertEqual(kit.signals_text("io_in"), "Тест [X.Y]")
        # шкаф видит тот же объект комплекта
        self.assertIs(catalog.cabinet("shet-311-01-1").kits[0], kit)

        custom = catalog.kit("domain-custom-kit")
        self.assertIsNotNone(custom)
        self.assertEqual(custom.kind, "other")
        self.assertTrue(custom.has_ied)
        self.assertEqual(catalog.stats()["kits"], 340)


class ContainerReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = DomainCatalog.load()

    def test_report_structure(self) -> None:
        container = self.catalog.container("ket-6-1-ii")
        self.assertIsNotNone(container)
        self.assertGreater(len(container.cabinets), 1)

        report = container.report_data()
        titles = [section["title"] for section in report["sections"]]
        self.assertEqual(titles, [
            "1. Общие сведения о контейнере",
            "2. Шкафы в контейнере",
            "3. Комплекты шкафов",
        ])

        cabinet_rows = report["sections"][1]["rows"]
        self.assertEqual(len(cabinet_rows), len(container.cabinets))
        self.assertEqual(cabinet_rows[0][0], "1")

        blocks = report["sections"][2]["blocks"]
        self.assertEqual(len(blocks), container.kit_count())
        row_labels = {row[0] for row in blocks[0]["rows"]}
        self.assertTrue({"Вид", "Тип", "Есть ИЭУ", "ИЭУ", "Функции"}
                        <= row_labels)

    def test_report_matches_app_report(self) -> None:
        """Тот же отчёт, что собирает редактор по словарям каталога."""
        import containers
        import main as app_main

        owner = next(
            getattr(app_main, name) for name in dir(app_main)
            if isinstance(getattr(app_main, name), type)
            and hasattr(getattr(app_main, name), "_catalog_container_report"))
        builder = owner._catalog_container_report

        container = self.catalog.container("ket-6-3-ii")
        old = builder(object.__new__(owner),
                      containers.find_container(container.key))
        new = container.report_data()

        self.assertEqual(old["title"], new["title"])
        general_old = {row[0]: row[1] for row in old["sections"][0]["rows"]}
        general_new = {row[0]: row[1] for row in new["sections"][0]["rows"]}
        for label, value in general_old.items():
            self.assertEqual(general_new.get(label), value, label)
        self.assertEqual(old["sections"][1]["rows"],
                         new["sections"][1]["rows"])
        self.assertEqual(len(old["sections"][2].get("blocks", [])),
                         len(new["sections"][2].get("blocks", [])))
        for block_old, block_new in zip(old["sections"][2]["blocks"],
                                        new["sections"][2]["blocks"]):
            rows_new = [row for row in block_new["rows"] if row[0] != "Тип"]
            self.assertEqual(block_old["rows"], rows_new, block_old["head"])

    def test_write_docx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.catalog.container("ket-6-1-ii").write_report(
                Path(directory) / "ket.docx")
            self.assertEqual(path.suffix, ".docx")
            with zipfile.ZipFile(path) as archive:
                self.assertIn("word/document.xml", archive.namelist())
                xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("КЭТ 6-1-II", xml)

    def test_report_to_text(self) -> None:
        from rza_catalog.domain import report_to_text

        container = self.catalog.container("ket-6-1-ii")
        text = report_to_text(container.report_data())
        self.assertIn("Шкафы в контейнере", text)
        self.assertIn("Комплектов всего", text)


if __name__ == "__main__":
    unittest.main()
