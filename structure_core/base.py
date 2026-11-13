"""Базовые типы плагинов структур.

Плагин описывает одну UML-схему и соответствующие данные. Он сам решает,
как загрузить структуру и какое рабочее окно показать; графический движок
передаётся только как хост для создания окон.
"""

import os
from tkinter import messagebox


class StructurePlugin:
    """Контракт одной расширяемой структуры."""

    def __init__(self, config, root):
        self.config = dict(config or {})
        self.root = os.path.abspath(root)
        self.id = str(self.config.get("id") or "")
        self.title = str(self.config.get("title") or self.id or "Структура")
        self.description = str(self.config.get("description") or "")
        self.module = str(self.config.get("module") or "")
        self.settings = dict(self.config.get("settings") or {})
        self.enabled = bool(self.config.get("enabled", True))
        self.available = False
        self.status = str(self.config.get("status") or "")
        self.supports_assembly = False
        self.error = ""
        self.schema_path = self._absolute(self.config.get("schema"))
        self.data_path = self._absolute(self.config.get("data"))

    def _absolute(self, value):
        if not value:
            return ""
        path = str(value)
        if not os.path.isabs(path):
            path = os.path.join(self.root, path)
        return os.path.abspath(path)

    @property
    def schema_exists(self):
        return bool(self.schema_path) and os.path.isfile(self.schema_path)

    @property
    def data_exists(self):
        return bool(self.data_path) and os.path.isfile(self.data_path)

    def relative(self, path):
        if not path:
            return "—"
        try:
            return os.path.relpath(path, self.root).replace(os.sep, "/")
        except ValueError:
            return path

    def summary(self):
        lines = [
            "ID: %s" % (self.id or "—"),
            "Название: %s" % self.title,
            "Описание: %s" % (self.description or "—"),
            "Статус: %s" % (self.status or "—"),
            "Доступна: %s" % ("да" if self.available else "нет"),
            "Сборка объектов: %s" % (
                "да" if self.supports_assembly else "нет"),
            "UML-схема: %s (%s)" % (
                self.relative(self.schema_path),
                "есть" if self.schema_exists else "нет"),
            "Данные: %s (%s)" % (
                self.relative(self.data_path),
                "есть" if self.data_exists else "нет"),
            "Модуль: %s" % (self.module or "—"),
        ]
        if self.error:
            lines.append("Ошибка: %s" % self.error)
        return "\n".join(lines)

    def create_workspace(self, parent, engine, registry):
        raise NotImplementedError(
            "плагин %s не реализовал рабочее окно структуры" % self.id)

    def create_assembly(self, parent, engine, registry):
        raise NotImplementedError(
            "плагин %s не реализовал сборку объектов" % self.id)


class PlaceholderPlugin(StructurePlugin):
    """Точка расширения для UML-схемы, которая появится позже."""

    def __init__(self, config, root):
        super().__init__(config, root)
        self.available = False
        self.status = str(self.config.get("status") or "Ожидает UML-схему")
        self.supports_assembly = False

    def note(self):
        return (
            "Структура «%s» зарегистрирована как точка расширения.\n\n"
            "Когда появятся UML-схема и выгрузка данных, добавьте модуль "
            "загрузки в structures/manifest.json и включите плагин.\n\n"
            "UML-схема: %s\nДанные: %s" % (
                self.title,
                self.relative(self.schema_path),
                self.relative(self.data_path)))

    def create_workspace(self, parent, engine, registry):
        messagebox.showinfo(self.title, self.note(), parent=parent)
        return None

    def create_assembly(self, parent, engine, registry):
        messagebox.showinfo(self.title, self.note(), parent=parent)
        return None


class UnavailablePlugin(PlaceholderPlugin):
    """Плагин, модуль которого зарегистрирован, но не загрузился."""

    def __init__(self, config, root, error):
        super().__init__(config, root)
        self.error = str(error)
        self.status = "Ошибка загрузки плагина"

    def note(self):
        return ("Не удалось загрузить плагин «%s».\n\n%s" % (
            self.title, self.error))
