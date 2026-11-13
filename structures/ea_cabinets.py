"""Первый рабочий плагин структуры: UML-шкафы EA.

Плагин только описывает источник данных и делегирует интерфейс уже
проверенному изолированному окну ``ea_uml_test.py``. Последующие структуры
могут предоставлять собственные реализации ``create_workspace``.
"""

from structure_core.base import StructurePlugin


class EaCabinetsPlugin(StructurePlugin):
    """Шкафы, комплекты и ИЭУ из ``EA/cabinets_uml.json``."""

    def __init__(self, config, root):
        super().__init__(config, root)
        self.supports_assembly = True
        self.available = self.schema_exists and self.data_exists
        if not self.available:
            self.status = "Нет UML-схемы или выгрузки данных"
            return
        try:
            import ea_uml_test

            catalog = ea_uml_test.load_uml_catalog(self.data_path)
            kits = ea_uml_test.collect_kits(catalog["cabinets"], "uml")
            self.status = "Готов: шкафов %d, комплектов %d" % (
                len(catalog["cabinets"]), len(kits))
        except Exception as error:
            self.available = False
            self.error = str(error)
            self.status = "Ошибка чтения UML-выгрузки"

    def summary(self):
        text = super().summary()
        return text + (
            "\n\nРабочее окно: отдельный холст UML-шкафов, вынос объектов "
            "на чертёж, сборка новых шкафов из существующих комплектов и "
            "сохранение тестового состояния в отдельный JSON.")

    def create_workspace(self, parent, engine, registry):
        import ea_uml_test

        return ea_uml_test.show_test_window(parent, self.data_path)

    def create_assembly(self, parent, engine, registry):
        import ea_uml_test

        return ea_uml_test.show_assembly_window(parent, self.data_path)


def create_plugin(config, root):
    return EaCabinetsPlugin(config, root)
