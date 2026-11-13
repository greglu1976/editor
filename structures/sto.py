"""Точка расширения для будущей UML-схемы стандартов СТО."""

from structure_core.base import PlaceholderPlugin


class StoStructurePlugin(PlaceholderPlugin):
    """Зарегистрированная, но ещё не подключённая структура СТО."""

    def __init__(self, config, root):
        super().__init__(config, root)
        self.status = "Ожидает UML-схему СТО"
        if self.schema_exists and self.data_exists:
            self.status = "Файлы найдены: требуется загрузчик структуры"

    def note(self):
        return (
            "Плагин «СТО» уже участвует в реестре структур.\n\n"
            "После появления UML-схемы и JSON-выгрузки замените этот класс "
            "реализацией StructurePlugin с методом create_workspace().\n\n"
            "UML-схема: %s\nДанные: %s" % (
                self.relative(self.schema_path),
                self.relative(self.data_path)))


def create_plugin(config, root):
    return StoStructurePlugin(config, root)
