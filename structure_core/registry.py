"""Реестр UML-структур на основе ``structures/manifest.json``.

Новая схема подключается добавлением записи в манифест и модуля с фабрикой
``create_plugin(config, root)``. Реестр не знает ничего о конкретных шкафах,
СТО или контейнерах.
"""

import importlib
import json
import os

from .base import PlaceholderPlugin, StructurePlugin, UnavailablePlugin


class StructureRegistry:
    """Загружает, проверяет и перечитывает список плагинов структур."""

    def __init__(self, root, manifest_path=None):
        self.root = os.path.abspath(root)
        if manifest_path is None:
            manifest_path = os.path.join(
                self.root, "structures", "manifest.json")
        self.manifest_path = os.path.abspath(manifest_path)
        self.version = 0
        self.default_id = ""
        self.plugins = []
        self.errors = []
        self.reload()

    def reload(self):
        """Перечитывает манифест, сохраняя прежнее состояние при ошибке.

        Разбор выполняется в локальные списки: если ``manifest.json`` испорчен
        или имеет неверную форму, уже работающие плагины и их окна не теряются.
        Ошибка отдельного модуля не считается ошибкой манифеста — для него
        создаётся ``UnavailablePlugin``.
        """
        with open(self.manifest_path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("манифест структур должен быть JSON-объектом")

        entries = data.get("plugins", [])
        if not isinstance(entries, list):
            raise ValueError("в манифесте структур нет списка plugins")
        version = int(data.get("version", 0) or 0)
        default_id = str(data.get("default_plugin") or "")

        plugins = []
        errors = []
        for raw in entries:
            config = dict(raw or {})
            plugin_id = str(config.get("id") or "?")
            if not config.get("enabled", True):
                plugin = PlaceholderPlugin(config, self.root)
                plugin.status = str(config.get("status") or "Отключён")
                plugins.append(plugin)
                continue

            try:
                module_name = str(config.get("module") or "")
                if not module_name:
                    raise ValueError("не указан module плагина")
                module = importlib.import_module(module_name)
                factory_name = str(config.get("factory") or "create_plugin")
                factory = getattr(module, factory_name)
                plugin = factory(config, self.root)
                if not isinstance(plugin, StructurePlugin):
                    raise TypeError(
                        "фабрика вернула не StructurePlugin: %s" %
                        type(plugin).__name__)
                plugins.append(plugin)
            except Exception as error:
                errors.append("%s: %s" % (plugin_id, error))
                plugins.append(
                    UnavailablePlugin(config, self.root, str(error)))

        # Подменяем состояние только после успешного разбора всего манифеста.
        self.version = version
        self.default_id = default_id
        self.plugins = plugins
        self.errors = errors
        return self.plugins

    def get(self, plugin_id):
        for plugin in self.plugins:
            if plugin.id == plugin_id:
                return plugin
        return None

    @property
    def available_plugins(self):
        return [plugin for plugin in self.plugins if plugin.available]

    def rows(self):
        return [
            {
                "id": plugin.id,
                "title": plugin.title,
                "status": plugin.status,
                "available": plugin.available,
                "assembly": plugin.supports_assembly,
                "schema": plugin.relative(plugin.schema_path),
                "data": plugin.relative(plugin.data_path),
            }
            for plugin in self.plugins
        ]
