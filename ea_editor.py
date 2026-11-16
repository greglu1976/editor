# -*- coding: utf-8 -*-
"""Окно редактирования стандарта СТО.

Слева — дерево стандарта (реквизиты, документ, шкафы), справа — редактор
выбранного узла. Правки копятся в памяти и записываются в JSON по кнопке
«Сохранить»; строки таблиц раскладываются по шкафам через :mod:`ea_edit`.

Таблица в документе остаётся только формой: редактор показывает и меняет
данные шкафа (``cabinets``), поэтому правка строки таблицы сразу видна во
всех местах, где эта таблица используется.
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import ea_edit as ee
import ea_standard as es
import ea_structure as st
import ui_theme


def _place_on_parent(window, parent):
    """Поставить окно на тот же монитор, где родитель."""
    try:
        window.update_idletasks()
        width = max(window.winfo_width(), window.winfo_reqwidth())
        height = max(window.winfo_height(), window.winfo_reqheight())
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if width <= 1 or height <= 1 or pw <= 1 or ph <= 1:
            return
        window.geometry("+%d+%d" % (px + max(0, (pw - width) // 2),
                                    py + max(0, (ph - height) // 2)))
    except tk.TclError:
        pass


def _button(parent, text, command, width=0, side=tk.LEFT, padx=(0, 4)):
    button = tk.Button(parent, text=text, command=command,
                       font=ui_theme.font(9))
    if width:
        button.config(width=width)
    button.pack(side=side, padx=padx, pady=2)
    return button


_CABINET_FIELDS = (
    ("cypher", "Шифр шкафа", 24),
    ("architecture", "Архитектура", 34),
    ("name", "Наименование", 52),
    ("controllable_element", "Управляемый элемент", 44),
    ("protected_element", "Защищаемый элемент", 44),
    ("scope", "Область применения", 44),
    ("type", "Тип", 24),
)

_KIT_FIELDS = (
    ("number", "Номер комплекта", 18),
    ("description", "Описание", 52),
    ("type", "Тип", 24),
)

_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


# ---------------------------------------------------------------------------
# Окно
# ---------------------------------------------------------------------------
class StandardEditorWindow(tk.Toplevel):
    """Редактор одного JSON стандарта: текст, таблицы, карточки шкафов."""

    def __init__(self, path, parent=None, on_saved=None):
        # main.py передаёт CircuitEditor (не виджет), как и в ea_ui
        root = getattr(parent, "root", parent) if parent is not None \
            else tk._default_root
        super().__init__(root)
        self.path = path
        self.data = es.load(path)
        self.on_saved = on_saved
        self._nodes = {}
        self._owners = {}             # iid -> (список, узел, iid родителя)
        self._meta_iid = None
        self._pending = None          # что записать в данные перед уходом
        self._current_node = None
        self._changed = False
        self._switching = False
        self._grid = None
        self._grid_rows = []
        self._grid_initial = []
        self._grid_editable = False
        self._grid_table = None
        self._grid_apply = None
        self._panel_item = None
        self._snapshot = None
        self.vars = {}
        self.title("Редактор стандарта — %s" % os.path.basename(path))
        self.geometry("1280x800")
        self.minsize(1000, 600)
        self.transient(root)
        self._build()
        self._fill_tree()
        self._place()
        self.bind("<Control-s>", self.save)
        self.bind("<Escape>", lambda event: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=(8, 2))
        self.file_label = tk.Label(top, text=os.path.basename(self.path),
                                   font=ui_theme.font(9, "bold"), anchor="w")
        self.file_label.pack(side=tk.LEFT)
        _button(top, "Сохранить", self.save, width=12, side=tk.RIGHT)
        _button(top, "Применить", self.apply, width=12, side=tk.RIGHT)
        _button(top, "Перечитать", self.reload, width=12, side=tk.RIGHT)
        _button(top, "Проверить", self.check, width=10, side=tk.RIGHT)
        _button(top, "Закрыть", self.close, width=10, side=tk.RIGHT)

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 6))

        left = tk.Frame(panes)
        scroll = tk.Scrollbar(left, orient="vertical")
        self.tree = ttk.Treeview(left, show="tree", yscrollcommand=scroll.set)
        scroll.config(command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)
        panes.add(left, weight=1)

        right = tk.Frame(panes)
        self.caption = tk.Label(right, text="", anchor="w", justify="left",
                                font=ui_theme.font(10, "bold"))
        self.caption.pack(fill=tk.X, padx=4, pady=(2, 4))
        self.body = tk.Frame(right)
        self.body.pack(fill=tk.BOTH, expand=True)
        panes.add(right, weight=3)

        self.status = tk.Label(self, text="Ctrl+S — сохранить, Esc — закрыть",
                               anchor="w", font=ui_theme.font(8),
                               fg=ui_theme.TEXT_MUTED)
        self.status.pack(fill=tk.X, padx=10, pady=(0, 8))

    def _place(self):
        parent = self.master
        if isinstance(parent, tk.Misc):
            _place_on_parent(self, parent)

    # -------------------------------------------------------------- дерево
    def _register_node(self, iid, node, container, item, parent_iid):
        """Запомнить узел дерева и его место в данных."""
        self._nodes[iid] = node
        self._owners[iid] = (container, item, parent_iid)

    def _fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._nodes.clear()
        self._owners.clear()
        root = self.tree.insert("", tk.END,
                                text=os.path.basename(self.path), open=True)
        meta = self.tree.insert(root, tk.END, text="Реквизиты")
        self._register_node(meta, ("meta",), None, None, None)
        self._meta_iid = meta

        doc = self.tree.insert(root, tk.END, text="Документ", open=True)
        sections = self.data.setdefault("sections", [])
        self._register_node(doc, ("root", "doc"), sections, None, None)
        for section in sections:
            title = "%s %s" % (section.get("number", ""),
                               section.get("header", ""))
            node = self.tree.insert(doc, tk.END, text=title.strip(),
                                    open=False)
            self._register_node(node, ("text", "section", section), sections,
                           section, doc)
            self._add_tables(node, section)
            self._add_figures(node, section, section.get("number", ""))
            clauses = section.setdefault("clauses", [])
            for clause in clauses:
                self._tree_clause(node, clause, clauses)
            subsections = section.setdefault("subsections", [])
            for sub in subsections:
                title = "%s %s" % (sub.get("number", ""),
                                   sub.get("header", ""))
                sub_node = self.tree.insert(node, tk.END,
                                            text=title.strip(), open=False)
                self._register_node(sub_node, ("text", "subsection", sub),
                               subsections, sub, node)
                self._add_tables(sub_node, sub)
                self._add_figures(sub_node, sub, sub.get("number", ""))
                sub_clauses = sub.setdefault("clauses", [])
                for clause in sub_clauses:
                    self._tree_clause(sub_node, clause, sub_clauses)

        cabs = self.tree.insert(root, tk.END, text="Шкафы", open=True)
        cabinets = self.data.setdefault("cabinets", [])
        self._register_node(cabs, ("root", "cabs"), cabinets, None, None)
        for item in cabinets:
            node = self.tree.insert(
                cabs, tk.END,
                text="Шкаф %s — %s" % (item.get("cypher", ""),
                                       item.get("name", "")), open=False)
            self._register_node(node, ("cabinet", item), cabinets, item, cabs)
            kits = item.setdefault("kits", [])
            for kit in kits:
                kit_node = self.tree.insert(
                    node, tk.END,
                    text="Комплект %s — %s" % (kit.get("number", ""),
                                               kit.get("description", "")),
                    open=False)
                self._register_node(kit_node, ("kit", kit), kits, kit, node)
                ieds = kit.setdefault("ieds", [])
                for ied in ieds:
                    ied_node = self.tree.insert(
                        kit_node, tk.END,
                        text="ИЭУ %s" % ied.get("number", ""))
                    self._register_node(ied_node, ("ied", ied), ieds, ied,
                                   kit_node)

        self._current_node = meta
        self.tree.selection_set(meta)
        self.tree.focus(meta)
        self._render(self._nodes[meta])

    def _add_tables(self, parent, container):
        tables = container.setdefault("tables", [])
        for table in tables:
            label = "%s %s" % (table.get("reference") or "Таблица",
                               table.get("name") or "")
            node = self.tree.insert(parent, tk.END, text=label.strip())
            self._register_node(node, ("table", table), tables, table, parent)

    def _add_figures(self, parent, container, number):
        figures = container.setdefault("figures", [])
        for figure in figures:
            label = "%s %s" % (figure.get("reference") or "Рисунок",
                               figure.get("name") or "")
            node = self.tree.insert(parent, tk.END, text=label.strip())
            self._register_node(node, ("figure", figure), figures, figure, parent)

    def _tree_clause(self, parent, clause, clauses):
        text = (clause.get("content") or "").split("\n")[0]
        node = self.tree.insert(
            parent, tk.END,
            text="%s %s" % (clause.get("number", ""), text[:90]))
        self._register_node(node, ("text", "clause", clause), clauses, clause,
                       parent)
        self._add_tables(node, clause)
        self._add_figures(node, clause, clause.get("number", ""))

    # ------------------------------------------------------------- выборка
    def _on_select(self, event=None):
        if self._switching:
            return
        selection = self.tree.selection()
        if not selection:
            return
        node_id = selection[0]
        if node_id == self._current_node:
            return
        if not self._apply_pending():
            self._switching = True
            if self._current_node and self.tree.exists(self._current_node):
                self.tree.selection_set(self._current_node)
            self._switching = False
            return
        self._current_node = node_id
        self._render(self._nodes.get(node_id))

    def _render(self, node):
        self._clear()
        self._pending = None
        self._grid = None
        self._grid_rows = []
        self._grid_initial = []
        self._grid_editable = False
        self._grid_table = None
        self._grid_apply = None
        self._panel_item = None
        self._snapshot = None
        self.vars = {}
        if not node:
            return
        kind = node[0]
        if kind == "meta":
            self._render_meta()
        elif kind == "root":
            title = "Документ" if node[1] == "doc" else "Шкафы"
            self.caption.config(text=title)
            tk.Label(self.body, text="Правый клик по дереву — добавить узел.",
                     font=ui_theme.font(9), fg=ui_theme.TEXT_MUTED,
                     anchor="w", justify="left").pack(fill=tk.X, padx=4,
                                                      pady=8)
        elif kind == "text":
            self._render_text(node[1], node[2])
        elif kind == "table":
            self._render_table(node[1])
        elif kind == "figure":
            self._render_figure(node[1])
        elif kind == "cabinet":
            self._render_cabinet(node[1])
        elif kind == "kit":
            self._render_kit(node[1])
        elif kind == "ied":
            self._render_ied(node[1])

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.caption.config(text="")

    # ---------------------------------------------------------- реквизиты
    def _render_meta(self):
        self.caption.config(text="Реквизиты стандарта")
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=4)
        form.columnconfigure(1, weight=1)
        fields = (
            ("code", "Шифр стандарта", 44),
            ("name", "Наименование", 64),
            ("property", "Принадлежность", 44),
            ("date", "Дата введения", 16),
        )
        row = 0
        for key, label, width in fields:
            tk.Label(form, text=label + ":", font=ui_theme.font(9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(self.data.get(key) or ""))
            tk.Entry(form, textvariable=var, font=ui_theme.font(9),
                     width=width).grid(row=row, column=1, sticky="we", pady=3)
            self.vars[key] = var
            row += 1
        tk.Label(form, text="Дата — ДД.ММ.ГГГГ; можно оставить пустой.",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED,
                 anchor="w").grid(row=row, column=0, columnspan=2,
                                  sticky="w", pady=(2, 6))
        self._snapshot = {key: str(self.data.get(key) or "") for key, _l, _w
                          in fields}
        self._pending = self._apply_meta

    def _apply_meta(self):
        meta = {key: var.get().strip() for key, var in self.vars.items()}
        if not meta["code"] or not meta["name"]:
            raise ee.TableEditError("заполните шифр и наименование")
        if meta["date"] and not _DATE.match(meta["date"]):
            raise ee.TableEditError("дата введения — в виде ДД.ММ.ГГГГ")
        if meta == self._snapshot:
            return False
        self.data.update(meta)
        self._snapshot = dict(meta)
        return True

    # --------------------------------------------------------------- текст
    def _render_text(self, kind, item):
        title = {"section": "Раздел", "subsection": "Подраздел",
                 "clause": "Пункт"}[kind]
        self.caption.config(text="%s %s" % (title, item.get("number", "")))
        self._panel_item = item
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=(2, 4))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Номер:", font=ui_theme.font(9),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        number = tk.StringVar(value=str(item.get("number") or ""))
        tk.Entry(form, textvariable=number, font=ui_theme.font(9),
                 width=16).grid(row=0, column=1, sticky="w", pady=2)
        self.vars["number"] = number
        if kind in ("section", "subsection"):
            tk.Label(form, text="Заголовок:", font=ui_theme.font(9),
                     anchor="w").grid(row=1, column=0, sticky="w", pady=2)
            header = tk.StringVar(value=str(item.get("header") or ""))
            tk.Entry(form, textvariable=header, font=ui_theme.font(9),
                     width=90).grid(row=1, column=1, sticky="we", pady=2)
            self.vars["header"] = header
        tk.Label(self.body, text="Текст:", font=ui_theme.font(9),
                 anchor="w").pack(fill=tk.X, padx=4)
        box = tk.Frame(self.body)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        scroll = tk.Scrollbar(box, orient="vertical")
        self.text = tk.Text(box, wrap="word", font=ui_theme.font(10),
                            yscrollcommand=scroll.set, undo=True)
        scroll.config(command=self.text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text.insert("1.0", item.get("content") or "")
        self._snapshot = {"number": str(item.get("number") or ""),
                          "content": item.get("content") or ""}
        if "header" in self.vars:
            self._snapshot["header"] = str(item.get("header") or "")
        self._pending = self._apply_text

    def _apply_text(self):
        item = self._panel_item
        if item is None:
            return False
        values = {"number": self.vars["number"].get().strip()}
        if "header" in self.vars:
            values["header"] = self.vars["header"].get().strip()
        values["content"] = self.text.get("1.0", "end-1c")
        if values == self._snapshot:
            return False
        item.update(values)
        self._snapshot = dict(values)
        return True

    # ------------------------------------------------------------- таблица
    def _render_table(self, table):
        caption = "%s %s" % (table.get("reference") or "Таблица",
                             table.get("name") or "")
        self.caption.config(text=caption.strip())
        try:
            headers, rows, note = ee.load(self.data, table)
        except ee.TableEditError as exc:
            tk.Label(self.body, text=str(exc), font=ui_theme.font(9),
                     fg=ui_theme.TEXT_MUTED, justify="left",
                     anchor="w").pack(fill=tk.X, padx=4, pady=8)
            return
        if note:
            tk.Label(self.body, text=note, font=ui_theme.font(8),
                     fg=ui_theme.TEXT_MUTED, justify="left",
                     anchor="w").pack(fill=tk.X, padx=4, pady=(0, 4))
        editable = not note
        if editable:
            tools = tk.Frame(self.body)
            tools.pack(fill=tk.X, padx=4, pady=(0, 2))
            _button(tools, "Добавить строку", self.add_row, width=18)
            _button(tools, "Удалить строку", self.delete_row, width=18)
            tk.Label(tools, text="двойной щелчок — правка ячейки",
                     font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED).pack(
                         side=tk.LEFT, padx=8)
        self._make_grid(self.body, headers, rows, editable,
                        self._apply_grid if editable else None)
        if editable:
            self._grid_table = table
            self._pending = self._apply_grid

    def _make_grid(self, parent, headers, rows, editable, apply=None):
        box = tk.Frame(parent)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        yscroll = tk.Scrollbar(box, orient="vertical")
        xscroll = tk.Scrollbar(box, orient="horizontal")
        tree = ttk.Treeview(box, show="headings", height=14,
                            yscrollcommand=yscroll.set,
                            xscrollcommand=xscroll.set)
        yscroll.config(command=tree.yview)
        xscroll.config(command=tree.xview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        columns = ["c%d" % index for index in range(len(headers))]
        tree["columns"] = columns
        for index, column in enumerate(columns):
            tree.heading(column, text=headers[index])
            width = max([len(str(headers[index]))] + [
                len(str(row[index])) for row in rows[:200]
                if index < len(row)])
            tree.column(column, width=min(420, max(90, width * 8 + 18)),
                        anchor="w", stretch=False)
        self._grid = tree
        self._grid_rows = [list(row) + [""] * (len(headers) - len(row))
                           for row in rows]
        self._grid_initial = [list(row) for row in self._grid_rows]
        self._grid_editable = editable
        self._grid_apply = apply
        self._fill_grid()
        if editable:
            tree.bind("<Double-1>", self._edit_cell)
            tree.bind("<Delete>", lambda event: self.delete_row())

    def _fill_grid(self):
        tree = self._grid
        tree.delete(*tree.get_children())
        for row in self._grid_rows:
            tree.insert("", tk.END, values=row)

    def _edit_cell(self, event):
        tree = self._grid
        if tree is None or not self._grid_editable:
            return
        if tree.identify("region", event.x, event.y) != "cell":
            return
        row_id = tree.identify_row(event.y)
        column = tree.identify_column(event.x)
        if not row_id or not column:
            return
        bbox = tree.bbox(row_id, column)
        if not bbox:
            return
        index = int(column[1:]) - 1
        row_index = tree.index(row_id)
        x, y, width, height = bbox
        entry = tk.Entry(tree, font=ui_theme.font(9), relief=tk.SOLID,
                         borderwidth=1)
        entry.insert(0, self._grid_rows[row_index][index])
        entry.select_range(0, tk.END)
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        state = {"done": False}

        def finish(save):
            if state["done"]:
                return
            state["done"] = True
            value = entry.get()
            entry.destroy()
            if not save:
                return
            self._grid_rows[row_index][index] = value
            if tree.exists(row_id):
                tree.set(row_id, column, value)
            self._pending = self._grid_apply

        entry.bind("<Return>", lambda event: finish(True))
        entry.bind("<FocusOut>", lambda event: finish(True))
        entry.bind("<Escape>", lambda event: finish(False))

    def add_row(self):
        if self._grid is None or not self._grid_editable:
            return
        count = len(self._grid["columns"])
        index = len(self._grid_rows)
        selected = self._grid.selection()
        if selected:
            index = self._grid.index(selected[-1]) + 1
        self._grid_rows.insert(index, [""] * count)
        self._fill_grid()
        children = self._grid.get_children()
        if index < len(children):
            self._grid.selection_set(children[index])
            self._grid.see(children[index])
        self._pending = self._grid_apply

    def delete_row(self):
        if self._grid is None or not self._grid_editable:
            return
        selected = self._grid.selection()
        if not selected:
            return
        for row_id in sorted(selected, key=self._grid.index, reverse=True):
            del self._grid_rows[self._grid.index(row_id)]
        self._fill_grid()
        self._pending = self._grid_apply

    def _apply_grid(self):
        if self._grid_table is None or not self._grid_editable:
            return False
        if self._grid_rows == self._grid_initial:
            return False
        ee.save(self.data, self._grid_table, self._grid_rows)
        self._grid_initial = [list(row) for row in self._grid_rows]
        return True

    # --------------------------------------------------------------- шкаф
    def _render_cabinet(self, item):
        self.caption.config(text="Шкаф %s — %s"
                            % (item.get("cypher", ""), item.get("name", "")))
        self._panel_item = item
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=(2, 4))
        form.columnconfigure(1, weight=1)
        row = 0
        for key, label, width in _CABINET_FIELDS:
            tk.Label(form, text=label + ":", font=ui_theme.font(9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(item.get(key) or ""))
            tk.Entry(form, textvariable=var, font=ui_theme.font(9),
                     width=width).grid(row=row, column=1, sticky="we", pady=2)
            self.vars[key] = var
            row += 1
        tk.Label(form, text="Описание:", font=ui_theme.font(9),
                 anchor="w").grid(row=row, column=0, sticky="nw", pady=2)
        self.description = tk.Text(form, height=5, wrap="word",
                                   font=ui_theme.font(9))
        self.description.grid(row=row, column=1, sticky="we", pady=2)
        self.description.insert("1.0", item.get("description") or "")
        row += 1

        tk.Label(self.body, text="Вводы питания:", font=ui_theme.font(9),
                 anchor="w").pack(fill=tk.X, padx=4, pady=(6, 2))
        tools = tk.Frame(self.body)
        tools.pack(fill=tk.X, padx=4)
        _button(tools, "Добавить строку", self.add_row, width=18)
        _button(tools, "Удалить строку", self.delete_row, width=18)
        rows = [[supply.get("purpose", "")]
                for supply in item.get("power_supplies") or []]
        self._make_grid(self.body, ["Назначение"], rows, True,
                        self._apply_cabinet)

        self._snapshot = {
            "fields": {key: str(item.get(key) or "") for key, _l, _w
                       in _CABINET_FIELDS},
            "description": item.get("description") or "",
            "rows": [list(row) for row in self._grid_rows],
        }
        self._pending = self._apply_cabinet

    def _apply_cabinet(self):
        item = self._panel_item
        if item is None:
            return False
        fields = {key: var.get().strip() for key, var in self.vars.items()}
        description = self.description.get("1.0", "end-1c")
        rows = [list(row) for row in self._grid_rows]
        if (fields == self._snapshot["fields"]
                and description == self._snapshot["description"]
                and rows == self._snapshot["rows"]):
            return False
        old = item.get("power_supplies") or []
        supplies = []
        for index, row in enumerate(rows):
            purpose = str(row[0] if row else "").strip()
            if not purpose:
                continue
            supply = dict(old[index]) if index < len(old) else {}
            supply["purpose"] = purpose
            supplies.append(supply)
        item.update(fields)
        item["description"] = description
        item["power_supplies"] = supplies
        self._snapshot = {"fields": dict(fields), "description": description,
                          "rows": [list(row) for row in rows]}
        return True

    # ------------------------------------------------------------ комплект
    def _render_kit(self, kit):
        self.caption.config(text="Комплект %s" % kit.get("number", ""))
        self._panel_item = kit
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=4)
        form.columnconfigure(1, weight=1)
        row = 0
        for key, label, width in _KIT_FIELDS:
            tk.Label(form, text=label + ":", font=ui_theme.font(9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(kit.get(key) or ""))
            tk.Entry(form, textvariable=var, font=ui_theme.font(9),
                     width=width).grid(row=row, column=1, sticky="we", pady=2)
            self.vars[key] = var
            row += 1
        self._snapshot = {key: str(kit.get(key) or "")
                          for key, _l, _w in _KIT_FIELDS}
        self._pending = self._apply_kit

    def _apply_kit(self):
        item = self._panel_item
        if item is None:
            return False
        values = {key: var.get().strip() for key, var in self.vars.items()}
        if values == self._snapshot:
            return False
        item.update(values)
        self._snapshot = dict(values)
        return True

    # -------------------------------------------------------------- рисунок
    def _render_figure(self, figure):
        self.caption.config(text="Рисунок %s" % figure.get("number", ""))
        self._panel_item = figure
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=4)
        form.columnconfigure(1, weight=1)
        fields = (("number", "Номер", 16), ("name", "Наименование", 70),
                  ("reference", "Ссылка", 24))
        for row, (key, label, width) in enumerate(fields):
            tk.Label(form, text=label + ":", font=ui_theme.font(9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(figure.get(key) or ""))
            tk.Entry(form, textvariable=var, font=ui_theme.font(9),
                     width=width).grid(row=row, column=1, sticky="we", pady=2)
            self.vars[key] = var
        self._snapshot = {key: str(figure.get(key) or "")
                          for key, _l, _w in fields}
        self._pending = self._apply_figure

    def _apply_figure(self):
        item = self._panel_item
        if item is None:
            return False
        values = {key: var.get().strip() for key, var in self.vars.items()}
        if values == self._snapshot:
            return False
        item.update(values)
        self._snapshot = dict(values)
        self.caption.config(text="Рисунок %s" % values["number"])
        return True

    # ----------------------------------------------------------------- ИЭУ
    def _render_ied(self, ied):
        self.caption.config(text="ИЭУ %s" % ied.get("number", ""))
        self._panel_item = ied
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=(2, 4))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Номер ИЭУ:", font=ui_theme.font(9),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        number = tk.StringVar(value=str(ied.get("number") or ""))
        tk.Entry(form, textvariable=number, font=ui_theme.font(9),
                 width=18).grid(row=0, column=1, sticky="w", pady=2)
        self.vars["number"] = number

        tk.Label(self.body, text="Цифровые порты:", font=ui_theme.font(9),
                 anchor="w").pack(fill=tk.X, padx=4, pady=(6, 2))
        tools = tk.Frame(self.body)
        tools.pack(fill=tk.X, padx=4)
        _button(tools, "Добавить строку", self.add_row, width=18)
        _button(tools, "Удалить строку", self.delete_row, width=18)
        rows = [[port.get("description", "")]
                for port in ied.get("ports") or []]
        self._make_grid(self.body, ["Описание порта"], rows, True,
                        self._apply_ied)
        self._snapshot = {
            "number": str(ied.get("number") or ""),
            "rows": [list(row) for row in self._grid_rows],
        }
        self._pending = self._apply_ied

    def _apply_ied(self):
        item = self._panel_item
        if item is None:
            return False
        number = self.vars["number"].get().strip()
        rows = [list(row) for row in self._grid_rows]
        if number == self._snapshot["number"] and rows == self._snapshot["rows"]:
            return False
        old = item.get("ports") or []
        ports = []
        for index, row in enumerate(rows):
            description = str(row[0] if row else "").strip()
            if not description:
                continue
            port = dict(old[index]) if index < len(old) else {}
            port["description"] = description
            ports.append(port)
        item["number"] = number
        item["ports"] = ports
        self._snapshot = {"number": number,
                          "rows": [list(row) for row in rows]}
        return True

    # --------------------------------------------------- структура дерева
    def _ask(self, prompt, initial=""):
        return simpledialog.askstring("Редактор стандарта", prompt,
                                      initialvalue=str(initial or ""),
                                      parent=self)

    def _find_iid(self, item):
        if item is None:
            return None
        for iid, node in self._nodes.items():
            if any(value is item for value in node[1:]):
                return iid
        return None

    def _child_container(self, parent_iid, kind):
        owner = self._owners.get(parent_iid)
        item = owner[1] if owner else None
        return st.child_list(self.data, item, kind)

    def _figure_base(self, parent_iid):
        iid = parent_iid
        while iid:
            node = self._nodes.get(iid)
            if node and node[0] == "text" and node[1] == "section":
                number = str(node[2].get("number") or "").strip()
                return number + "." if number else ""
            owner = self._owners.get(iid)
            iid = owner[2] if owner else None
        return ""

    def _mutate(self, action, select_item=None):
        """Применить правки панели, изменить данные и перестроить дерево."""
        if not self._apply_pending():
            return
        try:
            created = action()
        except st.StructureError as exc:
            messagebox.showerror("Редактор стандарта", str(exc), parent=self)
            return
        self._changed = True
        self._update_title()
        self._switching = True
        self._fill_tree()
        self._switching = False
        target = created if select_item is None else select_item
        iid = self._find_iid(target)
        if iid is None and self._meta_iid and self.tree.exists(self._meta_iid):
            iid = self._meta_iid
        if iid:
            self._switching = True
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
            self._switching = False
            self._current_node = iid
            self._render(self._nodes.get(iid))

    def _add_section(self, parent_iid):
        container = self._child_container(parent_iid, "section")
        suggested = st.new_section(self.data)
        number = self._ask("Номер раздела", suggested["number"])
        if number is None:
            return
        header = self._ask("Заголовок раздела", suggested["header"])
        if header is None:
            return

        def action():
            item = st.new_section(self.data, number=number.strip(),
                                  header=header.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_subsection(self, parent_iid):
        section = self._owners[parent_iid][1]
        container = self._child_container(parent_iid, "subsection")
        suggested = st.new_subsection(self.data, section)
        number = self._ask("Номер подраздела", suggested["number"])
        if number is None:
            return
        header = self._ask("Заголовок подраздела", suggested["header"])
        if header is None:
            return

        def action():
            item = st.new_subsection(self.data, section,
                                     number=number.strip(),
                                     header=header.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_clause(self, parent_iid):
        container_node = self._owners[parent_iid][1]
        container = self._child_container(parent_iid, "clause")
        suggested = st.new_clause(self.data, container_node)
        number = self._ask("Номер пункта", suggested["number"])
        if number is None:
            return

        def action():
            item = st.new_clause(self.data, container_node,
                                 number=number.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_figure(self, parent_iid):
        container = self._child_container(parent_iid, "figure")
        name = self._ask("Наименование рисунка", "Новый рисунок")
        if name is None:
            return

        def action():
            item = st.new_figure(self.data, container, name=name.strip(),
                                 base=self._figure_base(parent_iid))
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_table(self, parent_iid):
        container = self._child_container(parent_iid, "table")
        spec = ask_table_spec(self, self.data)
        if spec is None:
            return

        def action():
            item = st.new_table(self.data, spec)
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_cabinet(self, parent_iid):
        container = self._child_container(parent_iid, "cabinet")
        cypher = self._ask("Шифр шкафа", "Новый шкаф")
        if cypher is None:
            return
        name = self._ask("Наименование шкафа", "")
        if name is None:
            return

        def action():
            item = st.new_cabinet(self.data, cypher=cypher.strip(),
                                  name=name.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_kit(self, parent_iid):
        cabinet = self._owners[parent_iid][1]
        container = self._child_container(parent_iid, "kit")
        suggested = st.new_kit(self.data, cabinet)
        number = self._ask("Номер комплекта", suggested["number"])
        if number is None:
            return

        def action():
            item = st.new_kit(self.data, cabinet, number=number.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    def _add_ied(self, parent_iid):
        kit = self._owners[parent_iid][1]
        container = self._child_container(parent_iid, "ied")
        suggested = st.new_ied(self.data, kit)
        number = self._ask("Номер ИЭУ", suggested["number"])
        if number is None:
            return

        def action():
            item = st.new_ied(self.data, kit, number=number.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    def _delete_node(self, iid):
        owner = self._owners.get(iid)
        node = self._nodes.get(iid)
        if not owner or not node:
            return
        container, item, parent_iid = owner
        kind = node[1] if node[0] == "text" else node[0]
        if kind not in ("section", "subsection", "clause", "table",
                        "figure", "cabinet", "kit", "ied"):
            return
        issues = st.delete_issues(self.data, item, kind)
        if issues:
            messagebox.showwarning("Редактор стандарта", "\n".join(issues),
                                   parent=self)
            return
        label = {"section": "раздел", "subsection": "подраздел",
                 "clause": "пункт", "table": "таблицу",
                 "figure": "рисунок", "cabinet": "шкаф",
                 "kit": "комплект", "ied": "ИЭУ"}[kind]
        count = st.descendant_count(item) if isinstance(item, dict) else 0
        message = "Удалить %s?" % label
        if count:
            message += "\nВнутри %d узел(ов) — они будут удалены." % count
        if not messagebox.askyesno("Редактор стандарта", message,
                                   parent=self):
            return
        parent_item = (self._owners[parent_iid][1]
                       if parent_iid in self._owners else None)

        def action():
            st.remove(container, item)
            return None

        self._mutate(action, select_item=parent_item)

    # -------------------------------------------------- контекстное меню
    def _menu_items(self, iid, node):
        kind = node[0]
        if kind == "root":
            if node[1] == "doc":
                return [("Добавить раздел…", lambda: self._add_section(iid))]
            return [("Добавить шкаф…", lambda: self._add_cabinet(iid))]
        if kind == "meta":
            return []
        if kind == "text":
            if node[1] == "section":
                return [
                    ("Добавить подраздел…",
                     lambda: self._add_subsection(iid)),
                    ("Добавить пункт…", lambda: self._add_clause(iid)),
                    ("Добавить таблицу…", lambda: self._add_table(iid)),
                    ("Добавить рисунок…", lambda: self._add_figure(iid)),
                    None,
                    ("Удалить раздел", lambda: self._delete_node(iid)),
                ]
            if node[1] == "subsection":
                return [
                    ("Добавить пункт…", lambda: self._add_clause(iid)),
                    ("Добавить таблицу…", lambda: self._add_table(iid)),
                    ("Добавить рисунок…", lambda: self._add_figure(iid)),
                    None,
                    ("Удалить подраздел", lambda: self._delete_node(iid)),
                ]
            return [
                ("Добавить таблицу…", lambda: self._add_table(iid)),
                ("Добавить рисунок…", lambda: self._add_figure(iid)),
                None,
                ("Удалить пункт", lambda: self._delete_node(iid)),
            ]
        if kind == "cabinet":
            return [("Добавить комплект…", lambda: self._add_kit(iid)),
                    None, ("Удалить шкаф", lambda: self._delete_node(iid))]
        if kind == "kit":
            return [("Добавить ИЭУ…", lambda: self._add_ied(iid)),
                    None, ("Удалить комплект", lambda: self._delete_node(iid))]
        if kind == "table":
            return [("Удалить таблицу", lambda: self._delete_node(iid))]
        if kind == "figure":
            return [("Удалить рисунок", lambda: self._delete_node(iid))]
        return [("Удалить ИЭУ", lambda: self._delete_node(iid))]

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self._nodes:
            return
        if iid != self._current_node:
            if not self._apply_pending():
                return
            self._switching = True
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self._switching = False
            self._current_node = iid
            self._render(self._nodes.get(iid))
        node = self._nodes.get(iid)
        if not node:
            return
        items = self._menu_items(iid, node)
        if not items:
            return
        menu = tk.Menu(self, tearoff=0)
        for entry in items:
            if entry is None:
                menu.add_separator()
            else:
                menu.add_command(label=entry[0], command=entry[1],
                                 font=ui_theme.font(9))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------- запись
    def _apply_pending(self):
        """Записать правки текущей панели в данные; False — не удалось."""
        function, self._pending = self._pending, None
        if function is None:
            return True
        try:
            changed = function()
        except ee.TableEditError as exc:
            self._pending = function
            messagebox.showerror("Редактор стандарта", str(exc), parent=self)
            return False
        if changed:
            self._changed = True
            self._update_title()
        return True

    def apply(self):
        if self._apply_pending():
            self.status.config(text="Правки применены (в памяти)")

    def save(self, event=None):
        if not self._apply_pending():
            return
        try:
            size = es.save(self.data, self.path)
        except OSError as exc:
            messagebox.showerror("Редактор стандарта",
                                 "Не удалось записать файл:\n%s" % exc,
                                 parent=self)
            return
        self._changed = False
        self._update_title()
        problems = es.validate(self.data)
        text = "Сохранено: %s (%d КБ)" % (os.path.basename(self.path),
                                          size // 1024)
        if problems:
            text += " — проблем: %d" % len(problems)
        self.status.config(text=text)
        if self.on_saved:
            try:
                self.on_saved(self.path)
            except Exception:                          # noqa: BLE001
                pass

    def reload(self):
        if self._changed and not messagebox.askyesno(
                "Редактор стандарта",
                "Изменения не сохранены. Перечитать файл?", parent=self):
            return
        try:
            self.data = es.load(self.path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Редактор стандарта",
                                 "Не удалось прочитать файл:\n%s" % exc,
                                 parent=self)
            return
        self._changed = False
        self._pending = None
        self._update_title()
        self._fill_tree()
        self.status.config(text="Файл перечитан")

    def check(self):
        if not self._apply_pending():
            return
        problems = es.validate(self.data)
        if not problems:
            messagebox.showinfo("Редактор стандарта",
                                "Структура в порядке: все таблицы находят "
                                "свои шкафы, наборы данных полны.",
                                parent=self)
            self.status.config(text="Проверка: проблем нет")
            return
        messagebox.showwarning(
            "Редактор стандарта",
            "Найдено проблем: %d\n\n%s" % (len(problems),
                                           "\n".join(problems[:15])),
            parent=self)
        self.status.config(text="Проверка: проблем %d" % len(problems))

    def close(self):
        if self._changed:
            answer = messagebox.askyesnocancel(
                "Редактор стандарта",
                "Сохранить изменения перед закрытием?", parent=self)
            if answer is None:
                return
            if answer:
                self.save()
                if self._changed:
                    return
        self.destroy()

    def _update_title(self):
        mark = " *" if self._changed else ""
        self.title("Редактор стандарта — %s%s"
                   % (os.path.basename(self.path), mark))
        self.file_label.config(text=os.path.basename(self.path) + mark)


# ---------------------------------------------------------------------------
# Диалог новой таблицы
# ---------------------------------------------------------------------------
class TableDialog(tk.Toplevel):
    """Выбор вида таблицы: документа или таблицы шкафа с видом данных."""

    def __init__(self, parent, data):
        super().__init__(parent)
        self.spec = None
        self._data = data
        self._kinds = [(st.kind_name(kind), kind)
                       for _needle, kind in es.KINDS]
        self._suggested_name = ""
        self.title("Новая таблица")
        self.transient(parent)
        self.resizable(False, False)
        self._build()
        self._place_on_parent(parent)
        self.bind("<Escape>", lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _place_on_parent(self, parent):
        if isinstance(parent, tk.Misc):
            _place_on_parent(self, parent)

    def _build(self):
        form = tk.Frame(self)
        form.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        form.columnconfigure(1, weight=1)

        self.mode = tk.IntVar(value=0)
        row = 0
        tk.Label(form, text="Вид таблицы:", font=ui_theme.font(9),
                 anchor="w").grid(row=row, column=0, sticky="w", pady=3)
        choice = tk.Frame(form)
        choice.grid(row=row, column=1, sticky="w", pady=3)
        tk.Radiobutton(choice, text="Документ", variable=self.mode, value=0,
                       font=ui_theme.font(9),
                       command=self._on_mode).pack(side=tk.LEFT)
        tk.Radiobutton(choice, text="Шкаф", variable=self.mode, value=1,
                       font=ui_theme.font(9),
                       command=self._on_mode).pack(side=tk.LEFT, padx=(10, 0))
        row += 1

        self.name = tk.StringVar()
        self.number = tk.StringVar()
        self.reference = tk.StringVar()
        self.headers = tk.StringVar(value="Колонка 1; Колонка 2")
        fields = (("Наименование:", self.name),
                  ("Номер:", self.number),
                  ("Ссылка:", self.reference),
                  ("Колонки (через ;):", self.headers))
        for label, variable in fields:
            tk.Label(form, text=label, font=ui_theme.font(9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            tk.Entry(form, textvariable=variable, font=ui_theme.font(9),
                     width=46).grid(row=row, column=1, sticky="we", pady=3)
            row += 1
        self.headers_label = form.grid_slaves(row=row - 1, column=0)[0]
        self.headers_entry = form.grid_slaves(row=row - 1, column=1)[0]

        self.cabinet_label = tk.Label(form, text="Шкаф:",
                                      font=ui_theme.font(9), anchor="w")
        self.cabinet = ttk.Combobox(form, state="readonly", width=43,
                                    font=ui_theme.font(9))
        self.cabinet["values"] = [item.get("cypher", "")
                                  for item in es.cabinets(self._data)]
        self.kind_label = tk.Label(form, text="Вид данных:",
                                   font=ui_theme.font(9), anchor="w")
        self.kind = ttk.Combobox(form, state="readonly", width=43,
                                 font=ui_theme.font(9))
        self.kind["values"] = [label for label, _kind in self._kinds]
        for label, widget in ((self.cabinet_label, self.cabinet),
                              (self.kind_label, self.kind)):
            label.grid(row=row, column=0, sticky="w", pady=3)
            widget.grid(row=row, column=1, sticky="we", pady=3)
            row += 1
        self.kind.bind("<<ComboboxSelected>>", self._on_kind)
        if self.cabinet["values"]:
            self.cabinet.current(0)
        self._on_mode()

        buttons = tk.Frame(form)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        _button(buttons, "Отмена", self.destroy, width=10, side=tk.RIGHT)
        _button(buttons, "Добавить", self._ok, width=12, side=tk.RIGHT)

    def _on_mode(self):
        cabinet = self.mode.get() == 1
        state = "readonly" if cabinet else "disabled"
        self.cabinet.config(state=state)
        self.kind.config(state=state)
        entry_state = "disabled" if cabinet else "normal"
        self.headers_entry.config(state=entry_state)
        if cabinet and self.kind.get() == "" and self.kind["values"]:
            self.kind.current(0)
            self._on_kind()

    def _on_kind(self, event=None):
        label = self.kind.get()
        kind = next((value for text, value in self._kinds if text == label),
                    None)
        if kind is None:
            return
        suggestion = st.kind_name(kind)
        if not self.name.get() or self.name.get() == self._suggested_name:
            self.name.set(suggestion)
        self._suggested_name = suggestion
        number = self.number.get().strip()
        if not number:
            self.number.set(next_number_suggestion(self._data))

    def _ok(self):
        spec = {"name": self.name.get().strip(),
                "number": self.number.get().strip(),
                "reference": self.reference.get().strip()}
        if self.mode.get() == 1:
            label = self.kind.get()
            kind = next((value for text, value in self._kinds
                         if text == label), None)
            if not self.cabinet.get() or kind is None:
                messagebox.showwarning("Новая таблица",
                                       "Выберите шкаф и вид данных.",
                                       parent=self)
                return
            spec.update(cabinet=self.cabinet.get(), kind=kind)
        else:
            headers = [part.strip() for part in self.headers.get().split(";")
                       if part.strip()]
            if not spec["name"] or not headers:
                messagebox.showwarning(
                    "Новая таблица",
                    "Укажите наименование и хотя бы одну колонку.",
                    parent=self)
                return
            spec["headers"] = headers
        self.spec = spec
        self.destroy()


def next_number_suggestion(data):
    """Предлагаемый номер для новой таблицы стандарта."""
    return st.next_number(es.iter_tables(data))


def ask_table_spec(parent, data):
    """Показать диалог и вернуть спецификацию таблицы или None."""
    dialog = TableDialog(parent, data)
    parent.wait_window(dialog)
    return dialog.spec


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def show(path, parent=None, on_saved=None):
    """Открыть редактор стандарта."""
    if not path:
        raise ValueError("не указан файл стандарта")
    return StandardEditorWindow(path, parent, on_saved)
