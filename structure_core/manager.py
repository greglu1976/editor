"""Визуальный менеджер реестра UML-структур.

Окно повторяет трёхпанельную компоновку UML-тестового чертежа: список
структур слева, схема слоёв в центре и карточка выбранного плагина справа.
"""

import tkinter as tk
from tkinter import messagebox

BG = "#f3f3f3"
PANEL = "#ffffff"
CANVAS_BG = "#ffffff"
TEXT = "#263238"
MUTED = "#607d8b"
ACCENT = "#1565c0"
ACCENT_LIGHT = "#e3f2fd"
READY = "#e8f5e9"
READY_BORDER = "#2e7d32"
WAIT = "#f5f7fa"
WAIT_BORDER = "#b0bec5"
BORDER = "#d7dfe9"
CANVAS_W = 560
CANVAS_H = 430


class StructureManagerWindow:
    """Реестр плагинов и архитектурная схема нового каркаса."""

    def __init__(self, parent, engine, registry, on_close=None):
        self.parent = parent
        self.engine = engine
        self.registry = registry
        self.on_close = on_close
        self.selected_id = registry.default_id
        self._updating = False

        self.window = tk.Toplevel(parent)
        self.window.title("Реестр UML-структур")
        self.window.geometry("1120x680")
        self.window.minsize(900, 560)
        self.window.configure(bg=BG)
        try:
            self.window.transient(parent)
        except tk.TclError:
            pass
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.close())

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self.window, bg=BG)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))
        for label, command in (
                ("Открыть структуру", self.open_selected),
                ("Сборка…", self.assemble_selected),
                ("Обновить реестр", self.reload_registry),
                ("Закрыть", self.close)):
            tk.Button(toolbar, text=label, command=command, bg=PANEL,
                      fg=TEXT, activebackground=ACCENT_LIGHT,
                      relief=tk.GROOVE, bd=1, padx=8, pady=3).pack(
                          side=tk.LEFT, padx=(0, 4))

        body = tk.Frame(self.window, bg=BG)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = tk.LabelFrame(body, text="Зарегистрированные структуры",
                             bg=BG, fg=TEXT, padx=6, pady=6)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left.configure(width=300)
        left.pack_propagate(False)
        self.plugin_list = tk.Listbox(
            left, width=38, height=18, exportselection=False,
            bg=PANEL, fg=TEXT, selectbackground=ACCENT_LIGHT,
            selectforeground=ACCENT, highlightthickness=1,
            highlightcolor=BORDER, activestyle="none")
        list_scroll = tk.Scrollbar(left, orient=tk.VERTICAL,
                                   command=self.plugin_list.yview)
        self.plugin_list.configure(yscrollcommand=list_scroll.set)
        self.plugin_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.plugin_list.bind("<<ListboxSelect>>", self._on_list_select)
        self.plugin_list.bind("<Double-Button-1>",
                              lambda event: self.open_selected())

        center = tk.LabelFrame(body, text="Архитектура каркаса",
                               bg=BG, fg=TEXT, padx=4, pady=4)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.canvas = tk.Canvas(center, width=CANVAS_W, height=CANVAS_H,
                                bg=CANVAS_BG, highlightthickness=1,
                                highlightbackground=BORDER)
        hscroll = tk.Scrollbar(center, orient=tk.HORIZONTAL,
                               command=self.canvas.xview)
        vscroll = tk.Scrollbar(center, orient=tk.VERTICAL,
                               command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hscroll.set,
                              yscrollcommand=vscroll.set)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = tk.LabelFrame(body, text="Карточка структуры",
                              bg=BG, fg=TEXT, padx=6, pady=6)
        right.pack(side=tk.RIGHT, fill=tk.BOTH)
        right.configure(width=310)
        right.pack_propagate(False)
        self.details = tk.Text(right, wrap=tk.WORD, bg=PANEL, fg=TEXT,
                               relief=tk.FLAT, padx=8, pady=8,
                               font=("Arial", 9))
        detail_scroll = tk.Scrollbar(right, orient=tk.VERTICAL,
                                     command=self.details.yview)
        self.details.configure(yscrollcommand=detail_scroll.set,
                               state="disabled")
        self.details.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.status = tk.Label(self.window, text="", bg=BG, fg=MUTED,
                               anchor="w", justify="left")
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 6))

    def bring_to_front(self):
        self.window.deiconify()
        self.window.lift()
        try:
            self.window.focus_force()
        except tk.TclError:
            pass

    def close(self):
        if self.on_close:
            self.on_close(self)
        self.window.destroy()

    def _selected_plugin(self):
        plugin = self.registry.get(self.selected_id)
        if plugin:
            return plugin
        if self.registry.plugins:
            self.selected_id = self.registry.plugins[0].id
            return self.registry.plugins[0]
        return None

    def _refresh(self):
        self._updating = True
        self.plugin_list.delete(0, tk.END)
        ids = [plugin.id for plugin in self.registry.plugins]
        if self.selected_id not in ids and ids:
            self.selected_id = self.registry.default_id if (
                self.registry.default_id in ids) else ids[0]
        selected_index = None
        for index, plugin in enumerate(self.registry.plugins):
            marker = "[готов]" if plugin.available else "[ожидание]"
            self.plugin_list.insert(
                tk.END, "%s %s" % (marker, plugin.title))
            if not plugin.available:
                self.plugin_list.itemconfig(tk.END, fg=MUTED)
            if plugin.id == self.selected_id:
                selected_index = index
        if selected_index is None and self.registry.plugins:
            selected_index = 0
            self.selected_id = self.registry.plugins[0].id
        if selected_index is not None:
            self.plugin_list.selection_set(selected_index)
            self.plugin_list.activate(selected_index)
        self._updating = False
        self._show_details()
        self._draw_architecture()
        self._set_status(
            "Плагинов: %d; доступно: %d; ошибок загрузки: %d" % (
                len(self.registry.plugins),
                len(self.registry.available_plugins),
                len(self.registry.errors)))

    def _on_list_select(self, event=None):
        if self._updating:
            return
        selection = self.plugin_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.registry.plugins):
            return
        self.selected_id = self.registry.plugins[index].id
        self._show_details()
        self._draw_architecture()

    def _select_plugin(self, plugin_id):
        if self._updating:
            return
        self._updating = True
        self.selected_id = plugin_id
        self.plugin_list.selection_clear(0, tk.END)
        for index, plugin in enumerate(self.registry.plugins):
            if plugin.id == plugin_id:
                self.plugin_list.selection_set(index)
                self.plugin_list.activate(index)
                self.plugin_list.see(index)
                break
        self._updating = False
        self._show_details()
        self._draw_architecture()

    def _show_details(self):
        plugin = self._selected_plugin()
        if not plugin:
            text = "В реестре нет зарегистрированных структур."
        else:
            text = plugin.summary()
            text += (
                "\n\nПодключение новой UML-схемы:\n"
                "1. Добавить запись в structures/manifest.json.\n"
                "2. Указать schema, data и module плагина.\n"
                "3. Реализовать create_workspace() в модуле структуры.\n"
                "4. Нажать «Обновить реестр» без перезапуска движка.")
        self.details.configure(state="normal")
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")
        self.details.see("1.0")

    def _draw_architecture(self):
        self.canvas.delete("all")
        selected = self.selected_id

        def box(x1, y1, x2, y2, fill, outline, width=1, tags=()):
            return self.canvas.create_rectangle(
                x1, y1, x2, y2, fill=fill, outline=outline,
                width=width, tags=tags)

        box(70, 44, 490, 96, ACCENT_LIGHT, ACCENT, 2)
        self.canvas.create_text(
            280, 60, text="Графический движок", fill=ACCENT,
            font=("Arial", 11, "bold"))
        self.canvas.create_text(
            280, 80, text="main.py / CircuitEditor — без изменений",
            fill=TEXT, font=("Arial", 8))

        self.canvas.create_line(280, 96, 280, 122, fill=MUTED,
                                arrow=tk.LAST)
        box(110, 122, 450, 174, "#f1f8e9", "#7cb342", 2)
        self.canvas.create_text(
            280, 139, text="Реестр структур", fill="#33691e",
            font=("Arial", 11, "bold"))
        self.canvas.create_text(
            280, 158, text="structures/manifest.json + structure_core",
            fill=TEXT, font=("Arial", 8))

        self.canvas.create_line(280, 174, 280, 202, fill=MUTED)
        plugin_y = 224
        last_bottom = CANVAS_H
        for index, plugin in enumerate(self.registry.plugins):
            column = index % 2
            row = index // 2
            x1 = 30 + column * 270
            y1 = plugin_y + row * 78
            x2 = x1 + 240
            y2 = y1 + 58
            center_x = (x1 + x2) / 2
            self.canvas.create_line(
                280, 202, center_x, 202, center_x, y1,
                fill=WAIT_BORDER)
            is_selected = plugin.id == selected
            fill = READY if plugin.available else WAIT
            outline = ACCENT if is_selected else (
                READY_BORDER if plugin.available else WAIT_BORDER)
            tag = "plugin:%s" % plugin.id
            box(x1, y1, x2, y2, fill, outline,
                3 if is_selected else 1, (tag,))
            self.canvas.create_text(
                x1 + 10, y1 + 16, anchor="w", text=plugin.title,
                fill=TEXT, font=("Arial", 9, "bold"), tags=(tag,))
            state = "доступна" if plugin.available else plugin.status
            self.canvas.create_text(
                x1 + 10, y1 + 38, anchor="w",
                text="%s | %s" % (plugin.id, state),
                fill=MUTED, font=("Arial", 7), tags=(tag,))
            self.canvas.tag_bind(
                tag, "<Button-1>",
                lambda event, plugin_id=plugin.id:
                self._select_plugin(plugin_id))
            last_bottom = max(last_bottom, y2 + 30)

        self.canvas.configure(
            scrollregion=(0, 0, CANVAS_W, max(CANVAS_H, last_bottom)))

    def open_selected(self):
        plugin = self._selected_plugin()
        if not plugin:
            return None
        if not plugin.available:
            messagebox.showinfo(
                plugin.title,
                "Структура зарегистрирована, но пока недоступна.\n\n%s" %
                plugin.status,
                parent=self.window)
            return None
        try:
            result = plugin.create_workspace(
                self.engine.root, self.engine, self.registry)
        except Exception as error:
            messagebox.showerror(
                plugin.title, "Не удалось открыть структуру:\n%s" % error,
                parent=self.window)
            return None
        self._set_status("Открыта структура: %s" % plugin.title)
        return result

    def assemble_selected(self):
        plugin = self._selected_plugin()
        if not plugin:
            return None
        if not plugin.available or not plugin.supports_assembly:
            messagebox.showinfo(
                plugin.title,
                "Для этой структуры сборка объектов пока не поддерживается.",
                parent=self.window)
            return None
        try:
            result = plugin.create_assembly(
                self.engine.root, self.engine, self.registry)
        except Exception as error:
            messagebox.showerror(
                plugin.title, "Не удалось открыть сборку:\n%s" % error,
                parent=self.window)
            return None
        self._set_status("Открыта сборка структуры: %s" % plugin.title)
        return result

    def reload_registry(self):
        try:
            self.registry.reload()
        except Exception as error:
            messagebox.showerror(
                "Обновление реестра",
                "Не удалось перечитать manifest.json:\n%s" % error,
                parent=self.window)
            return
        self._refresh()
        self._set_status("Реестр структур обновлён")

    def refresh(self):
        """Публичное обновление представления после перезагрузки реестра."""
        self._refresh()

    def _set_status(self, text):
        self.status.configure(text=text)
