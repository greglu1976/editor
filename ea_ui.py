# -*- coding: utf-8 -*-
"""Окно стандартов СТО в структуре EA для редактора схем.

Показывает дерево документа (разделы → подразделы → пункты → таблицы) и
шкафы с комплектами и ИЭУ. Строки таблиц не хранятся в документе: они
собираются из шкафа через :func:`ea_standard.table_view`, поэтому в окне
видно ровно то, что лежит в ``cabinets``.

Из окна шкаф можно поставить на схему («На схему»), а комплект — добавить в
выбранный на схеме шкаф («Комплект → в шкаф»). Шкаф при этом один раз
заносится в каталог редактора через :mod:`ea_catalog`.

Модуль самостоятельный: старые окна стандартов (``standards_ui``) не
импортируются, чтобы новую ветку можно было оставить без старой.
"""

from __future__ import annotations

import datetime
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ea_catalog
import ea_docx
import ea_editor
import ea_merge as em
import ea_new_standard as ns
import ea_standard as es
import komplekts
import ui_theme


# ---------------------------------------------------------------------------
# Общие мелочи
# ---------------------------------------------------------------------------
def _place_on_parent(window, parent):
    """Поставить окно на тот же монитор, где родитель."""
    try:
        window.update_idletasks()
        # у ещё не показанного окна winfo_width() == 1: берём запрошенный размер
        width = max(window.winfo_width(), window.winfo_reqwidth())
        height = max(window.winfo_height(), window.winfo_reqheight())
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
        self.combo = ttk.Combobox(top, state="readonly", width=42,
                                  font=ui_theme.font(9))
        self.combo.pack(side=tk.LEFT, padx=(6, 4))
        self.combo.bind("<<ComboboxSelected>>", lambda event: self._combo_changed())
        _button(top, "Обновить", self.reload, width=10, side=tk.RIGHT)
        _button(top, "Открыть папку", lambda: open_folder(es.folder()),
                side=tk.RIGHT)
        _button(top, "Проверить", self.check, width=10, side=tk.RIGHT)
        _button(top, "Обновить шкафы и комплекты", self.update_cabinets_and_kits,
                side=tk.RIGHT)
        _button(top, "Реквизиты…", self.edit_standard, width=12,
                side=tk.RIGHT)
        _button(top, "Редактор…", self.open_editor, width=12, side=tk.RIGHT)
        _button(top, "Новый стандарт…", self.new_standard, width=17,
                side=tk.RIGHT)
        _button(top, "DOCX…", self.export_docx, width=10, side=tk.RIGHT)

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
        actions = tk.Frame(right)
        actions.pack(fill=tk.X, padx=4, pady=(2, 2))
        self.btn_place = tk.Button(actions, text="На схему",
                                   command=self.place_cabinet,
                                   font=ui_theme.font(9), state=tk.DISABLED)
        self.btn_place.pack(side=tk.LEFT)
        self.btn_kit = tk.Button(actions, text="Комплект → в шкаф",
                                 command=self.add_kit,
                                 font=ui_theme.font(9), state=tk.DISABLED)
        self.btn_kit.pack(side=tk.LEFT, padx=(4, 0))
        self.btn_sync = tk.Button(
            actions, text="Обновить шкафы и комплекты по данному стандарту",
            command=self.update_cabinets_and_kits,
            font=ui_theme.font(9))
        self.btn_sync.pack(side=tk.RIGHT)
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
            for kit in item.get("kits") or []:
                kit_node = self.tree.insert(
                    node, tk.END,
                    text="Комплект %s — %s" % (kit.get("number", ""),
                                               kit.get("description", "")),
                    open=False)
                self._nodes[kit_node] = ("kit", item, kit)
                for ied in kit.get("ieds") or []:
                    ied_node = self.tree.insert(
                        kit_node, tk.END,
                        text="ИЭУ %s — функций %d"
                             % (ied.get("number", ""),
                                es.function_count(ied)))
                    self._nodes[ied_node] = ("ied", item, kit, ied)
        self._update_actions(None)

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
        node = self._nodes.get(selection[0]) if selection else None
        if not node:
            self._update_actions(None)
            return
        kind = node[0]
        self._update_actions(kind)
        if kind == "table":
            self._show_table(node[1])
        elif kind == "cabinet":
            self._show_cabinet(node[1])
        elif kind == "kit":
            self._show_kit(node[1], node[2])
        elif kind == "ied":
            self._show_ied(node[2], node[3])
        else:
            self._show_text(node[1], node[2])

    def _update_actions(self, kind):
        """Кнопки действуют только для своего узла дерева."""
        self.btn_place.config(
            state=tk.NORMAL if kind == "cabinet" else tk.DISABLED)
        self.btn_kit.config(
            state=tk.NORMAL if kind == "kit" else tk.DISABLED)

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
        if not headers:
            self._show_text("Таблица", "(пустая таблица)")
            return
        self._show_grid("%s %s" % (table.get("reference", ""),
                                   table.get("name", "")), headers, rows)
        code = table.get("cabinet")
        note = ("Данные из шкафа %s" % code) if code else "Таблица документа"
        self.status.config(text="%s — строк %d" % (note, len(rows)))

    def _show_grid(self, caption, headers, rows):
        """Таблица с обеими прокрутками: ширина колонок по содержимому."""
        self._clear_right()
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.caption.config(text=caption)
        columns = ["c%d" % index for index in range(len(headers))]
        self.table["columns"] = columns
        for index, column in enumerate(columns):
            self.table.heading(column, text=headers[index])
            width = max([len(str(headers[index]))] + [
                len(str(row[index])) for row in rows[:80] if index < len(row)])
            self.table.column(column,
                              width=min(360, max(80, width * 8 + 18)),
                              anchor="w", stretch=False)
        for row in rows:
            values = [row[index] if index < len(row) else ""
                      for index in range(len(headers))]
            self.table.insert("", tk.END, values=values)
        if not rows:
            self.table.insert("", tk.END, values=["—"] * len(headers))

    def _show_card(self, caption, headers, rows):
        """Карточка «параметр — значение»: широкая колонка значений."""
        self._clear_right()
        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.caption.config(text=caption)
        columns = ["c%d" % index for index in range(len(headers))]
        self.table["columns"] = columns
        longest = max([len(str(row[1])) for row in rows if len(row) > 1] or [0])
        for index, column in enumerate(columns):
            self.table.heading(column, text=headers[index])
            width = 190 if index == 0 else min(1400, max(500, longest * 7))
            self.table.column(column, width=width, anchor="w", stretch=False)
        for row in rows:
            self.table.insert("", tk.END, values=row)

    def _show_cabinet(self, item):
        self._show_card("Шкаф %s — %s"
                        % (item.get("cypher", ""), item.get("name", "")),
                        ["Параметр", "Значение"], es.cabinet_card(item))
        self.status.config(text="Шкаф %s" % item.get("cypher", ""))

    def _show_kit(self, item, kit):
        ieds = kit.get("ieds") or []
        functions = ea_catalog.function_names(kit)
        analog = sum(len(ied.get("analog_inputs") or []) for ied in ieds)
        rows = [
            ["Шкаф", "%s — %s" % (item.get("cypher", ""),
                                  item.get("name", ""))],
            ["Номер", kit.get("number", "")],
            ["Тип", kit.get("type", "")],
            ["Описание", kit.get("description", "")],
            ["ИЭУ", ", ".join("ИЭУ %s" % ied.get("number", "")
                              for ied in ieds) or "—"],
            ["Функции", ", ".join(functions) or "—"],
            ["Аналоговые измерения", str(analog)],
        ]
        self._show_card("Комплект %s шкафа %s"
                        % (kit.get("number", ""), item.get("cypher", "")),
                        ["Параметр", "Значение"], rows)
        self.status.config(text="Комплект %s шкафа %s"
                           % (kit.get("number", ""), item.get("cypher", "")))

    def _show_ied(self, kit, ied):
        caption = "ИЭУ %s — комплект %s" % (ied.get("number", ""),
                                           kit.get("number", ""))
        blocks = es.function_blocks(ied)
        functions = list(es.iter_functions(ied))
        if not functions:
            rows = [
                ["Порты", str(len(ied.get("ports") or []))],
                ["Аналоговые входы", str(len(ied.get("analog_inputs") or []))],
                ["Дискретные цепи",
                 str(len(ied.get("inner_discrete_circuits") or []))],
                ["Входящие GOOSE",
                 str(len(ied.get("incoming_goose_signals") or []))],
                ["Наборы данных", str(len(ied.get("datasets") or []))],
            ]
            self._show_card(caption, ["Параметр", "Значение"], rows)
            self.status.config(text=caption)
            return
        headers = ["Блок", "Функция", "МЭК 61850", "Основная", "В ИТС",
                   "Параметров"]
        rows = [[es.block_label(block),
                 function.get("name") or "",
                 function.get("iec_name") or "",
                 "да" if block.get("isMainFunction") else "",
                 "да" if block.get("isInITS") else "",
                 str(len(function.get("parameters") or []))]
                for block, function in functions]
        self._show_grid(caption, headers, rows)
        self.status.config(text="Блоков: %d · функций: %d"
                                % (len(blocks), len(functions)))

    def _show_text(self, title, content):
        self._clear_right()
        self.caption.config(text=title)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content or "")
        self.text.config(state="disabled")

    # ---------------------------------------------------------- действия
    def _selected(self):
        selection = self.tree.selection()
        return self._nodes.get(selection[0]) if selection else None

    def place_cabinet(self):
        """Поставить выбранный шкаф стандарта на схему редактора."""
        node = self._selected()
        if not node or node[0] != "cabinet" or not self._data:
            return
        place = getattr(self.app, "_place_cabinet", None)
        if place is None:
            messagebox.showinfo("Шкаф на схему",
                                "Окно открыто без редактора схем: "
                                "размещать некуда.", parent=self)
            return
        try:
            record = ea_catalog.ensure_catalog(self._data, node[1])
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror("Шкаф на схему",
                                 "Не удалось подготовить шкаф каталога:\n%s"
                                 % exc, parent=self)
            return
        place(record)
        self.status.config(text="Шкаф %s размещён на схеме"
                           % (record.get("code") or record.get("name") or ""))

    def add_kit(self):
        """Добавить выбранный комплект в шкаф, выделенный на схеме."""
        node = self._selected()
        if not node or node[0] != "kit" or not self._data:
            return
        add = getattr(self.app, "add_komplekt_to_cabinet", None)
        if add is None:
            messagebox.showinfo("Комплект в шкаф",
                                "Окно открыто без редактора схем: "
                                "добавлять некуда.", parent=self)
            return
        add(ea_catalog.kit_entry(self._data, node[1], node[2]))

    def update_cabinets_and_kits(self):
        """Обновить шкафы и комплекты каталога по текущему стандарту."""
        if not self._data:
            messagebox.showinfo("Стандарт", "Стандарт не выбран.", parent=self)
            return
        code = self._data.get("code") or self._data.get("name") or "выбранному стандарту"
        count = len(es.cabinets(self._data))
        if not messagebox.askyesno(
                "Обновить шкафы и комплекты",
                f"Обновить шкафы ({count} шт.) и их комплекты в каталоге редактора\n"
                f"по данному стандарту «{code}»?\n\n"
                "Данные каталога будут синхронизированы со стандартом.",
                parent=self):
            return

        try:
            stats = ea_catalog.update_standard_cabinets(self._data)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror(
                "Ошибка обновления",
                f"Не удалось обновить шкафы и комплекты:\n{exc}", parent=self)
            return

        rebuild_msg = ""
        try:
            import structure_tools
            res = structure_tools.rebuild()
            if res.get("ok"):
                rebuild_msg = "\nСтруктура (structure.json) успешно пересобрана."
            elif res.get("ошибка"):
                rebuild_msg = f"\nПересборка структуры: {res.get('ошибка')}"
        except Exception:
            pass

        try:
            if hasattr(self.app, "redraw_all"):
                self.app.redraw_all()
        except Exception:
            pass

        msg = (f"Шкафы и комплекты стандарта «{code}» обновлены в каталоге:\n"
               f"• Обновлено существующих шкафов: {stats['updated']}\n"
               f"• Добавлено новых шкафов: {stats['created']}\n"
               f"• Комплектов в стандарте: {stats['kits']}"
               f"{rebuild_msg}")
        self.status.config(
            text=f"Каталог обновлён: {stats['updated']} шкафов обновлено, "
                 f"{stats['created']} создано, {stats['kits']} комплектов")
        messagebox.showinfo("Обновление каталога", msg, parent=self)

    def edit_standard(self):
        """Изменить реквизиты текущего стандарта и сохранить JSON."""
        if not self._data or not self._path:
            return
        dialog = StandardFieldsDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.status.config(text="Поля стандарта сохранены: %s"
                                    % os.path.basename(self._path))

    def open_editor(self):
        """Открыть стандарт в отдельном окне редактора."""
        if not self._data or not self._path:
            messagebox.showinfo("Редактор стандарта",
                                "Стандарт не выбран.", parent=self)
            return
        editor = ea_editor.show(self._path, self,
                                on_saved=self._standard_saved)
        self.wait_window(editor)

    def _standard_saved(self, path):
        """После сохранения в редакторе перечитать стандарт в этом окне."""
        if path == self._path:
            self.reload(path)

    def new_standard(self):
        """Новый стандарт на базе выбранного (копия с правкой реквизитов)."""
        if not self._data:
            return
        dialog = NewStandardDialog(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        paths = es.files()
        if dialog.result in paths:
            self.reload(dialog.result)
        else:
            self.status.config(text="Стандарт сохранён: %s" % dialog.result)

    def export_docx(self):
        """Выгрузить текущий стандарт в Word; таблицы — из шкафов."""
        if not self._data:
            return
        base = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", " ",
                      self._data.get("code") or "").strip() or "standard"
        path = filedialog.asksaveasfilename(
            parent=self, title="Куда сохранить документ",
            initialdir=es.folder(), initialfile=base + ".docx",
            defaultextension=".docx", filetypes=[("Word", "*.docx")])
        if not path:
            return
        progress = tk.Toplevel(self)
        progress.title("Выгрузка в DOCX")
        progress.transient(self)
        progress.resizable(False, False)
        tk.Label(progress, text="Собираю документ…",
                 font=ui_theme.font(9)).pack(padx=18, pady=(14, 6))
        bar = ttk.Progressbar(progress, mode="indeterminate", length=300)
        bar.pack(padx=18, pady=(0, 14))
        bar.start(12)
        _place_on_parent(progress, self)
        progress.grab_set()
        outcome = {}

        def work():
            try:
                outcome["counters"] = ea_docx.build(self._data, path)
            except Exception as exc:                  # noqa: BLE001
                outcome["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self._await_docx(thread, progress, bar, path, outcome)

    def _await_docx(self, thread, progress, bar, path, outcome):
        if thread.is_alive():
            try:
                self.after(120, lambda: self._await_docx(
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
            messagebox.showerror("DOCX",
                                 "Не удалось собрать документ:\n%s" % error,
                                 parent=self)
            return
        counters = outcome.get("counters") or {}
        messagebox.showinfo(
            "DOCX", "Документ сохранён:\n%s\n\nТаблиц: %s, строк: %s"
            % (path, counters.get("таблицы", "—"),
               counters.get("строки", "—")), parent=self)
        self.status.config(text="DOCX: %s" % path)

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
# Реквизиты открытого стандарта
# ---------------------------------------------------------------------------
class StandardFieldsDialog(tk.Toplevel):
    """Редактирование шифра, наименования, принадлежности и даты."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.data = window._data
        self.result = False
        self.title("Поля стандарта")
        self.transient(window)
        self.resizable(False, False)
        self._build()
        _place_on_parent(self, window)
        self.grab_set()
        self.bind("<Escape>", lambda event: self.destroy())

    def _build(self):
        form = tk.Frame(self, padx=12, pady=10)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        self.vars = {}
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
        row += 1
        footer = tk.Frame(form)
        footer.grid(row=row, column=0, columnspan=2, sticky="we")
        _button(footer, "Сохранить", self.save, width=14, side=tk.RIGHT)
        _button(footer, "Отмена", self.destroy, width=10, side=tk.RIGHT)

    def save(self):
        meta = {key: var.get().strip() for key, var in self.vars.items()}
        if not meta["code"] or not meta["name"]:
            messagebox.showwarning("Поля стандарта",
                                   "Заполните шифр и наименование.",
                                   parent=self)
            return
        if meta["date"] and not re.match(r"^\d{2}\.\d{2}\.\d{4}$",
                                        meta["date"]):
            messagebox.showwarning("Поля стандарта",
                                   "Дата введения — в виде ДД.ММ.ГГГГ.",
                                   parent=self)
            return
        updated = dict(self.data)
        updated.update(meta)
        try:
            es.save(updated, self.window._path)
        except OSError as exc:
            messagebox.showerror("Поля стандарта",
                                 "Не удалось записать файл:\n%s" % exc,
                                 parent=self)
            return
        self.data.update(meta)
        self.result = True
        self.destroy()


# ---------------------------------------------------------------------------
# Выбор типовых шкафов каталога
# ---------------------------------------------------------------------------
def choose_catalog_cabinets(parent, cabinets, title="Типовые шкафы каталога"):
    """Выбрать несколько шкафов каталога. Возвращает список записей."""
    if not cabinets:
        messagebox.showinfo(title, "Все подходящие шкафы уже добавлены.",
                            parent=parent)
        return []
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)

    find = tk.Frame(dialog)
    find.pack(fill=tk.X, padx=10, pady=(8, 4))
    tk.Label(find, text="Поиск:", font=ui_theme.font(9)).pack(side=tk.LEFT)
    query = tk.StringVar()
    tk.Entry(find, textvariable=query, width=46,
             font=ui_theme.font(9)).pack(side=tk.LEFT, padx=(6, 0))

    frame = tk.Frame(dialog)
    frame.pack(fill=tk.BOTH, expand=True, padx=10)
    listbox = tk.Listbox(frame, selectmode="extended", width=82, height=16,
                         activestyle="dotbox", exportselection=False,
                         font=ui_theme.font(9))
    scroll = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scroll.set)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    info = tk.Label(dialog, text="", anchor="w", justify="left",
                    wraplength=620, font=ui_theme.font(9))
    info.pack(fill=tk.X, padx=10, pady=6)

    state = {"visible": list(cabinets)}
    result = []

    def describe(cabinet):
        lines = ["Шифр: " + (cabinet.get("code") or "—")]
        if cabinet.get("name"):
            lines.append("Наименование: " + cabinet["name"])
        lines.append("Комплектов: %d" % len(cabinet.get("komplets") or []))
        if cabinet.get("its_functions"):
            lines.append("Функции: " + ", ".join(cabinet["its_functions"]))
        return "\n".join(lines)

    def refresh():
        needle = query.get().strip().lower()
        visible = []
        for cabinet in cabinets:
            haystack = " ".join([
                cabinet.get("code") or "", cabinet.get("name") or "",
                cabinet.get("title") or "", cabinet.get("group") or "",
                cabinet.get("standard_title") or "",
                ", ".join(cabinet.get("its_functions") or []),
            ]).lower()
            if needle and needle not in haystack:
                continue
            visible.append(cabinet)
        state["visible"] = visible
        listbox.delete(0, tk.END)
        for cabinet in visible:
            listbox.insert(tk.END, komplekts.cabinet_label(cabinet))
        if visible:
            listbox.selection_clear(0, tk.END)
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
        result.extend(state["visible"][index] for index in selection)
        dialog.destroy()

    buttons = tk.Frame(dialog)
    buttons.pack(fill=tk.X, padx=10, pady=(0, 8))
    tk.Button(buttons, text="Отмена", width=10, command=dialog.destroy,
              font=ui_theme.font(9)).pack(side=tk.RIGHT)
    tk.Button(buttons, text="Добавить", width=12, command=accept,
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
    return result


# ---------------------------------------------------------------------------
# Новый стандарт на базе выбранного
# ---------------------------------------------------------------------------
class NewStandardDialog(tk.Toplevel):
    """Копия стандарта с новыми реквизитами, набором шкафов и заменами."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.data = window._data
        self.result = None
        # Все шкафы всех стандартов, а не только текущего тома.
        self.entries = em.load_catalog_cached()
        # Строка списка: («standard», запись каталога стандартов) или
        # («catalog», типовой шкаф каталога редактора).
        self.items = [("standard", entry) for entry in self.entries]
        self.cyphers = [entry["cypher"] for entry in self.entries]
        self.title("Новый стандарт на базе выбранного")
        self.transient(window)
        self.resizable(False, False)
        self._build()
        _place_on_parent(self, window)
        self.grab_set()
        self.bind("<Escape>", lambda event: self.destroy())

    def _build(self):
        form = tk.Frame(self, padx=12, pady=10)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        self.vars = {}
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
            if key == "date" and not var.get():
                var.set(datetime.date.today().strftime("%d.%m.%Y"))
            tk.Entry(form, textvariable=var, font=ui_theme.font(9),
                     width=width).grid(row=row, column=1, sticky="we", pady=3)
            self.vars[key] = var
            row += 1

        tk.Label(form, text="Шкафы нового стандарта:",
                 font=ui_theme.font(9), anchor="w").grid(
                     row=row, column=0, columnspan=2, sticky="w",
                     pady=(8, 3))
        row += 1
        box = tk.Frame(form)
        box.grid(row=row, column=0, columnspan=2, sticky="we")
        scroll = tk.Scrollbar(box, orient="vertical")
        self.listbox = tk.Listbox(box, selectmode="extended", height=5,
                                  font=ui_theme.font(9),
                                  yscrollcommand=scroll.set)
        scroll.config(command=self.listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for kind, payload in self.items:
            self.listbox.insert(tk.END, self._label(kind, payload))
        self.listbox.selection_set(0, tk.END)
        row += 1
        buttons = tk.Frame(form)
        buttons.grid(row=row, column=0, columnspan=2, sticky="w",
                     pady=(4, 8))
        _button(buttons, "Все",
                lambda: self.listbox.selection_set(0, tk.END), side=tk.LEFT)
        _button(buttons, "Ни одного",
                lambda: self.listbox.selection_clear(0, tk.END), side=tk.LEFT)
        _button(buttons, "Из каталога…", self.add_catalog, width=16,
                side=tk.LEFT)
        row += 1

        tk.Label(form, text="Замены (старое => новое, по одной в строке):",
                 font=ui_theme.font(9), anchor="w").grid(
                     row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.replacements = tk.Text(form, height=3, width=64,
                                    font=ui_theme.font(9))
        self.replacements.grid(row=row, column=0, columnspan=2,
                               sticky="we", pady=(3, 6))
        row += 1

        self.renumber = tk.BooleanVar(value=True)
        tk.Checkbutton(form, text="Перенумеровать разделы, таблицы и рисунки",
                       variable=self.renumber, font=ui_theme.font(9),
                       anchor="w").grid(row=row, column=0, columnspan=2,
                                        sticky="w")
        row += 1

        footer = tk.Frame(form)
        footer.grid(row=row, column=0, columnspan=2, sticky="we",
                    pady=(8, 0))
        _button(footer, "Создать…", self.create, width=14, side=tk.RIGHT)
        _button(footer, "Отмена", self.destroy, width=10, side=tk.RIGHT)

    @staticmethod
    def _label(kind, payload):
        if kind == "catalog":
            return "%s — %s [каталог]" % (payload.get("code") or "",
                                          payload.get("name") or "")
        return "%s — %s [%s]" % (payload["cypher"], payload["name"],
                                 payload["volume"])

    @staticmethod
    def _cypher(kind, payload):
        return str(payload.get("cypher") or payload.get("code") or "")

    def add_catalog(self):
        """Дополнить список типовыми шкафами каталога редактора."""
        existing = {em.norm_cypher(self._cypher(kind, payload))
                    for kind, payload in self.items}
        cabinets = [cabinet for cabinet in komplekts.typical_cabinets()
                    if cabinet.get("komplets")
                    and em.norm_cypher(cabinet.get("code")) not in existing]
        chosen = choose_catalog_cabinets(self, cabinets)
        for cabinet in chosen:
            self.items.append(("catalog", cabinet))
            self.cyphers.append(self._cypher("catalog", cabinet))
            self.listbox.insert(tk.END, self._label("catalog", cabinet))
            self.listbox.selection_set(tk.END)
            self.listbox.see(tk.END)

    def create(self):
        meta = {key: var.get().strip() for key, var in self.vars.items()}
        if not meta["code"] or not meta["name"]:
            messagebox.showwarning("Новый стандарт",
                                   "Заполните шифр и наименование.",
                                   parent=self)
            return
        if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", meta["date"] or ""):
            messagebox.showwarning("Новый стандарт",
                                   "Дата введения — в виде ДД.ММ.ГГГГ.",
                                   parent=self)
            return
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showwarning("Новый стандарт",
                                   "Оставьте хотя бы один шкаф.", parent=self)
            return
        chosen = [self.items[index] for index in selected]
        standards = [payload for kind, payload in chosen
                     if kind == "standard"]
        catalog = [payload for kind, payload in chosen if kind == "catalog"]
        keep = [self._cypher(kind, payload) for kind, payload in chosen]
        if len(keep) == len(self.cyphers):
            keep = None
        replacements = [
            line.strip() for line in
            self.replacements.get("1.0", tk.END).splitlines() if line.strip()]
        try:
            # Собрать шкафы всех выбранных стандартов в один источник:
            # переносим формы/рисунки и сводим нумерацию, иначе проверка не пройдёт.
            source = em.merge_cabinets(self.data, standards)
            # Типовые шкафы каталога переносятся вместе с данными: карточка
            # шкафа, комплекты, ИЭУ, измерения и таблицы-формы.
            for cabinet in catalog:
                source = em.add_catalog_cabinet(source, cabinet)["data"]
            result = ns.build(source, meta=meta,
                              replacements=replacements, keep=keep,
                              renumber=self.renumber.get())
        except (ns.StandardError, em.MergeError) as exc:
            messagebox.showerror("Новый стандарт", str(exc), parent=self)
            return
        name = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", " ",
                      meta["code"]).strip() or "standard"
        self.grab_release()
        path = filedialog.asksaveasfilename(
            parent=self, title="Куда сохранить новый стандарт",
            initialdir=es.folder(), initialfile=name + ".json",
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            self.grab_set()
            return
        try:
            ns.write_standard(result["data"], path, overwrite=True)
        except (ns.StandardError, OSError) as exc:
            messagebox.showerror("Новый стандарт",
                                 "Не удалось записать файл:\n%s" % exc,
                                 parent=self)
            self.grab_set()
            return
        messagebox.showinfo("Новый стандарт", ns.report(result, path),
                            parent=self)
        self.result = path
        self.destroy()


# ---------------------------------------------------------------------------
# Точка входа для редактора
# ---------------------------------------------------------------------------
def show(app, path=None):
    """Открыть окно стандартов EA (или вернуть существующее)."""
    return EAStandardWindow(app, path)
