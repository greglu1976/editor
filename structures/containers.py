"""Точка расширения для будущей UML-схемы контейнеров."""

from structure_core.base import PlaceholderPlugin


class ContainersStructurePlugin(PlaceholderPlugin):
    """Зарегистрированная, но ещё не подключённая структура контейнеров."""

    def __init__(self, config, root):
        super().__init__(config, root)
        self.status = "Ожидает UML-схему контейнеров"
        if self.schema_exists and self.data_exists:
            self.status = "Файлы найдены: требуется загрузчик структуры"

    def note(self):
        return (
            "Плагин «Контейнеры» уже участвует в реестре структур.\n\n"
            "После появления UML-схемы и JSON-выгрузки замените этот класс "
            "реализацией StructurePlugin с методом create_workspace().\n\n"
            "UML-схема: %s\nДанные: %s" % (
                self.relative(self.schema_path),
                self.relative(self.data_path)))


def create_plugin(config, root):
    return ContainersStructurePlugin(config, root)
