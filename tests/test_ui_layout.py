# -*- coding: utf-8 -*-
"""Проверка стабильности главного окна и единой темы оформления.

Запуск:
    python3 tests/test_ui_layout.py           # полный набор, нужен tkinter
    python3 tests/test_ui_layout.py --no-gui  # только константы темы

Проверяет:

1. ``ui_theme`` — целостность палитры, шрифтов и таблицы совместимости;
2. геометрию: переключение всех шести вкладок ленты, панель поиска и
   переключатели не меняют ни фактический, ни «запрошенный» размер окна;
3. оформление: применена тема ``clam``, «исторические» цвета и шрифты
   Arial нормализованы, активная вкладка меняет только цвет;
4. окна, созданные после старта (проводник структуры), тоже получают тему.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ui_theme               # noqa: E402

try:                          # GUI-часть необязательна (например, в CI)
    import tkinter as tk
    from tkinter import ttk
except ImportError:           # pragma: no cover - зависит от сборки Python
    tk = ttk = None

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def _is_hex(value):
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)))


def test_theme_module():
    print("1. модуль ui_theme")
    palette = [value for name, value in vars(ui_theme).items()
               if name.isupper() and isinstance(value, str)
               and value.startswith("#")]
    check(all(_is_hex(value) for value in palette),
          "все цвета палитры заданы шестнадцатеричным кодом")
    check(ui_theme.ACCENT == "#1f4e79",
          "акцент совпадает с фирменным синим схемы")
    check(ui_theme.RIBBON != ui_theme.TABBAR != ui_theme.PALETTE,
          "лента, полоса вкладок и палитра различаются")
    check(set(ui_theme.LEGACY_COLORS.values()) <= set(palette),
          "все замены ведут в актуальную палитру")
    check("bg" not in ui_theme._COLOR_OPTIONS
          and "fg" not in ui_theme._COLOR_OPTIONS,
          "алиасы bg/fg не дублируют канонические опции")
    check(ui_theme.font(9, "bold") == (ui_theme.FONT_FAMILY, 9, "bold"),
          "font() собирает кортеж шрифта")
    check("{" in ui_theme.font_spec(9, "bold"),
          "font_spec() экранирует семейство с пробелом")


def _walk(widget):
    yield widget
    try:
        children = widget.winfo_children()
    except tk.TclError:
        return
    for child in children:
        for item in _walk(child):
            yield item


def _legacy_left(widget):
    """(цвета, шрифты Arial), оставшиеся в поддереве виджетов."""
    colors, fonts = [], []
    for item in _walk(widget):
        try:
            options = item.configure()
        except (tk.TclError, AttributeError, TypeError):
            continue
        for name, cfg in options.items():
            if not isinstance(cfg, tuple) or len(cfg) < 5:
                continue
            value = cfg[4]
            if (name in ui_theme._COLOR_OPTIONS and isinstance(value, str)
                    and value.strip().lower() in ui_theme.LEGACY_COLORS):
                colors.append((str(item), name, value))
            if (name == "font" and isinstance(value, str)
                    and value.split()[:1] == ["Arial"]):
                fonts.append((str(item), value))
    return colors, fonts


def test_gui():
    print("2. тема и геометрия главного окна")
    import main

    root = tk.Tk()
    try:
        app = main.CircuitEditor(root)
        root.update()

        check(ttk.Style(root).theme_use() == "clam",
              "используется предсказуемая тема ttk «clam»")
        check(ttk.Style(root).lookup("Treeview", "background")
              == ui_theme.CANVAS,
              "стиль дерева берёт цвет из палитры")
        probe_frame = tk.Frame(root)
        check(probe_frame.cget("bg") == ui_theme.WINDOW,
              "база опций Tk задаёт фон окон")
        probe_frame.destroy()
        check(app._palette_wrap.cget("bg") == ui_theme.PALETTE,
              "палитра элементов перекрашена")
        check(app._ribbon_pages["Главная"].cget("bg") == ui_theme.RIBBON,
              "страница ленты перекрашена")
        check(app._ribbon_tab_buttons["Главная"].cget("font")
              .find(ui_theme.FONT_FAMILY) >= 0,
              "шрифт вкладок берётся из темы")

        colors, fonts = _legacy_left(root)
        check(not colors, "устаревших цветов в главном окне нет (%d)" % len(colors))
        check(not fonts, "шрифтов Arial в главном окне нет (%d)" % len(fonts))

        print("3. стабильность размеров")
        size = app._ribbon_size
        tallest = max(page.winfo_reqheight()
                      for page in app._ribbon_pages.values())
        check(size[1] >= tallest,
              "высота ленты %d вмещает самую высокую вкладку %d"
              % (size[1], tallest))
        # Поведенческая проверка pack_propagate(False): заведомо высокий
        # «посторонний» ребёнок не должен растянуть область вкладок.
        probe = tk.Frame(app._ribbon_content, width=400, height=400)
        probe.pack()
        root.update()
        check(app._ribbon_content.winfo_height() == size[1],
              "лента не передаёт размеры страниц наверх")
        probe.pack_forget()
        probe.destroy()
        root.update()

        geometry = root.geometry()
        actual, requested, ribbon_sizes = set(), set(), set()
        for name in app._ribbon_pages:
            app._show_ribbon_tab(name)
            root.update()
            actual.add((root.winfo_width(), root.winfo_height()))
            requested.add((root.winfo_reqwidth(), root.winfo_reqheight()))
            ribbon_sizes.add((app._ribbon_content.winfo_width(),
                              app._ribbon_content.winfo_height()))
        check(len(actual) == 1,
              "размер окна одинаков на всех 6 вкладках: %s" % sorted(actual))
        check(len(requested) == 1,
              "запрошенный размер окна тоже не меняется")
        check(len(ribbon_sizes) == 1,
              "область вкладок имеет фиксированный размер")
        check(root.geometry() == geometry,
              "положение окна не смещается при переключении вкладок")

        app.open_search()
        root.update()
        open_size = (root.winfo_width(), root.winfo_height())
        app.close_search()
        root.update()
        closed_size = (root.winfo_width(), root.winfo_height())
        check(open_size == closed_size == next(iter(actual)),
              "панель поиска не меняет размер окна")
        app._refresh_ribbon_toggles()
        root.update()
        check((root.winfo_width(), root.winfo_height()) in actual,
              "обновление подписей переключателей не меняет размер окна")

        print("4. активная вкладка и динамические цвета")
        fonts_before = {name: button.cget("font")
                        for name, button in app._ribbon_tab_buttons.items()}
        app._show_ribbon_tab("Отчёты")
        root.update()
        fonts_after = {name: button.cget("font")
                       for name, button in app._ribbon_tab_buttons.items()}
        check(fonts_before == fonts_after,
              "выделение вкладки не меняет шрифт и не сдвигает соседей")
        check(app._ribbon_tab_buttons["Отчёты"].cget("bg")
              == ui_theme.TAB_ACTIVE,
              "активная вкладка сливается с рабочей областью ленты")
        check(app._ribbon_tab_buttons["Главная"].cget("bg")
              == ui_theme.TABBAR,
              "неактивная вкладка остаётся на полосе вкладок")

        app._show_ribbon_tab("Главная")
        app._mark_active_tool()
        root.update()
        marks = [canvas.cget("highlightbackground")
                 for canvas in app._tool_icons.values()]
        check(ui_theme.ACCENT in marks or ui_theme.BORDER in marks,
              "рамка активного инструмента использует цвета темы")
        check(not any(value.lower() in ui_theme.LEGACY_COLORS
                      for value in marks),
              "подсветка инструментов не возвращает устаревшие цвета")

        print("5. окна, созданные после старта")
        app.show_structure_overview()
        root.update()
        root.update_idletasks()
        windows = [w for w in root.winfo_children()
                   if isinstance(w, tk.Toplevel)]
        check(len(windows) == 1, "проводник структуры открыт")
        if windows:
            window = windows[0]
            check(window.cget("bg") == ui_theme.WINDOW,
                  "новое окно унаследовало фон темы")
            dcolors, dfonts = _legacy_left(window)
            check(not dcolors and not dfonts,
                  "в новом окне нет устаревших цветов и шрифтов")
            window.destroy()
    finally:
        root.destroy()


def test_source_has_no_dynamic_legacy_colors():
    """Динамические .config(bg=...) не должны возвращать старые цвета."""
    print("6. исходный код")
    source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    setters = re.findall(r"\.(?:config|configure)\([^)]*\bbg\s*=\s*"
                         r"\"(#[0-9a-fA-F]{6})\"", source)
    check(all(color.lower() not in ui_theme.LEGACY_COLORS
              for color in setters),
          "в динамических перекрасках нет «исторических» цветов")


def main_entry():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-gui", action="store_true",
                        help="только проверки, не требующие tkinter")
    args = parser.parse_args()

    test_theme_module()
    if not args.no_gui:
        if tk is None:
            print("\ntkinter недоступен — GUI-часть пропущена "
                  "(используйте --no-gui или Python с Tk)")
        else:
            test_gui()
    test_source_has_no_dynamic_legacy_colors()

    if FAILURES:
        print("\nПРОВАЛЫ (%d):" % len(FAILURES))
        for message in FAILURES:
            print("  x", message)
        return 1
    print("\nВсё в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(main_entry())
