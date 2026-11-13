"""Тонкая обёртка над рабочим графическим движком ``main.CircuitEditor``.

``main.py`` остаётся владельцем холста, инструментов, ленты, сериализации
схемы и всех проверенных графических режимов. Этот модуль только предоставляет
стабильные точки подключения для нового расширяемого каркаса: корневое окно,
добавление страницы ленты и создание отдельного окна.

Слой структур не импортируется отсюда: композиция выполняется в
``editor_app.py``.
"""

import tkinter as tk

import ui_theme


class EditorEngine:
    """Адаптер неизменённого графического движка редактора схем."""

    def __init__(self, root=None):
        # Импорт по требованию: модуль движка тяжёлый и должен загружаться
        # только при реальном запуске редактора.
        import main

        self.root = root or tk.Tk()
        self.engine_module = main
        self.editor = main.CircuitEditor(self.root)

    @property
    def canvas(self):
        return self.editor.canvas

    @property
    def ribbon_content(self):
        return self.editor._ribbon_content

    @property
    def ribbon_pages(self):
        return self.editor._ribbon_pages

    @property
    def ribbon_buttons(self):
        return self.editor._ribbon_tab_buttons

    def find_tabbar(self):
        """Находит полосу кнопок вкладок без изменения ``main.py``."""
        ribbon = self.ribbon_content.master
        for child in ribbon.winfo_children():
            if child.winfo_class() != "Frame":
                continue
            buttons = [widget for widget in child.winfo_children()
                       if widget.winfo_class() == "Button"]
            if len(buttons) >= 5:
                return child
        raise RuntimeError("не найдена полоса вкладок графического движка")

    def register_ribbon_page(self, name, builder):
        """Добавляет новую страницу ленты, не трогая существующие."""
        if name in self.ribbon_pages:
            return self.ribbon_pages[name]

        page = builder(self.ribbon_content)
        self.ribbon_pages[name] = page

        button = tk.Button(
            self.find_tabbar(), text=name, relief=tk.FLAT, bd=0,
            padx=16, pady=5, font=ui_theme.font(9, "bold"),
            bg=ui_theme.TABBAR, fg=ui_theme.TEXT_SOFT,
            activebackground=ui_theme.HOVER,
            activeforeground=ui_theme.ACCENT,
            command=lambda: self.show_ribbon_page(name))
        button.pack(side=tk.LEFT, padx=(2, 0), pady=(2, 0))
        self.ribbon_buttons[name] = button

        # Пересчитываем общую геометрию ленты с учётом новой страницы.
        self.editor._lock_ribbon_geometry()
        return page

    def show_ribbon_page(self, name):
        return self.editor._show_ribbon_tab(name)

    def create_toplevel(self, title):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.configure(bg=ui_theme.WINDOW)
        try:
            window.transient(self.root)
        except tk.TclError:
            pass
        return window

    def mainloop(self):
        return self.root.mainloop()
