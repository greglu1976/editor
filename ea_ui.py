# -*- coding: utf-8 -*-
"""Окно стандартов СТО в структуре EA для редактора схем.

Показывает дерево документа (разделы → подразделы → пункты → таблицы) и
шкафы. Строки таблиц не хранятся в документе: они собираются из шкафа через
:func:`ea_standard.table_view`, поэтому в окне видно ровно то, что лежит в
``cabinets``.

Модуль самостоятельный: старые окна стандартов (``standards_ui``) не
импортируются, чтобы новую ветку можно было оставить без старой.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

import ea_standard as es
import ui_theme


# ---------------------------------------------------------------------------
# Общие мелочи
# ---------------------------------------------------------------------------
def _place_on_parent(window, parent):
    """Поставить окно на тот же монитор, где родитель."""
    try:
        window.update_idletasks()
        width, height = window.winfo_width(), window.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if width <= 1 or height <= 1 or pw <= 1 or ph <= 1:
            return
        x = px + max(0, (pw - width) // 2)
        y = py + max(0, (ph - height) // 2)
        window.geometry("+%d+%d" % (x, y))
    except tk.TclError:
        pass


def _button(parent, text, command, width=0, side=tk.LEFT, padx=(0, 4)):
    button = tk.Button(parent, text=text, command=command,
                       font=ui_theme.font(9))
    if width:
        button.config(width=width)
    button.pack(side=side, padx=padx, pady=2)
    return button


def open_folder(path):
    """Открыть папку в проводнике (Windows/Linux)."""
    if not path or not os.path.isdir(path):
        return False
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                       # noqa: S606
            return True
        import subprocess
        subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Окно
# ---------------------------------------------------------------------------
class EAStandardWindow(tk.Toplevel):
    """Дерево стандарта EA и таблицы, собранные из шкафов."""

    def __init__(self, app, path=None):
        parent = getattr(app, "root", app)
        super().__init__(parent)
        self.app = app
        self.title("Стандарты СТО (структура EA)")
        self.geometry("1240x760")
        self.minsize(980, 560)
        self.transient(parent)
        self._path = path
        self._data = None
        self._nodes = {}
        self._build()
        self.reload(path)
        _place_on_parent(self, parent)

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=(8, 2))
        tk.Label(top, text="Стандарт:", font=ui_theme.font(9),
                 anchor="w").pack(side=tk.LEFT)
        self.combo = ttk.Combobox(top, state="readonly", width=62,
                                  font=ui_theme.font(9))
        self.combo.pack(side=tk.LEFT, padx=(6, 4))
        self.combo.bind("<<ComboboxSelected>>", lambda event: self._combo_changed())
        _button(top, "Обновить", self.reload, width=10, side=tk.RIGHT)
        _button(top, "Открыть папку", lambda: open_folder(es.folder()),
                side=tk.RIGHT)
        _button(top, "Проверить", self.check, width=10, side=tk.RIGHT)

        tk.Label(self, text="Таблицы в документе — только форма; строки "
                            "собираются из шкафа (поле «cabinet»).",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED, anchor="w",
                 justify="left").pack(fill=tk.X, padx=10, pady=(0, 4))

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        left = tk.Frame(panes)
        tree_scroll = tk.Scrollbar(left, orient="vertical")
        self.tree = ttk.Treeview(left, show="tree",
                                 yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self.tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._show())
        panes.add(left, weight=1)

        right = tk.Frame(panes)
        self.caption = tk.Label(right, text="", anchor="w", justify="left",
                                font=ui_theme.font(9, "bold"))
        self.caption.pack(fill=tk.X, padx=4, pady=(2, 4))
        body = tk.Frame(right)
        body.pack(fill=tk.BOTH, expand=True)
        self.scroll_y = tk.Scrollbar(body, orient="vertical")
        self.scroll_x = tk.Scrollbar(body, orient="horizontal")
        self.table = ttk.Treeview(body, show="headings",
                                  yscrollcommand=self.scroll_y.set,
                                  xscrollcommand=self.scroll_x.set)
        self.scroll_y.config(command=self.table.yview)
        self.scroll_x.config(command=self.table.xview)
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text = tk.Text(body, wrap="word", font=ui_theme.font(9),
                            height=8)
        panes.add(right, weight=3)

        self.status = tk.Label(self, text="", anchor="w",
                               font=ui_theme.font(8),
                               fg=ui_theme.TEXT_MUTED)
        self.status.pack(fill=tk.X, padx=10)
        footer = tk.Frame(self)
        footer.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(footer, text="F5 — обновить, Esc — закрыть",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED).pack(
                     side=tk.LEFT)
        _button(footer, "Закрыть", self.destroy, width=10, side=tk.RIGHT)
        self.bind("<F5>", lambda event: self.reload())
        self.bind("<Escape>", lambda event: self.destroy())

    # -------------------------------------------------------------- данные
    def _combo_changed(self):
        paths = es.files()
        index = self.combo.current()
        if 0 <= index < len(paths):
            self.reload(paths[index])

    def reload(self, path=None):
        """Перечитать папку и построить дерево."""
        paths = es.files()
        self.combo["values"] = [os.path.basename(item) for item in paths]
        chosen = path or self._path
        if chosen not in paths:
            chosen = paths[0] if paths else None
        self._path = chosen
        if not chosen:
            self.status.config(text="В папке нет JSON стандартов: %s"
                                    % es.folder())
            return
        self.combo.current(paths.index(chosen))
        try:
            self._data = es.load(chosen)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror("Стандарты СТО",
                                 "Не удалось прочитать стандарт:\n%s" % exc,
                                 parent=self)
            return
        self._fill_tree()
        self.status.config(text="%s — разделов %d, таблиц %d, шкафов %d"
                           % (os.path.basename(chosen),
                              len(es.sections(self._data)),
                              len(list(es.iter_tables(self._data))),
                              len(es.cabinets(self._data))))

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._nodes.clear()
        root = self.tree.insert("", tk.END, text=self._data.get("code", ""),
                                open=True)
        for section in es.sections(self._data):
            title = "%s %s" % (section.get("number", ""),
                               section.get("header", ""))
            node = self.tree.insert(root, tk.END, text=title.strip(), open=False)
            self._nodes[node] = ("text", section.get("header", ""),
                                 section.get("content", ""))
            self._add_tables(node, section)
            for clause in section.get("clauses") or []:
                self._add_clause(node, clause)
            for sub in section.get("subsections") or []:
                sub_node = self.tree.insert(
                    node, tk.END,
                    text="%s %s" % (sub.get("number", ""), sub.get("header", "")),
                    open=False)
                self._nodes[sub_node] = ("text", sub.get("header", ""), "")
                self._add_tables(sub_node, sub)
                for clause in sub.get("clauses") or []:
                    self._add_clause(sub_node, clause)
        cabinets_node = self.tree.insert("", tk.END, text="Шкафы", open=True)
        for item in es.cabinets(self._data):
            code = item.get("cypher", "")
            node = self.tree.insert(cabinets_node, tk.END,
                                    text="%s — %s" % (code, item.get("name", "")),
                                    open=False)
            self._nodes[node] = ("cabinet", item)

    def _add_tables(self, parent, container):
        for table in container.get("tables") or []:
            label = "%s %s" % (table.get("reference") or "Таблица",
                               table.get("name") or "")
            node = self.tree.insert(parent, tk.END, text=label.strip())
            self._nodes[node] = ("table", table)

    def _add_clause(self, parent, clause):
        text = clause.get("content") or ""
        title = "%s %s" % (clause.get("number", ""),
                           text.split("\n")[0][:90])
        node = self.tree.insert(parent, tk.END, text=title.strip())
        self._nodes[node] = ("text", "Пункт %s" % clause.get("number", ""),
                             text)
        self._add_tables(node, clause)

    # ------------------------------------------------------------- показ
    def _show(self):
        selection = self.tree.selection()
        if not selection:
            return
        node = self._nodes.get(selection[0])
        if not node:
            return
        kind = node[0]
        if kind == "table":
            self._show_table(node[1])
        elif kind == "cabinet":
            self._show_cabinet(node[1])
        else:
            self._show_text(node[1], node[2])

    def _clear_right(self):
        for column in self.table["columns"]:
            self.table.heading(column, text="")
        self.table["columns"] = ()
        self.table.delete(*self.table.get_children())
        self.table.pack_forget()
        self.scroll_y.pack_forget()
        self.scroll_x.pack_forget()
        self.text.pack_forget()

    def _show_table(self, table):
        headers, rows = es.table_view(self._data, table)
        self._clear_right()
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.caption.config(
            text="%s %s" % (table.get("reference", ""), table.get("name", "")))
        code = table.get("cabinet")
        note = ("Данные из шкафа %s" % code) if code else "Таблица документа"
        self.status.config(text="%s — строк %d" % (note, len(rows)))
        if not headers:
            self._show_text("Таблица", "(пустая таблица)")
            return
        columns = ["c%d" % index for index in range(len(headers))]
        self.table["columns"] = columns
        for index, column in enumerate(columns):
            self.table.heading(column, text=headers[index])
            width = max([len(headers[index])] + [len(str(row[index]))
                                                 for row in rows[:80]
                                                 if index < len(row)])
            self.table.column(column,
                              width=min(360, max(80, width * 8 + 18)),
                              anchor="w", stretch=False)
        for row in rows:
            values = [row[index] if index < len(row) else ""
                      for index in range(len(headers))]
            self.table.insert("", tk.END, values=values)
        if not rows:
            self.table.insert("", tk.END, values=["—"] * len(headers))

    def _show_cabinet(self, item):
        self._clear_right()
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.caption.config(text="Шкаф %s — %s"
                                 % (item.get("cypher", ""), item.get("name", "")))
        headers = ["Параметр", "Значение"]
        columns = ["c0", "c1"]
        self.table["columns"] = columns
        self.table.heading("c0", text=headers[0])
        self.table.heading("c1", text=headers[1])
        self.table.column("c0", width=190, anchor="w", stretch=False)
        self.table.column("c1", width=760, anchor="w", stretch=True)
        for row in es.cabinet_card(item):
            self.table.insert("", tk.END, values=row)
        self.status.config(text="Шкаф %s" % item.get("cypher", ""))

    def _show_text(self, title, content):
        self._clear_right()
        self.caption.config(text=title)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content or "")
        self.text.config(state="disabled")

    # ---------------------------------------------------------- действия
    def check(self):
        if not self._data:
            return
        problems = es.validate(self._data)
        if not problems:
            messagebox.showinfo("Стандарты СТО",
                                "Структура в порядке: все таблицы находят "
                                "свои шкафы, наборы данных полны.",
                                parent=self)
            self.status.config(text="Проверка: проблем нет")
            return
        messagebox.showwarning(
            "Стандарты СТО",
            "Найдено проблем: %d\n\n%s" % (len(problems),
                                           "\n".join(problems[:15])),
            parent=self)
        self.status.config(text="Проверка: проблем %d" % len(problems))


# ---------------------------------------------------------------------------
# Точка входа для редактора
# ---------------------------------------------------------------------------
def show(app, path=None):
    """Открыть окно стандартов EA (или вернуть существующее)."""
    return EAStandardWindow(app, path)
