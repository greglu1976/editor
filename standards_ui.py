# -*- coding: utf-8 -*-
"""Окна работы со стандартами для редактора схем.

Здесь живут все tkinter-окна интеграции ``standard_editor``:

* :class:`StandardsWindow` — список стандартов СТО с действиями;
* :func:`open_editor` — редактор изменений (``changes_gui.App``) внутри
  окна редактора схем, а не отдельным процессом;
* :class:`NewStandardWindow` — новый стандарт на основе выбранного;
* :class:`AssemblyWindow` — сборка редакции из всех ``*.изм.txt``;
* :class:`DocxWindow` — отчёт Word по стандарту или редакции.

Логика — в :mod:`standards_editor`; этот модуль только показывает её на
экране. Окна создаются как ``tk.Toplevel`` и автоматически подхватывают
оформление редактора (``ui_theme`` перекрашивает их при появлении).
"""

from __future__ import annotations

import os
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import standards_editor as se
import ui_theme


# ---------------------------------------------------------------------------
# Общие мелочи
# ---------------------------------------------------------------------------
def _toplevel(app, title):
    parent = getattr(app, "root", app)
    window = tk.Toplevel(parent)
    window.title(title)
    window.transient(parent)
    return window


def _button(parent, text, command, width=0, side=tk.LEFT, padx=(0, 4)):
    button = tk.Button(parent, text=text, command=command,
                       font=ui_theme.font(9))
    if width:
        button.config(width=width)
    button.pack(side=side, padx=padx, pady=2)
    return button


def _text_box(parent, height=8):
    frame = tk.Frame(parent)
    scroll = tk.Scrollbar(frame, orient="vertical")
    box = tk.Text(frame, height=height, wrap="word", font=ui_theme.font(9),
                  yscrollcommand=scroll.set)
    scroll.config(command=box.yview)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    box.frame = frame
    return frame, box


def _set_text(box, text):
    box.config(state="normal")
    box.delete("1.0", tk.END)
    if text:
        box.insert("1.0", text)
    box.see(tk.END)
    box.config(state="disabled")


def _get_text(box):
    return box.get("1.0", tk.END).strip()


def _tree(parent, columns, widths, height=12, headings=None):
    frame = tk.Frame(parent)
    scroll = tk.Scrollbar(frame, orient="vertical")
    table = ttk.Treeview(frame, columns=columns, show="headings",
                         height=height, yscrollcommand=scroll.set)
    scroll.config(command=table.yview)
    for column, width in zip(columns, widths):
        table.heading(column, text=(headings or {}).get(column, column))
        table.column(column, width=width, anchor="w")
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    table.frame = frame
    return frame, table


def _size_text(size):
    if not size:
        return "—"
    if size >= 1024 * 1024:
        return "%.1f МБ" % (size / (1024.0 * 1024.0))
    return "%.0f КБ" % (size / 1024.0)


def open_folder(path):
    """Открыть папку в проводнике Windows."""
    if path and os.path.isdir(path):
        try:
            os.startfile(path)                   # noqa: S606
            return True
        except OSError:
            return False
    return False


def _no_tools(app, action=""):
    messagebox.showerror(
        "Стандарты",
        "Папка standard_editor не найдена.\n"
        "Положите её рядом с редактором: %s" % se.FOLDER)
    return None


# ---------------------------------------------------------------------------
# Список стандартов
# ---------------------------------------------------------------------------
STANDARD_COLUMNS = ("файл", "шифр", "шкафы", "таблицы", "изменений",
                    "папка", "размер")
STANDARD_WIDTHS = (250, 250, 70, 80, 90, 110, 80)
STANDARD_HEADINGS = {"файл": "Файл", "шифр": "Шифр стандарта",
                     "шкафы": "Шкафов", "таблицы": "Таблиц",
                     "изменений": "Изменений", "папка": "Папка",
                     "размер": "Размер"}


class StandardsWindow(tk.Toplevel):
    """Список стандартов СТО с кнопками действий."""

    def __init__(self, app):
        super().__init__(getattr(app, "root", app))
        self.app = app
        self.title("Стандарты СТО")
        self.geometry("1120x660")
        self.minsize(900, 520)
        self.transient(getattr(app, "root", app))
        self._items = {}
        self._build()
        self.reload()

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=(8, 2))
        tk.Label(top, text="Папки стандартов:", font=ui_theme.font(9),
                 anchor="w").pack(side=tk.LEFT)
        folders = ", ".join(name for name, _path in se.standard_folders())
        tk.Label(top, text=folders, font=ui_theme.font(9, "bold"),
                 anchor="w").pack(side=tk.LEFT, padx=(6, 0))
        _button(top, "Открыть папку", self._open_folder,
                side=tk.RIGHT, padx=(4, 0))
        _button(top, "Обновить", self.reload, width=10, side=tk.RIGHT)

        hint = ("Стандарт — JSON с реквизитами и таблицами шкафов. "
                "Двойной щелчок открывает его в редакторе изменений.")
        tk.Label(self, text=hint, font=ui_theme.font(8),
                 fg=ui_theme.TEXT_MUTED, anchor="w",
                 justify="left").pack(fill=tk.X, padx=10, pady=(0, 4))

        frame, self.tree = _tree(self, STANDARD_COLUMNS, STANDARD_WIDTHS,
                                 height=13, headings=STANDARD_HEADINGS)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        self.tree.bind("<Double-1>", lambda event: self._edit_selected())
        self.tree.bind("<Return>", lambda event: self._edit_selected())

        actions = tk.Frame(self)
        actions.pack(fill=tk.X, padx=10)
        _button(actions, "Редактор изменений…", self._edit_selected, width=22)
        _button(actions, "Новый на основе выбранного…",
                self._new_standard, width=28)
        _button(actions, "Собрать редакцию…", self._assemble, width=20)
        _button(actions, "Проверить изменения", self._check_changes, width=20)
        _button(actions, "Отчёт DOCX…", self._docx, width=16)

        log_frame, self.log = _text_box(self, height=7)
        log_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(6, 6))
        _set_text(self.log, "Готово.")

        footer = tk.Frame(self)
        footer.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(footer, text="F5 — обновить список, Esc — закрыть",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED).pack(
                     side=tk.LEFT)
        _button(footer, "Закрыть", self.destroy, width=10, side=tk.RIGHT)
        self.bind("<F5>", lambda event: self.reload())
        self.bind("<Escape>", lambda event: self.destroy())

    # -------------------------------------------------------------- данные
    def reload(self):
        """Перечитать папки стандартов."""
        self._items.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        try:
            rows = se.standards()
        except Exception as exc:                    # noqa: BLE001
            _set_text(self.log, "Не удалось прочитать стандарты:\n%s" % exc)
            return
        for row in rows:
            iid = self.tree.insert("", tk.END, values=(
                row["имя"], row["шифр"], row["шкафов"], row["таблиц"],
                row["изменений"], row["папка"], _size_text(row["размер"])))
            self._items[iid] = row
        _set_text(self.log, "Стандартов: %d. Папка инструментов: %s"
                  % (len(rows), se.folder()))

    def selected(self):
        """Выбранный стандарт (dict) или None."""
        selection = self.tree.selection()
        if not selection:
            children = self.tree.get_children()
            if not children:
                return None
            selection = (children[0],)
        return self._items.get(selection[0])

    def paths(self):
        """Пути всех стандартов в порядке списка (для тестов)."""
        return [self._items[iid]["путь"] for iid in self.tree.get_children()]

    # ------------------------------------------------------------ действия
    def _open_folder(self):
        open_folder(se.folder())

    def _edit_selected(self):
        item = self.selected()
        window = open_editor(self.app, item["путь"] if item else None)
        if window is not None:
            _set_text(self.log, "Открыт редактор изменений: %s"
                      % (item["имя"] if item else "база по умолчанию"))

    def _new_standard(self):
        item = self.selected()
        show_new_standard(self.app, item["путь"] if item else None)

    def _assemble(self):
        item = self.selected()
        show_assembly(self.app, item["путь"] if item else None)

    def _check_changes(self):
        item = self.selected()
        base = item["путь"] if item else se.default_base()
        folder = se.CHANGES_FOLDER
        compiled, errors = se.compile_changes(folder)
        lines = ["База: %s" % os.path.basename(base),
                 "Изменения: %s" % folder,
                 "Файлов: %d, разобрано: %d"
                 % (len(se.change_files(folder)), len(compiled)), ""]
        for path, change_set, warnings in compiled:
            lines.append("%-24s %s v%s, операций %d"
                         % (os.path.basename(path), change_set["Идентификатор"],
                            change_set.get("Версия", 1),
                            len(change_set.get("Изменения") or [])))
            lines.extend("    ! %s" % warning for warning in warnings)
        if errors:
            lines.append("")
            lines.extend("ОШИБКА %s" % error for error in errors)
        if not errors and base:
            result = se.assembly(base, folder)
            lines.append("")
            lines.append("Сборка: %s" % ("OK" if result["ok"]
                                         else (result["ошибка"] or "ошибки")))
            if result["ok"]:
                lines.append("Изменений применено: %d, операций: %d"
                             % (result["изменений"], result["операций"]))
        _set_text(self.log, "\n".join(lines))

    def _docx(self):
        item = self.selected()
        show_docx(self.app, item["путь"] if item else None)


# ---------------------------------------------------------------------------
# Редактор изменений
# ---------------------------------------------------------------------------
def open_editor(app, base_path=None):
    """Открыть ``changes_gui.App`` в отдельном окне редактора схем."""
    if not se.available():
        return _no_tools(app)
    parent = getattr(app, "root", app)
    try:
        gui = se.module("changes_gui")
    except Exception as exc:                        # noqa: BLE001
        messagebox.showerror(
            "Редактор изменений",
            "Не удалось загрузить standard_editor:\n%s\n\n%s"
            % (exc, traceback.format_exc()[-1200:]), parent=parent)
        return None
    window = tk.Toplevel(parent)
    window.title("Редактор изменений стандарта")
    try:
        editor = gui.App(window)
    except Exception as exc:                        # noqa: BLE001
        window.destroy()
        messagebox.showerror(
            "Редактор изменений",
            "Окно редактора не построилось:\n%s\n\n%s"
            % (exc, traceback.format_exc()[-1200:]), parent=parent)
        return None
    window._std_editor = editor
    target = base_path or se.default_base()
    if target and os.path.isfile(target):
        try:
            editor.load_base(target)
            # Заготовка изменения должна ссылаться на эту базу, а не на
            # ту, что редактор загрузил при старте.
            editor.new_doc()
            editor.set_title()
        except Exception:                           # noqa: BLE001
            pass
        window.title("Редактор изменений стандарта — %s"
                     % os.path.basename(target))
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    return window


# ---------------------------------------------------------------------------
# Новый стандарт на основе выбранного
# ---------------------------------------------------------------------------
class NewStandardWindow(tk.Toplevel):
    """Копия выбранного стандарта с новыми реквизитами и набором шкафов."""

    META_FIELDS = ("Обозначение стандарта", "Шифр стандарта", "Дата введения",
                   "Принадлежность стандарта", "Область применения стандарта")
    META_LABELS = {"Обозначение стандарта": "Обозначение",
                   "Шифр стандарта": "Шифр",
                   "Дата введения": "Дата введения",
                   "Принадлежность стандарта": "Принадлежность",
                   "Область применения стандарта": "Область применения"}

    def __init__(self, app, source_path=None):
        super().__init__(getattr(app, "root", app))
        self.app = app
        self.title("Новый стандарт на основе выбранного")
        self.geometry("1040x760")
        self.minsize(880, 640)
        self.transient(getattr(app, "root", app))
        self.result = None
        self._sources = se.standards(with_changes=False)
        self._by_label = {self._label(item): item for item in self._sources}
        self.var_meta = {name: tk.StringVar() for name in self.META_FIELDS}
        self.var_renumber = tk.BooleanVar(value=True)
        self._build()
        start = source_path or se.default_base()
        if start:
            for label, item in self._by_label.items():
                if os.path.normcase(os.path.abspath(item["путь"])) == \
                        os.path.normcase(os.path.abspath(start)):
                    self.var_source.set(label)
                    self._load_source()
                    break
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ UI
    def _label(self, item):
        if item["шифр"]:
            return "%s — %s" % (item["шифр"], item["имя"])
        return item["имя"]

    def _build(self):
        pad = {"padx": 10}
        source_row = tk.Frame(self)
        source_row.pack(fill=tk.X, pady=(8, 2), **pad)
        tk.Label(source_row, text="Исходный стандарт:",
                 font=ui_theme.font(9)).pack(side=tk.LEFT)
        self.var_source = tk.StringVar()
        self.cmb_source = ttk.Combobox(
            source_row, textvariable=self.var_source, state="readonly",
            values=list(self._by_label), width=78, font=ui_theme.font(9))
        self.cmb_source.pack(side=tk.LEFT, padx=(6, 4))
        self.cmb_source.bind("<<ComboboxSelected>>",
                             lambda event: self._load_source())
        _button(source_row, "Обзор…", self._browse_source, width=8)

        meta = tk.LabelFrame(self, text=" Реквизиты ", padx=8, pady=6,
                             font=ui_theme.font(9))
        meta.pack(fill=tk.X, **pad)
        self.meta_entries = {}
        for row, name in enumerate(self.META_FIELDS):
            tk.Label(meta, text=self.META_LABELS[name] + ":",
                     font=ui_theme.font(9), anchor="w", width=18).grid(
                         row=row, column=0, sticky="w", pady=2)
            entry = tk.Entry(meta, textvariable=self.var_meta[name],
                             font=ui_theme.font(9))
            entry.grid(row=row, column=1, sticky="we", padx=(4, 0), pady=2)
            self.meta_entries[name] = entry
        meta.columnconfigure(1, weight=1)

        cabinets = tk.LabelFrame(self, text=" Шкафы ", padx=8, pady=6,
                                 font=ui_theme.font(9))
        cabinets.pack(fill=tk.BOTH, expand=True, **pad)
        frame, self.tree = _tree(
            cabinets, ("ok", "шифр", "раздел", "таблиц", "строк"),
            (40, 260, 90, 80, 90), height=8,
            headings={"ok": "✓", "шифр": "Шкаф", "раздел": "Раздел",
                      "таблиц": "Таблиц", "строк": "Строк"})
        frame.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda event: self._toggle())
        self.tree.bind("<space>", lambda event: self._toggle())
        self.tree.bind("<Button-1>", self._on_click, add="+")
        row = tk.Frame(cabinets)
        row.pack(fill=tk.X, pady=(4, 0))
        _button(row, "Все", self._select_all, width=8)
        _button(row, "Ничего", self._select_none, width=8)
        tk.Label(row, text="Снятый шкаф уйдёт из копии, разделы 5.2…5.N "
                           "перенумеруются.",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED).pack(
                     side=tk.LEFT, padx=8)

        replacements = tk.LabelFrame(self, text=" Замены (необязательно) ",
                                     padx=8, pady=6, font=ui_theme.font(9))
        replacements.pack(fill=tk.X, **pad)
        tk.Label(replacements,
                 text="По одной в строке: «старое => новое». Меняются и "
                      "ключи, и значения (один проход, без цепочек).",
                 font=ui_theme.font(8), fg=ui_theme.TEXT_MUTED,
                 anchor="w").pack(fill=tk.X)
        frame, self.text_replacements = _text_box(replacements, height=3)
        frame.pack(fill=tk.X, pady=(2, 0))

        options = tk.Frame(self)
        options.pack(fill=tk.X, pady=(4, 2), **pad)
        tk.Checkbutton(options, text="Перенумеровать разделы 5.2…5.N",
                       variable=self.var_renumber,
                       font=ui_theme.font(9)).pack(side=tk.LEFT)

        footer = tk.Frame(self)
        footer.pack(fill=tk.X, **pad)
        _button(footer, "Проверить", self.preview, width=14)
        _button(footer, "Создать…", self.create, width=14)
        _button(footer, "Закрыть", self.destroy, width=10, side=tk.RIGHT)

        log_frame, self.log = _text_box(self, height=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 8))

    # -------------------------------------------------------------- данные
    def source_item(self):
        return self._by_label.get(self.var_source.get())

    def _browse_source(self):
        path = filedialog.askopenfilename(
            title="Исходный стандарт", initialdir=se.folder(),
            filetypes=[("JSON стандарта", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        for label, item in self._by_label.items():
            if os.path.normcase(os.path.abspath(item["путь"])) == \
                    os.path.normcase(os.path.abspath(path)):
                self.var_source.set(label)
                self._load_source()
                return
        # файл вне стандартных папок
        try:
            data = se.load(path)
        except Exception as exc:                    # noqa: BLE001
            messagebox.showerror("Стандарт", "Не удалось прочитать:\n%s" % exc,
                                 parent=self)
            return
        if not isinstance(data.get("Содержимое стандарта"), dict):
            messagebox.showerror("Стандарт", "Это не стандарт: нет раздела "
                                             "«Содержимое стандарта».", parent=self)
            return
        label = se.standard_info(data, path)["шифр"] or os.path.basename(path)
        self._by_label[label] = {"путь": path, "шифр": label}
        self.cmb_source.config(values=list(self._by_label))
        self.var_source.set(label)
        self._load_source()

    def _load_source(self):
        item = self.source_item()
        if not item:
            return
        try:
            data = se.load(item["путь"])
        except Exception as exc:                    # noqa: BLE001
            _set_text(self.log, "Не удалось прочитать стандарт:\n%s" % exc)
            return
        for name in self.META_FIELDS:
            self.var_meta[name].set(str(data.get(name) or ""))
        self.fill_cabinets(data)
        _set_text(self.log, "Источник: %s\n%s"
                  % (os.path.basename(item["путь"]),
                     "\n".join("%-16s %s" % (label, self.var_meta[name].get())
                               for name, label in
                               ((name, self.META_LABELS[name])
                                for name in self.META_FIELDS))))

    def fill_cabinets(self, data, keep=None):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        keep_set = ({str(code) for code in keep} if keep else None)
        for cabinet in se.cabinets_of(data):
            checked = ("✓" if keep_set is None
                       or cabinet["шифр"] in keep_set else "·")
            self.tree.insert("", tk.END, values=(
                checked, cabinet["шифр"], cabinet["раздел"],
                cabinet["таблиц"], cabinet["строк"]))

    # ------------------------------------------------------------ шкафы
    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell":
            self._toggle()

    def _toggle(self):
        selection = self.tree.selection()
        for iid in selection:
            values = list(self.tree.item(iid, "values"))
            values[0] = "·" if values[0] == "✓" else "✓"
            self.tree.item(iid, values=values)

    def _select_all(self):
        for iid in self.tree.get_children():
            values = list(self.tree.item(iid, "values"))
            values[0] = "✓"
            self.tree.item(iid, values=values)

    def _select_none(self):
        for iid in self.tree.get_children():
            values = list(self.tree.item(iid, "values"))
            values[0] = "·"
            self.tree.item(iid, values=values)

    def checked_cabinets(self):
        """Шифры отмеченных шкафов (все — если отмечены все)."""
        codes = []
        for iid in self.tree.get_children():
            values = self.tree.item(iid, "values")
            if values and values[0] == "✓":
                codes.append(values[1])
        return codes

    def replacements(self):
        items = []
        for line in _get_text(self.text_replacements).splitlines():
            line = line.strip()
            if line:
                items.append(line)
        return items

    def collect(self):
        """Параметры для :func:`standards_editor.build_standard`."""
        item = self.source_item()
        if not item:
            return None
        meta = {name: self.var_meta[name].get().strip()
                for name in self.META_FIELDS}
        codes = self.checked_cabinets()
        total = len(self.tree.get_children())
        keep = None if len(codes) == total else codes
        return {"source_path": item["путь"], "meta": meta, "keep": keep,
                "replacements": self.replacements(),
                "renumber": bool(self.var_renumber.get())}

    # ------------------------------------------------------------ действия
    def preview(self):
        params = self.collect()
        if not params:
            messagebox.showwarning("Новый стандарт",
                                   "Выберите исходный стандарт.", parent=self)
            return None
        if params["keep"] is not None and not params["keep"]:
            messagebox.showwarning("Новый стандарт",
                                   "Не отмечено ни одного шкафа.", parent=self)
            return None
        result = se.build_standard(params["source_path"], **{
            key: params[key] for key in
            ("meta", "replacements", "keep", "renumber")})
        self.result = result
        text = result.get("отчёт") or ""
        if result.get("ошибка"):
            text += "\n\nОШИБКА: %s" % result["ошибка"]
        _set_text(self.log, text)
        return result

    def create(self):
        result = self.preview()
        if result is None:
            return None
        if not result.get("ok"):
            messagebox.showerror(
                "Новый стандарт",
                "Проверка не пройдена — файл не записан.\n%s"
                % (result.get("ошибка") or "см. отчёт"), parent=self)
            return None
        item = self.source_item()
        code = self.var_meta["Шифр стандарта"].get().strip() or "стандарт"
        suggested = os.path.join(se.folder(), "%s.json" % code)
        path = filedialog.asksaveasfilename(
            title="Куда записать новый стандарт", initialdir=se.folder(),
            initialfile=os.path.basename(suggested), defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return None
        overwrite = False
        if os.path.exists(path):
            if not messagebox.askyesno("Новый стандарт",
                                       "Файл существует. Заменить?\n%s" % path,
                                       parent=self):
                return None
            overwrite = True
        saved = se.new_standard(
            item["путь"], path,
            meta={name: self.var_meta[name].get().strip()
                  for name in self.META_FIELDS},
            replacements=self.replacements(),
            keep=(None if len(self.checked_cabinets())
                  == len(self.tree.get_children()) else self.checked_cabinets()),
            renumber=bool(self.var_renumber.get()), overwrite=overwrite)
        _set_text(self.log, (saved.get("отчёт") or "") +
                  ("\n\nФайл: %s (%.1f КБ)"
                   % (path, saved.get("размер", 0) / 1024.0)
                   if saved.get("ok") else
                   "\n\nОШИБКА: %s" % (saved.get("ошибка") or "")))
        if saved.get("ok"):
            messagebox.showinfo("Новый стандарт",
                                "Стандарт записан:\n%s" % path, parent=self)
            self.result = saved
            if messagebox.askyesno(
                    "Новый стандарт",
                    "Открыть новый стандарт в редакторе изменений?",
                    parent=self):
                open_editor(self.app, path)
        return saved


# ---------------------------------------------------------------------------
# Сборка редакции
# ---------------------------------------------------------------------------
class AssemblyWindow(tk.Toplevel):
    """База + все изменения каталога → JSON редакции и отчёт."""

    def __init__(self, app, base_path=None):
        super().__init__(getattr(app, "root", app))
        self.app = app
        self.title("Сборка редакции стандарта")
        self.geometry("1000x720")
        self.minsize(840, 600)
        self.transient(getattr(app, "root", app))
        self.result = None
        self._build()
        self.var_base.set(base_path or se.default_base())
        self.var_changes.set(se.CHANGES_FOLDER)
        self.var_out.set(os.path.join(se.ROOT, "output",
                                      "Редакция_с_изменениями.json"))
        self.refresh_changes()

    def _build(self):
        pad = {"padx": 10}
        rows = (("База:", "base", self._browse_base, "Стандарт JSON"),
                ("Изменения:", "changes", self._browse_changes,
                 "Каталог с *.изм.txt"),
                ("Результат:", "out", self._browse_out, "JSON редакции"))
        grid = tk.Frame(self)
        grid.pack(fill=tk.X, pady=(8, 2), **pad)
        self.var_base = tk.StringVar()
        self.var_changes = tk.StringVar()
        self.var_out = tk.StringVar()
        entries = {}
        for row, (label, key, command, _hint) in enumerate(rows):
            tk.Label(grid, text=label, font=ui_theme.font(9), anchor="w",
                     width=12).grid(row=row, column=0, sticky="w", pady=2)
            entry = tk.Entry(grid, textvariable=getattr(self, "var_" + key),
                             font=ui_theme.font(9))
            entry.grid(row=row, column=1, sticky="we", padx=(4, 4), pady=2)
            tk.Button(grid, text="Обзор…", command=command, width=8,
                      font=ui_theme.font(9)).grid(row=row, column=2, pady=2)
            entries[key] = entry
        grid.columnconfigure(1, weight=1)

        options = tk.Frame(self)
        options.pack(fill=tk.X, **pad)
        self.var_strict = tk.BooleanVar(value=False)
        self.var_ignore_hash = tk.BooleanVar(value=False)
        tk.Checkbutton(options, text="строгий режим", variable=self.var_strict,
                       font=ui_theme.font(9)).pack(side=tk.LEFT)
        tk.Checkbutton(options, text="игнорировать хэш базы",
                       variable=self.var_ignore_hash,
                       font=ui_theme.font(9)).pack(side=tk.LEFT, padx=8)

        self.lbl_changes = tk.Label(self, text="", font=ui_theme.font(8),
                                    fg=ui_theme.TEXT_MUTED, anchor="w",
                                    justify="left")
        self.lbl_changes.pack(fill=tk.X, **pad)

        frame, self.log = _text_box(self, height=18)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 6))

        footer = tk.Frame(self)
        footer.pack(fill=tk.X, **pad)
        _button(footer, "Проверить файлы", self.check_changes, width=18)
        _button(footer, "Собрать", self.assemble, width=14)
        _button(footer, "DOCX…", self.make_docx, width=12)
        _button(footer, "Закрыть", self.destroy, width=10, side=tk.RIGHT)

    # -------------------------------------------------------------- данные
    def _browse_base(self):
        path = filedialog.askopenfilename(
            title="Базовый стандарт", initialdir=se.folder(),
            filetypes=[("JSON стандарта", "*.json"), ("Все файлы", "*.*")])
        if path:
            self.var_base.set(path)

    def _browse_changes(self):
        path = filedialog.askdirectory(title="Каталог изменений",
                                       initialdir=self.var_changes.get()
                                       or se.CHANGES_FOLDER)
        if path:
            self.var_changes.set(path)
            self.refresh_changes()

    def _browse_out(self):
        path = filedialog.asksaveasfilename(
            title="Куда записать редакцию", initialdir=os.path.dirname(
                self.var_out.get()) or se.ROOT, defaultextension=".json",
            initialfile=os.path.basename(self.var_out.get()) or "Редакция.json",
            filetypes=[("JSON", "*.json")])
        if path:
            self.var_out.set(path)

    def refresh_changes(self):
        folder = self.var_changes.get() or se.CHANGES_FOLDER
        rows = se.changes_summary(folder)
        if not rows:
            text = "В каталоге нет файлов *.изм.txt: %s" % folder
        else:
            text = ("Файлов изменений: %d — %s"
                    % (len(rows), ", ".join(
                        "%s v%s" % (row["идентификатор"] or row["имя"],
                                    row["версия"] or "?") for row in rows)))
        self.lbl_changes.config(text=text)

    # ------------------------------------------------------------ действия
    def check_changes(self):
        compiled, errors = se.compile_changes(self.var_changes.get())
        lines = ["Каталог: %s" % self.var_changes.get(),
                 "Разобрано файлов: %d" % len(compiled), ""]
        for path, change_set, warnings in compiled:
            lines.append("%-26s %s v%s, операций %d"
                         % (os.path.basename(path), change_set["Идентификатор"],
                            change_set.get("Версия", 1),
                            len(change_set.get("Изменения") or [])))
            lines.extend("    ! %s" % warning for warning in warnings)
        for error in errors:
            lines.append("ОШИБКА %s" % error)
        if not compiled and not errors:
            lines.append("Изменений не найдено.")
        _set_text(self.log, "\n".join(lines))
        return compiled, errors

    def assemble(self):
        base = self.var_base.get().strip()
        folder = self.var_changes.get().strip()
        if not base or not os.path.isfile(base):
            messagebox.showwarning("Сборка", "Укажите файл базового стандарта.",
                                   parent=self)
            return None
        result = se.assembly(base, folder,
                             strict=bool(self.var_strict.get()),
                             ignore_hash=bool(self.var_ignore_hash.get()))
        self.result = result
        text = result.get("отчёт") or ""
        if result.get("ошибка"):
            text += "\n\nОШИБКА: %s" % result["ошибка"]
        if result.get("ok"):
            out = self.var_out.get().strip()
            try:
                size = se.write_json(result["data"], out)
            except OSError as exc:
                text += "\n\nНе удалось записать %s: %s" % (out, exc)
            else:
                text += "\n\nРедакция записана: %s (%.1f КБ)" % (
                    out, size / 1024.0)
        _set_text(self.log, text)
        return result

    def make_docx(self):
        if self.result and self.result.get("ok"):
            show_docx(self.app, self.var_out.get().strip() or None,
                      data=self.result["data"])
            return
        show_docx(self.app, self.var_base.get().strip() or None)


# ---------------------------------------------------------------------------
# Отчёт DOCX
# ---------------------------------------------------------------------------
class DocxWindow(tk.Toplevel):
    """Отчёт Word по стандарту или собранной редакции."""

    def __init__(self, app, json_path=None, data=None):
        super().__init__(getattr(app, "root", app))
        self.app = app
        self.title("Отчёт DOCX по стандарту")
        self.geometry("940x640")
        self.minsize(780, 520)
        self.transient(getattr(app, "root", app))
        self._data = data
        self.var_json = tk.StringVar(value=json_path or "")
        self.var_out = tk.StringVar(value=os.path.join(
            se.ROOT, "output", "Отчёт_стандарта.docx"))
        self.var_toc = tk.BooleanVar(value=True)
        self._build()
        self.hint()

    def _build(self):
        pad = {"padx": 10}
        grid = tk.Frame(self)
        grid.pack(fill=tk.X, pady=(8, 4), **pad)
        tk.Label(grid, text="JSON:", font=ui_theme.font(9), anchor="w",
                 width=8).grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(grid, textvariable=self.var_json,
                 font=ui_theme.font(9)).grid(row=0, column=1, sticky="we",
                                             padx=4, pady=2)
        tk.Button(grid, text="Обзор…", command=self._browse_json, width=8,
                  font=ui_theme.font(9)).grid(row=0, column=2, pady=2)
        tk.Label(grid, text="DOCX:", font=ui_theme.font(9), anchor="w",
                 width=8).grid(row=1, column=0, sticky="w", pady=2)
        tk.Entry(grid, textvariable=self.var_out,
                 font=ui_theme.font(9)).grid(row=1, column=1, sticky="we",
                                             padx=4, pady=2)
        tk.Button(grid, text="Обзор…", command=self._browse_out, width=8,
                  font=ui_theme.font(9)).grid(row=1, column=2, pady=2)
        grid.columnconfigure(1, weight=1)

        options = tk.Frame(self)
        options.pack(fill=tk.X, **pad)
        tk.Checkbutton(options, text="Оглавление", variable=self.var_toc,
                       font=ui_theme.font(9)).pack(side=tk.LEFT)
        self.lbl_python = tk.Label(options, text="", font=ui_theme.font(8),
                                   fg=ui_theme.TEXT_MUTED, anchor="w")
        self.lbl_python.pack(side=tk.LEFT, padx=10)

        frame, self.log = _text_box(self, height=16)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 6))

        footer = tk.Frame(self)
        footer.pack(fill=tk.X, **pad)
        _button(footer, "Построить", self.build, width=14)
        _button(footer, "Открыть папку", self._open_folder, width=14)
        _button(footer, "Закрыть", self.destroy, width=10, side=tk.RIGHT)

    def hint(self):
        interpreter = se.docx_interpreter()
        if interpreter:
            text = "DOCX строит: %s" % interpreter
        else:
            text = ("python-docx не найден — установите: \"%s\" -m pip "
                    "install python-docx" % sys.executable)
        self.lbl_python.config(text=text)

    def _browse_json(self):
        path = filedialog.askopenfilename(
            title="JSON стандарта или редакции", initialdir=se.folder(),
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if path:
            self.var_json.set(path)
            self._data = None

    def _browse_out(self):
        path = filedialog.asksaveasfilename(
            title="Куда записать отчёт", defaultextension=".docx",
            initialdir=os.path.dirname(self.var_out.get()) or se.ROOT,
            initialfile=os.path.basename(self.var_out.get()) or "Отчёт.docx",
            filetypes=[("Word", "*.docx")])
        if path:
            self.var_out.set(path)

    def _open_folder(self):
        open_folder(os.path.dirname(os.path.abspath(self.var_out.get())))

    def build(self):
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning("DOCX", "Укажите файл отчёта.", parent=self)
            return None
        data = self._data
        if data is None:
            path = self.var_json.get().strip()
            if not path or not os.path.isfile(path):
                messagebox.showwarning("DOCX",
                                       "Выберите JSON стандарта или редакции.",
                                       parent=self)
                return None
            try:
                data = se.load(path)
            except Exception as exc:                # noqa: BLE001
                messagebox.showerror("DOCX", "Не удалось прочитать JSON:\n%s"
                                     % exc, parent=self)
                return None
        result = se.build_docx(data, out, toc=bool(self.var_toc.get()))
        if result["ok"]:
            stats = result.get("статистика") or {}
            _set_text(self.log,
                      "Отчёт готов: %s\nшкафов %s, комплектов %s, "
                      "таблиц %s, строк %s\nинтерпретатор: %s"
                      % (out, stats.get("cabinets"), stats.get("complects"),
                         stats.get("tables"), stats.get("rows"),
                         result.get("интерпретатор")))
            messagebox.showinfo("DOCX", "Отчёт готов:\n%s" % out, parent=self)
        else:
            _set_text(self.log, "ОШИБКА DOCX:\n%s" % result.get("ошибка"))
            messagebox.showerror("DOCX", result.get("ошибка") or "ошибка",
                                 parent=self)
        return result


# ---------------------------------------------------------------------------
# Точки входа для ленты
# ---------------------------------------------------------------------------
def show_standards(app):
    """Окно «Стандарты…»."""
    if not se.available():
        return _no_tools(app)
    return StandardsWindow(app)


def show_new_standard(app, source_path=None):
    """Окно «Новый стандарт…»."""
    if not se.available():
        return _no_tools(app)
    return NewStandardWindow(app, source_path)


def show_assembly(app, base_path=None):
    """Окно «Собрать редакцию…»."""
    if not se.available():
        return _no_tools(app)
    return AssemblyWindow(app, base_path)


def show_docx(app, json_path=None, data=None):
    """Окно «Отчёт DOCX…»."""
    if not se.available():
        return _no_tools(app)
    return DocxWindow(app, json_path, data=data)
