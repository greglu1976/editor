"""Изолированный тестовый чертёж шкафов по UML-выгрузке EA.

Модуль читает только ``EA/cabinets_uml.json``, работает в собственном
``Toplevel`` с собственным ``Canvas`` и хранит пробные сборки/размещения
в отдельном JSON-файле по выбору пользователя. Логика вкладки не использует
компоненты, каталоги и состояние основного редактора схем.
"""

import copy
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "EA", "cabinets_uml.json")
STATE_VERSION = 1
STATE_KIND = "ea-uml-test-drawing"

WINDOW_TITLE = "UML-шкафы: тестовый чертёж"
BG = "#f3f3f3"
PANEL = "#ffffff"
CANVAS_BG = "#ffffff"
TEXT = "#263238"
MUTED = "#607d8b"
ACCENT = "#1565c0"
ACCENT_LIGHT = "#e3f2fd"
GRID = "#e8edf1"
GRID_MAJOR = "#d4dee6"
BORDER = "#78909c"
CABINET_FILL = "#fffdf5"
KIT_FILL = "#f2f8ff"

_WINDOWS = {}


def text_or(value, default=""):
    """Аккуратно приводит значение UML-атрибута к строке."""
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def clip(value, limit):
    """Обрезает длинную подпись для компактного вида на холсте."""
    value = text_or(value)
    if len(value) <= limit:
        return value
    return value[:max(1, limit - 1)].rstrip() + "…"


def ied_count(kit):
    return len(kit.get("IED", []) or [])


def terminal_block_count(kit):
    return len(kit.get("TerminalBlock", []) or [])


def terminal_count(kit):
    return sum(
        len(row.get("Terminal", []) or [])
        for block in kit.get("TerminalBlock", []) or []
        for row in block.get("TerminalRow", []) or []
    )


def function_count(kit):
    return sum(
        len(ied.get("Function", []) or [])
        for ied in kit.get("IED", []) or []
    )


def cabinet_kit_count(cabinet):
    return len(cabinet.get("Kit", []) or [])


def cabinet_label(record, prefix=""):
    cabinet = record.get("Cabinet", {}) if isinstance(record, dict) else {}
    code = text_or(cabinet.get("cypher"), "Без шифра")
    name = text_or(cabinet.get("name"), "Без наименования")
    kits = cabinet_kit_count(cabinet)
    label = "%s%s — %s  [%d компл.]" % (prefix, code, clip(name, 52), kits)
    return label


def kit_label(item):
    kit = item["kit"]
    return "%s | %s | ИЭУ %d | функций %d | блоков %d | клемм %d" % (
        clip(item.get("source_cypher"), 18),
        clip(kit.get("description"), 34),
        ied_count(kit),
        function_count(kit),
        terminal_block_count(kit),
        terminal_count(kit),
    )


def load_uml_catalog(path=DATA_PATH):
    """Загружает UML-выгрузку и готовит независимые копии шкафов.

    Возвращает словарь с исходными шкафами, значением ``Cabinet.standard``
    и метаданными стандарта. Содержимое файла не изменяется.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or not isinstance(data.get("шкафы"), list):
        raise ValueError("В UML-выгрузке нет списка 'шкафы'")

    cabinets = []
    standards = set()
    for entry in data["шкафы"]:
        if not isinstance(entry, dict):
            continue
        cabinet = entry.get("Cabinet")
        if not isinstance(cabinet, dict):
            continue
        cabinets.append({
            "Cabinet": copy.deepcopy(cabinet),
            "CabinetReport": copy.deepcopy(entry.get("CabinetReport") or {}),
        })
        if cabinet.get("standard"):
            standards.add(text_or(cabinet.get("standard")))

    if not cabinets:
        raise ValueError("В UML-выгрузке не найдено ни одного Cabinet")

    standard = (sorted(standards)[0] if standards else
                text_or((data.get("стандарт") or {}).get("шифр"),
                        "Стандарт не указан"))
    return {
        "path": os.path.abspath(path),
        "standard": standard,
        "standards": sorted(standards),
        "standard_meta": copy.deepcopy(data.get("стандарт") or {}),
        "class_count": len((data.get("схема") or {}).get("классы") or {}),
        "cabinets": cabinets,
    }


def collect_kits(records, kind):
    """Собирает доступные комплекты из записей ``{'Cabinet': ...}``."""
    result = []
    for cabinet_index, record in enumerate(records):
        cabinet = record.get("Cabinet", {})
        for kit_index, kit in enumerate(cabinet.get("Kit", []) or []):
            result.append({
                "id": "%s:%d:%d" % (kind, cabinet_index, kit_index),
                "kind": kind,
                "source_cypher": text_or(cabinet.get("cypher"), "Без шифра"),
                "source_name": text_or(cabinet.get("name")),
                "source_standard": text_or(cabinet.get("standard")),
                "kit": copy.deepcopy(kit),
            })
    return result


def assemble_cabinet(cypher, name, standard, kit_items, description=""):
    """Создаёт новую UML-образную запись Cabinet из выбранных Kit.

    В результат попадают только атрибуты ``Cabinet`` и композиция
    ``Cabinet.Kit``; каждый скопированный комплект получает новый номер.
    """
    if not kit_items:
        raise ValueError("Нужно выбрать хотя бы один комплект")

    cypher = text_or(cypher)
    name = text_or(name)
    standard = text_or(standard)
    if not cypher:
        raise ValueError("Не задан шифр нового шкафа")
    if not name:
        raise ValueError("Не задано наименование нового шкафа")

    kits = []
    for number, item in enumerate(kit_items, start=1):
        kit = copy.deepcopy(item["kit"])
        kit["number"] = number
        kits.append(kit)

    sources = ", ".join(
        "%s / %s" % (text_or(item.get("source_cypher"), "?"),
                     clip(item["kit"].get("description"), 30))
        for item in kit_items
    )
    base_description = "Сборка из существующих комплектов: %s" % sources
    full_description = (text_or(description) + "\n" + base_description).strip()

    cabinet = {
        "standard": standard,
        "cypher": cypher,
        "architecture": "Сборный",
        "name": name,
        "scope": "Тестовая сборка",
        "description": full_description,
        "Kit": kits,
    }
    report = {
        "cab_cypher": cypher,
        "architecture": "Сборный",
        "cab_name": name,
        "components": [],
    }
    return {"Cabinet": cabinet, "CabinetReport": report}


def summarize_cabinet(record):
    """Текстовая карточка шкафа для правой панели."""
    cabinet = record.get("Cabinet", {}) if isinstance(record, dict) else {}
    kits = cabinet.get("Kit", []) or []
    lines = [
        "Шифр: %s" % text_or(cabinet.get("cypher"), "—"),
        "Наименование: %s" % text_or(cabinet.get("name"), "—"),
        "Standard: %s" % text_or(cabinet.get("standard"), "—"),
        "Архитектура: %s" % text_or(cabinet.get("architecture"), "—"),
        "Область применения: %s" % text_or(cabinet.get("scope"), "—"),
        "Управляемый элемент: %s" % text_or(
            cabinet.get("controllable_element"), "—"),
        "Защищаемый элемент: %s" % text_or(
            cabinet.get("protected_element"), "—"),
        "",
        "Описание:",
        text_or(cabinet.get("description"), "—"),
        "",
        "Комплектов: %d" % len(kits),
    ]
    for index, kit in enumerate(kits, start=1):
        lines.append(
            "  %d. %s — ИЭУ %d, функций %d, блоков зажимов %d, клемм %d" % (
                index,
                text_or(kit.get("description"), "Комплект"),
                ied_count(kit),
                function_count(kit),
                terminal_block_count(kit),
                terminal_count(kit),
            )
        )
    return "\n".join(lines)


def cabinet_size(cabinet):
    """Размер условного обозначения шкафа на отдельном тестовом холсте."""
    kits = cabinet.get("Kit", []) or []
    shown = min(len(kits), 6)
    extra = 22 if len(kits) > shown else 0
    return 310, 78 + shown * 52 + extra + 24


def _window_key(parent, path):
    return (id(parent), os.path.abspath(path))


def _window_alive(instance):
    try:
        return bool(instance.window.winfo_exists())
    except (AttributeError, tk.TclError):
        return False


def _release_window(instance):
    for key, value in list(_WINDOWS.items()):
        if value is instance:
            _WINDOWS.pop(key, None)


def get_test_window(parent, path=DATA_PATH):
    """Возвращает единственное тестовое окно для заданного родителя."""
    key = _window_key(parent, path)
    instance = _WINDOWS.get(key)
    if instance and _window_alive(instance):
        return instance
    instance = UmlTestWindow(parent, path)
    _WINDOWS[key] = instance
    return instance


def show_test_window(parent, path=DATA_PATH):
    """Открывает изолированный тестовый чертёж."""
    instance = get_test_window(parent, path)
    instance.bring_to_front()
    return instance


def show_assembly_window(parent, path=DATA_PATH):
    """Открывает тестовый чертёж и сразу диалог сборки шкафа."""
    instance = get_test_window(parent, path)
    instance.bring_to_front()
    instance.open_assembly_dialog()
    return instance


class UmlTestWindow:
    """Окно с каталогом UML-шкафов, сборкой и отдельным холстом."""

    def __init__(self, parent, path=DATA_PATH):
        self.parent = parent
        self.catalog = load_uml_catalog(path)
        self.custom_cabinets = []
        self.placed = []
        self.next_uid = 1
        self.selected_uid = None
        self.catalog_index = []
        self._drag = None
        self._assembly_dialog = None
        self.state_path = None

        self.window = tk.Toplevel(parent)
        self.window.title(WINDOW_TITLE)
        self.window.geometry("1180x720")
        self.window.minsize(900, 560)
        self.window.configure(bg=BG)
        try:
            self.window.transient(parent)
        except tk.TclError:
            pass
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self._refresh_catalog()
        self._redraw()
        self._set_status(
            "Загружено шкафов: %d; классов UML: %d; standard: %s" % (
                len(self.catalog["cabinets"]),
                self.catalog["class_count"],
                self.catalog["standard"],
            ))

    # ------------------------------------------------------------- построение
    def _build_ui(self):
        toolbar = tk.Frame(self.window, bg=BG)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))

        buttons = [
            ("Вынести шкаф", self.place_selected),
            ("Собрать из комплектов…", self.open_assembly_dialog),
            ("Убрать с чертежа", self.delete_selected_placed),
            ("Очистить чертёж", self.clear_drawing),
            ("Сохранить…", self.save_state),
            ("Загрузить…", self.load_state),
        ]
        for label, command in buttons:
            tk.Button(toolbar, text=label, command=command, bg=PANEL,
                      fg=TEXT, activebackground=ACCENT_LIGHT,
                      relief=tk.GROOVE, bd=1, padx=8, pady=3).pack(
                          side=tk.LEFT, padx=(0, 4))

        body = tk.Frame(self.window, bg=BG)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = tk.LabelFrame(body, text="Шкафы UML-выгрузки и сборки",
                             bg=BG, fg=TEXT, padx=6, pady=6)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left.configure(width=340)
        left.pack_propagate(False)

        self.catalog_list = tk.Listbox(
            left, width=48, height=24, exportselection=False,
            bg=PANEL, fg=TEXT, selectbackground=ACCENT_LIGHT,
            selectforeground=ACCENT, highlightthickness=1,
            highlightcolor=BORDER, activestyle="none")
        catalog_scroll = tk.Scrollbar(left, orient=tk.VERTICAL,
                                      command=self.catalog_list.yview)
        self.catalog_list.configure(yscrollcommand=catalog_scroll.set)
        self.catalog_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        catalog_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.catalog_list.bind("<<ListboxSelect>>",
                               self._on_catalog_select)
        self.catalog_list.bind("<Double-Button-1>",
                               lambda event: self.place_selected())

        catalog_actions = tk.Frame(left, bg=BG)
        catalog_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        tk.Button(catalog_actions, text="На чертёж",
                  command=self.place_selected, width=14).pack(side=tk.LEFT)
        tk.Button(catalog_actions, text="Удалить сборку",
                  command=self.delete_selected_custom,
                  width=16).pack(side=tk.LEFT, padx=(4, 0))

        center = tk.LabelFrame(body, text="Тестовый чертёж",
                               bg=BG, fg=TEXT, padx=4, pady=4)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self.canvas = tk.Canvas(center, bg=CANVAS_BG,
                                highlightthickness=1,
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
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        right = tk.LabelFrame(body, text="Карточка", bg=BG, fg=TEXT,
                              padx=6, pady=6)
        right.pack(side=tk.RIGHT, fill=tk.BOTH)
        right.configure(width=290)
        right.pack_propagate(False)
        self.details = tk.Text(right, wrap=tk.WORD, bg=PANEL, fg=TEXT,
                               relief=tk.FLAT, padx=8, pady=8,
                               font=("Arial", 9))
        details_scroll = tk.Scrollbar(right, orient=tk.VERTICAL,
                                      command=self.details.yview)
        self.details.configure(yscrollcommand=details_scroll.set,
                               state="disabled")
        self.details.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        details_scroll.pack(side=tk.RIGHT, fill=tk.Y)

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
        _release_window(self)
        self.window.destroy()

    # --------------------------------------------------------------- каталог
    def _refresh_catalog(self):
        selection = self.catalog_list.curselection()
        previous = selection[0] if selection else None
        self.catalog_list.delete(0, tk.END)
        self.catalog_index = []

        for index, record in enumerate(self.catalog["cabinets"]):
            self.catalog_index.append(("standard", index, record))
            self.catalog_list.insert(tk.END, cabinet_label(record))
        for index, record in enumerate(self.custom_cabinets):
            self.catalog_index.append(("custom", index, record))
            self.catalog_list.insert(
                tk.END, cabinet_label(record, prefix="СБОРНЫЙ | "))
            self.catalog_list.itemconfig(tk.END, fg=ACCENT)

        if previous is not None and previous < self.catalog_list.size():
            self.catalog_list.selection_set(previous)
            self.catalog_list.activate(previous)
        elif self.catalog_list.size():
            self.catalog_list.selection_set(0)
            self.catalog_list.activate(0)
        self._on_catalog_select()

    def _selected_catalog_entry(self):
        selection = self.catalog_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.catalog_index):
            return None
        return self.catalog_index[index]

    def _on_catalog_select(self, event=None):
        entry = self._selected_catalog_entry()
        if not entry:
            self._set_details("Выберите шкаф в списке слева.")
            return
        kind, _, record = entry
        title = "Сборный шкаф\n\n" if kind == "custom" else "Шкаф UML-выгрузки\n\n"
        self._set_details(title + summarize_cabinet(record))

    def collect_available_kits(self):
        return (collect_kits(self.catalog["cabinets"], "uml") +
                collect_kits(self.custom_cabinets, "assembly"))

    def taken_cyphers(self):
        return {
            text_or(record.get("Cabinet", {}).get("cypher")).lower()
            for record in (self.catalog["cabinets"] + self.custom_cabinets)
        }

    def next_custom_cypher(self):
        taken = self.taken_cyphers()
        number = 1
        while ("сборный-%d" % number) in taken:
            number += 1
        return "СБОРНЫЙ-%d" % number

    def default_standard(self):
        return self.catalog["standard"]

    def delete_selected_custom(self):
        entry = self._selected_catalog_entry()
        if not entry or entry[0] != "custom":
            messagebox.showwarning(
                "Удаление сборки",
                "Удалить можно только шкаф, собранный в этом тестовом окне.",
                parent=self.window)
            return
        _, index, record = entry
        code = text_or(record.get("Cabinet", {}).get("cypher"))
        if not messagebox.askyesno(
                "Удаление сборки", "Удалить сборный шкаф %s из списка?" % code,
                parent=self.window):
            return
        self.custom_cabinets.pop(index)
        self._refresh_catalog()
        self._set_status("Сборный шкаф удалён из списка: %s" % code)

    # --------------------------------------------------------------- сборка
    def open_assembly_dialog(self):
        if self._assembly_dialog and _dialog_alive(self._assembly_dialog):
            self._assembly_dialog.bring_to_front()
            return self._assembly_dialog
        dialog = AssemblyDialog(
            self.window,
            kits=self.collect_available_kits(),
            default_cypher=self.next_custom_cypher(),
            default_standard=self.default_standard(),
            taken_cyphers=self.taken_cyphers(),
            on_create=self._on_assembly_created,
            on_close=self._on_assembly_dialog_closed)
        self._assembly_dialog = dialog
        return dialog

    def _on_assembly_dialog_closed(self, dialog):
        if self._assembly_dialog is dialog:
            self._assembly_dialog = None

    def _on_assembly_created(self, record, place):
        cypher = text_or(record.get("Cabinet", {}).get("cypher"))
        if cypher.lower() in self.taken_cyphers():
            messagebox.showerror(
                "Сборка шкафа",
                "Шкаф с шифром %s уже есть в списке." % cypher,
                parent=self.window)
            return False
        self.custom_cabinets.append(copy.deepcopy(record))
        self._refresh_catalog()
        last = self.catalog_list.size() - 1
        if last >= 0:
            self.catalog_list.selection_clear(0, tk.END)
            self.catalog_list.selection_set(last)
            self.catalog_list.activate(last)
            self.catalog_list.see(last)
        self._on_catalog_select()
        if place:
            self.place_selected()
        self._set_status("Создан сборный шкаф %s; комплектов: %d" % (
            cypher, cabinet_kit_count(record.get("Cabinet", {}))))
        return True

    # --------------------------------------------------------------- чертёж
    def place_selected(self):
        entry = self._selected_catalog_entry()
        if not entry:
            messagebox.showwarning(
                "Вынос шкафа", "Сначала выберите шкаф в списке.",
                parent=self.window)
            return None
        _, _, record = entry
        cabinet = copy.deepcopy(record.get("Cabinet", {}))
        number = len(self.placed)
        uid = "C%d" % self.next_uid
        self.next_uid += 1
        item = {
            "uid": uid,
            "cabinet": cabinet,
            "x": 40 + (number % 3) * 360,
            "y": 40 + (number // 3) * 350,
        }
        self.placed.append(item)
        self.selected_uid = uid
        self._redraw()
        self._show_placed_details(uid)
        self._set_status("На чертёж вынесен шкаф %s (%s)" % (
            text_or(cabinet.get("cypher"), "без шифра"), uid))
        return item

    def delete_selected_placed(self):
        if not self.selected_uid:
            messagebox.showwarning(
                "Удаление с чертежа", "Сначала выберите шкаф на чертеже.",
                parent=self.window)
            return
        self.placed = [item for item in self.placed
                       if item.get("uid") != self.selected_uid]
        uid = self.selected_uid
        self.selected_uid = None
        self._redraw()
        self._set_details("Шкаф %s убран с чертежа." % uid)
        self._set_status("Шкаф %s убран с чертежа" % uid)

    def clear_drawing(self):
        if self.placed and not messagebox.askyesno(
                "Очистка чертежа",
                "Убрать все шкафы с тестового чертежа?",
                parent=self.window):
            return
        self.placed = []
        self.selected_uid = None
        self._redraw()
        self._set_details("Тестовый чертёж пуст.")
        self._set_status("Тестовый чертёж очищен")

    def _draw_grid(self):
        for x in range(0, 1801, 20):
            color = GRID_MAJOR if x % 100 == 0 else GRID
            self.canvas.create_line(x, 0, x, 1400, fill=color,
                                    tags=("grid",))
        for y in range(0, 1401, 20):
            color = GRID_MAJOR if y % 100 == 0 else GRID
            self.canvas.create_line(0, y, 1800, y, fill=color,
                                    tags=("grid",))

    def _redraw(self):
        self.canvas.delete("all")
        self._draw_grid()
        max_x, max_y = 1800, 1400
        for item in self.placed:
            self._draw_cabinet(item)
            width, height = cabinet_size(item.get("cabinet", {}))
            max_x = max(max_x, float(item.get("x", 0)) + width + 80)
            max_y = max(max_y, float(item.get("y", 0)) + height + 80)
        self.canvas.configure(scrollregion=(0, 0, max_x, max_y))

    def _draw_cabinet(self, item):
        cabinet = item.get("cabinet", {})
        uid = text_or(item.get("uid"), "C?")
        x = float(item.get("x", 0))
        y = float(item.get("y", 0))
        width, height = cabinet_size(cabinet)
        tag = "umlcab:%s" % uid
        selected = uid == self.selected_uid
        outline = ACCENT if selected else "#37474f"
        outline_width = 3 if selected else 2

        self.canvas.create_rectangle(
            x, y, x + width, y + height,
            fill=CABINET_FILL, outline=outline, width=outline_width,
            tags=(tag, "umlcab"))
        self.canvas.create_rectangle(
            x + 1, y + 1, x + width - 1, y + 42,
            fill=ACCENT_LIGHT if selected else "#eceff1", outline="",
            tags=(tag, "umlcab"))
        self.canvas.create_text(
            x + 10, y + 10, anchor="nw",
            text=clip(text_or(cabinet.get("cypher"), "Без шифра"), 34),
            fill=ACCENT if selected else TEXT,
            font=("Arial", 10, "bold"), tags=(tag, "umlcab"))
        self.canvas.create_text(
            x + 10, y + 27, anchor="nw",
            text=clip(text_or(cabinet.get("name"), "Без наименования"), 43),
            fill=TEXT, font=("Arial", 8), tags=(tag, "umlcab"))

        kits = cabinet.get("Kit", []) or []
        shown = kits[:6]
        for index, kit in enumerate(shown):
            row_y = y + 50 + index * 52
            self.canvas.create_rectangle(
                x + 8, row_y, x + width - 8, row_y + 46,
                fill=KIT_FILL, outline="#bbdefb", tags=(tag, "umlcab"))
            self.canvas.create_text(
                x + 14, row_y + 5, anchor="nw",
                text="Комплект %s: %s" % (
                    text_or(kit.get("number"), index + 1),
                    clip(kit.get("description"), 32)),
                fill=TEXT, font=("Arial", 8, "bold"),
                tags=(tag, "umlcab"))
            self.canvas.create_text(
                x + 14, row_y + 23, anchor="nw",
                text="ИЭУ %d · функций %d · блоков %d · клемм %d" % (
                    ied_count(kit), function_count(kit),
                    terminal_block_count(kit), terminal_count(kit)),
                fill=MUTED, font=("Arial", 7),
                tags=(tag, "umlcab"))

        footer_y = y + height - 18
        if len(kits) > len(shown):
            self.canvas.create_text(
                x + 12, footer_y - 18, anchor="w",
                text="+ ещё %d комплектов" % (len(kits) - len(shown)),
                fill=MUTED, font=("Arial", 7), tags=(tag, "umlcab"))
        self.canvas.create_text(
            x + 12, footer_y, anchor="w",
            text="%s | %s" % (
                uid, clip(cabinet.get("standard"), 42)),
            fill=MUTED, font=("Arial", 7), tags=(tag, "umlcab"))

    def _cabinet_tag_from_event(self, event):
        found = self.canvas.find_withtag(tk.CURRENT)
        if not found:
            return None
        for tag in self.canvas.gettags(found[0]):
            if tag.startswith("umlcab:"):
                return tag
        return None

    def _on_canvas_press(self, event):
        tag = self._cabinet_tag_from_event(event)
        if not tag:
            if self.selected_uid:
                self.selected_uid = None
                self._redraw()
            return
        uid = tag.split(":", 1)[1]
        self.selected_uid = uid
        self._redraw()
        self._show_placed_details(uid)
        self._drag = {
            "uid": uid,
            "tag": tag,
            "last_x": self.canvas.canvasx(event.x),
            "last_y": self.canvas.canvasy(event.y),
        }

    def _on_canvas_drag(self, event):
        if not self._drag:
            return
        current_x = self.canvas.canvasx(event.x)
        current_y = self.canvas.canvasy(event.y)
        dx = current_x - self._drag["last_x"]
        dy = current_y - self._drag["last_y"]
        if dx == 0 and dy == 0:
            return
        self.canvas.move(self._drag["tag"], dx, dy)
        for item in self.placed:
            if item.get("uid") == self._drag["uid"]:
                item["x"] = float(item.get("x", 0)) + dx
                item["y"] = float(item.get("y", 0)) + dy
                break
        self._drag["last_x"] = current_x
        self._drag["last_y"] = current_y

    def _on_canvas_release(self, event):
        if not self._drag:
            return
        uid = self._drag["uid"]
        self._drag = None
        for item in self.placed:
            if item.get("uid") == uid:
                self._set_status("%s: x=%d, y=%d" % (
                    uid, round(float(item.get("x", 0))),
                    round(float(item.get("y", 0)))))
                break
        self._show_placed_details(uid)

    def _show_placed_details(self, uid):
        for item in self.placed:
            if item.get("uid") != uid:
                continue
            cabinet = item.get("cabinet", {})
            header = "Размещение %s: x=%d, y=%d\n\n" % (
                uid, round(float(item.get("x", 0))),
                round(float(item.get("y", 0))))
            self._set_details(header + summarize_cabinet(
                {"Cabinet": cabinet}))
            return
        self._set_details("Размещение не найдено.")

    # --------------------------------------------------------------- состояние
    def serialize_state(self):
        return {
            "kind": STATE_KIND,
            "version": STATE_VERSION,
            "source": os.path.relpath(
                self.catalog["path"], ROOT).replace(os.sep, "/"),
            "standard": self.catalog["standard"],
            "custom_cabinets": copy.deepcopy(self.custom_cabinets),
            "placed": copy.deepcopy(self.placed),
            "next_uid": self.next_uid,
        }

    def restore_state(self, state):
        if not isinstance(state, dict):
            raise ValueError("Файл состояния должен содержать JSON-объект")
        if state.get("kind") != STATE_KIND or state.get("version") != STATE_VERSION:
            raise ValueError("Это не файл тестового UML-чертежа версии 1")
        custom = state.get("custom_cabinets", [])
        placed = state.get("placed", [])
        if not isinstance(custom, list) or not isinstance(placed, list):
            raise ValueError("Повреждены списки сборок или размещений")
        for item in placed:
            if not isinstance(item, dict) or not isinstance(
                    item.get("cabinet"), dict):
                raise ValueError("Повреждена запись размещённого шкафа")
            item["x"] = float(item.get("x", 0))
            item["y"] = float(item.get("y", 0))
            item["uid"] = text_or(item.get("uid"), "C?")
        self.custom_cabinets = copy.deepcopy(custom)
        self.placed = copy.deepcopy(placed)
        self.next_uid = max(
            int(state.get("next_uid", 1) or 1),
            len(self.placed) + 1)
        self.selected_uid = None
        self._refresh_catalog()
        self._redraw()

    def save_state(self):
        initial_dir = os.path.join(ROOT, "EA")
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title="Сохранить тестовый UML-чертёж",
            defaultextension=".json",
            initialdir=initial_dir,
            initialfile=self.state_path or "uml_test_drawing.json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.serialize_state(), handle,
                      ensure_ascii=False, indent=2)
        self.state_path = os.path.basename(path)
        self._set_status("Тестовый чертёж сохранён: %s" % path)
        return path

    def load_state(self):
        initial_dir = os.path.join(ROOT, "EA")
        path = filedialog.askopenfilename(
            parent=self.window,
            title="Загрузить тестовый UML-чертёж",
            initialdir=initial_dir,
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                state = json.load(handle)
            self.restore_state(state)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            messagebox.showerror(
                "Загрузка чертежа",
                "Не удалось загрузить файл:\n%s" % error,
                parent=self.window)
            return None
        if state.get("standard") not in (None, self.catalog["standard"]):
            messagebox.showwarning(
                "Загрузка чертежа",
                "Standard загруженного файла отличается от текущей UML-выгрузки.",
                parent=self.window)
        self.state_path = os.path.basename(path)
        self._set_status("Тестовый чертёж загружен: %s" % path)
        return path

    # ------------------------------------------------------------------ utils
    def _set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")
        self.details.see("1.0")

    def _set_status(self, text):
        self.status.configure(text=text)


def _dialog_alive(dialog):
    try:
        return bool(dialog.window.winfo_exists())
    except (AttributeError, tk.TclError):
        return False


class AssemblyDialog:
    """Диалог выбора существующих UML-комплектов для нового шкафа."""

    def __init__(self, parent, kits, default_cypher, default_standard,
                 taken_cyphers, on_create, on_close):
        self.parent = parent
        self.kits = kits
        self.taken_cyphers = {str(value).lower() for value in taken_cyphers}
        self.on_create = on_create
        self.on_close = on_close

        self.window = tk.Toplevel(parent)
        self.window.title("Сборка шкафа из UML-комплектов")
        self.window.geometry("760x520")
        self.window.minsize(640, 420)
        self.window.configure(bg=BG)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.close())

        form = tk.LabelFrame(self.window, text="Карточка нового шкафа",
                             bg=BG, fg=TEXT, padx=8, pady=6)
        form.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))
        form.columnconfigure(1, weight=1)

        self.cypher_var = tk.StringVar(value=default_cypher)
        self.name_var = tk.StringVar(value="Сборный шкаф РЗА")
        self.standard_var = tk.StringVar(value=default_standard)
        self.description_var = tk.StringVar()

        rows = [
            ("Шифр", self.cypher_var),
            ("Наименование", self.name_var),
            ("Standard", self.standard_var),
            ("Описание", self.description_var),
        ]
        for row, (label, variable) in enumerate(rows):
            tk.Label(form, text=label, bg=BG, fg=TEXT, width=14,
                     anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            tk.Entry(form, textvariable=variable, bg=PANEL, fg=TEXT,
                     relief=tk.GROOVE, bd=1).grid(
                         row=row, column=1, sticky="ew", pady=2)

        kit_frame = tk.LabelFrame(
            self.window,
            text="Существующие комплекты (можно выбрать несколько)",
            bg=BG, fg=TEXT, padx=8, pady=6)
        kit_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                       padx=10, pady=6)
        self.kit_list = tk.Listbox(
            kit_frame, selectmode=tk.EXTENDED, exportselection=False,
            bg=PANEL, fg=TEXT, selectbackground=ACCENT_LIGHT,
            selectforeground=ACCENT, highlightthickness=1,
            highlightcolor=BORDER, activestyle="none",
            font=("Consolas", 9))
        scroll = tk.Scrollbar(kit_frame, orient=tk.VERTICAL,
                              command=self.kit_list.yview)
        self.kit_list.configure(yscrollcommand=scroll.set)
        self.kit_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for item in self.kits:
            self.kit_list.insert(tk.END, kit_label(item))
        if self.kits:
            self.kit_list.selection_set(0)
            self.kit_list.activate(0)

        note = tk.Label(
            self.window,
            text="Новый шкаф остаётся в этом тестовом окне; исходная "
                 "UML-выгрузка не изменяется.",
            bg=BG, fg=MUTED, anchor="w", justify="left")
        note.pack(side=tk.TOP, fill=tk.X, padx=12)

        actions = tk.Frame(self.window, bg=BG)
        actions.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        tk.Button(actions, text="Отмена", command=self.close,
                  width=12).pack(side=tk.RIGHT)
        tk.Button(actions, text="Собрать и вынести",
                  command=lambda: self._submit(True),
                  width=20).pack(side=tk.RIGHT, padx=(4, 4))
        tk.Button(actions, text="Собрать",
                  command=lambda: self._submit(False),
                  width=12).pack(side=tk.RIGHT)

        try:
            self.window.grab_set()
        except tk.TclError:
            pass
        self.cypher_var.set(default_cypher)
        self.window.after(50, self._focus_cypher)

    def _focus_cypher(self):
        try:
            self.window.focus_force()
        except tk.TclError:
            pass

    def bring_to_front(self):
        self.window.deiconify()
        self.window.lift()
        try:
            self.window.focus_force()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close(self)
        self.window.destroy()

    def _submit(self, place):
        cypher = text_or(self.cypher_var.get())
        if cypher.lower() in self.taken_cyphers:
            messagebox.showerror(
                "Сборка шкафа",
                "Шкаф с шифром %s уже есть в списке." % cypher,
                parent=self.window)
            return
        selection = self.kit_list.curselection()
        if not selection:
            messagebox.showwarning(
                "Сборка шкафа", "Выберите хотя бы один комплект.",
                parent=self.window)
            return
        selected = [self.kits[index] for index in selection]
        try:
            record = assemble_cabinet(
                cypher,
                self.name_var.get(),
                self.standard_var.get(),
                selected,
                self.description_var.get())
        except ValueError as error:
            messagebox.showerror("Сборка шкафа", str(error),
                                 parent=self.window)
            return
        if self.on_create and self.on_create(record, place) is False:
            return
        self.close()


def _standalone():
    root = tk.Tk()
    root.withdraw()
    show_test_window(root)
    root.mainloop()


if __name__ == "__main__":
    _standalone()
