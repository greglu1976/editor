# -*- coding: utf-8 -*-
"""Графический редактор изменений стандарта (tkinter).

Визуальная оболочка над тем же текстовым форматом `*.изм.txt`, что и
`changes_editor.py`. Ничего не изобретает заново: GUI собирает обычный
текст изменения, а проверка/сборка идут через `changes_editor` и
`apply_changes`. Поэтому один и тот же файл можно править и в Блокноте,
и в этом окне.

    Запуск:  python changes_gui.py
        или  py -3.13 changes_gui.py
        или  run_changes_gui.bat  (двойной щелчок)

Если в текущем Python нет tkinter, скрипт сам найдёт интерпретатор с
tkinter (через `py -0p`) и перезапустится под ним.

Что умеет
    * дерево базового JSON с ленивой подгрузкой (1.9 МБ / 100+ таблиц),
      поиск по ключам и значениям, просмотр текущего значения узла;
    * динамическая таблица выбранного узла: столбцы собираются из полей
      строк, ячейки редактируются двойным щелчком (F2 — редактировать,
      Delete — удалить строку), можно добавлять строки и столбцы;
      кнопка «→ В операции» превращает правки в обычные блоки `*.изм.txt`;
    * взятие пути из дерева сразу в виде DSL (`шкаф=... / ... / №=2`)
      и подстановка текущего значения в `БЫЛО`;
    * дублирование любого узла базы («Дублировать узел»): копия встаёт
      рядом с источником, её ключ и содержимое можно сразу поправить
      заменами (`431.02-0 => 431.04-0`, `Таблица 5.3. => Таблица 5.4.`),
      перенумеровать строки и открыть отдельное окно правки копии;
    * создание нового стандарта на основе выбранного (меню «База»):
      копия JSON с новыми реквизитами, набором шкафов и заменами кодов;
      исходный файл не меняется;
    * шапка изменения, список операций, форма операции, вкладка с живым
      текстом `*.изм.txt` (можно править и применить обратно);
    * проверка путей по базе, сборка редакции со всеми `*.изм.txt`
      каталога, журнал операций, сохранение JSON и отчёта DOCX.

Структура окна: слева дерево стандарта и таблица узла, в центре список
операций, справа формы (Шапка / Операция / Текст), снизу журнал.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
from collections import OrderedDict
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# tkinter может отсутствовать в «основном» Python (например, во встроенном
# интерпретаторе WorkBuddy). Найдём любой интерпретатор, где он есть.
# ---------------------------------------------------------------------------
def _ensure_tkinter():
    try:
        import tkinter  # noqa: F401
        return
    except ImportError:
        pass
    candidates = []
    try:
        out = subprocess.check_output(["py", "-0p"], text=True,
                                      stderr=subprocess.DEVNULL, timeout=10)
        for line in out.splitlines():
            m = re.search(r"([A-Za-z]:[\\/][^\s]*pythonw?\.exe)", line, re.I)
            if m:
                candidates.append(m.group(1))
    except Exception:
        pass
    candidates += [r"C:\Python%d\python.exe" % m
                   for m in (314, 313, 312, 311, 310, 39, 38)]
    seen = set()
    me = os.path.normcase(os.path.abspath(sys.executable))
    for exe in candidates:
        exe = os.path.normpath(exe)
        key = os.path.normcase(os.path.abspath(exe))
        if key in seen or not os.path.isfile(exe) or key == me:
            continue
        seen.add(key)
        try:
            rc = subprocess.run([exe, "-c", "import tkinter"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=10).returncode
            if rc == 0:
                os.execv(exe, [exe, os.path.abspath(__file__)] + sys.argv[1:])
        except Exception:
            continue
    sys.stderr.write(
        "Не найден Python с модулем tkinter.\n"
        "Установите Python с python.org или запустите:\n"
        r"  C:\Python313\python.exe changes_gui.py" "\n")
    sys.exit(1)


_ensure_tkinter()

import tkinter as tk  # noqa: E402
from tkinter import (filedialog, messagebox, scrolledtext,  # noqa: E402
                     simpledialog, ttk)

import apply_changes as ac  # noqa: E402
import changes_editor as ce  # noqa: E402
import make_standard as ms  # noqa: E402
import node_table as nt  # noqa: E402

BASE_DEFAULT = os.path.join(ROOT, "СТО 56947007-33.040.20.279-2019.json")
CHANGES_DEFAULT = os.path.join(ROOT, "changes_text")


def _place_over_parent(window, parent):
    """Поставить окно на тот же монитор, что и родитель.

    Без явных координат оконный менеджер ставит новое окно на основной
    монитор, даже если редактор открыт на другом.
    """
    try:
        window.update_idletasks()
        width = max(window.winfo_width(), window.winfo_reqwidth())
        height = max(window.winfo_height(), window.winfo_reqheight())
        x = parent.winfo_rootx() + max(
            0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(
            0, (parent.winfo_height() - height) // 4)
        window.geometry("+%d+%d" % (x, y))
    except tk.TclError:
        pass


HEADER_ORDER = list(ce.HEADER.keys())
VERBS = ["ЗАМЕНИТЬ", "ИЗМЕНИТЬ ПОЛЯ", "ДОБАВИТЬ", "ДУБЛИРОВАТЬ",
         "ОТМЕНИТЬ", "УДАЛИТЬ", "ПЕРЕИМЕНОВАТЬ"]
VERB_ALIASES = {"OVERRIDE": "ЗАМЕНИТЬ", "NEW": "ДОБАВИТЬ", "COPY": "ДУБЛИРОВАТЬ",
                "DEPRECATED": "ОТМЕНИТЬ", "DELETE": "УДАЛИТЬ",
                "RENAME": "ПЕРЕИМЕНОВАТЬ"}
HEADER_HINTS = {
    "ИЗМЕНЕНИЕ": "Идентификатор изменения (одинаковый у всех версий)",
    "ВЕРСИЯ": "Номер версии этого изменения",
    "ДАТА": "ГГГГ-ММ-ДД",
    "ПОРЯДОК": "Порядок применения (чем меньше, тем раньше)",
    "СТАТУС": "действует / отменено",
    "НАЗВАНИЕ": "Краткое описание",
    "ОСНОВАНИЕ": "Приказ, распоряжение",
    "БАЗА": "Шифр базового стандарта",
    "ХЭШ": "SHA-256 файла базы (заполняется автоматически)",
    "ЗАМЕНЯЕТ": "Идентификаторы через запятую",
}


def shorten(s, n=100):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def one_line(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def seg_key(key, value):
    """Сегмент пути для узла-объекта: шкаф адресуется по «Шифр шкафа»."""
    if (isinstance(value, dict) and "Таблицы" in value
            and "Описание шкафа" in value and "Шифр шкафа" in value):
        return {"@where": {"Шифр шкафа": str(value["Шифр шкафа"])}}
    return key


def seg_idx(i, value):
    if isinstance(value, dict) and "№" in value:
        return {"№": str(value["№"])}
    return {"@index": i}


def segkey(seg):
    if isinstance(seg, dict):
        return json.dumps(seg, ensure_ascii=False, sort_keys=True)
    return "s:" + str(seg)


def label_idx(i, value):
    if isinstance(value, dict):
        for k in ("№", "Краткое наименование ФК", "Наименование",
                  "Параметр", "Сигнал", "Аналоговая цепь"):
            if isinstance(value.get(k), (str, int, float)) and str(value[k]):
                return "[%d] %s: %s" % (i, k, value[k])
        for k, v in value.items():
            if isinstance(v, str) and v:
                return "[%d] %s: %s" % (i, k, v)
    return "[%d] %s" % (i, shorten(value, 60))


def split_first(line):
    """Первая строка операции -> (глагол, путь)."""
    s = line.strip()
    m = re.match(r"^(ИЗМЕНИТЬ\s+ПОЛЯ)\s+(.*)$", s, re.I)
    if m:
        return "ИЗМЕНИТЬ ПОЛЯ", m.group(2).strip()
    verb, _, rest = s.partition(" ")
    return verb.upper(), rest.strip()


def split_document(text):
    """Текст -> (преамбула, OrderedDict шапки, список блоков операций)."""
    preamble, header, blocks = [], OrderedDict(), []
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            if cur is None:
                preamble.append("")
            continue
        if s.startswith("#"):
            if cur is None:
                preamble.append(line)
            continue
        if not line[:1].isspace():
            key = s.split(":", 1)[0].strip().upper()
            if ":" in s and key in ce.HEADER and cur is None:
                k, v = s.split(":", 1)
                header[k.strip().upper()] = v.strip()
                continue
            cur = [s]
            blocks.append(cur)
        else:
            if cur is None:
                preamble.append(line)
            else:
                # Сохраняем отступ: он признак поля операции в DSL.
                cur.append("  " + s)
    return preamble, header, ["\n".join(b) for b in blocks]


def set_entry(w, value):
    w.delete(0, "end")
    w.insert(0, value)


def set_text(w, value):
    w.delete("1.0", "end")
    w.insert("1.0", value)


def get_text(w):
    return w.get("1.0", "end-1c")


class NodeGridView(ttk.Frame):
    """Редактируемая динамическая таблица содержимого выбранного узла.

    Столбцы и строки берутся из `node_table.build_model()`, поэтому у узла
    «Строки» это широкая таблица по полям строк, у объекта — ключ/значение,
    у списка скаляров — одна колонка. Правки живут только в модели и
    превращаются в блоки DSL по кнопке «В операции».
    """
    TAG_EDIT = "#FFF3CD"
    TAG_NEW = "#E6F4EA"
    TAG_DEL = "#F1F3F4"

    def __init__(self, master, on_generate, on_status=None):
        super().__init__(master)
        self.on_generate = on_generate
        self.on_status = on_status or (lambda s: None)
        self.model = None
        self.path = []
        self.cols = []
        self.col_ids = []
        self._editor = None
        self._dirty = False

        self.var_bylo = tk.BooleanVar(value=True)
        self.var_renumber = tk.BooleanVar(value=False)
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self, padding=(0, 2))
        bar.pack(side="top", fill="x")
        self.lbl_node = ttk.Label(bar, text="узел не выбран", anchor="w")
        self.lbl_node.pack(side="left", padx=(0, 6))
        for text, cmd in (("+ строка", self.add_row), ("− строка", self.del_row),
                          ("+ столбец", self.add_column), ("Сброс", self.reset)):
            ttk.Button(bar, text=text, width=10, command=cmd).pack(side="left", padx=1)
        ttk.Button(bar, text="→ В операции", command=self.generate).pack(side="right")

        opts = ttk.Frame(self)
        opts.pack(side="top", fill="x", pady=(2, 2))
        ttk.Checkbutton(opts, text="БЫЛО", variable=self.var_bylo).pack(side="left")
        ttk.Checkbutton(opts, text="перенумеровать",
                        variable=self.var_renumber).pack(side="left", padx=(6, 0))
        ttk.Label(opts, text="Причина:").pack(side="left", padx=(10, 2))
        self.ent_reason = ttk.Entry(opts, width=28)
        self.ent_reason.pack(side="left", fill="x", expand=True)

        tf = ttk.Frame(self)
        tf.pack(side="top", fill="both", expand=True)
        self.grid = ttk.Treeview(tf, show="headings", selectmode="browse")
        ysb = ttk.Scrollbar(tf, orient="vertical", command=self.grid.yview)
        xsb = ttk.Scrollbar(tf, orient="horizontal", command=self.grid.xview)
        self.grid.configure(yscroll=ysb.set, xscroll=xsb.set)
        self.grid.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        self.grid.tag_configure("edit", background=self.TAG_EDIT)
        self.grid.tag_configure("new", background=self.TAG_NEW)
        self.grid.tag_configure("del", background=self.TAG_DEL,
                                foreground="#9AA0A6")
        self.grid.bind("<Double-1>", self._on_double)
        self.grid.bind("<Return>", lambda e: self._edit_selected())
        self.grid.bind("<F2>", lambda e: self._edit_selected())
        self.grid.bind("<Delete>", lambda e: self.del_row())

        self.lbl_stats = ttk.Label(self, text="—", anchor="w", foreground="#555555")
        self.lbl_stats.pack(side="bottom", fill="x")

    def _status(self, text):
        self.on_status(text)

    # ------------------------------------------------------------------
    def load(self, value, path, label=""):
        self.close_editor()
        self.model = nt.build_model(value)
        self.path = list(path)
        self.lbl_node.configure(text=nt.short_text(label or "(узел)", 62))
        self._dirty = False
        self.refresh()

    def clear(self):
        self.close_editor()
        self.model = None
        self.path = []
        self._dirty = False
        self.cols, self.col_ids = [], []
        self.grid["columns"] = ()
        self.grid.delete(*self.grid.get_children())
        self.lbl_node.configure(text="узел не выбран")
        self.lbl_stats.configure(text="—")

    def refresh(self):
        self.close_editor()
        if self.model is None:
            return
        self.cols = ["#"] + list(self.model.columns)
        self.col_ids = ["c%d" % i for i in range(len(self.cols))]
        self.grid["columns"] = tuple(self.col_ids)
        for j, (cid, name) in enumerate(zip(self.col_ids, self.cols)):
            self.grid.heading(cid, text=name, anchor="w")
            if name == "#":
                w = 48
            elif name == "Тип":
                w = 108
            else:
                maxlen = len(str(name))
                for row in self.model.rows[:300]:
                    maxlen = max(maxlen, len(nt.short_text(
                        row.cells.get(name, ""), 80)))
                w = max(90, min(430, min(maxlen, 60) * 8 + 18))
            self.grid.column(cid, width=w, minwidth=48,
                             stretch=name not in ("#", "Тип"), anchor="w")
        self.grid.delete(*self.grid.get_children())
        for i, row in enumerate(self.model.rows):
            self.grid.insert("", "end", iid=str(i),
                             values=self._row_values(i, row),
                             tags=self._row_tags(row))
        s = self.model.stats()
        text = ("строк %d · столбцов %d · изменено %d · добавлено %d · удалено %d"
                % (s["rows"], s["cols"], s["changed"], s["new"], s["deleted"]))
        if self.model.notes:
            text += " · " + "; ".join(self.model.notes)
        self.lbl_stats.configure(text=text)

    def _row_values(self, i, row):
        out = ["×" if row.deleted else str(i + 1)]
        for name in self.model.columns:
            if name == "Тип" and self.model.kind == "dict":
                out.append(nt.type_text(row.cells.get("Значение", "")))
            else:
                out.append(nt.short_text(row.cells.get(name, ""), 220))
        return out

    @staticmethod
    def _row_tags(row):
        if row.deleted:
            return ("del",)
        if row.new:
            return ("new",)
        if row.changed_cols():
            return ("edit",)
        return ()

    # ------------------------------------------------------------- правка
    def _editable(self, iid, idx):
        if self.model is None or idx <= 0 or idx >= len(self.cols):
            return False
        name = self.cols[idx]
        if name in ("#", "Тип"):
            return False
        try:
            row = self.model.rows[int(iid)]
        except (ValueError, IndexError):
            return False
        if row.deleted:
            return False
        if self.model.kind == "dict" and name == "Ключ" and not row.new:
            return False
        return True

    def _on_double(self, event):
        if self.grid.identify_region(event.x, event.y) != "cell":
            return
        iid = self.grid.identify_row(event.y)
        cid = self.grid.identify_column(event.x)
        if not iid or cid not in self.col_ids:
            return
        self._edit_cell(iid, self.col_ids.index(cid))

    def _edit_selected(self):
        sel = self.grid.selection()
        if not sel:
            messagebox.showinfo("Ячейка", "Сначала выберите строку в таблице.")
            return
        for idx in range(len(self.cols)):
            if self._editable(sel[0], idx):
                self._edit_cell(sel[0], idx)
                return

    def _edit_cell(self, iid, idx):
        if not self._editable(iid, idx):
            return
        name = self.cols[idx]
        row = self.model.rows[int(iid)]
        text = nt.value_text(row.cells.get(name, ""))
        self.grid.see(iid)
        if "\n" in text or "\r" in text or len(text) > 160:
            new = self._ask_text(name, text)
            if new is not None:
                self.commit_cell(iid, idx, new)
            return
        bbox = self.grid.bbox(iid, self.col_ids[idx])
        if not bbox:
            return
        x, y, w, h = bbox
        e = ttk.Entry(self.grid)
        e.insert(0, text)
        e.place(x=x, y=y, width=w, height=h)
        e.focus_set()
        e.select_range(0, "end")
        self._editor = (e, iid, idx)
        e.bind("<Return>", lambda ev: self._commit_inline())
        e.bind("<KP_Enter>", lambda ev: self._commit_inline())
        e.bind("<Escape>", lambda ev: self.close_editor())
        e.bind("<FocusOut>", lambda ev: self._commit_inline())

    def _ask_text(self, name, text):
        dlg = tk.Toplevel(self)
        dlg.title("Поле: %s" % name)
        dlg.transient(self.winfo_toplevel())
        dlg.geometry("720x420")
        t = scrolledtext.ScrolledText(dlg, wrap="word", font=("Consolas", 10))
        t.pack(fill="both", expand=True, padx=6, pady=6)
        t.insert("1.0", text)
        res = {"text": None}

        def ok():
            res["text"] = get_text(t)
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(bf, text="Отмена", command=dlg.destroy).pack(side="right")
        ttk.Button(bf, text="OK", command=ok).pack(side="right", padx=4)
        dlg.bind("<Escape>", lambda ev: dlg.destroy())
        _place_over_parent(dlg, self.winfo_toplevel())
        dlg.grab_set()
        t.focus_set()
        self.wait_window(dlg)
        return res["text"]

    def close_editor(self):
        if self._editor:
            e = self._editor[0]
            self._editor = None
            try:
                e.destroy()
            except tk.TclError:
                pass

    def _commit_inline(self):
        if not self._editor:
            return
        e, iid, idx = self._editor
        self._editor = None
        text = e.get()
        try:
            e.destroy()
        except tk.TclError:
            pass
        self.commit_cell(iid, idx, text)

    def commit_cell(self, iid, idx, text):
        """Записать новое значение ячейки (используется и в автотестах)."""
        if not self._editable(iid, idx):
            return False
        row = self.model.rows[int(iid)]
        name = self.cols[idx]
        old = row.cells.get(name, "")
        new = nt.parse_cell(text, old)
        if old == new and type(old) is type(new):
            self.close_editor()
            return False
        row.cells[name] = new
        if self.model.kind == "dict" and name == "Значение":
            row.cells["Тип"] = nt.type_text(new)
        self._dirty = True
        self.refresh()
        try:
            self.grid.selection_set(iid)
            self.grid.see(iid)
        except tk.TclError:
            pass
        self._status("Ячейка изменена: %s" % nt.short_text(
            "%s = %s" % (name, nt.value_text(new)), 90))
        return True

    def add_row(self):
        if self.model is None:
            messagebox.showinfo("Строка", "Сначала выберите узел в дереве базы.")
            return None
        row = self.model.add_row()
        if row is None:
            messagebox.showinfo("Строка", "У скалярного узла нет строк; "
                                          "правьте ячейку «Значение».")
            return None
        self._dirty = True
        self.refresh()
        iid = str(len(self.model.rows) - 1)
        self.grid.selection_set(iid)
        self.grid.see(iid)
        self._status("Добавлена строка %d — заполните ячейки двойным щелчком"
                     % len(self.model.rows))
        return row

    def del_row(self):
        if self.model is None or not self.grid.selection():
            messagebox.showinfo("Строка", "Выберите строку в таблице узла.")
            return
        i = int(self.grid.selection()[0])
        row = self.model.rows[i]
        if row.new:
            del self.model.rows[i]
        else:
            row.deleted = not row.deleted
        self._dirty = True
        self.refresh()
        if i < len(self.model.rows):
            self.grid.selection_set(str(i))
        self._status("Удаление помечено: операция появится после «В операции»")

    def add_column(self):
        if self.model is None or self.model.kind != "table":
            messagebox.showinfo(
                "Столбец",
                "Новый столбец добавляется к таблице строк (список объектов).\n"
                "У объекта добавляйте строку с новым ключом.")
            return
        name = simpledialog.askstring("Новый столбец", "Имя поля:", parent=self)
        if name:
            self.add_column_named(name)

    def add_column_named(self, name):
        if not self.model.add_column(name):
            messagebox.showinfo("Столбец", "Такое поле уже есть или имя пустое.")
            return False
        self._dirty = True
        self.refresh()
        self._status("Добавлен столбец «%s»" % name)
        return True

    def reset(self):
        if self.model is None:
            return
        self.model = nt.build_model(self.model.source)
        self._dirty = False
        self.refresh()
        self._status("Таблица узла сброшена к значениям базы")

    # ---------------------------------------------------------- операции
    def has_edits(self):
        """Есть ли в таблице неприменённые правки (для предупреждений)."""
        if self.model is None:
            return False
        return bool(self._dirty)

    def generate(self):
        if self.model is None:
            messagebox.showinfo("Операции", "Сначала выберите узел в дереве базы.")
            return []
        if not self._dirty and not any(r.dirty() for r in self.model.rows):
            messagebox.showinfo("Операции", "В таблице нет новых правок.")
            return []
        blocks, warnings = nt.generate_ops(
            self.model, self.path, bylo=self.var_bylo.get(),
            renumber=self.var_renumber.get(), reason=self.ent_reason.get())
        if not blocks:
            messagebox.showinfo(
                "Операции",
                "Операции не сформированы.\n" + "\n".join(warnings[:6]))
            return []
        self.on_generate(blocks, warnings)
        self._dirty = False
        return blocks


class CopyEditor(tk.Toplevel):
    """Окно правки копии узла до применения изменения к базе.

    Копии ещё нет в базовом JSON, поэтому её нельзя выбрать в основном
    дереве. Здесь своё дерево копии: выбираете любой её узел, правите в
    обычной таблице, а кнопка «Добавить правки копии в изменение» превращает
    правки в блоки `ИЗМЕНИТЬ ПОЛЯ` / `ЗАМЕНИТЬ` с путями от копии.
    """

    def __init__(self, master, value, base_path, label, on_generate,
                 on_status=None, on_close=None):
        super().__init__(master)
        self.title("Правка копии — %s" % shorten(label, 70))
        self.geometry("1100x780")
        self.minsize(820, 520)
        self.value = value
        self.base_path = list(base_path)
        self.on_generate = on_generate
        self.on_status = on_status or (lambda s: None)
        self.on_close = on_close
        self.item_seg = {}
        self.item_val = {}
        self.item_path = {}
        self.children_done = {}
        self.children_map = {}
        self.cur_iid = None
        self._build()
        self.children_done[""] = True
        self._populate("", self.value, self.base_path)
        if not isinstance(self.value, (dict, list)):
            self.grid_view.load(self.value, self.base_path, label)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.transient(master)
        _place_over_parent(self, master)
        self.lift()

    # ------------------------------------------------------------------
    def _build(self):
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(side="top", fill="x")
        ttk.Label(top, text="Копия узла — правьте её здесь, пока изменение "
                            "не применено к базе",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.lbl_path = ttk.Label(
            top, text="Путь: %s" % shorten(ce.render_path(self.base_path), 150),
            foreground="#555555")
        self.lbl_path.pack(anchor="w")

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        tf = ttk.Frame(panes)
        self.tree = ttk.Treeview(tf, show="tree", selectmode="browse")
        ysb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        panes.add(tf, weight=2)

        gf = ttk.Frame(panes)
        ttk.Label(gf, text="Содержимое узла копии (правится как обычная таблица)",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.grid_view = NodeGridView(gf, on_generate=self.on_generate,
                                      on_status=self.on_status)
        self.grid_view.pack(fill="both", expand=True, pady=(2, 0))
        panes.add(gf, weight=3)

        bottom = ttk.Frame(self, padding=(8, 4))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Добавить правки копии в изменение",
                   command=self.grid_view.generate).pack(side="left")
        ttk.Button(bottom, text="Закрыть", command=self.close).pack(side="right")
        self.status = ttk.Label(bottom, text="Выберите узел копии",
                                foreground="#555555")
        self.status.pack(side="left", padx=12)

    # ------------------------------------------------------------------
    def _populate(self, parent, value, path):
        if isinstance(value, dict):
            pairs = [(seg_key(k, v), v, k) for k, v in value.items()]
        elif isinstance(value, list):
            pairs = [(seg_idx(i, v), v, label_idx(i, v))
                     for i, v in enumerate(value)]
        else:
            return
        m = self.children_map.setdefault(parent, {})
        for seg, val, label in pairs:
            iid = self.tree.insert(parent, "end", text=shorten(label, 120))
            self.item_seg[iid] = seg
            self.item_val[iid] = val
            self.item_path[iid] = path + [seg]
            m[segkey(seg)] = iid
            if isinstance(val, (dict, list)) and val:
                self.tree.insert(iid, "end", text="…")
                self.children_done[iid] = False
            else:
                self.children_done[iid] = True

    def _ensure_children(self, iid):
        if self.children_done.get(iid, True):
            return
        for dummy in self.tree.get_children(iid):
            self.tree.delete(dummy)
        self.children_done[iid] = True
        self._populate(iid, self.item_val.get(iid), self.item_path.get(iid, []))

    def _on_open(self, event):
        iid = self.tree.focus()
        if iid:
            self._ensure_children(iid)

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == self.cur_iid:
            return
        if self.grid_view.has_edits():
            ans = messagebox.askyesnocancel(
                "Правка копии",
                "В таблице есть неприменённые правки.\n"
                "Добавить их в изменение перед переходом к другому узлу?\n\n"
                "«Да» — добавить, «Нет» — потерять, «Отмена» — остаться.",
                parent=self)
            if ans is None:
                if self.cur_iid:
                    self.tree.selection_set(self.cur_iid)
                return
            if ans:
                self.grid_view.generate()
                if self.grid_view.has_edits():
                    if self.cur_iid:
                        self.tree.selection_set(self.cur_iid)
                    self.status.configure(
                        text="Правки не удалось превратить в операции — "
                             "узел не переключён")
                    return
        self.cur_iid = iid
        self.grid_view.load(self.item_val.get(iid), self.item_path.get(iid, []),
                            self.tree.item(iid, "text"))
        self.status.configure(text="Узел: %s" %
                              shorten(self.tree.item(iid, "text"), 90))

    def expand_to(self, segs):
        """Раскрыть дерево копии по относительным сегментам (для тестов)."""
        parent = ""
        for seg in segs:
            self._ensure_children(parent)
            iid = self.children_map.get(parent, {}).get(segkey(seg))
            if not iid:
                return None
            self.tree.item(iid, open=True)
            self._ensure_children(iid)
            parent = iid
        self.tree.selection_set(parent)
        self.tree.see(parent)
        self._on_select(None)
        return parent

    def close(self):
        if self.grid_view.has_edits():
            if not messagebox.askyesno(
                    "Правка копии",
                    "Не все правки копии добавлены в изменение. Закрыть окно?",
                    parent=self):
                return
        if self.on_close:
            self.on_close()
        self.destroy()


class NewStandardDialog(tk.Toplevel):
    """Диалог «Новый стандарт на основе выбранного».

    Показывает реквизиты выбранного стандарта, позволяет их изменить,
    выбрать шкафы, задать замены кодов и номеров и собрать НОВЫЙ базовый
    JSON. Исходный файл не изменяется.
    """

    def __init__(self, app, sources):
        super().__init__(app.root)
        self.app = app
        self.sources = list(sources)          # [(подпись, путь)]
        self.cache = {}
        self.cab_names = []
        self._source = None
        self._source_path = None
        self._last = None
        self.result = None

        self.title("Новый стандарт на основе выбранного")
        self.transient(app.root)
        self.geometry("1000x840")
        self.minsize(880, 660)
        self._build()
        if self.sources:
            self._select(0)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _place_over_parent(self, app.root)
        self.grab_set()

    # ------------------------------------------------------------------ UI
    def _build(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Исходный стандарт:").pack(side="left")
        self.cb_source = ttk.Combobox(
            top, values=[label for label, _ in self.sources],
            state="readonly", width=90)
        self.cb_source.pack(side="left", padx=6, fill="x", expand=True)
        self.cb_source.bind("<<ComboboxSelected>>",
                            lambda e: self._select(self.cb_source.current()))

        meta = ttk.LabelFrame(outer, text="Реквизиты нового стандарта",
                              padding=8)
        meta.pack(fill="x", pady=(8, 6))
        meta.columnconfigure(1, weight=1)

        self.ent_code = ttk.Entry(meta)
        self.ent_title = ttk.Entry(meta)
        self.ent_date = ttk.Entry(meta, width=14)
        self.ent_owner = ttk.Entry(meta)
        rows = (("Шифр стандарта:", self.ent_code),
                ("Обозначение стандарта:", self.ent_title),
                ("Дата введения:", self.ent_date),
                ("Принадлежность стандарта:", self.ent_owner))
        for i, (label, widget) in enumerate(rows):
            ttk.Label(meta, text=label).grid(row=i, column=0, sticky="w",
                                             pady=2)
            widget.grid(row=i, column=1, sticky="ew", pady=2, padx=(6, 0))
        ttk.Label(meta, text="Область применения:").grid(
            row=len(rows), column=0, sticky="nw", pady=(4, 2))
        self.txt_scope = tk.Text(meta, height=3, wrap="word",
                                 font=("Segoe UI", 9))
        self.txt_scope.grid(row=len(rows), column=1, sticky="ew",
                            pady=(4, 2), padx=(6, 0))
        self.ent_code.bind("<FocusOut>", lambda e: self._suggest_code())

        mid = ttk.Frame(outer)
        mid.pack(fill="both", expand=True)

        cabs_f = ttk.LabelFrame(mid, text="Шкафы в новом стандарте", padding=6)
        cabs_f.pack(side="left", fill="both", expand=True)
        self.lst_cabs = tk.Listbox(cabs_f, selectmode="extended", height=9,
                                   exportselection=False,
                                   font=("Segoe UI", 9))
        self.lst_cabs.pack(side="left", fill="both", expand=True)
        cab_scroll = ttk.Scrollbar(cabs_f, orient="vertical",
                                   command=self.lst_cabs.yview)
        cab_scroll.place(in_=self.lst_cabs, relx=1.0, rely=0, relheight=1.0,
                         anchor="ne")
        self.lst_cabs.configure(yscrollcommand=cab_scroll.set)
        self.lst_cabs.bind("<<ListboxSelect>>", lambda e: self._update_count())
        cab_btns = ttk.Frame(cabs_f)
        cab_btns.pack(side="left", fill="y", padx=(6, 0))
        ttk.Button(cab_btns, text="Все",
                   command=lambda: self._select_all(True)).pack(fill="x")
        ttk.Button(cab_btns, text="Ничего",
                   command=lambda: self._select_all(False)).pack(fill="x",
                                                                 pady=2)
        self.lbl_count = ttk.Label(cabs_f, text="", foreground="#555555",
                                   font=("Segoe UI", 8))
        self.lbl_count.pack(side="bottom", anchor="w")

        reps_f = ttk.LabelFrame(mid, text="Замены (старое => новое)",
                                padding=6)
        reps_f.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.txt_reps = scrolledtext.ScrolledText(
            reps_f, height=9, wrap="none", font=("Consolas", 9))
        self.txt_reps.pack(fill="both", expand=True)
        ttk.Label(reps_f, text="Коды ШЭТ, номера таблиц, «279-2019 => 282-2019». "
                              "Пустые строки и # игнорируются.",
                  foreground="#666666", font=("Segoe UI", 8),
                  wraplength=420, justify="left").pack(anchor="w", pady=(4, 0))

        self.var_renumber = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            outer, text="Перенумеровать разделы подряд 5.2…5.N "
                        "(таблицы и ссылки переименуются автоматически)",
            variable=self.var_renumber).pack(anchor="w", pady=(6, 2))

        rep_f = ttk.LabelFrame(outer, text="Проверка и отчёт", padding=6)
        rep_f.pack(fill="both", expand=True, pady=(4, 6))
        self.txt_report = tk.Text(rep_f, height=11, wrap="none",
                                  font=("Consolas", 9), state="disabled")
        self.txt_report.pack(side="left", fill="both", expand=True)
        rep_scroll = ttk.Scrollbar(rep_f, orient="vertical",
                                   command=self.txt_report.yview)
        rep_scroll.place(in_=self.txt_report, relx=1.0, rely=0, relheight=1.0,
                         anchor="ne")
        self.txt_report.configure(yscrollcommand=rep_scroll.set)

        btns = ttk.Frame(outer)
        btns.pack(fill="x")
        ttk.Button(btns, text="Проверить", command=self.preview).pack(side="left")
        ttk.Button(btns, text="Создать…", command=self.save).pack(side="left",
                                                                  padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right")

    # ------------------------------------------------------------- данные
    def _select(self, index):
        if not 0 <= index < len(self.sources):
            return
        self.cb_source.current(index)
        label, path = self.sources[index]
        data = self.cache.get(path)
        if data is None:
            try:
                data = ac.load_json(path)
            except Exception as exc:
                messagebox.showerror("Новый стандарт",
                                     "Не удалось прочитать %s:\n%s"
                                     % (path, exc), parent=self)
                return
            if not isinstance(data, dict) or not isinstance(
                    data.get(ms.CONTENT_KEY), dict):
                messagebox.showerror(
                    "Новый стандарт",
                    "Файл %s не похож на стандарт: нет «%s»."
                    % (os.path.basename(path), ms.CONTENT_KEY), parent=self)
                return
            self.cache[path] = data
        self._source = data
        self._source_path = path
        self._fill(data, label)

    def _fill(self, data, label):
        set_entry(self.ent_code, data.get("Шифр стандарта", ""))
        set_entry(self.ent_title, data.get("Обозначение стандарта", ""))
        set_entry(self.ent_date, data.get("Дата введения", ""))
        set_entry(self.ent_owner, data.get("Принадлежность стандарта", ""))
        set_text(self.txt_scope, data.get("Область применения стандарта", ""))

        set_text(self.txt_reps, "")

        self.lst_cabs.delete(0, "end")
        self.cab_names = []
        for info in ms.cabinet_list(data):
            self.cab_names.append(info["name"])
            self.lst_cabs.insert(
                "end", "%s — раздел %s, таблиц %d — %s"
                % (info["cipher"] or "?", info["section"] or "?",
                   info["tables"], shorten(info["name"], 90)))
        self._select_all(True)

        stats = ms.stats_of(data)
        self._set_report(
            "Источник: %s\nШкафов: %d, таблиц: %d, строк: %d.\n\n"
            "Измените реквизиты, при необходимости снимите лишние шкафы и "
            "задайте замены, затем нажмите «Проверить»."
            % (label, stats["cabinets"], stats["tables"], stats["rows"]))

    def _select_all(self, on):
        if on:
            self.lst_cabs.selection_set(0, "end")
        else:
            self.lst_cabs.selection_clear(0, "end")
        self._update_count()

    def _update_count(self):
        total = len(self.cab_names)
        chosen = len(self.lst_cabs.curselection())
        self.lbl_count.configure(text="Выбрано %d из %d" % (chosen, total))

    def _suggest_code(self):
        """Подсказать замену старого шифра на новый (и его номера)."""
        if not self._source:
            return
        old = str(self._source.get("Шифр стандарта") or "").strip()
        new = self.ent_code.get().strip()
        suggested = ms.code_replacements(old, new)
        if not suggested:
            return
        text = get_text(self.txt_reps)
        pairs = set()
        for line in text.splitlines():
            a, sep, b = line.partition("=>")
            if sep:
                pairs.add((a.strip(), b.strip()))
        add = [rep for rep in suggested
               if (rep["Старое"], rep["Новое"]) not in pairs]
        if not add:
            return
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join("%s => %s\n" % (rep["Старое"], rep["Новое"])
                        for rep in add)
        set_text(self.txt_reps, text)

    # ------------------------------------------------------------- сборка
    def collect(self):
        """Прочитать диалог в параметры сборки (или поднять StandardError)."""
        if not self._source:
            raise ms.StandardError("не выбран исходный стандарт")
        meta = {
            "Шифр стандарта": self.ent_code.get().strip(),
            "Обозначение стандарта": self.ent_title.get().strip(),
            "Дата введения": self.ent_date.get().strip(),
            "Принадлежность стандарта": self.ent_owner.get().strip(),
            "Область применения стандарта": get_text(self.txt_scope).strip(),
        }
        missing = [key for key, value in meta.items() if not value]
        if missing:
            raise ms.StandardError(
                "заполните: %s" % ", ".join("«%s»" % key for key in missing))
        meta = {key: value for key, value in meta.items() if value}

        replacements = []
        for lineno, line in enumerate(get_text(self.txt_reps).splitlines(), 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            old, sep, new = text.partition("=>")
            if not sep or not old.strip():
                raise ms.StandardError(
                    "замена, строка %d: ожидается «старое => новое»" % lineno)
            replacements.append({"Старое": old.strip(), "Новое": new.strip()})

        old_code = str(self._source.get("Шифр стандарта") or "").strip()
        new_code = meta.get("Шифр стандарта", "")
        pairs = {(rep["Старое"], rep["Новое"]) for rep in replacements}
        for rep in ms.code_replacements(old_code, new_code):
            if (rep["Старое"], rep["Новое"]) not in pairs:
                replacements.append(rep)
                pairs.add((rep["Старое"], rep["Новое"]))

        chosen = [self.cab_names[i] for i in self.lst_cabs.curselection()]
        if not chosen:
            raise ms.StandardError("выберите хотя бы один шкаф")
        return {
            "source": self._source,
            "source_path": self._source_path,
            "meta": meta,
            "replacements": replacements,
            "keep": chosen if len(chosen) < len(self.cab_names) else None,
            "renumber": bool(self.var_renumber.get()),
        }

    def build_now(self):
        """Собрать стандарт в память и показать отчёт. Возвращает (opts, res)."""
        opts = self.collect()
        res = ms.build(opts["source"], meta=opts["meta"],
                       replacements=opts["replacements"], keep=opts["keep"],
                       renumber=opts["renumber"],
                       source_label=os.path.basename(opts["source_path"]))
        self._last = (opts, res)
        self._set_report(ms.report(res))
        return opts, res

    def preview(self):
        try:
            _, res = self.build_now()
        except ms.StandardError as exc:
            messagebox.showerror("Новый стандарт", str(exc), parent=self)
            return
        if res["problems"]:
            self.app.set_status("Новый стандарт: проблем — %d"
                                % len(res["problems"]))
        else:
            self.app.set_status("Новый стандарт: проверка пройдена")
            self.app.write_log(
                "Новый стандарт проверен: %s, шкафов %d, таблиц %d"
                % (res["data"].get("Шифр стандарта", ""),
                   res["stats"]["cabinets"], res["stats"]["tables"]), "ok")

    def save(self):
        try:
            _, res = self.build_now()
        except ms.StandardError as exc:
            messagebox.showerror("Новый стандарт", str(exc), parent=self)
            return
        if res["problems"]:
            messagebox.showerror(
                "Новый стандарт",
                "Проверка не пройдена:\n" + "\n".join(res["problems"][:8]),
                parent=self)
            return
        code = res["data"].get("Шифр стандарта") or "новый стандарт"
        default = re.sub(r'[\\/:*?"<>|]+', "-", code) + ".json"
        path = filedialog.asksaveasfilename(
            parent=self, title="Сохранить новый стандарт", initialdir=ROOT,
            initialfile=default, defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            size = ms.write_standard(res["data"], path, overwrite=True)
        except (ms.StandardError, OSError) as exc:
            messagebox.showerror("Новый стандарт",
                                 "Не удалось записать:\n%s" % exc, parent=self)
            return
        self.result = path
        self.app.write_log(
            "Новый стандарт создан: %s (%d байт, шкафов %d, таблиц %d, строк %d)"
            % (path, size, res["stats"]["cabinets"], res["stats"]["tables"],
               res["stats"]["rows"]), "ok")
        self.app.set_status("Новый стандарт: %s" % os.path.basename(path))
        if messagebox.askyesno(
                "Новый стандарт",
                "Стандарт сохранён.\n\nОткрыть его как базу для изменений?",
                parent=self):
            self.app.load_base(path)
        self.destroy()

    def _set_report(self, text):
        self.txt_report.configure(state="normal")
        self.txt_report.delete("1.0", "end")
        self.txt_report.insert("1.0", text)
        self.txt_report.configure(state="disabled")


class App:
    def __init__(self, root):
        self.root = root
        self.base = None
        self.base_path = None
        self.index = []
        self.search_pos = -1

        self.preamble = []
        self.header = OrderedDict()
        self.header_present = set()
        self.blocks = []
        self.cur_index = None
        self.path = None
        self.edition = None
        self.copy_editor = None
        self._loading = False

        self.item_seg = {}
        self.item_val = {}
        self.children_done = {}
        self.children_map = {}

        self.var_strict = tk.BooleanVar(value=False)
        self.var_ignore_hash = tk.BooleanVar(value=False)
        self.var_toc = tk.BooleanVar(value=True)

        self._build_ui()
        self._bind_keys()
        if os.path.isfile(BASE_DEFAULT):
            self.load_base(BASE_DEFAULT)
        self.new_doc()
        self.root.after(200, self._initial_hint)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        r = self.root
        r.title("Редактор изменений стандарта — СТО")
        r.geometry("1520x920")
        r.minsize(1100, 700)
        try:
            from tkinter import font
            font.nametofont("TkDefaultFont").configure(family="Segoe UI", size=10)
            font.nametofont("TkTextFont").configure(family="Consolas", size=10)
        except Exception:
            pass

        menubar = tk.Menu(r)
        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Новое", command=self.new_doc, accelerator="Ctrl+N")
        m.add_command(label="Открыть…", command=self.open_doc, accelerator="Ctrl+O")
        m.add_command(label="Сохранить", command=self.save_doc, accelerator="Ctrl+S")
        m.add_command(label="Сохранить как…", command=self.save_as)
        m.add_separator()
        m.add_command(label="Экспорт в JSON изменения…", command=self.export_json)
        m.add_separator()
        m.add_command(label="Выход", command=r.destroy)
        menubar.add_cascade(label="Файл", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Загрузить базовый стандарт…", command=self.pick_base)
        m.add_command(label="Создать стандарт на основе выбранного…",
                      command=self.new_standard)
        m.add_command(label="Обновить дерево", command=self.refresh_tree)
        menubar.add_cascade(label="База", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Добавить строку", command=lambda: self.grid_view.add_row())
        m.add_command(label="Удалить строку", command=lambda: self.grid_view.del_row())
        m.add_command(label="Добавить столбец", command=lambda: self.grid_view.add_column())
        m.add_command(label="Сбросить таблицу", command=lambda: self.grid_view.reset())
        m.add_separator()
        m.add_command(label="Дублировать узел (копия)…", command=self.duplicate_node)
        m.add_command(label="Правки → операции",
                      command=lambda: self.grid_view.generate())
        menubar.add_cascade(label="Таблица узла", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Проверить изменения", command=self.action_check,
                      accelerator="F5")
        m.add_command(label="Собрать редакцию", command=self.action_assemble,
                      accelerator="F6")
        m.add_separator()
        m.add_command(label="Сохранить собранный JSON…", command=self.save_edition)
        m.add_command(label="Построить отчёт DOCX…", command=self.action_docx)
        menubar.add_cascade(label="Сборка", menu=m)

        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="Справка по формату", command=self.show_help)
        m.add_command(label="О программе", command=self.show_about)
        menubar.add_cascade(label="Справка", menu=m)
        r.config(menu=menubar)

        # --- панель сверху -------------------------------------------------
        top = ttk.Frame(r, padding=(8, 6))
        top.pack(side="top", fill="x")
        ttk.Label(top, text="База:").pack(side="left")
        self.ent_base = ttk.Entry(top, width=54)
        self.ent_base.pack(side="left", padx=(4, 2))
        ttk.Button(top, text="Обзор…", command=self.pick_base).pack(side="left")
        ttk.Button(top, text="Загрузить", command=self.refresh_tree).pack(side="left", padx=2)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(top, text="Новое", command=self.new_doc).pack(side="left")
        ttk.Button(top, text="Открыть", command=self.open_doc).pack(side="left", padx=2)
        ttk.Button(top, text="Сохранить", command=self.save_doc).pack(side="left")
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(top, text="Проверить", command=self.action_check).pack(side="left")
        ttk.Button(top, text="Собрать редакцию", command=self.action_assemble).pack(side="left", padx=2)
        ttk.Button(top, text="DOCX", command=self.action_docx).pack(side="left")
        ttk.Checkbutton(top, text="строго", variable=self.var_strict).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(top, text="игнорировать хэш", variable=self.var_ignore_hash).pack(side="left")

        # --- основная область ---------------------------------------------
        panes = ttk.PanedWindow(r, orient="horizontal")
        panes.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 4))

        left = ttk.Frame(panes)
        mid = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(mid, weight=3)
        panes.add(right, weight=4)

        # --- левая часть: вертикальная панель «дерево ⟂ таблица узла» -----
        left_panes = ttk.PanedWindow(left, orient="vertical")
        left_panes.pack(side="top", fill="both", expand=True)

        # верх: дерево базы + поиск + кнопки «в операцию»
        tree_f = ttk.Frame(left_panes)
        ttk.Label(tree_f, text="Базовый стандарт", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        sframe = ttk.Frame(tree_f)
        sframe.pack(fill="x", pady=(3, 3))
        self.ent_search = ttk.Entry(sframe)
        self.ent_search.pack(side="left", fill="x", expand=True)
        ttk.Button(sframe, text="Найти", command=self.action_search).pack(side="left", padx=2)
        self.tree = ttk.Treeview(tree_f, show="tree", selectmode="browse")
        ysb = ttk.Scrollbar(tree_f, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(tree_f, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        self.tree.pack(side="top", fill="both", expand=True)
        ysb.place(in_=self.tree, relx=1.0, rely=0, relheight=1.0, anchor="ne")
        xsb.pack(side="bottom", fill="x")
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self.take_path())

        btns = ttk.Frame(tree_f)
        btns.pack(fill="x", pady=3)
        ttk.Button(btns, text="← Путь в операцию", command=self.take_path).pack(side="left")
        ttk.Button(btns, text="Подставить БЫЛО", command=self.take_bylo).pack(side="left", padx=2)
        ttk.Button(btns, text="Дублировать узел", command=self.duplicate_node).pack(side="left", padx=2)
        left_panes.add(tree_f, weight=2)

        # низ: динамическая таблица содержимого выбранного узла
        grid_f = ttk.Frame(left_panes)
        ttk.Label(grid_f, text="Содержимое выбранного узла (редактируемая таблица)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.grid_view = NodeGridView(grid_f, on_generate=self.on_grid_generate,
                                     on_status=self.set_status)
        self.grid_view.pack(fill="both", expand=True, pady=(2, 0))
        left_panes.add(grid_f, weight=3)

        # Список операций
        ttk.Label(mid, text="Операции изменения", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ob = ttk.Frame(mid)
        ob.pack(fill="x", pady=3)
        for text, cmd in (("+", self.add_op), ("−", self.del_op),
                          ("↑", self.move_up), ("↓", self.move_down),
                          ("копия", self.dup_op)):
            ttk.Button(ob, text=text, width=5 if len(text) < 4 else 7,
                       command=cmd).pack(side="left", padx=1)
        cols = ("n", "op", "path")
        self.ops = ttk.Treeview(mid, columns=cols, show="headings", height=18)
        self.ops.heading("n", text="№")
        self.ops.heading("op", text="Операция")
        self.ops.heading("path", text="Путь")
        self.ops.column("n", width=38, stretch=False)
        self.ops.column("op", width=130, stretch=False)
        self.ops.column("path", width=250)
        oysb = ttk.Scrollbar(mid, orient="vertical", command=self.ops.yview)
        self.ops.configure(yscroll=oysb.set)
        self.ops.pack(side="left", fill="both", expand=True)
        oysb.pack(side="right", fill="y")
        self.ops.bind("<<TreeviewSelect>>", self._on_op_select)

        # Правая часть: ноутбук
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        self.tab_head = ttk.Frame(self.nb)
        self.tab_op = ttk.Frame(self.nb)
        self.tab_text = ttk.Frame(self.nb)
        self.nb.add(self.tab_head, text=" Шапка ")
        self.nb.add(self.tab_op, text=" Операция ")
        self.nb.add(self.tab_text, text=" Текст *.изм.txt ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._build_header_tab()
        self._build_op_tab()
        self._build_text_tab()

        # --- журнал --------------------------------------------------------
        logf = ttk.LabelFrame(r, text="Журнал проверки и сборки", padding=3)
        logf.pack(side="top", fill="both", padx=8, pady=(0, 4))
        logf.configure(height=210)
        logf.pack_propagate(False)
        self.log = scrolledtext.ScrolledText(logf, wrap="word",
                                             font=("Consolas", 9), height=10)
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("err", foreground="#c02020")
        self.log.tag_config("ok", foreground="#137333")
        self.log.tag_config("warn", foreground="#a06000")
        self.log.tag_config("hdr", foreground="#1a56b0")
        self.log.configure(state="disabled")

        self.status = ttk.Label(r, text="Готово", anchor="w", relief="sunken", padding=(6, 2))
        self.status.pack(side="bottom", fill="x")

    def _build_header_tab(self):
        f = ttk.Frame(self.tab_head, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        self.header_entries = {}
        for i, token in enumerate(HEADER_ORDER):
            ttk.Label(f, text=token + ":").grid(row=i * 2, column=0, sticky="w", pady=(6, 0))
            e = ttk.Entry(f)
            e.grid(row=i * 2, column=1, sticky="ew", pady=(6, 0))
            self.header_entries[token] = e
            ttk.Label(f, text=HEADER_HINTS.get(token, ""), foreground="#666666",
                      font=("Segoe UI", 8)).grid(row=i * 2 + 1, column=1, sticky="w")
        ttk.Button(f, text="Заполнить БАЗА / ХЭШ из базы",
                   command=self.fill_base_header).grid(row=len(HEADER_ORDER) * 2,
                                                       column=1, sticky="w", pady=(14, 0))

    def _build_op_tab(self):
        f = ttk.Frame(self.tab_op, padding=8)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Операция:").grid(row=0, column=0, sticky="w")
        self.cmb_verb = ttk.Combobox(f, values=VERBS, state="readonly", width=24)
        self.cmb_verb.grid(row=0, column=1, sticky="w", pady=2)
        self.cmb_verb.set("ЗАМЕНИТЬ")

        ttk.Label(f, text="Путь:").grid(row=1, column=0, sticky="w")
        pf = ttk.Frame(f)
        pf.grid(row=1, column=1, sticky="ew", pady=2)
        pf.columnconfigure(0, weight=1)
        self.ent_path = ttk.Entry(pf)
        self.ent_path.grid(row=0, column=0, sticky="ew")
        ttk.Button(pf, text="из дерева", command=self.take_path).grid(row=0, column=1, padx=2)
        ttk.Button(pf, text="проверить", command=self.check_path).grid(row=0, column=2)
        ttk.Label(f, text="шкаф=ШЭТ 431.02-0 / Таблицы / Таблица 5.3.8 / Строки / №=2",
                  foreground="#666666", font=("Consolas", 8)).grid(row=2, column=1, sticky="w")

        specs = [
            ("txt_bylo", "БЫЛО (строки БЫЛО: / БЫЛО.Поле:)", 3),
            ("txt_stalo", "СТАЛО / ЗНАЧЕНИЕ (одна строка; объект — JSON)", 2),
            ("txt_fields", "Поля (строки > ключ: значение)", 4),
            ("txt_extra", "Прочие поля (КЛЮЧ:, ПРИЧИНА:, ПЕРЕНУМЕРОВАТЬ: и др.)", 4),
        ]
        row = 3
        for attr, label, height in specs:
            ttk.Label(f, text=label).grid(row=row, column=0, columnspan=2,
                                         sticky="w", pady=(7, 0))
            row += 1
            w = scrolledtext.ScrolledText(f, height=height, wrap="word",
                                          font=("Consolas", 9))
            w.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=(1, 0))
            f.rowconfigure(row, weight=1 if height > 3 else 0)
            setattr(self, attr, w)
            row += 1
        ttk.Button(f, text="Применить форму к операции",
                   command=self.apply_form_now).grid(row=row, column=0,
                                                     columnspan=2, pady=(8, 0))

    def _build_text_tab(self):
        f = ttk.Frame(self.tab_text, padding=6)
        f.pack(fill="both", expand=True)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Обновить из формы",
                   command=lambda: set_text(self.doc_text, self.build_text())).pack(side="left")
        ttk.Button(bar, text="Применить текст в форму",
                   command=self.apply_doc_text).pack(side="left", padx=3)
        ttk.Label(bar, text="После ручной правки нажмите «Применить текст в форму»",
                  foreground="#666666").pack(side="left", padx=10)
        self.doc_text = scrolledtext.ScrolledText(f, wrap="none",
                                                  font=("Consolas", 9))
        self.doc_text.pack(fill="both", expand=True)

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-n>", lambda e: self.new_doc())
        r.bind("<Control-o>", lambda e: self.open_doc())
        r.bind("<Control-s>", lambda e: self.save_doc())
        r.bind("<F5>", lambda e: self.action_check())
        r.bind("<F6>", lambda e: self.action_assemble())
        self.ent_search.bind("<Return>", lambda e: self.action_search())

    def _initial_hint(self):
        self.write_log("Редактор готов.\n"
                       "1) Слева выберите узел базы → «Путь в операцию».\n"
                       "2) «Подставить БЫЛО» → заполните СТАЛО / поля.\n"
                       "3) «Дублировать узел» — копия любого узла с заменами "
                       "и окном правки копии.\n"
                       "4) «База → Создать стандарт на основе выбранного» — "
                       "новый стандарт из копии.\n"
                       "5) F5 — проверить, F6 — собрать редакцию.\n", "hdr")

    # ------------------------------------------------------------- журнал
    def write_log(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text if text.endswith("\n") else text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")
        self.root.update_idletasks()

    def set_status(self, text):
        self.status.configure(text=text)
        self.root.update_idletasks()

    def busy(self, on=True):
        self.root.configure(cursor="watch" if on else "")
        self.root.update_idletasks()

    # --------------------------------------------------------------- база
    def load_base(self, path):
        try:
            data = ac.load_json(path)
        except Exception as exc:
            messagebox.showerror("База", "Не удалось загрузить: %s" % exc)
            return
        self.base = data
        self.base_path = path
        set_entry(self.ent_base, path)
        self.refresh_tree()
        self.write_log("База загружена: %s (%s), узлов в индексе: %d" %
                       (os.path.basename(path), data.get("Шифр стандарта", ""),
                        len(self.index)), "ok")

    def pick_base(self):
        p = filedialog.askopenfilename(
            title="Базовый JSON стандарта", initialdir=ROOT,
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if p:
            self.load_base(p)

    # --------------------------------------------------- новый стандарт
    def standard_sources(self):
        """Кандидаты для «Новый стандарт на основе выбранного»."""
        out, seen = [], set()

        def add(label, path):
            key = os.path.normcase(os.path.abspath(path))
            if key in seen or not os.path.isfile(path):
                return
            seen.add(key)
            out.append((label, path))

        if self.base_path:
            add("Текущая база — %s" % os.path.basename(self.base_path),
                self.base_path)
        for path in sorted(glob.glob(os.path.join(ROOT, "*.json"))):
            try:
                data = ac.load_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or not isinstance(
                    data.get(ms.CONTENT_KEY), dict):
                continue
            add("%s — %s" % (data.get("Шифр стандарта") or "без шифра",
                             os.path.basename(path)), path)
        return out

    def new_standard(self):
        sources = self.standard_sources()
        if not sources:
            messagebox.showwarning(
                "Новый стандарт",
                "В папке нет JSON стандартов: положите файл рядом с программой "
                "или загрузите базу.")
            return
        dlg = NewStandardDialog(self, sources)
        self.root.wait_window(dlg)
        if dlg.result:
            self.write_log("Новый стандарт: %s" % dlg.result, "ok")

    def refresh_tree(self):
        p = self.ent_base.get().strip()
        if not p or not os.path.isfile(p):
            messagebox.showwarning("База", "Укажите существующий JSON базового стандарта.")
            return
        if self.base is None or self.base_path != p:
            self.base = ac.load_json(p)
            self.base_path = p
        self.busy()
        try:
            self.tree.delete(*self.tree.get_children())
            self.item_seg.clear()
            self.item_val.clear()
            self.children_done.clear()
            self.children_map.clear()
            self.children_done[""] = True
            self._populate("", self.base)
            self.index = []
            self._walk(self.base, [], 0)
            self.search_pos = -1
            self.set_status("База: %s | узлов: %d" %
                            (os.path.basename(p), len(self.index)))
        finally:
            self.busy(False)

    # ---- дерево: ленивая подгрузка --------------------------------------
    def _seg_key(self, key, value):
        return seg_key(key, value)

    @staticmethod
    def _seg_idx(i, value):
        return seg_idx(i, value)

    @staticmethod
    def _segkey(seg):
        return segkey(seg)

    @staticmethod
    def _label_idx(i, value):
        return label_idx(i, value)

    def _populate(self, parent, value):
        m = self.children_map.setdefault(parent, {})
        if isinstance(value, dict):
            pairs = [(self._seg_key(k, v), v, k) for k, v in value.items()]
        elif isinstance(value, list):
            pairs = [(self._seg_idx(i, v), v, self._label_idx(i, v))
                     for i, v in enumerate(value)]
        else:
            return
        for seg, val, label in pairs:
            iid = self.tree.insert(parent, "end", text=shorten(label, 120))
            self.item_seg[iid] = seg
            self.item_val[iid] = val
            m[self._segkey(seg)] = iid
            if isinstance(val, (dict, list)) and val:
                self.tree.insert(iid, "end", text="…")
                self.children_done[iid] = False
            else:
                self.children_done[iid] = True

    def _ensure_children(self, iid):
        if self.children_done.get(iid, True):
            return
        for dummy in self.tree.get_children(iid):
            self.tree.delete(dummy)
        self.children_done[iid] = True
        self._populate(iid, self.item_val.get(iid))

    def _walk(self, node, segs, depth):
        if depth > 9:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                p = segs + [self._seg_key(k, v)]
                label = k if isinstance(v, (dict, list)) else "%s = %s" % (k, shorten(v, 70))
                self.index.append((label, p, v, "/".join(
                    str(x) for x in p)))
                self._walk(v, p, depth + 1)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                p = segs + [self._seg_idx(i, v)]
                self.index.append((self._label_idx(i, v), p, v, "/".join(
                    str(x) for x in p)))
                self._walk(v, p, depth + 1)

    def _on_tree_open(self, event):
        iid = self.tree.focus()
        if iid and not self.children_done.get(iid, True):
            self._ensure_children(iid)
        else:
            for node, done in list(self.children_done.items()):
                if node and not done and self.tree.exists(node) and \
                        self.tree.item(node, "open"):
                    self._ensure_children(node)

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        value = self.item_val.get(sel[0])
        try:
            self.grid_view.load(value, self.path_from_item(sel[0]),
                               self.tree.item(sel[0], "text"))
        except Exception as exc:
            self.write_log("Ошибка отображения узла в таблице: %s" % exc, "err")

    def path_from_item(self, iid):
        segs = []
        cur = iid
        while cur:
            if cur in self.item_seg:
                segs.append(self.item_seg[cur])
            cur = self.tree.parent(cur)
        return list(reversed(segs))

    def expand_to(self, segs):
        parent = ""
        for seg in segs:
            self._ensure_children(parent)
            iid = self.children_map.get(parent, {}).get(self._segkey(seg))
            if not iid:
                return None
            self.tree.item(iid, open=True)
            self._ensure_children(iid)
            parent = iid
        self.tree.selection_set(parent)
        self.tree.see(parent)
        self._on_tree_select(None)
        return parent

    def action_search(self):
        q = self.ent_search.get().strip().lower()
        if not q or not self.index:
            return
        n = len(self.index)
        for step in range(1, n + 1):
            i = (self.search_pos + step) % n
            label, path, _, joined = self.index[i]
            if q in label.lower() or q in joined.lower():
                self.search_pos = i
                if self.expand_to(path):
                    self.set_status("Найдено: %s" % shorten(label, 110))
                return
        self.set_status("Совпадений нет: %s" % q)

    def take_path(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Путь", "Сначала выберите узел в дереве базы.")
            return
        path = ce.render_path(self.path_from_item(sel[0]))
        set_entry(self.ent_path, path)
        self.nb.select(self.tab_op)
        self.set_status("Путь: %s" % path)

    def take_bylo(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("БЫЛО", "Сначала выберите узел в дереве базы.")
            return
        v = self.item_val.get(sel[0])
        if isinstance(v, dict):
            line = None
            for k in ("Краткое наименование ФК", "Примечание", "Наименование",
                      "Сигнал", "Параметр", "Значение"):
                if isinstance(v.get(k), str) and v[k]:
                    line = "БЫЛО.%s: %s" % (k, one_line(v[k]))
                    break
            if line is None:
                for k, vv in v.items():
                    if isinstance(vv, str) and vv:
                        line = "БЫЛО.%s: %s" % (k, one_line(vv))
                        break
            if line is None:
                line = "БЫЛО: %s" % one_line(json.dumps(v, ensure_ascii=False))
        else:
            line = "БЫЛО: %s" % one_line(v)
        set_text(self.txt_bylo, line)
        self.nb.select(self.tab_op)
        self.set_status("Подставлено: %s" % shorten(line, 100))

    def check_path(self):
        if self.base is None:
            messagebox.showwarning("Путь", "База не загружена.")
            return
        raw = self.ent_path.get().strip()
        try:
            parent, key, value, canon, _, _ = ac.resolve(self.base, ce.parse_path(raw))
            shown = (json.dumps(value, ensure_ascii=False)
                     if isinstance(value, (dict, list)) else str(value))
            self.write_log("Путь OK: %s\n  значение: %s" %
                           (ac.canon_str(canon), shorten(shown, 300)), "ok")
        except Exception as exc:
            self.write_log("Путь НЕ НАЙДЕН: %s\n  %s" % (raw, exc), "err")

    def on_grid_generate(self, blocks, warnings):
        """Правки таблицы узла -> новые операции в текущем документе."""
        for w in warnings:
            self.write_log("  ! таблица узла: " + w, "warn")
        if not blocks:
            return
        start = len(self.blocks)
        for b in blocks:
            self.blocks.append(b)
        self.rebuild_ops(select=start)
        self.nb.select(self.tab_op)
        self.write_log("Из таблицы узла добавлено операций: %d (%s)" %
                       (len(blocks), nt.summary(blocks)), "ok")
        self.set_status("Добавлено из таблицы: %d операций" % len(blocks))

    # ------------------------------------------------------ дублирование
    def suggest_copy_key(self, key, parent):
        base = "%s (копия)" % key
        if base not in parent:
            return base
        for i in range(2, 100):
            cand = "%s (копия %d)" % (key, i)
            if cand not in parent:
                return cand
        return base

    @staticmethod
    def _default_renumber(value):
        if isinstance(value, dict):
            if "№" in value:
                return True
            return "Строки" in value and "Столбцы" in value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return "№" in value[0]
        return False

    def ask_duplicate_options(self, parent, key, value, path):
        """Диалог параметров копии. Возвращает dict или None."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Дублирование узла")
        dlg.transient(self.root)
        dlg.resizable(False, True)
        dlg.geometry("780x600")
        result = {"value": None}

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Источник:").grid(row=0, column=0, sticky="nw")
        ttk.Label(frm, text=shorten(ce.render_path(path), 160), wraplength=620,
                  justify="left", foreground="#333333").grid(
            row=0, column=1, sticky="w")

        r = 1
        ent_key = None
        var_pos = None
        is_dict = isinstance(parent, dict)
        if isinstance(value, dict) and isinstance(value.get("Шифр шкафа"), str):
            ttk.Label(frm, text="В копии останется «Шифр шкафа»: %s — замените "
                                "его в «Заменах», иначе пути по шифру станут "
                                "неоднозначными." % value["Шифр шкафа"],
                      foreground="#8a6d3b", font=("Segoe UI", 8),
                      wraplength=720, justify="left").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
            r += 1
        if is_dict:
            ttk.Label(frm, text="Новый ключ:").grid(row=r, column=0, sticky="w",
                                                    pady=(10, 0))
            ent_key = ttk.Entry(frm)
            ent_key.grid(row=r, column=1, sticky="ew", pady=(10, 0))
            set_entry(ent_key, self.suggest_copy_key(key, parent))
            r += 1
            ttk.Label(frm, text="Копия встанет в тот же объект сразу после "
                                "источника; ключ должен быть уникальным.",
                      foreground="#666666", font=("Segoe UI", 8)).grid(
                row=r, column=1, sticky="w")
            r += 1
        else:
            ttk.Label(frm, text="Позиция вставки:").grid(
                row=r, column=0, sticky="w", pady=(10, 0))
            var_pos = tk.IntVar(value=min(len(parent), key + 1))
            ttk.Spinbox(frm, from_=0, to=len(parent), textvariable=var_pos,
                        width=8).grid(row=r, column=1, sticky="w", pady=(10, 0))
            r += 1
            ttk.Label(frm, text="0…%d; по умолчанию — сразу после источника."
                      % len(parent), foreground="#666666",
                      font=("Segoe UI", 8)).grid(row=r, column=1, sticky="w")
            r += 1

        ttk.Label(frm, text="Замены в копии (старое => новое, по одной в строке):"
                  ).grid(row=r, column=0, columnspan=2, sticky="w",
                         pady=(12, 2))
        r += 1
        rep_text = scrolledtext.ScrolledText(frm, height=6, wrap="none",
                                             font=("Consolas", 9))
        rep_text.grid(row=r, column=0, columnspan=2, sticky="nsew")
        frm.rowconfigure(r, weight=1)
        r += 1
        ttk.Label(frm, text="Заменяются имена полей и строковые значения. "
                            "Примеры: 431.02-0 => 431.04-0; "
                            "Таблица 5.3. => Таблица 5.4.",
                  foreground="#666666", font=("Segoe UI", 8),
                  wraplength=720, justify="left").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
        r += 1

        var_ren = tk.BooleanVar(value=self._default_renumber(value))
        var_edit = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Перенумеровать строки таблиц копии (1…N)",
                        variable=var_ren).grid(row=r, column=0, columnspan=2,
                                               sticky="w", pady=(10, 0))
        r += 1
        ttk.Checkbutton(frm, text="Открыть копию для правки",
                        variable=var_edit).grid(row=r, column=0, columnspan=2,
                                                sticky="w")
        r += 1

        def ok():
            reps, bad = [], None
            for lineno, line in enumerate(get_text(rep_text).splitlines(), 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                old, sep, new = s.partition("=>")
                if not sep or not old.strip():
                    bad = "строка %d: ожидается «старое => новое»" % lineno
                    break
                reps.append({"Старое": old.strip(), "Новое": new.strip()})
            if bad:
                messagebox.showerror("Дублирование", bad, parent=dlg)
                return
            out = {"replacements": reps, "renumber": bool(var_ren.get()),
                   "edit": bool(var_edit.get())}
            if is_dict:
                new_key = ent_key.get().strip()
                if not new_key:
                    messagebox.showerror("Дублирование",
                                         "Укажите ключ копии.", parent=dlg)
                    return
                if new_key in parent:
                    messagebox.showerror(
                        "Дублирование",
                        "Ключ %r уже существует — выберите другое имя."
                        % new_key, parent=dlg)
                    return
                out["key"] = new_key
            else:
                try:
                    pos = int(var_pos.get())
                except Exception:
                    pos = -1
                if not 0 <= pos <= len(parent):
                    messagebox.showerror(
                        "Дублирование",
                        "Позиция должна быть от 0 до %d." % len(parent),
                        parent=dlg)
                    return
                out["position"] = pos
            result["value"] = out
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=r, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Создать копию", command=ok).pack(side="left")
        ttk.Button(btns, text="Отмена", command=dlg.destroy).pack(side="left",
                                                                  padx=6)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        _place_over_parent(dlg, self.root)
        dlg.grab_set()
        dlg.wait_window()
        return result["value"]

    def copy_block(self, path, opts):
        lines = ["ДУБЛИРОВАТЬ %s" % ce.render_path(path)]
        if "key" in opts:
            lines.append("  КЛЮЧ: %s" % one_line(opts["key"]))
        else:
            lines.append("  ПОЗИЦИЯ: %d" % opts["position"])
        for rep in opts["replacements"]:
            lines.append("  ЗАМЕНА: %s" % ce.render_replacement(rep))
        if opts["renumber"]:
            lines.append("  ПЕРЕНУМЕРОВАТЬ: да")
        return "\n".join(lines)

    def _copy_editor_closed(self):
        self.copy_editor = None

    def duplicate_node(self):
        if self.base is None:
            messagebox.showwarning("Дублирование",
                                   "Сначала загрузите базовый стандарт.")
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Дублирование",
                                "Выберите узел в дереве базы.")
            return
        path = self.path_from_item(sel[0])
        if not path:
            messagebox.showinfo("Дублирование", "Узел не выбран.")
            return
        try:
            parent, key, value, canon, ancestors, phys = ac.resolve(
                self.base, path)
        except Exception as exc:
            messagebox.showerror("Дублирование",
                                 "Не удалось прочитать узел:\n%s" % exc)
            return
        if not isinstance(parent, (dict, list)):
            messagebox.showinfo("Дублирование",
                                "Корень стандарта нельзя дублировать.")
            return
        opts = self.ask_duplicate_options(parent, key, value, path)
        if not opts:
            return
        op = {"Операция": "COPY", "Путь": path,
              "Замены": opts["replacements"]}
        if "key" in opts:
            op["Ключ"] = opts["key"]
        else:
            op["Позиция"] = opts["position"]
        if opts["renumber"]:
            op["Перенумеровать"] = True
        block = self.copy_block(path, opts)
        self.blocks.append(block)
        self.rebuild_ops(select=len(self.blocks) - 1)
        self.nb.select(self.tab_op)
        self.write_log("Дублирование узла:\n%s" % block, "ok")
        self.set_status("Копия создана: %s" %
                        (opts.get("key") or "позиция %d" % opts["position"]))
        if not opts["edit"]:
            return
        try:
            copied, stats = ac.build_copy(value, op, "копия")
        except Exception as exc:
            messagebox.showerror("Дублирование",
                                 "Не удалось построить копию:\n%s" % exc)
            return
        new_path = list(path[:-1])
        if "key" in opts:
            new_path.append(opts["key"])
        else:
            new_path.append({"@index": opts["position"]})
        self.copy_editor = CopyEditor(
            self.root, copied, new_path,
            "копия %s" % (opts.get("key") or shorten(ce.render_path(path), 40)),
            on_generate=self.on_grid_generate, on_status=self.set_status,
            on_close=self._copy_editor_closed)
        self.write_log("Копия открыта для правки; замен: ключей %d, значений %d"
                       % (stats["keys"], stats["values"]), "ok")

    # ------------------------------------------------------ модель документа
    def sync_header(self):
        for token, w in self.header_entries.items():
            self.header[token] = w.get().strip()

    def load_header(self):
        for token, w in self.header_entries.items():
            set_entry(w, self.header.get(token, ""))

    def sync_form(self):
        if self._loading:
            return
        if self.cur_index is not None and 0 <= self.cur_index < len(self.blocks):
            self.blocks[self.cur_index] = self.form_to_block()

    def form_to_block(self):
        verb = self.cmb_verb.get().strip().upper() or "ЗАМЕНИТЬ"
        lines = ["%s %s" % (verb, self.ent_path.get().strip())]
        for w in (self.txt_bylo, self.txt_stalo, self.txt_fields, self.txt_extra):
            for line in get_text(w).splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    lines.append("  " + s)
        return "\n".join(lines)

    def block_to_form(self, block):
        lines = block.splitlines()
        verb, path = split_first(lines[0] if lines else "ЗАМЕНИТЬ ")
        verb = VERB_ALIASES.get(verb, verb)
        if verb not in VERBS:
            verb = "ЗАМЕНИТЬ"
        buckets = {"bylo": [], "stalo": [], "fields": [], "extra": []}
        has_fields = False
        for line in lines[1:]:
            s = line.strip()
            if not s:
                continue
            if re.match(r"^БЫЛО", s, re.I):
                buckets["bylo"].append(s)
            elif s.startswith(">"):
                buckets["fields"].append(s)
                has_fields = True
            elif re.match(r"^(СТАЛО|ЗНАЧЕНИЕ)\s*:", s, re.I):
                buckets["stalo"].append(s)
            else:
                buckets["extra"].append(s)
        if has_fields and verb == "ЗАМЕНИТЬ":
            verb = "ИЗМЕНИТЬ ПОЛЯ"
        self.cmb_verb.set(verb)
        set_entry(self.ent_path, path)
        set_text(self.txt_bylo, "\n".join(buckets["bylo"]))
        set_text(self.txt_stalo, "\n".join(buckets["stalo"]))
        set_text(self.txt_fields, "\n".join(buckets["fields"]))
        set_text(self.txt_extra, "\n".join(buckets["extra"]))

    def _load_selected(self):
        self._loading = True
        try:
            if self.cur_index is None or self.cur_index >= len(self.blocks):
                set_entry(self.ent_path, "")
                set_text(self.txt_bylo, "")
                set_text(self.txt_stalo, "")
                set_text(self.txt_fields, "")
                set_text(self.txt_extra, "")
                self.cmb_verb.set("ЗАМЕНИТЬ")
            else:
                self.block_to_form(self.blocks[self.cur_index])
        finally:
            self._loading = False

    def rebuild_ops(self, select=None):
        self._loading = True
        try:
            self.ops.delete(*self.ops.get_children())
            for i, b in enumerate(self.blocks):
                lines = b.splitlines()
                verb, path = split_first(lines[0] if lines else "")
                self.ops.insert("", "end", iid=str(i),
                                values=(i + 1, verb, shorten(path, 90)))
            if select is not None:
                self.cur_index = select
            if self.blocks:
                self.cur_index = max(0, min(self.cur_index or 0, len(self.blocks) - 1))
                self.ops.selection_set(str(self.cur_index))
                self.ops.see(str(self.cur_index))
            else:
                self.cur_index = None
        finally:
            self._loading = False
        self._load_selected()

    def build_text(self):
        self.sync_header()
        self.sync_form()
        lines = list(self.preamble)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        seen = set()
        for token in HEADER_ORDER:
            value = self.header.get(token, "")
            # Пустые поля, которых не было в исходном файле, не добавляем:
            # иначе, например, пустой ХЭШ превратился бы в «Применимо к».
            if value or token in self.header_present:
                lines.append("%s: %s" % (token, value))
            seen.add(token)
        for token, value in self.header.items():
            if token not in seen:
                lines.append("%s: %s" % (token, value))
        lines.append("")
        for block in self.blocks:
            lines.append(block.strip("\n"))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def set_document(self, text, starter=False):
        self.preamble, self.header, self.blocks = split_document(text)
        self.header_present = set(self.header.keys())
        # БАЗА / ХЭШ не подставляем автоматически: у открытого файла мог
        # намеренно отсутствовать хэш (например, ИЗМ-3). Для нового документа
        # они уже есть в шаблоне, а для существующего — кнопка «Заполнить».
        defaults = {
            "ИЗМЕНЕНИЕ": "ИЗМ-4", "ВЕРСИЯ": "1",
            "ДАТА": date.today().isoformat(), "ПОРЯДОК": "10",
            "СТАТУС": "действует", "ЗАМЕНЯЕТ": "",
        }
        for k, v in defaults.items():
            self.header.setdefault(k, v)
        if starter and not self.blocks:
            self.blocks = ["ЗАМЕНИТЬ \n  СТАЛО: "]
        self.cur_index = 0 if self.blocks else None
        self.load_header()
        self.rebuild_ops()
        self.edition = None
        self.set_title()

    def set_title(self):
        name = os.path.basename(self.path) if self.path else "(новое изменение)"
        self.root.title("Редактор изменений стандарта — %s" % name)

    # ---------------------------------------------------------- команды GUI
    def _on_op_select(self, event):
        if self._loading:
            return
        sel = self.ops.selection()
        if not sel:
            return
        try:
            new = int(sel[0])
        except ValueError:
            return
        if new == self.cur_index:
            return
        self.sync_form()
        self.cur_index = new
        self._load_selected()

    def _on_tab_changed(self, event):
        if self.nb.select() == str(self.tab_text):
            set_text(self.doc_text, self.build_text())

    def apply_form_now(self):
        self.sync_form()
        self.rebuild_ops()
        self.set_status("Форма применена к операции %s" %
                        ((self.cur_index or 0) + 1))

    def apply_doc_text(self):
        text = get_text(self.doc_text)
        try:
            ce.compile_text(text)
        except Exception as exc:
            messagebox.showerror("Текст", "Ошибка разбора: %s" % exc)
            return
        self.preamble, self.header, self.blocks = split_document(text)
        self.header_present = set(self.header.keys())
        for k, v in (("ИЗМЕНЕНИЕ", "ИЗМ-4"), ("ВЕРСИЯ", "1"),
                     ("ДАТА", date.today().isoformat()), ("ПОРЯДОК", "10"),
                     ("СТАТУС", "действует"), ("ЗАМЕНЯЕТ", "")):
            self.header.setdefault(k, v)
        self.cur_index = 0 if self.blocks else None
        self.load_header()
        self.rebuild_ops()
        self.write_log("Текст применён: операций %d" % len(self.blocks), "ok")

    def add_op(self):
        self.sync_form()
        sel = self.tree.selection()
        path = ce.render_path(self.path_from_item(sel[0])) if sel else ""
        self.blocks.append("ЗАМЕНИТЬ %s\n  СТАЛО: " % path)
        self.rebuild_ops(select=len(self.blocks) - 1)

    def del_op(self):
        self.sync_form()
        if self.cur_index is None:
            return
        del self.blocks[self.cur_index]
        self.cur_index = min(self.cur_index, len(self.blocks) - 1)
        if not self.blocks:
            self.cur_index = None
        self.rebuild_ops()

    def dup_op(self):
        self.sync_form()
        if self.cur_index is None:
            return
        self.blocks.insert(self.cur_index + 1, self.blocks[self.cur_index])
        self.rebuild_ops(select=self.cur_index + 1)

    def move_up(self):
        self.sync_form()
        i = self.cur_index
        if i is None or i == 0:
            return
        self.blocks[i - 1], self.blocks[i] = self.blocks[i], self.blocks[i - 1]
        self.rebuild_ops(select=i - 1)

    def move_down(self):
        self.sync_form()
        i = self.cur_index
        if i is None or i >= len(self.blocks) - 1:
            return
        self.blocks[i + 1], self.blocks[i] = self.blocks[i], self.blocks[i + 1]
        self.rebuild_ops(select=i + 1)

    def fill_base_header(self):
        if not self.base_path:
            messagebox.showwarning("База", "База не загружена.")
            return
        self.header["БАЗА"] = self.base.get("Шифр стандарта", "")
        self.header["ХЭШ"] = ac.sha256_file(self.base_path)
        self.load_header()
        self.set_status("БАЗА / ХЭШ обновлены")

    # ------------------------------------------------------------- файлы
    def new_doc(self):
        text = ce.TEMPLATE.format(
            id="ИЗМ-4", date=date.today().isoformat(), order=10,
            base=self.base_path or "",
            base_code=self.base.get("Шифр стандарта", "") if self.base else "",
            base_sha=ac.sha256_file(self.base_path) if self.base_path else "")
        self.path = None
        self.set_document(text, starter=True)
        self.set_status("Новое изменение")

    def open_doc(self):
        p = filedialog.askopenfilename(
            title="Открыть изменение", initialdir=CHANGES_DEFAULT,
            filetypes=[("Текстовые изменения", "*.изм.txt"),
                       ("JSON изменения", "*.json"), ("Все файлы", "*.*")])
        if not p:
            return
        try:
            if p.lower().endswith(".json"):
                text = ce.decompile(ac.load_json(p))
                self.path = os.path.splitext(p)[0] + ce.TEXT_EXT
            else:
                text = open(p, encoding="utf-8").read()
                self.path = p
        except Exception as exc:
            messagebox.showerror("Открытие", str(exc))
            return
        self.set_document(text)
        self.set_status("Открыто: %s" % os.path.basename(p))

    def save_doc(self):
        if not self.path:
            return self.save_as()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.build_text())
        except OSError as exc:
            messagebox.showerror("Сохранение", str(exc))
            return
        self.set_title()
        self.write_log("Сохранено: %s" % self.path, "ok")

    def save_as(self):
        p = filedialog.asksaveasfilename(
            title="Сохранить изменение", initialdir=CHANGES_DEFAULT,
            defaultextension=ce.TEXT_EXT,
            filetypes=[("Текстовые изменения", "*.изм.txt"), ("Все файлы", "*.*")])
        if not p:
            return
        self.path = p
        self.save_doc()

    def export_json(self):
        try:
            cs, _ = ce.compile_text(self.build_text())
        except Exception as exc:
            messagebox.showerror("Экспорт", str(exc))
            return
        p = filedialog.asksaveasfilename(
            title="Канонический JSON изменения", initialdir=CHANGES_DEFAULT,
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cs, f, ensure_ascii=False, indent=2)
        self.write_log("Экспорт JSON: %s" % p, "ok")

    # ------------------------------------------------------------- сборка
    def collect_texts(self):
        """Текущий документ + остальные *.изм.txt из того же каталога."""
        current = self.build_text()
        folder = os.path.dirname(self.path) if self.path else CHANGES_DEFAULT
        cur_src = self.path or os.path.join(folder, "Текущее.изм.txt")
        out = [(cur_src, current)]
        if os.path.isdir(folder):
            skip = {os.path.normcase(os.path.abspath(cur_src))}
            for f in sorted(glob.glob(os.path.join(folder, "*" + ce.TEXT_EXT))):
                if os.path.normcase(os.path.abspath(f)) not in skip:
                    out.append((f, open(f, encoding="utf-8").read()))
        return out

    def compile_all(self):
        compiled = []
        for src, text in self.collect_texts():
            try:
                cs, warns = ce.compile_text(text)
            except Exception as exc:
                self.write_log("%s: ОШИБКА разбора: %s" %
                               (os.path.basename(src), exc), "err")
                return None
            compiled.append((src, cs, warns))
        compiled.sort(key=ce.sort_key)
        return compiled

    def action_check(self):
        if self.base is None:
            messagebox.showwarning("Проверка", "Сначала загрузите базовый стандарт.")
            return
        compiled = self.compile_all()
        if compiled is None:
            return
        work = copy.deepcopy(self.base)
        ok = True
        self.write_log("ПРОВЕРКА (%d файлов)" % len(compiled), "hdr")
        for src, cs, warns in compiled:
            errors = ce.check_paths(cs, self.base, work)
            for w in warns:
                errors.append("ПРЕДУПРЕЖДЕНИЕ: " + w)
            n = len(cs.get("Изменения", []))
            self.write_log("  %-24s %s v%s, операций %d%s" %
                           (os.path.basename(src), cs["Идентификатор"],
                            cs.get("Версия", 1), n,
                            "" if not errors else " — ОШИБКИ"),
                           None if not errors else "err")
            for e in errors:
                self.write_log("      ! " + e, "err")
                ok = False
        self.write_log("ИТОГ: %s" % ("OK" if ok else "есть ошибки"),
                       "ok" if ok else "err")
        self.set_status("Проверка: %s" % ("OK" if ok else "ошибки"))

    def action_assemble(self):
        if self.base is None:
            messagebox.showwarning("Сборка", "Сначала загрузите базовый стандарт.")
            return
        compiled = self.compile_all()
        if compiled is None:
            return
        self.busy()
        try:
            with tempfile.TemporaryDirectory(prefix="sto-gui-") as tmp:
                sources, used = {}, set()
                for i, (src, cs, _) in enumerate(compiled):
                    name = "%02d_%s" % (i, re.sub(r"\.изм\.txt$", "",
                                                  os.path.basename(src)) + ".json")
                    if name in used:
                        name = "%03d.json" % i
                    used.add(name)
                    p = os.path.join(tmp, name)
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(cs, f, ensure_ascii=False, indent=2)
                    sources[os.path.abspath(p)] = src
                try:
                    (data, ctx, registry, skipped, base_sha,
                     problems, warnings) = ac.assemble(
                        self.base_path, [tmp], strict=self.var_strict.get(),
                        ignore_hash=self.var_ignore_hash.get())
                except ac.ChangeError as exc:
                    msg = str(exc)
                    for t, s in sources.items():
                        msg = msg.replace(t, s)
                    self.write_log("ОШИБКА СБОРКИ: " + msg, "err")
                    self.set_status("Сборка: ошибка")
                    return
            self.edition = data
            report = ac.build_report(ctx, registry, skipped, base_sha,
                                     problems, warnings)
            self.write_log(report, "err" if problems else None)
            self.set_status("Сборка: %d изменений, %d операций%s" %
                            (len(registry),
                             sum(r["Операций"] for r in registry),
                             ", ОШИБКИ" if problems else " · OK"))
        finally:
            self.busy(False)

    def save_edition(self):
        if self.edition is None:
            messagebox.showinfo("Редакция", "Сначала выполните «Собрать редакцию».")
            return
        p = filedialog.asksaveasfilename(
            title="Собранный JSON редакции", initialdir=ROOT,
            defaultextension=".json", initialfile="Редакция_с_изменениями.json",
            filetypes=[("JSON", "*.json")])
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.edition, f, ensure_ascii=False, indent=2)
        self.write_log("Редакция записана: %s" % p, "ok")

    def action_docx(self):
        data = self.edition
        if data is None:
            p = filedialog.askopenfilename(
                title="Выберите собранный JSON редакции", initialdir=ROOT,
                filetypes=[("JSON", "*.json")])
            if not p:
                return
            try:
                data = ac.load_json(p)
            except Exception as exc:
                messagebox.showerror("DOCX", str(exc))
                return
        out = filedialog.asksaveasfilename(
            title="Отчёт DOCX", initialdir=ROOT, defaultextension=".docx",
            initialfile="Редакция_с_изменениями.docx",
            filetypes=[("Word", "*.docx")])
        if not out:
            return
        self.busy()
        try:
            import json_to_docx
            stats = json_to_docx.build_report(data, out, toc=self.var_toc.get())
            self.write_log("Отчёт DOCX: %s\n  шкафов %d, комплектов %d, "
                           "таблиц %d, строк %d" %
                           (out, stats["cabinets"], stats["complects"],
                            stats["tables"], stats["rows"]), "ok")
            self.set_status("DOCX готов: %s" % os.path.basename(out))
        except SystemExit as exc:
            # json_to_docx.py при отсутствии python-docx делает sys.exit():
            # в GUI это не должно закрывать всё окно.
            msg = str(exc) or "Не установлен python-docx"
            msg += ("\n\nТекущий интерпретатор:\n%s\n\n"
                    "Установите пакет именно в него:\n"
                    "\"%s\" -m pip install python-docx"
                    % (sys.executable, sys.executable))
            self.write_log("ОШИБКА DOCX: %s" % msg, "err")
            messagebox.showerror("DOCX", msg)
        except Exception as exc:
            self.write_log("ОШИБКА DOCX: %s\n%s" %
                           (exc, traceback.format_exc()), "err")
        finally:
            self.busy(False)

    # ------------------------------------------------------------- справка
    def show_help(self):
        w = tk.Toplevel(self.root)
        w.title("Формат *.изм.txt")
        w.geometry("900x700")
        t = scrolledtext.ScrolledText(w, wrap="word", font=("Consolas", 9))
        t.pack(fill="both", expand=True, padx=6, pady=6)
        t.insert("1.0", (ce.__doc__ or "").strip())
        t.configure(state="disabled")
        _place_over_parent(w, self.root)

    def show_about(self):
        messagebox.showinfo(
            "О программе",
            "Графический редактор изменений стандарта\n\n"
            "Формат: %s\n"
            "Проверка/сборка: changes_editor.py + apply_changes.py\n"
            "Отчёт: json_to_docx.py\n\n"
            "GUI пишет обычные текстовые *.изм.txt — их можно править "
            "в любом текстовом редакторе.\n\n"
            "Дублирование: выберите узел → «Дублировать узел». Копия "
            "создаётся операцией COPY (в тексте — ДУБЛИРОВАТЬ) и встаёт "
            "рядом с источником; замены и правки применяются к копии.\n\n"
            "Новый стандарт: «База → Создать стандарт на основе выбранного» — "
            "копия стандарта с новыми реквизитами, набором шкафов и заменами. "
            "Исходный файл не изменяется."
            % ac.FORMAT)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        try:
            messagebox.showerror("Ошибка", tb[-2000:])
        except Exception:
            pass
        sys.exit(1)
