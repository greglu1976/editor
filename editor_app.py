"""Новая точка входа расширяемого редактора.

Запуск:

    python editor_app.py            # графический режим
    python editor_app.py --selftest # проверка без удержания mainloop

Архитектура:

* ``main.py`` — неизменённый, полностью рабочий графический движок;
* ``editor_engine.py`` — тонкий адаптер движка;
* ``structure_core`` — реестр, контракт плагинов и визуальный менеджер;
* ``structures`` — конкретные UML-структуры и точки расширения.

Старый запуск ``python main.py`` продолжает работать независимо.
"""

import argparse
import json
import os
import sys
import tempfile
import tkinter as tk
from tkinter import messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ui_theme
from editor_engine import EditorEngine
from structure_core.manager import StructureManagerWindow
from structure_core.registry import StructureRegistry

MANIFEST_PATH = os.path.join(ROOT, "structures", "manifest.json")
_MANAGER_WINDOWS = {}


def _release_manager(key, manager):
    if _MANAGER_WINDOWS.get(key) is manager:
        _MANAGER_WINDOWS.pop(key, None)


def open_manager(engine, registry):
    """Открывает единственный на корневое окно менеджер структур."""
    key = id(engine.root)
    manager = _MANAGER_WINDOWS.get(key)
    if manager is not None:
        try:
            if manager.window.winfo_exists():
                manager.bring_to_front()
                return manager
        except tk.TclError:
            pass
    manager = StructureManagerWindow(
        engine.root, engine, registry,
        on_close=lambda window: _release_manager(key, window))
    _MANAGER_WINDOWS[key] = manager
    return manager


def open_plugin(engine, registry, plugin_id):
    plugin = registry.get(plugin_id)
    if plugin is None:
        messagebox.showerror(
            "Реестр структур", "Плагин не найден: %s" % plugin_id,
            parent=engine.root)
        return None
    if not plugin.available:
        messagebox.showinfo(
            plugin.title,
            "Структура пока недоступна.\n\n%s" % plugin.status,
            parent=engine.root)
        return None
    try:
        return plugin.create_workspace(engine.root, engine, registry)
    except Exception as error:
        messagebox.showerror(
            plugin.title, "Не удалось открыть структуру:\n%s" % error,
            parent=engine.root)
        return None


def assemble_plugin(engine, registry, plugin_id):
    plugin = registry.get(plugin_id)
    if plugin is None or not plugin.available:
        return open_plugin(engine, registry, plugin_id)
    if not plugin.supports_assembly:
        messagebox.showinfo(
            plugin.title,
            "Для этой структуры сборка объектов пока не поддерживается.",
            parent=engine.root)
        return None
    try:
        return plugin.create_assembly(engine.root, engine, registry)
    except Exception as error:
        messagebox.showerror(
            plugin.title, "Не удалось открыть сборку:\n%s" % error,
            parent=engine.root)
        return None


def reload_registry(engine, registry):
    try:
        registry.reload()
    except Exception as error:
        messagebox.showerror(
            "Реестр структур",
            "Не удалось перечитать manifest.json:\n%s" % error,
            parent=engine.root)
        return
    manager = _MANAGER_WINDOWS.get(id(engine.root))
    if manager is not None:
        try:
            if manager.window.winfo_exists():
                manager.refresh()
        except tk.TclError:
            pass
    messagebox.showinfo(
        "Реестр структур",
        "Реестр обновлён. Зарегистрировано плагинов: %d" %
        len(registry.plugins),
        parent=engine.root)


def build_structure_ribbon(engine, registry):
    """Строит новую страницу ленты «UML структуры»."""

    def builder(parent):
        icons = engine.engine_module
        page = tk.Frame(parent, bg="#f3f3f3")
        engine.editor._ribbon_group(page, "Реестр", lambda row: [
            engine.editor._ribbon_button(
                row, "Структуры…",
                lambda: open_manager(engine, registry),
                icons._ri_structure, 92).pack(side=tk.LEFT),
            engine.editor._ribbon_button(
                row, "Обновить",
                lambda: reload_registry(engine, registry),
                icons._ri_sync, 76).pack(side=tk.LEFT, padx=(4, 0)),
        ])
        engine.editor._ribbon_group(page, "Шкафы EA", lambda row: [
            engine.editor._ribbon_button(
                row, "Чертёж…",
                lambda: open_plugin(engine, registry, "ea_cabinets"),
                icons._ri_shield, 82).pack(side=tk.LEFT),
            engine.editor._ribbon_button(
                row, "Сборка…",
                lambda: assemble_plugin(engine, registry, "ea_cabinets"),
                icons._ri_merge, 78).pack(side=tk.LEFT, padx=(4, 0)),
        ])
        tk.Label(
            page,
            text="Графический движок main.py сохранён без изменений.\n"
                 "Структуры подключаются через structures/manifest.json.\n"
                 "Следующие UML-схемы: СТО, контейнеры.",
            bg=ui_theme.RIBBON, fg=ui_theme.TEXT_MUTED,
            font=ui_theme.font(8), justify="left").pack(
                side=tk.LEFT, padx=12)
        return page

    return builder


def build_app(root):
    """Собирает движок и слой структур, не изменяя исходный main.py."""
    engine = EditorEngine(root)
    registry = StructureRegistry(ROOT, MANIFEST_PATH)
    engine.register_ribbon_page(
        "UML структуры", build_structure_ribbon(engine, registry))
    engine.show_ribbon_page("UML структуры")
    return engine, registry


def check_registry_dynamics():
    """Проверяет расширяемость реестра на временном манифесте.

    Рабочий ``structures/manifest.json`` не изменяется: моделируется добавление
    четвёртой UML-структуры и порча манифеста, чтобы убедиться, что реестр
    подхватывает новую схему и не теряет уже загруженные плагины при ошибке.
    """
    with open(MANIFEST_PATH, encoding="utf-8") as handle:
        manifest = json.load(handle)

    extra = dict(manifest["plugins"][1])
    extra["id"] = "sto_probe"
    extra["title"] = "СТО (проверка)"
    manifest["plugins"].append(extra)

    descriptor, path = tempfile.mkstemp(prefix="structures-", suffix=".json")
    os.close(descriptor)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False)
        registry = StructureRegistry(ROOT, path)
        checks = [
            ("горячее добавление плагина",
             len(registry.plugins) == 4 and
             registry.get("sto_probe") is not None),
        ]

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ повреждённый манифест")
        rejected = False
        try:
            registry.reload()
        except ValueError:
            rejected = True
        checks.append(("битый манифест отклонён", rejected))
        checks.append(("реестр после ошибки",
                       len(registry.plugins) == 4 and
                       registry.get("sto_probe") is not None and
                       not registry.errors))
        return checks
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_selftest():
    root = tk.Tk()
    workspace = None
    manager = None
    try:
        engine, registry = build_app(root)
        root.withdraw()
        root.update_idletasks()
        state_before = (
            len(engine.editor.elements),
            len(engine.editor.connections),
            engine.editor.current_tool,
            engine.editor.current_path,
            engine.editor.is_modified,
            id(engine.canvas),
        )

        checks = [
            ("движок", engine.editor.__class__.__name__ == "CircuitEditor"),
            ("вкладка UML структуры",
             "UML структуры" in engine.ribbon_pages),
            ("активная вкладка",
             engine.editor._active_ribbon_tab == "UML структуры"),
            ("плагинов", len(registry.plugins) == 3),
            ("доступных плагинов", len(registry.available_plugins) == 1),
            ("ошибок загрузки", not registry.errors),
        ]

        manager = open_manager(engine, registry)
        manager.window.withdraw()
        root.update_idletasks()
        checks.append(("менеджер структур",
                       manager.plugin_list.size() == len(registry.plugins)))
        checks.append(("схема архитектуры",
                       bool(manager.canvas.find_all())))

        plugin = registry.get("ea_cabinets")
        workspace = plugin.create_workspace(engine.root, engine, registry)
        workspace.window.withdraw()
        root.update_idletasks()
        checks.append(("рабочее окно шкафов",
                       workspace.catalog_list.size() == 4))
        checks.append(("standard плагина",
                       plugin.status.startswith("Готов")))
        state_after = (
            len(engine.editor.elements),
            len(engine.editor.connections),
            engine.editor.current_tool,
            engine.editor.current_path,
            engine.editor.is_modified,
            id(engine.canvas),
        )
        checks.append(("состояние движка", state_before == state_after))
        checks.extend(check_registry_dynamics())

        for name, result in checks:
            print("%-28s %s" % (name, "OK" if result else "FAIL"))
        print("плагины: %s" % [
            (row["id"], row["available"], row["status"])
            for row in registry.rows()])
        print("вкладки: %s" % list(engine.ribbon_pages))
        ok = all(result for _, result in checks)
        print("SELFTEST: %s" % ("OK" if ok else "FAIL"))
        return 0 if ok else 1
    except Exception as error:
        print("SELFTEST ERROR: %s: %s" % (type(error).__name__, error))
        return 1
    finally:
        try:
            if workspace is not None:
                workspace.close()
        except Exception:
            pass
        try:
            if manager is not None:
                manager.close()
        except Exception:
            pass
        try:
            for child in list(root.winfo_children()):
                if isinstance(child, tk.Toplevel):
                    child.destroy()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Расширяемый редактор электрических схем")
    parser.add_argument(
        "--selftest", action="store_true",
        help="проверить сборку каркаса без удержания главного цикла")
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()

    root = tk.Tk()
    build_app(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
