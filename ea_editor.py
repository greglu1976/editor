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

import json
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import ea_catalog as ec
import ea_edit as ee
import ea_merge as em
import ea_report as er
import ea_schema as sc
import ea_standard as es
import ea_structure as st
import komplekts
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


def choose_item(parent, items, title, label, describe):
    """Выбор одной записи из списка: поиск, подпись и описание."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)

    find = tk.Frame(dialog)
    find.pack(fill=tk.X, padx=10, pady=(8, 4))
    tk.Label(find, text="Поиск:", font=ui_theme.font(9)).pack(side=tk.LEFT)
    query = tk.StringVar()
    tk.Entry(find, textvariable=query, width=42,
             font=ui_theme.font(9)).pack(side=tk.LEFT, padx=(6, 0))

    frame = tk.Frame(dialog)
    frame.pack(fill=tk.BOTH, expand=True, padx=10)
    listbox = tk.Listbox(frame, width=76, height=14, activestyle="dotbox",
                         exportselection=False, font=ui_theme.font(9))
    scroll = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scroll.set)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    info = tk.Label(dialog, text="", anchor="w", justify="left",
                    wraplength=560, font=ui_theme.font(9))
    info.pack(fill=tk.X, padx=10, pady=6)

    state = {"visible": list(items)}
    result = {"value": None}

    def haystack_of(item):
        parts = [str(item.get(key) or "") for key in (
            "name", "desc", "code", "cabinet_code", "cabinet_name",
            "cabinet_group", "title", "group", "standard_title",
            "label", "hint",
        )]
        for key in ("functions", "its_functions"):
            value = item.get(key) or []
            if isinstance(value, str):
                parts.append(value)
            else:
                parts.extend(str(part) for part in value)
        return " ".join(parts).lower()

    def refresh():
        needle = query.get().strip().lower()
        visible = []
        for item in items:
            if needle and needle not in haystack_of(item):
                continue
            visible.append(item)
        state["visible"] = visible
        listbox.delete(0, "end")
        for item in visible:
            listbox.insert("end", label(item))
        if visible:
            listbox.selection_clear(0, "end")
            listbox.selection_set(0)
            listbox.activate(0)
            info.config(text=describe(visible[0]))
        else:
            info.config(text="Ничего не найдено.")

    def on_select(event=None):
        selection = listbox.curselection()
        if selection:
            info.config(text=describe(state["visible"][selection[0]]))

    def accept(event=None):
        selection = listbox.curselection()
        if not selection:
            return
        result["value"] = state["visible"][selection[0]]
        dialog.destroy()

    buttons = tk.Frame(dialog)
    buttons.pack(fill=tk.X, padx=10, pady=(0, 8))
    tk.Button(buttons, text="Отмена", width=10,
              command=dialog.destroy,
              font=ui_theme.font(9)).pack(side=tk.RIGHT)
    tk.Button(buttons, text="Добавить", width=12,
              command=accept,
              font=ui_theme.font(9)).pack(side=tk.RIGHT, padx=(0, 6))

    listbox.bind("<<ListboxSelect>>", on_select)
    listbox.bind("<Double-Button-1>", accept)
    dialog.bind("<Return>", accept)
    dialog.bind("<Escape>", lambda event: dialog.destroy())
    query.trace_add("write", lambda *args: refresh())
    refresh()
    _place_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window(dialog)
    return result["value"]


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
    ("identical", "Идентичны (группа)", 24),
)

_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

#: Узлы дерева, для которых панель строится целиком по схеме structure2.
_GENERIC_KINDS = ("block", "function", "slot", "setting", "parameter",
                 "fb_entry")

#: Узлы функциональной модели, которые можно дублировать целиком.
_DUPLICATE_KINDS = ("block", "function", "slot", "setting", "parameter",
                    "fb_entry")

#: Вид узла → ключ коллекции и класс схемы для добавления потомка.
_GENERIC_CHILD = {
    "block": ("function_blocks", "FunctionBlock", "блок"),
    "function": ("functions", "Function", "функцию"),
    "slot": (None, "Input", "вход"),
    "setting": ("settings", "Setting", "уставку"),
    "parameter": ("parameters", "Parameter", "параметр"),
}


def _replace_strings(node, old, new):
    """Заменить ``old`` на ``new`` во всех строках структуры данных."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                if old in value:
                    node[key] = value.replace(old, new)
            else:
                _replace_strings(value, old, new)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                if old in value:
                    node[index] = value.replace(old, new)
            else:
                _replace_strings(value, old, new)


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
        self._clipboard = None        # (вид, контейнер, узел) для копии
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
        self.tree = ttk.Treeview(left, show="tree", selectmode="extended",
                                 yscrollcommand=scroll.set)
        scroll.config(command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Delete>", lambda event: self._delete_selection())
        self.tree.bind("<Control-d>",
                       lambda event: self._duplicate_selection())
        self.tree.bind("<Control-c>", self._copy_node)
        self.tree.bind("<Control-v>", self._paste_node)
        # Перетаскивание мышью: разделы, подразделы, таблицы и рисунки.
        self.tree.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._on_drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_drag_end, add="+")
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
            self._add_items(node, section)
            subsections = section.setdefault("subsections", [])
            for sub in subsections:
                title = "%s %s" % (sub.get("number", ""),
                                   sub.get("header", ""))
                sub_node = self.tree.insert(node, tk.END,
                                            text=title.strip(), open=False)
                self._register_node(sub_node, ("text", "subsection", sub),
                               subsections, sub, node)
                self._add_items(sub_node, sub)

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
                    self._add_function_tree(ied_node, ied)

        # Плоский каталог функциональных блоков — отдельный модуль стандарта,
        # откуда блоки берутся прямо на схему (вместе с принадлежностью).
        fbs = self.tree.insert(root, tk.END, text="Функциональные блоки",
                               open=True)
        # Каталог может ещё не существовать в JSON: материализуем его в
        # памяти один раз, чтобы записи были доступны для правки. Пустой
        # список, оставленный пользователем, не восстанавливаем заново.
        if "functional_blocks" not in self.data:
            es.rebuild_functional_blocks(self.data)
        fb_list = self.data.setdefault("functional_blocks", [])
        self._register_node(fbs, ("root", "fb"), fb_list, None, None)
        for entry in fb_list:
            if not isinstance(entry, dict):
                continue
            label = "%s  [%s / ИЭУ %s]" % (
                es.functional_block_label(entry),
                entry.get("cabinet") or "—", entry.get("ied") or "—")
            fb_node = self.tree.insert(fbs, tk.END, text=label, open=False)
            self._register_node(fb_node, ("fb_entry", entry), fb_list,
                                entry, fbs)
            self._add_function_nodes(
                fb_node, entry, entry.get("functions") or [])

        self._current_node = meta
        self.tree.selection_set(meta)
        self.tree.focus(meta)
        self._render(self._nodes[meta])

    def _add_function_tree(self, ied_node, ied):
        """Показать блоки, функции, входы/выходы, уставки и параметры ИЭУ."""
        blocks = ied.get("function_blocks")
        if not isinstance(blocks, list):
            blocks = ied.get("functions")
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            label = "Блок — %s" % (block.get("name")
                                   or block.get("russian_path") or "без имени")
            bnode = self.tree.insert(ied_node, tk.END, text=label)
            self._register_node(bnode, ("block", block), blocks, block,
                                ied_node)
            functions = block.setdefault("functions", [])
            self._add_function_nodes(bnode, block, functions)

    def _add_function_nodes(self, parent, owner, functions):
        """Показать функции и их сигналы/уставки/параметры под узлом."""
        for function in functions or []:
            if not isinstance(function, dict):
                continue
            flabel = "Функция — %s" % (function.get("name") or "без имени")
            fnode = self.tree.insert(parent, tk.END, text=flabel)
            self._register_node(fnode, ("function", function, owner),
                                functions, function, parent)
            for key, kind, word in (
                    ("inputs", "slot", "Вход"),
                    ("outputs", "slot", "Выход"),
                    ("settings", "setting", "Уставка"),
                    ("parameters", "parameter", "Параметр")):
                entries = function.setdefault(key, [])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    elabel = "%s — %s" % (word, entry.get("name")
                                          or "без имени")
                    enode = self.tree.insert(fnode, tk.END, text=elabel)
                    node = ((kind, entry, "in" if key == "inputs"
                             else "out") if kind == "slot"
                            else (kind, entry))
                    self._register_node(enode, node, entries, entry, fnode)

    def _add_items(self, parent, container):
        """Пункты, подпункты, таблицы и рисунки — в общем порядке документа."""
        for kind, item in st.ordered_items(container):
            if kind == "table":
                label = "%s %s" % (item.get("reference") or "Таблица",
                                   item.get("name") or "")
                node = self.tree.insert(parent, tk.END, text=label.strip())
                self._register_node(node, ("table", item),
                                    container.setdefault("tables", []),
                                    item, parent)
                self._add_table_columns(node, item)
            elif kind == "figure":
                label = "%s %s" % (item.get("reference") or "Рисунок",
                                   item.get("name") or "")
                node = self.tree.insert(parent, tk.END, text=label.strip())
                self._register_node(node, ("figure", item),
                                    container.setdefault("figures", []),
                                    item, parent)
            elif kind == "clause":
                self._tree_clause(parent, item,
                                  container.setdefault("clauses", []))
            else:
                self._tree_subclause(parent, item,
                                     container.setdefault("subclauses", []))

    def _add_table_columns(self, node, table):
        """Колонки таблицы — дочерними узлами: состав виден прямо в дереве."""
        for index, header in enumerate(es.table_headers(self.data, table)):
            title = str(header or "").strip() or "колонка %d" % (index + 1)
            column = self.tree.insert(node, tk.END, text="• %s" % title)
            self._register_node(column, ("table_column", table, index),
                                None, table, node)

    def _tree_clause(self, parent, clause, clauses):
        text = (clause.get("content") or "").split("\n")[0]
        node = self.tree.insert(
            parent, tk.END,
            text="%s %s" % (clause.get("number", ""), text[:90]))
        self._register_node(node, ("text", "clause", clause), clauses, clause,
                       parent)
        self._add_items(node, clause)

    def _tree_subclause(self, parent, subclause, subclauses):
        text = (subclause.get("content") or "").split("\n")[0]
        node = self.tree.insert(
            parent, tk.END,
            text="%s %s" % (subclause.get("number", ""), text[:90]))
        self._register_node(node, ("text", "subclause", subclause),
                            subclauses, subclause, parent)
        self._add_items(node, subclause)

    # ------------------------------------------------------------- выборка
    def _selection_iids(self):
        """Выделенные узлы дерева в порядке показа."""
        selected = set(self.tree.selection())
        order = []

        def walk(parent):
            for iid in self.tree.get_children(parent):
                if iid in selected and iid in self._nodes:
                    order.append(iid)
                walk(iid)

        walk("")
        return order

    def _node_kind(self, iid):
        """Вид узла дерева: ``section``, ``table``, ``cabinet`` и т. п."""
        node = self._nodes.get(iid)
        if not node:
            return None
        return node[1] if node[0] == "text" else node[0]

    # ------------------------------------------------------- мышь: перенос
    _DRAG_KINDS = {"section", "subsection", "clause", "subclause",
                   "table", "figure"}
    _DRAG_WORDS = {"section": "раздел", "subsection": "подраздел",
                   "clause": "пункт", "subclause": "подпункт",
                   "table": "таблица", "figure": "рисунок"}

    def _drag_kind(self, iid):
        kind = self._node_kind(iid)
        return kind if kind in self._DRAG_KINDS else None

    def _is_descendant(self, iid, ancestor):
        parent = self.tree.parent(iid)
        while parent:
            if parent == ancestor:
                return True
            parent = self.tree.parent(parent)
        return False

    @staticmethod
    def _drop_position(iid, y, box):
        """Перед/после/внутрь строки — по положению курсора в строке."""
        _x, top, _w, height = box
        if y < top + height / 3.0:
            return "before"
        if y > top + 2.0 * height / 3.0:
            return "after"
        return "into"

    def _container_for_iid(self, iid):
        """Словарь-владелец для текстового узла или таблицы/рисунка."""
        node = self._nodes.get(iid)
        if not node:
            return None
        if node[0] == "text":
            return node[2]
        if node[0] in ("table", "figure"):
            owner = self._owners.get(iid)
            return self._container_for_iid(owner[2]) if owner else None
        return None

    def _drag_destination(self, source, target, where):
        """План переноса: список с якорем или контейнер общего порядка."""
        kind = self._drag_kind(source)
        owner = self._owners.get(source)
        if not kind or not owner or owner[1] is None:
            return None
        if target == source or self._is_descendant(target, source):
            return None
        tnode = self._nodes.get(target)
        if not tnode:
            return None
        tkind = self._node_kind(target)
        towner = self._owners.get(target)

        if kind == "section":
            if tkind != "section" or not towner:
                return None
            dest, anchor = owner[0], towner[1]
            after = where != "before"
        elif kind == "subsection":
            if tkind == "subsection" and towner:
                dest, anchor = towner[0], towner[1]
                after = where != "before"
            elif tkind == "section":
                dest = tnode[2].setdefault("subsections", [])
                anchor, after = None, False
            else:
                return None
        elif kind in ("clause", "subclause"):
            # Пункт вкладывается в раздел/подраздел, подпункт — в пункт.
            parents = (("section", "subsection") if kind == "clause"
                       else ("clause",))
            if tkind == kind and towner:
                container = self._container_for_iid(towner[2])
                anchor, after = towner[1], where != "before"
            elif tkind in ("table", "figure") and towner:
                container = self._container_for_iid(towner[2])
                if container is None \
                        or self._node_kind(towner[2]) not in parents:
                    return None
                anchor, after = towner[1], where != "before"
            elif tkind in parents:
                container = tnode[2]
                anchor, after = None, False
            else:
                return None
            if container is None:
                return None
            return {"container": container, "anchor": anchor,
                    "after": after, "kind": kind,
                    "word": self._DRAG_WORDS[kind]}
        else:
            if tkind in ("table", "figure") and towner:
                container = self._container_for_iid(towner[2])
                if container is None:
                    return None
                anchor = towner[1]
                after = where != "before"
            elif tkind in ("clause", "subclause"):
                if where == "into":
                    # Внутрь пункта — в конец его собственных элементов.
                    container = tnode[2]
                    anchor, after = None, False
                else:
                    # Перед/после пункта — среди его соседей.
                    container = (self._container_for_iid(towner[2])
                                 if towner else None)
                    if container is None:
                        return None
                    anchor, after = towner[1], where == "after"
            elif tkind in ("section", "subsection"):
                container = tnode[2]
                anchor, after = None, False
            else:
                return None
            return {"container": container, "anchor": anchor,
                    "after": after, "kind": kind,
                    "word": self._DRAG_WORDS[kind]}
        return {"dest": dest, "anchor": anchor, "after": after,
                "word": self._DRAG_WORDS[kind]}

    def _on_drag_start(self, event):
        x, y = int(event.x), int(event.y)
        iid = self.tree.identify_row(y)
        if not self._drag_kind(iid):
            self._drag = None
            return
        self._drag = {"iid": iid, "x": x, "y": y,
                      "active": False, "plan": None}

    def _on_drag_motion(self, event):
        drag = getattr(self, "_drag", None)
        if not drag:
            return
        x, y = int(event.x), int(event.y)
        if not drag["active"] and abs(x - drag["x"]) \
                + abs(y - drag["y"]) < 6:
            return
        drag["active"] = True
        target = self.tree.identify_row(y)
        drag["plan"] = None
        if target:
            box = self.tree.bbox(target)
            if box:
                where = self._drop_position(target, y, box)
                drag["plan"] = self._drag_destination(drag["iid"],
                                                      target, where)
        if drag["plan"]:
            word = drag["plan"]["word"]
            self.status.config(text="Отпустите, чтобы переместить %s сюда"
                                    % word)
        else:
            self.status.config(text="Сюда перемещать нельзя")

    def _on_drag_end(self, event):
        drag = getattr(self, "_drag", None)
        self._drag = None
        if not drag or not drag.get("active"):
            return
        plan = drag.get("plan")
        if not plan:
            self.status.config(text="Перемещение отменено")
            return
        owner = self._owners.get(drag["iid"])
        if not owner or owner[1] is None:
            return
        label = self.tree.item(drag["iid"], "text")

        def action():
            if plan.get("container") is not None:
                return st.move_item(plan["kind"], owner[1], owner[0],
                                    plan["container"], plan["anchor"],
                                    plan["after"])
            return st.place_node(owner[1], owner[0], plan["dest"],
                                 plan["anchor"], plan["after"])

        self._mutate(action, select_item=owner[1])
        self.status.config(text="%s «%s» перемещён мышью"
                                % (plan["word"].capitalize(), label))

    def _on_select(self, event=None):
        if self._switching:
            return
        selection = self.tree.selection()
        if not selection:
            return
        if len(selection) > 1:
            self.status.config(
                text="Выделено узлов: %d — правый клик: перенос, копирование, "
                     "удаление" % len(selection))
        elif self.status.cget("text").startswith("Выделено узлов"):
            self.status.config(text="Ctrl+S — сохранить, Esc — закрыть")
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
        self._field_item = None
        self._field_cls = None
        self._field_keys = []
        self.vars = {}
        if not node:
            return
        kind = node[0]
        if kind in _GENERIC_KINDS:
            self._render_generic(node)
            return
        if kind == "meta":
            self._render_meta()
        elif kind == "root":
            title = {"doc": "Документ", "cabs": "Шкафы",
                     "fb": "Функциональные блоки"}.get(node[1], "")
            self.caption.config(text=title)
            tk.Label(self.body, text="Правый клик по дереву — добавить узел.",
                     font=ui_theme.font(9), fg=ui_theme.TEXT_MUTED,
                     anchor="w", justify="left").pack(fill=tk.X, padx=4,
                                                      pady=8)
        elif kind == "text":
            self._render_text(node[1], node[2])
        elif kind == "table":
            self._render_table(node[1])
        elif kind == "table_column":
            self._render_table(node[1], column=node[2])
        elif kind == "figure":
            self._render_figure(node[1])
        elif kind == "cabinet":
            self._render_cabinet(node[1])
        elif kind == "kit":
            self._render_kit(node[1])
        elif kind == "ied":
            self._render_ied(node[1])
        item = self._generic_item(node)
        if item is not None:
            self._render_fields(item, self._generic_class(node))

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
            ("title_page", "Титульный лист (DOCX)", 44),
        )
        row = 0
        for key, label, width in fields:
            tk.Label(form, text=label + ":", font=ui_theme.font(9),
                     anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(self.data.get(key) or ""))
            tk.Entry(form, textvariable=var, font=ui_theme.font(9),
                     width=width).grid(row=row, column=1, sticky="we", pady=3)
            self.vars[key] = var
            if key == "title_page":
                ttk.Button(form, text="Выбрать…",
                           command=self._pick_title_page).grid(
                               row=row, column=2, sticky="w", pady=3,
                               padx=(4, 0))
            row += 1
        tk.Label(form, text="Дата — ДД.ММ.ГГГГ; можно оставить пустой.\n"
                            "Титульный лист: DOCX открывает отчёт, дальше "
                            "идёт сгенерированный документ.",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED,
                 anchor="w", justify="left").grid(
                     row=row, column=0, columnspan=3,
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

    def _pick_title_page(self):
        """Выбрать DOCX титульного листа для сборки стандарта."""
        path = filedialog.askopenfilename(
            parent=self, title="DOCX титульного листа",
            initialdir=es.folder(),
            filetypes=[("Word", "*.docx"), ("Все файлы", "*.*")])
        if not path:
            return
        reference = path
        try:
            relative = os.path.relpath(path, es.folder())
            if not relative.startswith(".."):
                reference = relative
        except ValueError:
            pass
        self.vars["title_page"].set(reference)

    # --------------------------------------------------------------- текст
    def _render_text(self, kind, item):
        title = {"section": "Раздел", "subsection": "Подраздел",
                 "clause": "Пункт", "subclause": "Подпункт"}[kind]
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
    def _render_table(self, table, column=None):
        caption = "%s %s" % (table.get("reference") or "Таблица",
                             table.get("name") or "")
        # Выбрана колонка таблицы: показываем ту же сетку, но подписываем,
        # какая колонка открыта.
        if column is not None:
            headers = es.table_headers(self.data, table)
            title = (str(headers[column]).strip()
                     if 0 <= column < len(headers) else "")
            if title:
                caption = "%s — колонка «%s»" % (caption.strip(), title)
        self.caption.config(text=caption.strip())
        self._panel_item = table
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=(0, 4))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Номер:", font=ui_theme.font(9),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        number = tk.StringVar(value=str(table.get("number") or ""))
        tk.Entry(form, textvariable=number, font=ui_theme.font(9),
                 width=14).grid(row=0, column=1, sticky="w", pady=2)
        self.vars["number"] = number
        tk.Label(form, text="Наименование:", font=ui_theme.font(9),
                 anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        name = tk.StringVar(value=str(table.get("name") or ""))
        tk.Entry(form, textvariable=name, font=ui_theme.font(9),
                 width=90).grid(row=1, column=1, sticky="we", pady=2)
        self.vars["name"] = name
        if table.get("cabinet"):
            link = tk.Frame(form)
            link.grid(row=2, column=0, columnspan=2, sticky="we", pady=(2, 0))
            tk.Label(link, text="Данные шкафа: %s" % table.get("cabinet"),
                     font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED,
                     anchor="w").pack(side=tk.LEFT)
            _button(link, "Привязать к другому шкафу…",
                    lambda: self._rebind_table(self._current_node),
                    width=26, side=tk.RIGHT)
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
        self._pending = self._apply_table

    def _apply_table(self):
        """Записать номер, наименование и строки таблицы."""
        table = self._panel_item
        if table is None:
            return False
        changed = False
        if self._grid_apply is not None:
            changed = bool(self._grid_apply()) or changed
        number = str(self.vars["number"].get()).strip()
        name = str(self.vars["name"].get()).strip()
        old_number = str(table.get("number") or "")
        old_name = str(table.get("name") or "")
        # проверяем только изменённые поля: в данных встречаются таблицы
        # без номера и наименования, их нельзя ломать при простом открытии
        if number != old_number:
            if not number:
                raise ee.TableEditError("номер таблицы не может быть пустым")
            for other in es.iter_tables(self.data):
                if (other is not table
                        and str(other.get("number") or "") == number):
                    raise ee.TableEditError("номер таблицы уже занят: %s"
                                            % number)
        if name != old_name and table.get("cabinet"):
            if not name:
                raise ee.TableEditError(
                    "наименование таблицы не может быть пустым")
            old_kind = es.table_kind(old_name)
            new_kind = es.table_kind(name)
            if new_kind is None:
                raise ee.TableEditError(
                    "в наименовании нет вида данных (Описание, Входные "
                    "аналоговые измерения, Ряды зажимов и т. п.): "
                    "таблица шкафа станет пустой")
            if old_kind and new_kind != old_kind:
                raise ee.TableEditError(
                    "вид данных таблицы менять нельзя: форма (%s) "
                    "не совпадёт со строками шкафа" % st.kind_name(old_kind))
        if number != old_number:
            table["number"] = number
            table["reference"] = "Таблица %s" % number
            changed = True
        if name != old_name:
            table["name"] = name
            changed = True
        if changed:
            label = "%s %s" % (table.get("reference") or "Таблица", name)
            self.caption.config(text=label)
            self._refresh_label(label)
            self.status.config(text="Таблица %s сохранена в памяти" % number)
            code = str(table.get("cabinet") or "")
            mentioned = [item.get("cypher") for item in es.cabinets(self.data)
                         if item.get("cypher") and item.get("cypher") != code
                         and item.get("cypher") in name]
            if code and mentioned:
                self.status.config(
                    text="В наименовании шкаф %s, а таблица привязана к %s — "
                         "нажмите «Привязать к другому шкафу…»"
                         % (mentioned[0], code))
        return changed

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
        previous = str(self._snapshot["fields"].get("cypher") or "")
        code = fields["cypher"]
        if not code:
            raise ee.TableEditError("шифр шкафа не может быть пустым")
        if code != previous and any(
                other is not item and other.get("cypher") == code
                for other in es.cabinets(self.data)):
            raise ee.TableEditError("шкаф с таким шифром уже есть: %s" % code)
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
        if code != previous:
            if previous:
                _replace_strings(item, previous, code)
                self._rebind_links(previous, code)
        label = "Шкаф %s — %s" % (fields["cypher"], fields["name"])
        self.caption.config(text=label)
        self._refresh_label(label)
        return True

    def _rebind_links(self, old, new):
        """После смены шифра шкафа обновить ссылки и подписи таблиц."""
        if not old or old == new:
            return
        count = st.rebind_tables(self.data, old, new)
        for iid, node in self._nodes.items():
            if node[0] != "table" or node[1].get("cabinet") != new:
                continue
            label = "%s %s" % (node[1].get("reference") or "Таблица",
                               node[1].get("name") or "")
            if self.tree.exists(iid):
                self.tree.item(iid, text=label.strip())
        if count:
            self.status.config(
                text="Шифр шкафа изменён, таблиц перепривязано: %d" % count)

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
        tk.Label(self.body,
                 text="Комплекты с одинаковой непустой группой считаются "
                      "идентичными: таблицы шкафа остаются рабочими, пока "
                      "в нём есть хотя бы один комплект этой группы.",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED,
                 anchor="w", justify="left").pack(fill=tk.X, padx=4, pady=(0, 6))
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
        self.caption.config(text="Комплект %s" % values["number"])
        self._refresh_label("Комплект %s — %s"
                            % (values["number"], values["description"]))
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

        # Файл схемы редактора: рисунок в документе строится по нему.
        row = len(fields)
        tk.Label(form, text="Файл схемы:", font=ui_theme.font(9),
                 anchor="w").grid(row=row, column=0, sticky="w", pady=2)
        scheme_frame = tk.Frame(form)
        scheme_frame.grid(row=row, column=1, sticky="we", pady=2)
        scheme_var = tk.StringVar(value=str(figure.get("scheme") or ""))
        self.vars["scheme"] = scheme_var
        scheme_entry = tk.Entry(scheme_frame, textvariable=scheme_var,
                                font=ui_theme.font(9))
        scheme_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scheme_entry.bind("<Return>", lambda event: self._apply_pending())
        scheme_entry.bind("<KP_Enter>", lambda event: self._apply_pending())
        _button(scheme_frame, "Выбрать…", self._pick_figure_scheme, width=10)

        # Формат и ориентация страницы рисунка в документе. Пустые значения
        # означают «как в остальном документе».
        for offset, (key, label, values) in enumerate((
                ("format", "Формат:", ["", "A5", "A4", "A3"]),
                ("orientation", "Ориентация:",
                 ["", "книжная", "альбомная"])), start=1):
            combo_row = row + offset
            tk.Label(form, text=label, font=ui_theme.font(9),
                     anchor="w").grid(row=combo_row, column=0, sticky="w",
                                      pady=2)
            combo_var = tk.StringVar(
                value=str(figure.get(key) or ""))
            combo = ttk.Combobox(form, textvariable=combo_var,
                                 values=values, width=16)
            combo.grid(row=combo_row, column=1, sticky="w", pady=2)
            self.vars[key] = combo_var
        tk.Label(self.body, font=ui_theme.font(8),
                 fg=ui_theme.TEXT_MUTED, anchor="w", justify="left",
                 text="Можно указать JSON схемы ФЛС или готовую картинку "
                      "PNG/JPEG: файл вставляется в документ изображением; "
                      "иначе выводится только подпись."
                 ).pack(fill=tk.X, padx=4, pady=(2, 4))
        self._figure_scheme_preview = tk.Canvas(
            self.body, height=self.IED_SCHEME_PREVIEW_H,
            bg=ui_theme.CANVAS, highlightthickness=1,
            highlightbackground=ui_theme.BORDER)
        self._figure_scheme_preview.pack(fill=tk.X, padx=4, pady=(0, 2))
        self._refresh_figure_scheme_preview()

        self._snapshot = {key: str(figure.get(key) or "")
                          for key, _l, _w in fields}
        self._snapshot["scheme"] = str(figure.get("scheme") or "")
        for key in ("format", "orientation"):
            self._snapshot[key] = str(figure.get(key) or "")
        self._pending = self._apply_figure

    def _figure_scheme_path(self):
        """Абсолютный путь к файлу схемы рисунка или None."""
        figure = self._panel_item
        if figure is None:
            return None
        reference = str(figure.get("scheme") or "").strip()
        if not reference:
            return None
        if os.path.isabs(reference):
            return reference if os.path.isfile(reference) else None
        path = os.path.join(es.folder(), reference)
        return path if os.path.isfile(path) else None

    def _pick_figure_scheme(self):
        """Выбор файла схемы для рисунка."""
        path = filedialog.askopenfilename(
            parent=self, title="Файл схемы для рисунка",
            initialdir=self._ied_scheme_dir(),
            filetypes=[("Схемы и изображения", "*.json;*.png;*.jpg;*.jpeg"),
                       ("Схемы редактора", "*.json"),
                       ("Изображения", "*.png;*.jpg;*.jpeg"),
                       ("Все файлы", "*.*")])
        if not path:
            return
        reference = path
        try:
            relative = os.path.relpath(path, es.folder())
            if not relative.startswith(".."):
                reference = relative
        except ValueError:
            pass
        self.vars["scheme"].set(reference)
        self._refresh_figure_scheme_preview()

    def _refresh_figure_scheme_preview(self):
        """Перерисовать предпросмотр схемы рисунка."""
        canvas = getattr(self, "_figure_scheme_preview", None)
        if canvas is None:
            return
        saved_preview = getattr(self, "_scheme_preview", None)
        saved_file = getattr(self, "_ied_scheme_file", None)
        self._scheme_preview = canvas
        self._ied_scheme_file = self._figure_scheme_path()
        try:
            self._refresh_ied_scheme_preview()
        finally:
            self._scheme_preview = saved_preview
            self._ied_scheme_file = saved_file

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
        self._refresh_label("%s %s" % (values["reference"] or "Рисунок",
                                       values["name"]))
        return True

    # ----------------------------------------------------------------- ИЭУ
    #: Высота предпросмотра схемы ФЛС в панели ИЭУ, пикселей.
    IED_SCHEME_PREVIEW_H = 220

    def _render_ied(self, ied):
        self.caption.config(text="ИЭУ %s" % ied.get("number", ""))
        self._panel_item = ied
        form = tk.Frame(self.body)
        form.pack(fill=tk.X, padx=4, pady=(2, 4))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Номер ИЭУ:", font=ui_theme.font(9),
                 anchor="w").grid(row=0, column=0, sticky="w", pady=2)
        number = tk.StringVar(value=str(ied.get("number") or ""))
        entry = tk.Entry(form, textvariable=number, font=ui_theme.font(9),
                         width=18)
        entry.grid(row=0, column=1, sticky="w", pady=2)
        entry.bind("<Return>", lambda event: self._apply_pending())
        entry.bind("<KP_Enter>", lambda event: self._apply_pending())
        self.vars["number"] = number

        # ---- ФЛС в составе ИЭУ (FunctionalLogicScheme, structure2.xml) ----
        scheme = tk.Frame(self.body)
        scheme.pack(fill=tk.X, padx=4, pady=(8, 2))
        tk.Label(scheme, text="Функционально-логическая схема:",
                 font=ui_theme.font(9, "bold"), anchor="w").pack(fill=tk.X)
        row = tk.Frame(scheme)
        row.pack(fill=tk.X, pady=(2, 0))
        scheme_var = tk.StringVar(
            value=str(ied.get("scheme") or "").strip())
        self.vars["scheme"] = scheme_var
        tk.Label(row, text="Файл схемы:", font=ui_theme.font(9),
                 anchor="w").pack(side=tk.LEFT)
        path_entry = tk.Entry(row, textvariable=scheme_var,
                              font=ui_theme.font(9))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))
        path_entry.bind("<Return>", lambda event: self._apply_pending())
        path_entry.bind("<KP_Enter>", lambda event: self._apply_pending())
        _button(row, "Выбрать…", self._pick_ied_scheme, width=10)
        buttons = tk.Frame(scheme)
        buttons.pack(fill=tk.X, pady=(4, 0))
        _button(buttons, "Создать из функций…",
                self._make_ied_scheme_from_functions, width=22)
        _button(buttons, "Открыть в редакторе…",
                self._open_ied_scheme, width=22)
        _button(buttons, "Убрать", self._clear_ied_scheme, width=8)
        self._scheme_preview = tk.Canvas(
            self.body, height=self.IED_SCHEME_PREVIEW_H,
            bg=ui_theme.CANVAS, highlightthickness=1,
            highlightbackground=ui_theme.BORDER)
        self._scheme_preview.pack(fill=tk.X, padx=4, pady=(6, 0))
        self._ied_scheme_file = self._ied_scheme_path(ied)
        self._refresh_ied_scheme_preview()

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
            "scheme": str(ied.get("scheme") or ""),
            "rows": [list(row) for row in self._grid_rows],
        }
        self._pending = self._apply_ied

    # ---------------------------------------------------------- ФЛС ИЭУ
    def _ied_scheme_path(self, ied):
        """Абсолютный путь к файлу схемы ИЭУ или None."""
        reference = str((ied or {}).get("scheme") or "").strip()
        if not reference:
            return None
        if os.path.isabs(reference):
            return reference if os.path.isfile(reference) else None
        path = os.path.join(es.folder(), reference)
        return path if os.path.isfile(path) else None

    def _ied_scheme_dir(self):
        """Папка для новых файлов схем — рядом со стандартом."""
        folder = es.folder()
        target = os.path.join(folder, "schemes")
        return target if os.path.isdir(target) else folder

    def _scheme_suggest_name(self, ied):
        """Имя файла схемы по шифру шкафа и номеру ИЭУ."""
        return "флс-%s-%s.json" % (
            (self._ied_cabinet_code() or "ИЭУ").replace(" ", "_"),
            str((ied or {}).get("number") or "1"))

    def _ied_cabinet_code(self):
        """Шифр шкафа, в котором лежит текущее ИЭУ (для имени файла)."""
        item = self._panel_item
        if item is None:
            return ""
        # iid узла ИЭУ: родитель — комплект, его родитель — шкаф.
        ied_iid = None
        for iid, node in getattr(self, "_nodes", {}).items():
            if node[0] == "ied" and node[1] is item:
                ied_iid = iid
                break
        current = ied_iid
        while current is not None:
            owner = self._owners.get(current)
            if owner is None:
                return ""
            parent_iid = owner[2]
            node = self._nodes.get(parent_iid) if parent_iid else None
            if node is not None and node[0] == "cabinet":
                return str(node[1].get("cypher") or "")
            current = parent_iid
        return ""

    def _pick_ied_scheme(self):
        """Выбор существующего файла схемы для ИЭУ."""
        path = filedialog.askopenfilename(
            parent=self, title="Файл схемы ФЛС",
            initialdir=self._ied_scheme_dir(),
            filetypes=[("Схемы и изображения", "*.json;*.png;*.jpg;*.jpeg"),
                       ("Схемы редактора", "*.json"),
                       ("Изображения", "*.png;*.jpg;*.jpeg"),
                       ("Все файлы", "*.*")])
        if not path:
            return
        reference = path
        try:
            relative = os.path.relpath(path, es.folder())
            if not relative.startswith(".."):
                reference = relative
        except ValueError:
            pass
        self.vars["scheme"].set(reference)
        self._ied_scheme_file = path if os.path.isfile(path) else None
        self._refresh_ied_scheme_preview()

    def _clear_ied_scheme(self):
        """Убрать ссылку на файл схемы у ИЭУ."""
        self.vars["scheme"].set("")
        self._ied_scheme_file = None
        self._refresh_ied_scheme_preview()

    def _make_ied_scheme_from_functions(self):
        """Сгенерировать ФЛС ИЭУ из блоков и функций (structure2)."""
        ied = self._panel_item
        if ied is None:
            return
        import logic_scheme_render as lsr
        scheme = lsr.scheme_from_ied(ied)
        initial = os.path.join(self._ied_scheme_dir(),
                               self._scheme_suggest_name(ied))
        path = filedialog.asksaveasfilename(
            parent=self, title="Куда сохранить схему ФЛС",
            initialdir=self._ied_scheme_dir(),
            initialfile=os.path.basename(initial),
            defaultextension=".json",
            filetypes=[("Схемы редактора", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(scheme, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showerror("Схема ФЛС",
                                 "Не удалось записать файл:\n%s" % exc,
                                 parent=self)
            return
        try:
            reference = os.path.relpath(path, es.folder())
            if reference.startswith(".."):
                reference = path
        except ValueError:
            reference = path
        self.vars["scheme"].set(reference)
        self._ied_scheme_file = path
        self._refresh_ied_scheme_preview()
        self._apply_pending()

    def _open_ied_scheme(self):
        """Открыть файл схемы ИЭУ в редакторе схем (новое окно)."""
        ied = self._panel_item
        path = self._ied_scheme_path(ied)
        if path and os.path.splitext(path)[1].lower() in (
                ".png", ".jpg", ".jpeg", ".bmp", ".gif"):
            messagebox.showinfo(
                "Схема ФЛС",
                "Это готовое изображение — оно вставляется в документ "
                "как есть и не открывается в редакторе схем.", parent=self)
            return
        if not path:
            messagebox.showinfo(
                "Схема ФЛС",
                "У ИЭУ нет файла схемы.\n\n"
                "Выберите существующий файл или создайте схему "
                "из функций ИЭУ.", parent=self)
            return
        # Редактор схем — отдельное приложение: запускаем новый процесс,
        # чтобы не зависеть от того, открыт ли он сейчас.
        import subprocess
        import sys
        try:
            subprocess.Popen([sys.executable,
                              os.path.join(os.path.dirname(
                                  os.path.abspath(__file__)), "main.py"),
                              path])
        except OSError as exc:
            messagebox.showerror("Схема ФЛС",
                                 "Не удалось открыть редактор:\n%s" % exc,
                                 parent=self)

    def _show_image_preview(self, canvas, path):
        """Показать готовое изображение (PNG/JPEG) в предпросмотре."""
        try:
            from PIL import Image, ImageTk
            image = Image.open(path)
            width = canvas.winfo_width() or 400
            scale = min(width / max(1, image.width),
                        self.IED_SCHEME_PREVIEW_H / max(1, image.height))
            image = image.resize((max(1, int(image.width * scale)),
                                  max(1, int(image.height * scale))))
            photo = ImageTk.PhotoImage(image)
        except Exception:
            canvas.create_text(
                canvas.winfo_width() or 400,
                self.IED_SCHEME_PREVIEW_H / 2.0,
                text="Не удалось прочитать изображение", anchor="center",
                font=ui_theme.font(9), fill=ui_theme.TEXT_MUTED)
            return
        canvas.create_image(canvas.winfo_width() or 400,
                            self.IED_SCHEME_PREVIEW_H / 2.0,
                            image=photo, anchor="center")
        canvas._scheme_photo = photo   # держать ссылку, иначе картинка исчезнет

    def _refresh_ied_scheme_preview(self):
        """Перерисовать предпросмотр схемы ФЛС в панели ИЭУ."""
        canvas = getattr(self, "_scheme_preview", None)
        if canvas is None:
            return
        canvas.delete("all")
        path = getattr(self, "_ied_scheme_file", None)
        if path and os.path.splitext(path)[1].lower() in (
                ".png", ".jpg", ".jpeg", ".bmp", ".gif"):
            self._show_image_preview(canvas, path)
            return
        if not path:
            canvas.create_text(
                canvas.winfo_width() or 400,
                self.IED_SCHEME_PREVIEW_H / 2.0,
                text="Схема не выбрана", anchor="center",
                font=ui_theme.font(9), fill=ui_theme.TEXT_MUTED)
            return
        try:
            import logic_scheme_render as lsr
            data = lsr.load(path)
            recorder = lsr.pdfexport.SceneRecorder()
            lsr.render_scene(recorder, data)
            bounds = recorder.bounds() or (0.0, 0.0, 800.0, 600.0)
        except Exception:
            canvas.create_text(
                canvas.winfo_width() or 400,
                self.IED_SCHEME_PREVIEW_H / 2.0,
                text="Не удалось прочитать схему", anchor="center",
                font=ui_theme.font(9), fill=ui_theme.TEXT_MUTED)
            return
        min_x, min_y, max_x, max_y = bounds
        width = canvas.winfo_width() or 400
        height = self.IED_SCHEME_PREVIEW_H
        margin = 6.0
        scale = min((width - 2 * margin) / max(20.0, max_x - min_x),
                    (height - 2 * margin) / max(20.0, max_y - min_y))
        offset_x = -min_x * scale + (width - (max_x - min_x) * scale) / 2.0
        offset_y = -min_y * scale + (height - (max_y - min_y) * scale) / 2.0

        class _Scaled:
            """Канва-адаптер: те же примитивы в масштабе предпросмотра."""

            def __init__(self, canvas, scale, dx, dy):
                self._canvas = canvas
                self._scale = scale
                self._dx = dx
                self._dy = dy

            def create_line(self, *coords, **kwargs):
                pts = []
                for x, y in zip(coords[0::2], coords[1::2]):
                    pts.extend((x * self._scale + self._dx,
                                y * self._scale + self._dy))
                return self._canvas.create_line(*pts, **kwargs)

            def create_rectangle(self, x1, y1, x2, y2, **kwargs):
                return self._canvas.create_rectangle(
                    x1 * self._scale + self._dx, y1 * self._scale + self._dy,
                    x2 * self._scale + self._dx, y2 * self._scale + self._dy,
                    **kwargs)

            def create_polygon(self, *coords, **kwargs):
                pts = []
                for x, y in zip(coords[0::2], coords[1::2]):
                    pts.extend((x * self._scale + self._dx,
                                y * self._scale + self._dy))
                return self._canvas.create_polygon(*pts, **kwargs)

            def create_oval(self, x1, y1, x2, y2, **kwargs):
                return self._canvas.create_oval(
                    x1 * self._scale + self._dx, y1 * self._scale + self._dy,
                    x2 * self._scale + self._dx, y2 * self._scale + self._dy,
                    **kwargs)

            def create_arc(self, x1, y1, x2, y2, **kwargs):
                return self._canvas.create_arc(
                    x1 * self._scale + self._dx, y1 * self._scale + self._dy,
                    x2 * self._scale + self._dx, y2 * self._scale + self._dy,
                    **kwargs)

            def create_text(self, x, y, **kwargs):
                return self._canvas.create_text(
                    x * self._scale + self._dx, y * self._scale + self._dy,
                    **kwargs)

        try:
            lsr.render_scene(_Scaled(canvas, scale, offset_x, offset_y), data)
        except Exception:
            canvas.delete("all")
            canvas.create_text(
                width / 2.0, height / 2.0,
                text="Не удалось нарисовать схему", anchor="center",
                font=ui_theme.font(9), fill=ui_theme.TEXT_MUTED)

    def _apply_ied(self):
        item = self._panel_item
        if item is None:
            return False
        number = self.vars["number"].get().strip()
        scheme = self.vars["scheme"].get().strip()
        rows = [list(row) for row in self._grid_rows]
        if (number == self._snapshot["number"]
                and scheme == self._snapshot["scheme"]
                and rows == self._snapshot["rows"]):
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
        item["scheme"] = scheme
        item["ports"] = ports
        self._snapshot = {"number": number, "scheme": scheme,
                          "rows": [list(row) for row in rows]}
        self.caption.config(text="ИЭУ %s" % number)
        self._refresh_label("ИЭУ %s" % number)
        return True

    # --------------------------------------------- поля по схеме structure2
    def _generic_class(self, node):
        """Класс схемы для узла дерева."""
        kind = node[0]
        if kind == "text":
            return {"section": "Section", "subsection": "Subsection",
                    "clause": "Clause",
                    "subclause": "Subclause"}.get(node[1], "Section")
        if kind == "table_column":
            return "Table"
        if kind == "slot":
            return "Output" if (len(node) > 2 and node[2] == "out") else "Input"
        return sc.KIND_CLASS.get(kind)

    def _generic_item(self, node):
        """Словарь данных, соответствующий узлу дерева."""
        if not node:
            return None
        if node[0] == "meta":
            return self.data
        if node[0] == "text":
            return node[2] if len(node) > 2 else None
        return node[1] if len(node) > 1 else None

    def _render_generic(self, node):
        """Панель узла функциональной модели: только произвольные поля."""
        item = self._generic_item(node)
        cls = self._generic_class(node)
        if not isinstance(item, dict):
            self.caption.config(text="Узел")
            return
        self._panel_item = item
        kind = node[0]
        if kind == "block":
            caption = "Блок функций — %s" % (item.get("name") or "без имени")
        elif kind == "function":
            caption = "Функция — %s" % (item.get("name") or "без имени")
        elif kind == "slot":
            caption = "%s — %s" % ("Выход" if node[2] == "out" else "Вход",
                                   item.get("name") or "без имени")
        elif kind == "setting":
            caption = "Уставка — %s" % (item.get("name") or "без имени")
        elif kind == "fb_entry":
            caption = "Функциональный блок — %s" % es.functional_block_label(item)
        else:
            caption = "Параметр — %s" % (item.get("name") or "без имени")
        self.caption.config(text=caption)
        self._render_fields(item, cls, main=True)

    def _render_fields(self, item, cls=None, main=False):
        """Список всех полей узла с правкой, добавлением и удалением."""
        if not isinstance(item, dict):
            return
        frame = ttk.LabelFrame(self.body, text="Поля узла", padding=4)
        frame.pack(fill=tk.BOTH, expand=main,
                   padx=4, pady=(2 if main else 8, 4))
        self._field_item = item
        self._field_cls = cls
        self._field_keys = []
        box = tk.Frame(frame)
        box.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(box, orient=tk.VERTICAL)
        listing = tk.Listbox(box, height=8 if not main else 16,
                             exportselection=False, font=ui_theme.font(9),
                             yscrollcommand=scroll.set)
        scroll.config(command=listing.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listing.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for key, value in item.items():
            if isinstance(value, (dict, list)):
                text = "%s: [%d]" % (sc.label(key), len(value))
            else:
                text = "%s = %s" % (sc.label(key), value)
            listing.insert(tk.END, text)
            self._field_keys.append(key)
        listing.bind("<Double-Button-1>", lambda event: self._edit_field())
        self.field_list = listing
        tools = tk.Frame(frame)
        tools.pack(fill=tk.X, pady=(4, 0))
        _button(tools, "Изменить…", self._edit_field)
        _button(tools, "Добавить поле…", self._add_field)
        _button(tools, "Удалить поле", self._delete_field)

    def _selected_field(self):
        selection = self.field_list.curselection() \
            if getattr(self, "field_list", None) else ()
        if not selection:
            messagebox.showinfo("Редактор стандарта",
                                "Выберите поле в списке.", parent=self)
            return None
        return self._field_keys[selection[0]]

    def _parse_field_value(self, key, text, current):
        """Привести введённое значение к типу существующего поля/схемы."""
        kind = sc.kind_of(self._field_cls, key)
        if isinstance(current, bool) or kind == "b":
            return text.strip().lower() in ("1", "да", "true", "yes")
        if isinstance(current, int) or kind == "i":
            try:
                return int(text.strip())
            except ValueError:
                return text
        if isinstance(current, float) or kind == "f":
            try:
                return float(text.replace(",", "."))
            except ValueError:
                return text
        if isinstance(current, (list, dict)) or kind in ("l", "d"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, type(current)) or (
                        isinstance(current, (str, int, float))
                        and kind in ("l", "d")
                        and isinstance(parsed, (list, dict))):
                    return parsed
            except ValueError:
                pass
        if kind is None and not isinstance(current, (list, dict, bool)):
            stripped = text.strip()
            if stripped.lstrip("-").isdigit():
                return int(stripped)
            try:
                return float(stripped.replace(",", "."))
            except ValueError:
                pass
        return text

    def _rerender_current(self):
        node = self._nodes.get(self._current_node)
        if node:
            self._render(node)

    def _edit_field(self):
        key = self._selected_field()
        if key is None or not self._apply_pending():
            return
        item = self._field_item
        current = item.get(key)
        if isinstance(current, (list, dict)):
            initial = json.dumps(current, ensure_ascii=False)
        else:
            initial = "" if current is None else str(current)
        value = simpledialog.askstring(
            "Поле «%s»" % sc.label(key), "Значение:",
            initialvalue=initial, parent=self)
        if value is None:
            return
        item[key] = self._parse_field_value(key, value, current)
        self._changed = True
        self._update_title()
        self._rerender_current()

    def _add_field(self):
        if not self._apply_pending():
            return
        item = self._field_item
        suggestions = sc.missing_fields(self._field_cls, item)
        key = self._ask("Имя нового поля (подсказка: %s)"
                        % (", ".join(suggestions[:4]) or "любое"),
                        suggestions[0] if suggestions else "")
        if key is None or not key.strip():
            return
        key = key.strip()
        if key in item:
            messagebox.showinfo("Редактор стандарта",
                                "Такое поле уже есть: %s" % key, parent=self)
            return
        default = sc.default_of(self._field_cls, key)
        initial = json.dumps(default, ensure_ascii=False) \
            if isinstance(default, (list, dict)) else str(default)
        value = self._ask("Значение поля «%s»" % sc.label(key), initial)
        if value is None:
            return
        item[key] = self._parse_field_value(key, value, default)
        self._changed = True
        self._update_title()
        self._rerender_current()

    def _delete_field(self):
        key = self._selected_field()
        if key is None or not self._apply_pending():
            return
        if not messagebox.askyesno(
                "Редактор стандарта",
                "Удалить поле «%s» из этого узла?" % sc.label(key),
                parent=self):
            return
        del self._field_item[key]
        self._changed = True
        self._update_title()
        self._rerender_current()

    def _refresh_label(self, text):
        """Обновить подпись текущего узла дерева после правки полей."""
        iid = self._current_node
        node = self._nodes.get(iid) if iid else None
        # У выбранной колонки подпись менять нельзя: правится-то таблица.
        if node and node[0] == "table_column":
            iid = self._find_iid(self._panel_item)
            node = self._nodes.get(iid) if iid else None
        if (node and self._panel_item is not None
                and node[-1] is self._panel_item and self.tree.exists(iid)):
            self.tree.item(iid, text=text)

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

    def _mutate(self, action, select_item=None, select_items=None):
        """Применить правки панели, изменить данные и перестроить дерево.

        Если ``action`` вернула список узлов, в дереве выделяются все они.
        Возвращает ``False``, если правку применить не удалось.
        """
        if not self._apply_pending():
            return False
        try:
            created = action()
        except (st.StructureError, AttributeError, KeyError, TypeError,
                ValueError) as exc:
            # Ошибки добавления показываем окном, а не traceback в консоли.
            messagebox.showerror("Редактор стандарта", str(exc), parent=self)
            return False
        self._changed = True
        self._update_title()
        if select_items is None:
            if isinstance(created, list):
                select_items = created
            else:
                select_items = [created if select_item is None
                                else select_item]
        self._switching = True
        self._fill_tree()
        self._switching = False
        iids = [iid for iid in (self._find_iid(item) for item in select_items)
                if iid]
        if not iids and self._meta_iid and self.tree.exists(self._meta_iid):
            iids = [self._meta_iid]
        if iids:
            self._switching = True
            self.tree.selection_set(iids)
            self.tree.focus(iids[0])
            self.tree.see(iids[0])
            self._switching = False
            self._current_node = iids[0]
            self._render(self._nodes.get(iids[0]))
        return True

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
        # new_figure ждёт владельца (dict со списком figures), а не сам
        # список: раньше сюда попадал список и добавление падало с
        # AttributeError.
        owner = self._owners[parent_iid][1]
        container = self._child_container(parent_iid, "figure")
        name = self._ask("Наименование рисунка", "Новый рисунок")
        if name is None:
            return

        def action():
            item = st.new_figure(self.data, owner, name=name.strip(),
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

    def _add_cabinets(self, parent_iid):
        """Добавить шкафы из всех стандартов (формы/рисунки перенести)."""
        if not self._apply_pending():
            return
        dialog = CabinetDialog(self, self.data)
        self.wait_window(dialog)
        if not dialog.chosen:
            return
        try:
            merged = em.merge_cabinets(self.data, dialog.chosen)
        except em.MergeError as exc:
            messagebox.showerror("Редактор стандарта", str(exc), parent=self)
            return
        self.data = merged
        self._changed = True
        self._update_title()
        self._pending = None
        self._grid = None
        self._grid_rows = []
        self._grid_initial = []
        self._grid_editable = False
        self._grid_table = None
        self._grid_apply = None
        self._panel_item = None
        self._snapshot = None
        self._switching = True
        self._fill_tree()
        self._switching = False
        codes = {em.norm_cypher(entry["cypher"]) for entry in dialog.chosen}
        target = next((iid for iid, node in self._nodes.items()
                       if node[0] == "cabinet"
                       and em.norm_cypher(node[1].get("cypher")) in codes),
                      None)
        if target and self.tree.exists(target):
            self._switching = True
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)
            self._switching = False
            self._current_node = target
            self._render(self._nodes.get(target))
        self.status.config(
            text="Добавлено шкафов: %d — формы и рисунки перенесены, "
                 "нумерация сведена" % len(dialog.chosen))

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

    def _duplicate_kit(self, iid):
        """Скопировать комплект, сохранив группу «Идентичны»."""
        owner = self._owners.get(iid)
        if not owner or owner[1] is None:
            return
        kit = owner[1]
        parent = self._owners.get(owner[2])
        cabinet = parent[1] if parent else None
        if cabinet is None:
            return

        def action():
            return st.copy_kit(kit, cabinet)

        self._mutate(action)

    def _move_kit(self, iid):
        """Перенести комплект в другой шкаф, при необходимости — таблицы."""
        owner = self._owners.get(iid)
        if not owner or owner[1] is None:
            return
        kit = owner[1]
        parent = self._owners.get(owner[2])
        cabinet = parent[1] if parent else None
        if cabinet is None:
            return
        others = [item for item in es.cabinets(self.data)
                  if item is not cabinet]
        if not others:
            messagebox.showinfo("Редактор стандарта",
                                "В стандарте нет другого шкафа.",
                                parent=self)
            return
        target = self._choose_cabinet(others, "Куда переместить комплект")
        if target is None:
            return
        source_code = str(cabinet.get("cypher") or "")
        target_code = str(target.get("cypher") or "")
        was_source = st.kit_feeds_tables(self.data, kit, cabinet)
        rebind = False
        if was_source:
            detail = ""
            if target.get("kits"):
                detail = ("\nВ шкафу %s уже есть комплекты: таблицы будут "
                          "брать данные из первого из них." % target_code)
            rebind = messagebox.askyesno(
                "Перенос комплекта",
                "Комплект %s — первый у шкафа %s, из него собираются "
                "таблицы.\nПерепривязать эти таблицы к шкафу %s?%s"
                % (kit.get("number"), source_code, target_code, detail),
                parent=self)
        replacement = None
        if was_source and not rebind:
            replacement = st.identical_replacement(self.data, kit, cabinet)
            if replacement[0] is not cabinet:
                messagebox.showwarning(
                    "Перенос комплекта",
                    "В шкафу %s нет другого комплекта с той же группой "
                    "«Идентичны». Перепривязать таблицы к шкафу %s или "
                    "отменить перенос." % (source_code, target_code),
                    parent=self)
                return

        def action():
            st.move_kit(kit, cabinet, target)
            if rebind:
                st.rebind_tables(self.data, source_code, target_code)
            elif replacement is not None and replacement[0] is not None:
                st.promote_kit(replacement[0], replacement[1])
            return kit

        if self._mutate(action, select_item=kit):
            if rebind:
                self.status.config(text="Комплект перенесён, таблицы "
                                        "привязаны к шкафу %s" % target_code)
            elif replacement is not None and replacement[0] is not None:
                self.status.config(text="Комплект перенесён, таблицы "
                                        "остались на шкафу %s (идентичный "
                                        "комплект)" % source_code)

    def _choose_typical_kit(self):
        """Выбрать типовой комплект каталога. Возвращает dict или None."""
        kits = komplekts.typical_komplekts()
        if not kits:
            messagebox.showinfo(
                "Редактор стандарта",
                "В каталоге нет типовых комплектов.", parent=self)
            return None

        def describe(kit):
            lines = ["Шкаф: " + (kit.get("cabinet_code") or "—")]
            if kit.get("functions"):
                lines.append("Функции: " + ", ".join(kit["functions"]))
            lines.append("ИЭУ: %d" % len(komplekts.effective_ieds(kit)))
            if kit.get("test_block_list"):
                lines.append("Испытательных блоков: %d"
                             % len(kit["test_block_list"]))
            return "\n".join(lines)

        return choose_item(self, kits,
                           "Типовой комплект из каталога",
                           komplekts.kit_label, describe)

    def _choose_typical_cabinet(self):
        """Выбрать типовой шкаф каталога. Возвращает dict или None."""
        existing = {em.norm_cypher(item.get("cypher"))
                    for item in es.cabinets(self.data)}
        cabinets = [cabinet for cabinet in komplekts.typical_cabinets()
                    if cabinet.get("komplets")
                    and em.norm_cypher(cabinet.get("code")) not in existing]
        if not cabinets:
            messagebox.showinfo(
                "Редактор стандарта",
                "Все типовые шкафы каталога уже есть в стандарте.",
                parent=self)
            return None

        def describe(cabinet):
            lines = ["Шифр: " + (cabinet.get("code") or "—")]
            if cabinet.get("name"):
                lines.append("Наименование: " + cabinet["name"])
            lines.append("Комплектов: %d"
                         % len(cabinet.get("komplets") or []))
            if cabinet.get("its_functions"):
                lines.append("Функции: " + ", ".join(cabinet["its_functions"]))
            return "\n".join(lines)

        return choose_item(self, cabinets,
                           "Типовой шкаф из каталога",
                           komplekts.cabinet_label, describe)

    def _add_typical_cabinet(self, parent_iid):
        """Добавить типовой шкаф каталога: карточку и таблицы-формы."""
        picked = self._choose_typical_cabinet()
        if picked is None:
            return
        before = len(es.cabinets(self.data))

        def action():
            result = em.add_catalog_cabinet(self.data, picked)
            self.data = result["data"]
            return result["cabinet"]

        self._mutate(action)
        if len(es.cabinets(self.data)) > before:
            self.status.config(
                text="Шкаф %s добавлен: карточка и таблицы-формы перенесены"
                     % (picked.get("code") or ""))

    def _add_typical_kit(self, parent_iid):
        """Добавить типовой комплект каталога в шкаф стандарта."""
        cabinet = self._owners[parent_iid][1]
        container = self._child_container(parent_iid, "kit")
        picked = self._choose_typical_kit()
        if picked is None:
            return
        kit = ec.kit_from_catalog(
            picked, number=st.next_number(cabinet.get("kits") or []))

        def action():
            st.add(container, kit)
            ec.add_test_blocks(cabinet, picked)
            return kit

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

    def _add_generic_child(self, parent_iid, kind, direction=None):
        """Добавить блок, функцию, вход/выход, уставку или параметр."""
        parent = self._owners[parent_iid][1]
        if not isinstance(parent, dict):
            return
        if kind == "slot":
            cls = "Output" if direction == "out" else "Input"
            key = "outputs" if direction == "out" else "inputs"
            word = "выход" if direction == "out" else "вход"
        else:
            key, cls, word = _GENERIC_CHILD[kind]
        container = parent.setdefault(key, [])
        if not self._apply_pending():
            return
        name = self._ask("Наименование (%s)" % word, "Новый %s" % word)
        if name is None:
            return

        def action():
            item = sc.new_node(cls, name=name.strip())
            st.add(container, item)
            return item

        self._mutate(action)

    # ----------------------------------------------- каталог функциональных блоков
    def _add_fb_entry(self, parent_iid):
        """Добавить пустую запись в каталог функциональных блоков."""
        container = self._child_container(parent_iid, "fb_entry")
        if not self._apply_pending():
            return
        name = self._ask("Наименование функционального блока",
                         "Новый функциональный блок")
        if name is None:
            return

        def action():
            entry = st.new_functional_block_entry(self.data)
            entry["name"] = name.strip()
            st.add(container, entry)
            return entry

        self._mutate(action)

    def _ied_source(self, iid):
        """Найти шкаф и комплект для узла ИЭУ по дереву редактора."""
        kit_iid = self._owners[iid][2] if iid in self._owners else None
        kit = self._owners[kit_iid][1] if kit_iid in self._owners else None
        cab_iid = self._owners[kit_iid][2] if kit_iid in self._owners else None
        cabinet = self._owners[cab_iid][1] if cab_iid in self._owners else None
        return cabinet, kit

    def _fb_from_ied(self, iid):
        """Скопировать блоки функций ИЭУ в каталог стандарта."""
        owner = self._owners.get(iid)
        ied = owner[1] if owner else None
        if not isinstance(ied, dict):
            return
        cabinet, kit = self._ied_source(iid)
        blocks = ied.get("function_blocks")
        if not isinstance(blocks, list):
            blocks = ied.get("functions") or []
        if not blocks:
            messagebox.showinfo("Каталог ФБ", "У ИЭУ нет блоков функций.",
                                parent=self)
            return
        if not messagebox.askyesno(
                "Каталог ФБ",
                "Скопировать блоков в каталог: %d?\n"
                "Блоки из шкафа останутся на месте." % len(blocks),
                parent=self):
            return
        container = self.data.setdefault("functional_blocks", [])
        cabinet_code = str((cabinet or {}).get("cypher") or "")
        kit_number = str((kit or {}).get("number") or "")
        ied_number = str(ied.get("number") or "")

        def key_of(entry):
            return (str(entry.get("cabinet") or ""),
                    str(entry.get("kit") or ""),
                    str(entry.get("ied") or ""),
                    str(entry.get("name") or ""),
                    str(entry.get("iec_name") or ""))

        known = {key_of(entry) for entry in container
                 if isinstance(entry, dict)}
        created = []
        for raw in blocks:
            entry = st.new_functional_block_entry(
                self.data, raw, cabinet_code, kit_number, ied_number)
            if key_of(entry) in known:
                continue
            known.add(key_of(entry))
            st.add(container, entry)
            created.append(entry)
        self._mutate(lambda: created)
        self.status.config(text="В каталог ФБ добавлено блоков: %d"
                                % len(created))

    def _rebuild_fb(self):
        """Пересобрать каталог блоков по текущим шкафам стандарта."""
        count = len(es.all_functional_blocks(self.data))
        if not messagebox.askyesno(
                "Каталог ФБ",
                "Пересобрать каталог (%d записей) из шкафов стандарта?\n"
                "Ручные правки записей будут заменены." % count,
                parent=self):
            return

        def action():
            total = es.rebuild_functional_blocks(self.data)
            self.status.config(text="Каталог ФБ пересобран: %d записей" % total)
            return es.all_functional_blocks(self.data)

        self._mutate(action)

    def _container_targets(self):
        """Контейнеры документа, куда можно положить таблицу или рисунок."""
        entries = []

        def add(container, title, level, section):
            number = str(container.get("number") or "").strip()
            header = (container.get("header") or container.get("content")
                      or "").strip().split("\n")[0]
            if len(header) > 70:
                header = header[:70].rstrip() + "…"
            prefix = "  " * level
            if number:
                label = "%s%s %s — %s" % (prefix, title, number, header)
            else:
                label = "%s%s — %s" % (prefix, title, header)
            entries.append({
                "label": label.strip(),
                "hint": "Таблиц: %d, рисунков: %d" % (
                    len(container.get("tables") or []),
                    len(container.get("figures") or [])),
                "container": container,
                "section": section,
            })

        for section in es.sections(self.data):
            add(section, "Раздел", 0, section)
            for clause in section.get("clauses") or []:
                add(clause, "Пункт", 1, section)
            for sub in section.get("subsections") or []:
                add(sub, "Подраздел", 1, section)
                for clause in sub.get("clauses") or []:
                    add(clause, "Пункт", 2, section)
        return entries

    @staticmethod
    def _number_base(section_number):
        """Префикс номера рисунка в разделе: «5» → «5.»."""
        number = str(section_number or "").strip()
        return number + "." if number else ""

    def _transfer(self, iids, copy=False):
        """Перенести или скопировать узлы (таблицы, рисунки) в другой раздел."""
        entries = []
        for iid in iids:
            owner = self._owners.get(iid)
            kind = self._node_kind(iid)
            if not owner or owner[1] is None:
                continue
            if kind not in ("table", "figure"):
                messagebox.showinfo(
                    "Редактор стандарта",
                    "Переносить и копировать группой можно только таблицы "
                    "и рисунки.\nРазделы, пункты, шкафы и комплекты "
                    "удаляются группой целиком.", parent=self)
                return
            entries.append({"kind": kind, "source": owner[0],
                            "item": owner[1]})
        if not entries:
            return
        targets = self._container_targets()
        if not targets:
            messagebox.showinfo("Редактор стандарта",
                                "В стандарте нет разделов для переноса.",
                                parent=self)
            return
        if len(entries) == 1:
            title = "%s %s" % (
                "Куда скопировать" if copy else "Куда перенести",
                "таблицу" if entries[0]["kind"] == "table" else "рисунок")
        else:
            title = "%s выделенное (%d)" % (
                "Куда скопировать" if copy else "Куда перенести",
                len(entries))
        target = choose_item(self, targets, title,
                             lambda entry: entry["label"],
                             lambda entry: entry["hint"])
        if target is None:
            return
        container = target["container"]
        section_number = target["section"].get("number")
        number = None
        if copy and len(entries) == 1 and entries[0]["kind"] == "table":
            # одну таблицу нумеруем вручную, как и раньше
            number = simpledialog.askstring(
                "Копирование таблицы", "Номер новой таблицы:",
                initialvalue=st.next_table_number(self.data, section_number),
                parent=self)
            if number is None:
                return
            number = number.strip()
            if not number:
                messagebox.showwarning("Копирование таблицы",
                                       "Номер таблицы не может быть пустым.",
                                       parent=self)
                return
        if copy:
            linked = sorted({str(entry["item"].get("cabinet"))
                             for entry in entries if entry["kind"] == "table"
                             and entry["item"].get("cabinet")})
            if linked and not messagebox.askyesno(
                    "Копирование таблиц",
                    "Копии берут данные из шкафа: %s.\n"
                    "Они будут показывать те же данные шкафа. Продолжить?"
                    % ", ".join(linked), parent=self):
                return
        base = self._number_base(section_number)
        made = []

        def action():
            for entry in entries:
                dest = container.setdefault(
                    "tables" if entry["kind"] == "table" else "figures", [])
                if copy:
                    if entry["kind"] == "table":
                        item = st.copy_table(self.data, entry["item"],
                                             container, number=number,
                                             section_number=section_number)
                    else:
                        item = st.copy_figure(entry["item"], container,
                                              base=base)
                else:
                    if dest is entry["source"]:
                        continue
                    item = st.move_node(entry["item"], entry["source"], dest)
                made.append(item)
            if not made:
                raise st.StructureError(
                    "выделенные узлы уже находятся в этом разделе")
            return made

        self._mutate(action)
        if made:
            numbers = [str(item.get("number") or "") for item in made]
            detail = (numbers[0] if len(numbers) == 1
                      else "%s…%s" % (numbers[0], numbers[-1]))
            self.status.config(
                text="%s %d узел(ов) в «%s» (%s)"
                     % ("Скопировано" if copy else "Перенесено",
                        len(made), target["label"], detail))

    def _move_table(self, iid, copy=False):
        """Перенести или скопировать одну таблицу в другой раздел."""
        self._transfer([iid], copy=copy)

    @staticmethod
    def _cabinet_label(item):
        """Подпись шкафа стандарта для списков выбора."""
        code = str(item.get("cypher") or "").strip()
        name = str(item.get("name") or "").strip()
        return "%s — %s" % (code, name) if name else code

    def _choose_cabinet(self, cabinets, title):
        """Выбрать шкаф документа для привязки таблиц."""
        def describe(item):
            lines = [str(item.get("description") or "")]
            kits = len(item.get("kits") or [])
            if kits:
                lines.append("Комплектов: %d" % kits)
            return "\n".join(line for line in lines if line)

        return choose_item(self, cabinets, title, self._cabinet_label,
                           describe)

    def _table_rows_for(self, table, cabinet_item):
        """Строки, которые таблица покажет после привязки к шкафу."""
        probe = dict(table, cabinet=cabinet_item.get("cypher"))
        return es.table_view(self.data, probe)[1]

    def _rebind_table(self, iid):
        """Привязать таблицу к другому шкафу документа."""
        owner = self._owners.get(iid)
        if not owner or owner[1] is None:
            return
        table = owner[1]
        current = str(table.get("cabinet") or "")
        others = [item for item in es.cabinets(self.data)
                  if str(item.get("cypher") or "") != current]
        if not others:
            messagebox.showinfo("Редактор стандарта",
                                "В стандарте нет другого шкафа.", parent=self)
            return
        target = self._choose_cabinet(others,
                                      "К какому шкафу привязать таблицу")
        if target is None:
            return
        code = str(target.get("cypher") or "")
        if not self._table_rows_for(table, target) and not messagebox.askyesno(
                "Редактор стандарта",
                "У шкафа %s нет данных для этой таблицы.\n"
                "Таблица останется с одной шапкой. Продолжить?" % code,
                parent=self):
            return

        def action():
            return st.rebind_table(table, code)

        self._mutate(action)
        self.status.config(text="Таблица %s привязана к шкафу %s"
                                % (table.get("number") or "", code))

    def _rebind_group(self, group):
        """Привязать выделенные таблицы к одному шкафу."""
        tables = []
        for iid in group:
            owner = self._owners.get(iid)
            if self._node_kind(iid) == "table" and owner and owner[1]:
                tables.append(owner[1])
        if not tables:
            return
        current = {str(table.get("cabinet") or "") for table in tables}
        others = [item for item in es.cabinets(self.data)
                  if str(item.get("cypher") or "") not in current]
        if not others:
            messagebox.showinfo("Редактор стандарта",
                                "В стандарте нет другого шкафа.", parent=self)
            return
        target = self._choose_cabinet(
            others, "К какому шкафу привязать таблицы (%d)" % len(tables))
        if target is None:
            return
        code = str(target.get("cypher") or "")
        empty = [str(table.get("number") or "(без номера)") for table in tables
                 if not self._table_rows_for(table, target)]
        if empty and not messagebox.askyesno(
                "Редактор стандарта",
                "У шкафа %s нет данных для таблиц: %s.\n"
                "Они останутся с одной шапкой. Продолжить?"
                % (code, ", ".join(empty[:8])), parent=self):
            return

        def action():
            for table in tables:
                st.rebind_table(table, code)
            return tables

        self._mutate(action)
        self.status.config(text="Таблиц привязано к %s: %d"
                                % (code, len(tables)))

    def _ask_rebind(self, cabinet_item):
        """Спросить шкаф для таблиц удаляемого шкафа; None — отказались."""
        code = str(cabinet_item.get("cypher") or "")
        tables = [table for table in es.iter_tables(self.data)
                  if table.get("cabinet") == code]
        others = [item for item in es.cabinets(self.data)
                  if item is not cabinet_item]
        if not tables or not others:
            return None
        if not messagebox.askyesno(
                "Редактор стандарта",
                "На шкаф %s ссылаются таблицы: %d.\n"
                "Перепривязать их к другому шкафу перед удалением?"
                % (code, len(tables)), parent=self):
            return None
        target = self._choose_cabinet(others, "Новый шкаф для таблиц")
        if target is None:
            return None
        empty = [table.get("number") or "(без номера)" for table in tables
                 if not self._table_rows_for(table, target)]
        if empty and not messagebox.askyesno(
                "Редактор стандарта",
                "У шкафа %s нет данных для таблиц: %s.\n"
                "Они останутся с одной шапкой. Продолжить?"
                % (target.get("cypher"), ", ".join(empty[:8])), parent=self):
            return None
        return target

    def _delete_group(self, iids):
        """Удалить выделенные узлы одним подтверждением."""
        entries = []
        for iid in iids:
            owner = self._owners.get(iid)
            kind = self._node_kind(iid)
            if not owner or owner[1] is None:
                continue
            if kind not in ("section", "subsection", "clause", "subclause",
                            "table", "figure", "cabinet", "kit", "ied") \
                    and kind not in _GENERIC_KINDS:
                continue
            entries.append((iid, kind, owner[0], owner[1], owner[2]))
        if not entries:
            return
        selected = {entry[0] for entry in entries}
        kept = []
        for entry in entries:
            parent_iid = entry[4]
            inside = False
            while parent_iid:
                if parent_iid in selected:
                    inside = True
                    break
                owner = self._owners.get(parent_iid)
                parent_iid = owner[2] if owner else None
            if not inside:
                kept.append(entry)
        problems = []
        for _iid, kind, _container, item, _parent in kept:
            problems.extend(st.delete_issues(self.data, item, kind))
        if problems:
            messagebox.showwarning("Редактор стандарта",
                                   "\n".join(problems), parent=self)
            return
        count = sum(st.descendant_count(item)
                    for _i, _k, _c, item, _p in kept)
        message = "Удалить выделенные узлы: %d?" % len(kept)
        if count:
            message += "\nВнутри ещё %d узел(ов) — они будут удалены." % count
        if not messagebox.askyesno("Редактор стандарта", message,
                                   parent=self):
            return
        parent_item = (self._owners[kept[0][4]][1]
                       if kept[0][4] in self._owners else None)

        def action():
            for _iid, _kind, container, item, _parent in reversed(kept):
                st.remove(container, item)
            return None

        self._mutate(action, select_item=parent_item)

    def _delete_selection(self):
        """Удалить выделение: один узел или группу."""
        iids = self._selection_iids()
        if len(iids) > 1:
            self._delete_group(iids)
        elif iids:
            self._delete_node(iids[0])

    # ---------------------------------------------------- дублирование узлов
    def _copy_name(self, node):
        """Имя узла для сообщения о копии."""
        item = self._generic_item(node) if node else None
        if isinstance(item, dict):
            return str(item.get("name") or "").strip()
        return ""

    def _report_copy(self):
        """Показать в строке состояния имя только что вставленной копии."""
        name = self._copy_name(self._nodes.get(self._current_node))
        self.status.config(text="Вставлена копия%s"
                                % (": %s" % name if name else ""))

    def _duplicate_selection(self):
        """Ctrl+D: вставить копию выделенного узла."""
        iids = self._selection_iids()
        if len(iids) != 1:
            self.status.config(text="Для копии выберите один узел")
            return
        self._duplicate_node(iids[0])

    def _duplicate_node(self, iid):
        """Вставить копию блока, функции, входа/выхода, уставки, параметра."""
        owner = self._owners.get(iid)
        kind = self._node_kind(iid)
        if not owner or kind not in _DUPLICATE_KINDS:
            return
        container, item, _parent = owner
        if not isinstance(item, dict) or not isinstance(container, list):
            return

        def action():
            return st.duplicate_node(item, container)

        if self._mutate(action):
            self._report_copy()

    def _copy_node(self, event=None):
        """Ctrl+C: запомнить узел функциональной модели для вставки."""
        iids = self._selection_iids()
        if len(iids) != 1:
            self.status.config(text="Для копии выберите один узел")
            return "break"
        iid = iids[0]
        owner = self._owners.get(iid)
        kind = self._node_kind(iid)
        if kind not in _DUPLICATE_KINDS or not owner \
                or not isinstance(owner[1], dict) \
                or not isinstance(owner[0], list):
            self.status.config(text="Этот узел копировать нельзя")
            return "break"
        self._clipboard = (kind, owner[0], owner[1])
        self.status.config(text="Скопировано: %s"
                                % self.tree.item(iid, "text"))
        return "break"

    def _paste_node(self, event=None):
        """Ctrl+V: вставить копию запомненного узла рядом с оригиналом."""
        if not self._clipboard:
            self.status.config(text="Буфер пуст: сначала скопируйте узел")
            return "break"
        _kind, container, item = self._clipboard
        if not isinstance(container, list) \
                or not any(value is item for value in container):
            self._clipboard = None
            self.status.config(text="Исходный узел не найден — скопируйте заново")
            return "break"

        def action():
            return st.duplicate_node(item, container)

        if self._mutate(action):
            self._report_copy()
        return "break"

    def _delete_node(self, iid):
        owner = self._owners.get(iid)
        node = self._nodes.get(iid)
        if not owner or not node:
            return
        container, item, parent_iid = owner
        kind = node[1] if node[0] == "text" else node[0]
        if kind not in ("section", "subsection", "clause", "subclause",
                        "table", "figure", "cabinet", "kit", "ied") \
                and kind not in _GENERIC_KINDS:
            return
        issues = st.delete_issues(self.data, item, kind)
        rebind = None
        cabinet = None
        replacement = None
        if kind == "kit" and parent_iid in self._owners:
            cabinet = self._owners[parent_iid][1]
            if st.kit_feeds_tables(self.data, item, cabinet):
                replacement_cabinet, replacement_kit = \
                    st.identical_replacement(self.data, item, cabinet)
                if replacement_cabinet is not None:
                    replacement = (replacement_cabinet, replacement_kit)
                    issues = []      # есть идентичный комплект-замена
        if issues and kind == "cabinet":
            rebind = self._ask_rebind(item)
            if rebind is not None:
                issues = []      # перепривязка снимает замечание о ссылках
        if issues:
            messagebox.showwarning("Редактор стандарта", "\n".join(issues),
                                   parent=self)
            return
        label = {"section": "раздел", "subsection": "подраздел",
                 "clause": "пункт", "subclause": "подпункт",
                 "table": "таблицу",
                 "figure": "рисунок", "cabinet": "шкаф",
                 "kit": "комплект", "ied": "ИЭУ",
                 "block": "блок функций", "function": "функцию",
                  "fb_entry": "функциональный блок",
                 "slot": "вход/выход", "setting": "уставку",
                 "parameter": "параметр"}.get(kind, "узел")
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
            if replacement is not None:
                replacement_cabinet, replacement_kit = replacement
                st.promote_kit(replacement_cabinet, replacement_kit)
                if cabinet is not None and replacement_cabinet is not cabinet:
                    st.rebind_tables(self.data, cabinet.get("cypher"),
                                     replacement_cabinet.get("cypher"))
            if rebind is not None:
                st.rebind_tables(self.data, item.get("cypher"),
                                 rebind.get("cypher"))
            st.remove(container, item)
            return None

        if self._mutate(action, select_item=parent_item) \
                and replacement is not None and cabinet is not None:
            replacement_cabinet = replacement[0]
            if replacement_cabinet is cabinet:
                text = ("Комплект заменён идентичным — таблицы остались "
                        "на шкафу %s" % cabinet.get("cypher"))
            else:
                text = ("Таблицы перепривязаны к шкафу %s (идентичный "
                        "комплект)" % replacement_cabinet.get("cypher"))
            self.status.config(text=text)

    # -------------------------------------------------- контекстное меню
    def _targets_for_node(self, node):
        """Элементы отчёта для узла дерева (пусто — отчёт не строится)."""
        kind = node[0]
        if kind == "root":
            which = node[1]
            if which == "doc":
                return [er.target("Standard", self.data,
                                  "Документ стандарта")]
            if which == "cabs":
                return [er.target("Cabinet", item)
                        for item in self.data.get("cabinets") or []
                        if isinstance(item, dict)]
            if which == "fb":
                return [er.target("FunctionalBlockEntry", item)
                        for item in self.data.get("functional_blocks") or []
                        if isinstance(item, dict)]
            return []
        if kind == "meta":
            return [er.target("Standard", self.data, "Реквизиты стандарта",
                              children=False)]
        if kind == "text":
            class_name = er.TEXT_CLASS.get(node[1])
            return [er.target(class_name, node[2])] if class_name else []
        if kind == "slot":
            class_name = er.SLOT_CLASS.get(node[2])
            return [er.target(class_name, node[1])] if class_name else []
        if kind == "table_column":
            # Колонка — не самостоятельный элемент модели.
            return []
        class_name = sc.KIND_CLASS.get(kind)
        return [er.target(class_name, node[1])] if class_name else []

    def _report_targets(self, iids):
        """Описания элементов отчёта без повторов (по объекту данных)."""
        targets, seen = [], set()
        for iid in iids:
            node = self._nodes.get(iid)
            if not node:
                continue
            for item in self._targets_for_node(node):
                key = (id(item["item"]), item.get("children", True))
                if key in seen:
                    continue
                seen.add(key)
                targets.append(item)
        return targets

    def _report_nodes(self, iids):
        """Спросить файл и записать отчёт по узлам ``iids`` в DOCX."""
        if not self._apply_pending():
            return
        targets = self._report_targets(iids)
        if not targets:
            messagebox.showinfo("Отчёт",
                                "Для этого элемента отчёт не строится.",
                                parent=self)
            return
        if len(targets) == 1:
            name = targets[0].get("title") or "элемент"
        else:
            name = "выделенная группа"
        base = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", " ", name).strip()
        base = (base[:80].strip() or "отчет")
        path = filedialog.asksaveasfilename(
            parent=self, title="Куда сохранить отчёт",
            initialdir=es.folder(), initialfile=base + ".docx",
            defaultextension=".docx", filetypes=[("Word", "*.docx")])
        if not path:
            return
        # Отчёт по документу или крупному шкафу собирается секунды: показываем
        # модальное окно и строим в фоне, чтобы редактор не «замерзал».
        progress = tk.Toplevel(self)
        progress.title("Отчёт")
        progress.transient(self)
        progress.resizable(False, False)
        tk.Label(progress, text="Собираю отчёт…",
                 font=ui_theme.font(9)).pack(padx=18, pady=(14, 6))
        bar = ttk.Progressbar(progress, mode="indeterminate", length=300)
        bar.pack(padx=18, pady=(0, 14))
        bar.start(12)
        _place_on_parent(progress, self)
        progress.grab_set()
        outcome = {}

        def work():
            try:
                outcome["counters"] = er.build(self.data, targets, path)
            except Exception as exc:                  # noqa: BLE001
                outcome["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self._await_report(thread, progress, bar, path, outcome)

    def _await_report(self, thread, progress, bar, path, outcome):
        """Дождаться фоновой сборки отчёта и показать итог."""
        if thread.is_alive():
            try:
                self.after(120, lambda: self._await_report(
                    thread, progress, bar, path, outcome))
            except tk.TclError:
                pass
            return
        try:
            bar.stop()
            progress.destroy()
        except tk.TclError:
            pass
        error = outcome.get("error")
        if error is not None:
            messagebox.showerror(
                "Отчёт", "Не удалось собрать отчёт:\n%s" % error, parent=self)
            return
        counters = outcome.get("counters") or {}
        messagebox.showinfo(
            "Отчёт",
            "Отчёт сохранён:\n%s\n\nЭлементов: %s, таблиц данных: %s, "
            "полей: %s"
            % (path, counters.get("элементы"), counters.get("таблицы"),
               counters.get("поля")), parent=self)
        self.status.config(text="Отчёт: %s" % path)

    def _reference_item(self, node):
        """Объект дерева, к которому можно привязать метку ссылки."""
        if not node:
            return None
        if node[0] == "text" and node[1] in ("section", "subsection"):
            return node[2]
        if node[0] in ("table", "figure"):
            return node[1]
        return None

    def _label_owner(self, label, current):
        """Подпись узла, у которого уже занята эта метка."""
        key = sc.normalize_ref_label(label)
        for iid, node in self._nodes.items():
            item = self._reference_item(node)
            if item is None or item is current:
                continue
            for used in sc.reference_labels(item.get("ref")):
                if sc.normalize_ref_label(used) == key:
                    return self.tree.item(iid, "text") or "другой элемент"
        return None

    def _insert_reference(self, iid):
        r"""Пункт 31: метки ``\ref{…}`` для таблицы, рисунка, раздела."""
        item = self._reference_item(self._nodes.get(iid))
        if item is None or not self._apply_pending():
            return
        prompt = ("Метка перекрёстной ссылки.\n"
                  r"В тексте стандарта: \ref{метка}. "
                  "Несколько меток — через ';'.")
        raw = self._ask(prompt, item.get("ref") or "")
        if raw is None:
            return
        labels = sc.reference_labels(raw)
        if str(raw).strip() and not labels:
            messagebox.showerror(
                "Редактор стандарта",
                "Метка пустая или содержит '{}' — так ссылка не найдётся.",
                parent=self)
            return
        for name in labels:
            owner = self._label_owner(name, item)
            if owner:
                messagebox.showerror(
                    "Редактор стандарта",
                    "Метка «%s» уже привязана к: %s" % (name, owner),
                    parent=self)
                return

        def action():
            if labels:
                item["ref"] = "; ".join(labels)
            else:
                item.pop("ref", None)
            return item

        if self._mutate(action):
            if labels:
                self.status.config(
                    text="Метка ссылки: \\ref{%s}" % labels[0])
            else:
                self.status.config(text="Метки перекрёстных ссылок удалены")

    def _group_menu(self, group):
        """Меню действий над выделенной группой узлов."""
        kinds = {self._node_kind(iid) for iid in group}
        items = []
        if self._report_targets(group):
            items += [
                ("Сформировать отчёт по выделенному (%d)…" % len(group),
                 lambda: self._report_nodes(group)),
                None,
            ]
        if kinds == {"table"}:
            items += [
                ("Привязать выделенное (%d) к другому шкафу…" % len(group),
                 lambda: self._rebind_group(group)),
                None,
            ]
        if kinds <= {"table", "figure"}:
            items += [
                ("Переместить выделенное (%d) в другой раздел…" % len(group),
                 lambda: self._transfer(group, copy=False)),
                ("Копировать выделенное (%d) в другой раздел…" % len(group),
                 lambda: self._transfer(group, copy=True)),
                None,
            ]
        items.append(("Удалить выделенное (%d)" % len(group),
                      lambda: self._delete_group(group)))
        return items

    def _menu_items(self, iid, node):
        """Меню узла: общий пункт отчёта плюс действия по виду узла."""
        group = self._selection_iids()
        if len(group) > 1 and iid in group:
            return self._group_menu(group)
        items = self._base_menu_items(iid, node)
        if self._targets_for_node(node):
            items = [("Сформировать отчёт (DOCX)…",
                      lambda: self._report_nodes([iid])), None] + items
        return items

    def _base_menu_items(self, iid, node):
        kind = node[0]
        if kind == "root":
            if node[1] == "doc":
                return [("Добавить раздел…", lambda: self._add_section(iid))]
            if node[1] == "fb":
                return [
                    ("Добавить функциональный блок…",
                     lambda: self._add_fb_entry(iid)),
                    ("Пересобрать каталог из шкафов…",
                     lambda: self._rebuild_fb()),
                ]
            return [
                ("Добавить шкафы из всех стандартов…",
                 lambda: self._add_cabinets(iid)),
                ("Добавить типовой шкаф из каталога…",
                 lambda: self._add_typical_cabinet(iid)),
                ("Добавить пустой шкаф…", lambda: self._add_cabinet(iid)),
            ]
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
                    ("Вставить ссылку…", lambda: self._insert_reference(iid)),
                    ("Удалить раздел", lambda: self._delete_node(iid)),
                ]
            if node[1] == "subsection":
                return [
                    ("Добавить пункт…", lambda: self._add_clause(iid)),
                    ("Добавить таблицу…", lambda: self._add_table(iid)),
                    ("Добавить рисунок…", lambda: self._add_figure(iid)),
                    None,
                    ("Вставить ссылку…", lambda: self._insert_reference(iid)),
                    ("Удалить подраздел", lambda: self._delete_node(iid)),
                ]
            word = "подпункт" if node[1] == "subclause" else "пункт"
            return [
                ("Добавить таблицу…", lambda: self._add_table(iid)),
                ("Добавить рисунок…", lambda: self._add_figure(iid)),
                None,
                ("Удалить %s" % word, lambda: self._delete_node(iid)),
            ]
        if kind == "cabinet":
            return [
                ("Добавить комплект…", lambda: self._add_kit(iid)),
                ("Добавить типовой комплект из каталога…",
                 lambda: self._add_typical_kit(iid)),
                None, ("Удалить шкаф", lambda: self._delete_node(iid)),
            ]
        if kind == "kit":
            return [
                ("Добавить ИЭУ…", lambda: self._add_ied(iid)),
                ("Дублировать комплект", lambda: self._duplicate_kit(iid)),
                ("Переместить в другой шкаф…", lambda: self._move_kit(iid)),
                None, ("Удалить комплект", lambda: self._delete_node(iid)),
            ]
        if kind == "table":
            items = [("Вставить ссылку…",
                      lambda: self._insert_reference(iid))]
            if node[1].get("cabinet"):
                items += [None, ("Привязать к другому шкафу…",
                                 lambda: self._rebind_table(iid))]
            return items + [
                None,
                ("Переместить в другой раздел…",
                 lambda: self._move_table(iid, copy=False)),
                ("Копировать в другой раздел…",
                 lambda: self._move_table(iid, copy=True)),
                None,
                ("Удалить таблицу", lambda: self._delete_node(iid)),
            ]
        if kind == "figure":
            return [("Вставить ссылку…",
                     lambda: self._insert_reference(iid)),
                    None,
                    ("Удалить рисунок", lambda: self._delete_node(iid))]
        if kind == "ied":
            return [
                ("Добавить блок функций…",
                 lambda: self._add_generic_child(iid, "block")),
                ("Скопировать блоки в каталог ФБ…",
                 lambda: self._fb_from_ied(iid)),
                None, ("Удалить ИЭУ", lambda: self._delete_node(iid)),
            ]
        if kind == "fb_entry":
            return [
                ("Дублировать функциональный блок",
                 lambda: self._duplicate_node(iid)),
                ("Добавить функцию…",
                 lambda: self._add_generic_child(iid, "function")),
                None, ("Удалить функциональный блок",
                       lambda: self._delete_node(iid)),
            ]
        if kind == "block":
            return [
                ("Дублировать блок",
                 lambda: self._duplicate_node(iid)),
                ("Добавить функцию…",
                 lambda: self._add_generic_child(iid, "function")),
                None, ("Удалить блок", lambda: self._delete_node(iid)),
            ]
        if kind == "function":
            return [
                ("Дублировать функцию",
                 lambda: self._duplicate_node(iid)),
                ("Добавить вход…",
                 lambda: self._add_generic_child(iid, "slot", "in")),
                ("Добавить выход…",
                 lambda: self._add_generic_child(iid, "slot", "out")),
                ("Добавить уставку…",
                 lambda: self._add_generic_child(iid, "setting")),
                ("Добавить параметр…",
                 lambda: self._add_generic_child(iid, "parameter")),
                None, ("Удалить функцию", lambda: self._delete_node(iid)),
            ]
        if kind == "slot":
            word = "выход" if node[2] == "out" else "вход"
            return [("Дублировать %s" % word,
                     lambda: self._duplicate_node(iid)),
                    None,
                    ("Удалить %s" % word,
                     lambda: self._delete_node(iid))]
        if kind == "setting":
            return [("Дублировать уставку",
                     lambda: self._duplicate_node(iid)),
                    None,
                    ("Удалить уставку", lambda: self._delete_node(iid))]
        if kind == "parameter":
            return [("Дублировать параметр",
                     lambda: self._duplicate_node(iid)),
                    None,
                    ("Удалить параметр", lambda: self._delete_node(iid))]
        if kind == "table_column":
            # Колонка — не отдельный узел модели: действия у самой таблицы.
            return []
        return [("Удалить ИЭУ", lambda: self._delete_node(iid))]

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self._nodes:
            return
        if iid not in self.tree.selection():
            if not self._apply_pending():
                return
            self._switching = True
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self._switching = False
            self._current_node = iid
            self._render(self._nodes.get(iid))
        elif iid != self._current_node:
            # клик по одному из выделенных: панель показывает именно его
            if not self._apply_pending():
                return
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
        """Записать правки текущей панели в данные; False — не удалось.

        Панель остаётся активной: повторные правки того же узла тоже
        записываются (панель сбрасывает обработчик при перерисовке).
        """
        function = self._pending
        if function is None:
            return True
        try:
            changed = function()
        except ee.TableEditError as exc:
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
# Диалог добавления шкафов из всех стандартов
# ---------------------------------------------------------------------------
class CabinetDialog(tk.Toplevel):
    """Выбор шкафов всех стандартов; уже имеющиеся пропускаются слиянием."""

    def __init__(self, parent, data):
        super().__init__(parent)
        self.chosen = None
        self._parent = parent
        existing = {em.norm_cypher(item.get("cypher"))
                    for item in es.cabinets(data)}
        self._entries = [entry for entry in em.load_catalog_cached()
                         if em.norm_cypher(entry["cypher"]) not in existing]
        self.title("Шкафы из всех стандартов")
        self.transient(parent)
        self.resizable(False, False)
        self._build()
        if isinstance(parent, tk.Misc):
            _place_on_parent(self, parent)
        self.bind("<Escape>", lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        form = tk.Frame(self)
        form.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        note = ("Доступные шкафы из всех стандартов СТО. "
                "Для каждого переносятся таблицы-формы и рисунки.")
        tk.Label(form, text=note, font=ui_theme.font(8),
                 fg=ui_theme.TEXT_MUTED, anchor="w", justify="left",
                 wraplength=520).pack(fill=tk.X, pady=(0, 6))
        box = tk.Frame(form)
        box.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(box, orient="vertical")
        self.listbox = tk.Listbox(box, selectmode="extended", height=12,
                                  width=68, font=ui_theme.font(9),
                                  yscrollcommand=scroll.set)
        scroll.config(command=self.listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for entry in self._entries:
            self.listbox.insert(
                tk.END, "%s — %s [%s]"
                % (entry["cypher"], entry["name"], entry["volume"]))
        if not self._entries:
            self.listbox.insert(tk.END, "Все шкафы уже есть в стандарте")
            self.listbox.config(state="disabled")
        else:
            self.listbox.selection_set(0, tk.END)
        buttons = tk.Frame(form)
        buttons.pack(fill=tk.X, pady=(8, 0))
        _button(buttons, "Все", self._select_all, side=tk.LEFT)
        _button(buttons, "Ни одного", self._select_none, side=tk.LEFT)
        _button(buttons, "Отмена", self.destroy, side=tk.RIGHT)
        _button(buttons, "Добавить", self._ok, width=12, side=tk.RIGHT)

    def _select_all(self):
        if self._entries:
            self.listbox.selection_set(0, tk.END)

    def _select_none(self):
        self.listbox.selection_clear(0, tk.END)

    def _ok(self):
        if not self._entries:
            self.destroy()
            return
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showwarning("Шкафы из всех стандартов",
                                   "Выберите хотя бы один шкаф.",
                                   parent=self)
            return
        self.chosen = [self._entries[index] for index in selected]
        self.destroy()


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
