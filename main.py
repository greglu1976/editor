import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import re
import sys
import subprocess
import uuid
import math
import copy
import os
from datetime import datetime
import library
import pdfunderlay
import pdfexport
import ssdexport
import cabs
import komplekts
import containers as ketlib
import docxreport

try:
    import pdf2json
except Exception:  # подписи в подложке необязательны
    pdf2json = None


# Префиксы обозначений по типу элемента — единый источник для добавления,
# копирования, вставки из файла и развёртывания состава КЭТ.
# Все обозначения — латиницей: шкафы «EL», контейнеры «EK».
PREFIX_BY_TYPE = {
    "breaker": "Q", "disconnector": "QS", "transformer": "T",
    "split_transformer": "T", "three_winding_transformer": "T",
    "autotransformer": "AT", "reactor": "R", "line": "W",
    "bus": "BB", "node": "N", "corner": "C", "grounding_switch": "QSG",
    "ground": "G", "voltage_transformer": "TV", "current_transformer": "TA",
    "opn": "FV", "coupling_capacitor": "CC", "line_trap": "LT",
    "connection_filter": "CF", "av_breaker": "QF", "fuse": "FU",
    "cabinet": "EL", "container": "EK", "bushing_monitor": "BSH",
    "capacitor_battery": "BSK",
}

# Названия типов элементов для отчётов и подсказок.
ELEMENT_TYPE_TITLES = {
    "breaker": "Выключатель",
    "disconnector": "Разъединитель",
    "bus": "Сборные шины",
    "transformer": "Трансформатор",
    "split_transformer": "Трансформатор с расщеплением обмоток",
    "three_winding_transformer": "Трёхобмоточный трансформатор",
    "autotransformer": "Автотрансформатор",
    "reactor": "Реактор",
    "line": "ЛЭП",
    "voltage_transformer": "Трансформатор напряжения",
    "current_transformer": "Трансформатор тока",
    "opn": "ОПН",
    "coupling_capacitor": "Конденсатор связи",
    "line_trap": "ВЧ-заградитель",
    "connection_filter": "Фильтр присоединения",
    "av_breaker": "Автоматический выключатель 0,4 кВ",
    "fuse": "Предохранитель",
    "grounding_switch": "Заземляющий разъединитель",
    "ground": "Заземление",
    "bushing_monitor": "КИВ — контроль изоляции вводов",
    "capacitor_battery": "БСК — батарея статических конденсаторов",
    "cabinet": "Шкаф РЗА",
    "container": "Контейнер КЭТ",
    "corner": "Уголок",
    "node": "Узел",
}

# Палитра иконок: подпись (всплывающая подсказка) и тип элемента.
PALETTE_ITEMS = [
    ("Выключатель", "breaker"),
    ("Разъединитель", "disconnector"),
    ("Шина", "bus"),
    ("Трансформатор", "transformer"),
    ("Трансформатор с расщеплением", "split_transformer"),
    ("Трёхобмоточный трансформатор", "three_winding_transformer"),
    ("Автотрансформатор", "autotransformer"),
    ("Реактор", "reactor"),
    ("ЛЭП", "line"),
    ("ТН — трансформатор напряжения", "voltage_transformer"),
    ("ТТ — трансформатор тока", "current_transformer"),
    ("ОПН — ограничитель перенапряжений", "opn"),
    ("КС — конденсатор связи", "coupling_capacitor"),
    ("ВЧЗ — высокочастотный заградитель", "line_trap"),
    ("ФП — фильтр присоединения", "connection_filter"),
    ("Автоматический выключатель 0,4 кВ", "av_breaker"),
    ("Предохранитель", "fuse"),
    ("Уголок", "corner"),
    ("Заземляющий разъединитель", "grounding_switch"),
    ("Заземление", "ground"),
    ("Узел", "node"),
    ("КИВ — контроль изоляции вводов", "bushing_monitor"),
    ("БСК — батарея статических конденсаторов", "capacitor_battery"),
]


class ToolTip:
    """Всплывающая подсказка для кнопок-иконок."""

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        self._after_id = None
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() + 4
        # Владелец — корневое окно: вложенный Toplevel внутри canvas не отображается
        self.tip = tk.Toplevel(self.widget.winfo_toplevel())
        self.tip.wm_overrideredirect(True)
        self.tip.wm_attributes("-topmost", True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#ffffe0", fg="black",
                 relief="solid", bd=1, padx=6, pady=2,
                 font=("Arial", 9)).pack()

    def _hide(self, event=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None


class UndoManager:
    """Менеджер истории с поддержкой Undo и Redo"""
    def __init__(self):
        self.history = []      # Стек для отмены
        self.redo_stack = []   # Стек для повтора
        self.max_history = 50

    def save_state(self, elements, connections, selected_elements,
                   protection_links=None, analog_links=None):
        """Сохраняет состояние и очищает стек redo (т.к. создана новая ветка)"""
        state = {
            "elements": copy.deepcopy(elements),
            "connections": copy.deepcopy(connections),
            "selected_elements": list(selected_elements),
            "protection": copy.deepcopy(protection_links or []),
            "analog": copy.deepcopy(analog_links or []),
        }
        self.push_state(state)

    def push_state(self, state):
        """Кладёт в историю уже снятую копию состояния (для отложенных операций)."""
        if state is None:
            return
        self.history.append(state)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        # Очищаем redo, так как мы сделали новое действие
        self.redo_stack.clear()

    def undo(self, current_state):
        if not self.history:
            return None
        self.redo_stack.append(current_state)
        return self.history.pop()

    def redo(self, current_state):
        if not self.redo_stack:
            return None
        self.history.append(current_state)
        return self.redo_stack.pop()


# ================= ИКОНКИ ЛЕНТЫ =================
# Рисуются на canvas 32x32 — без внешних файлов и зависимостей.

def _ri_select(c):
    c.create_polygon(12, 5, 12, 26, 16, 22, 19, 28, 22, 26.5, 19, 20.5, 24, 19.5,
                     fill="black")


def _ri_undo(c):
    c.create_line(24, 16, 12, 16, width=2, fill="black")
    c.create_polygon(6, 16, 14, 10, 14, 22, fill="black")


def _ri_redo(c):
    c.create_line(8, 16, 20, 16, width=2, fill="black")
    c.create_polygon(26, 16, 18, 10, 18, 22, fill="black")


def _ri_copy(c):
    c.create_rectangle(6, 10, 19, 25, outline="black", width=2)
    c.create_rectangle(12, 6, 25, 21, outline="black", width=2)


def _ri_paste(c):
    c.create_rectangle(7, 8, 25, 27, outline="black", width=2)
    c.create_rectangle(12, 4, 20, 9, outline="black", width=2, fill="white")
    c.create_line(11, 16, 21, 16, width=1)


def _ri_save(c):
    c.create_rectangle(6, 5, 26, 27, outline="black", width=2)
    c.create_rectangle(10, 5, 22, 13, outline="black", width=1)
    c.create_rectangle(9, 18, 23, 27, outline="black", width=1)


def _ri_load(c):
    c.create_polygon(5, 11, 12, 11, 15, 8, 27, 8, 27, 25, 5, 25,
                     outline="black", fill="white", width=2)


def _ri_insert(c):
    c.create_rectangle(5, 5, 17, 27, outline="black", width=1)
    c.create_line(20, 16, 28, 16, width=2, fill="black")
    c.create_line(24, 12, 28, 16, width=2, fill="black")
    c.create_line(24, 20, 28, 16, width=2, fill="black")


def _ri_clear(c):
    c.create_line(6, 9, 26, 9, width=2)
    c.create_line(12, 6, 20, 6, width=2)
    c.create_polygon(8, 10, 24, 10, 22, 27, 10, 27, outline="black", fill="white", width=2)
    c.create_line(13, 14, 13, 24, width=1)
    c.create_line(19, 14, 19, 24, width=1)


def _ri_minus(c):
    c.create_oval(5, 5, 27, 27, outline="black", width=2)
    c.create_line(11, 16, 21, 16, width=2)


def _ri_plus(c):
    c.create_oval(5, 5, 27, 27, outline="black", width=2)
    c.create_line(11, 16, 21, 16, width=2)
    c.create_line(16, 11, 16, 21, width=2)


def _ri_fit(c):
    c.create_rectangle(11, 11, 21, 21, outline="black", width=2)
    for x1, y1, x2, y2 in ((5, 5, 10, 10), (27, 5, 22, 10),
                           (5, 27, 10, 22), (27, 27, 22, 22)):
        c.create_line(x1, y1, x2, y2, width=2, arrow=tk.LAST)


def _ri_pdf(c):
    c.create_polygon(8, 4, 19, 4, 24, 9, 24, 28, 8, 28,
                     outline="black", fill="white", width=2)
    c.create_line(19, 4, 19, 9, 24, 9, width=1)
    c.create_text(16, 19, text="PDF", font=("Arial", 6, "bold"))


def _ri_ssd(c):
    c.create_polygon(8, 4, 19, 4, 24, 9, 24, 28, 8, 28,
                     outline="black", fill="white", width=2)
    c.create_line(19, 4, 19, 9, 24, 9, width=1)
    c.create_text(16, 19, text="SSD", font=("Arial", 6, "bold"))


def _ri_shield(c):
    c.create_polygon(16, 4, 27, 9, 27, 17, 16, 29, 5, 17, 5, 9,
                     outline="black", fill="white", width=2)
    c.create_line(16, 11, 16, 21, width=2)
    c.create_line(11, 16, 21, 16, width=2)


def _ri_report(c):
    """Отчёт: страница с таблицей."""
    c.create_rectangle(8, 4, 25, 28, outline="black", width=2)
    c.create_line(11, 9, 22, 9, width=1, fill="#666666")
    c.create_rectangle(11, 13, 22, 26, outline="black", width=1)
    for y in (16, 19.5, 23):
        c.create_line(11, y, 22, y, width=1, fill="#666666")
    c.create_line(15, 13, 15, 26, width=1, fill="#666666")


def _ri_analog(c):
    """Аналоговые цепи: стрелка с синусоидой, фиолетовая."""
    c.create_line(5, 16, 27, 16, width=2, fill="#7b1fa2", arrow=tk.LAST)
    c.create_text(16, 8, text="~", font=("Arial", 11, "bold"), fill="#7b1fa2")


def _ri_protlink(c):
    c.create_line(6, 26, 24, 8, width=2, arrow=tk.LAST)
    c.create_oval(22, 4, 28, 10, outline="black", width=1)


def _ri_container(c):
    c.create_rectangle(3, 9, 29, 25, outline="black", width=2)
    for x in (9, 15, 21):
        c.create_line(x, 10, x, 24, width=1, fill="#666666")
    c.create_line(3, 13, 29, 13, width=1)
    c.create_line(4, 9, 4, 25, width=1, fill="#666666")


def _ri_komplekt(c):
    """Комплект: рамка с двумя строками и выводом порта."""
    c.create_rectangle(4, 6, 25, 26, outline="black", width=2)
    c.create_line(4, 14, 25, 14, width=1)
    c.create_line(4, 20, 25, 20, width=1)
    c.create_line(25, 17, 30, 17, width=2, fill="#1f4e79")
    c.create_oval(28, 14, 32, 20, fill="#1f4e79", outline="white")
    for y in (10, 17, 23):
        c.create_line(8, y, 12, y, width=1, fill="#666666")


def _ri_ket_link(c):
    """Связь КЭТ: точка слота (●) — линия — точка шкафа (□)."""
    c.create_line(9, 16, 23, 16, width=2)
    c.create_oval(3, 11, 11, 21, outline="#a0522d", width=2, fill="white")
    c.create_rectangle(22, 10, 30, 22, outline="#a0522d", width=2, fill="white")


def _ri_eye(c):
    c.create_oval(4, 11, 28, 21, outline="black", width=2)
    c.create_oval(13, 13, 19, 19, fill="black", outline="black")


def _ri_grid(c):
    for x in (8, 16, 24):
        c.create_line(x, 6, x, 26, width=1, fill="#666666")
    for y in (8, 16, 24):
        c.create_line(6, y, 26, y, width=1, fill="#666666")
    c.create_rectangle(6, 6, 26, 26, outline="black", width=1)


def _ri_nodes(c):
    c.create_line(9, 23, 16, 10, width=1, fill="#666666")
    c.create_line(16, 10, 23, 23, width=1, fill="#666666")
    c.create_line(9, 23, 23, 23, width=1, fill="#666666")
    for x, y in ((16, 10), (9, 23), (23, 23)):
        c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="white", outline="black", width=2)


def _format_option(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class SsdOptionsDialog(tk.Toplevel):
    """Параметры SSD: подстанция, РУ, отсек, напряжение и частота."""

    FIELDS = (
        ("substation", "Подстанция", 34),
        ("voltage_level", "РУ (VoltageLevel)", 34),
        ("bay", "Отсек (Bay)", 34),
        ("voltage_kv", "Напряжение, кВ", 10),
        ("frequency_hz", "Частота, Гц", 10),
    )

    def __init__(self, parent, defaults):
        super().__init__(parent)
        self.title("Экспорт в SSD — МЭК 61850-6")
        self.transient(parent)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.result = None
        self.vars = {}

        form = tk.Frame(self, padx=12, pady=10)
        form.pack(fill=tk.BOTH, expand=True)

        for row, (key, label, width) in enumerate(self.FIELDS):
            tk.Label(form, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=3)
            variable = tk.StringVar(value=_format_option(defaults.get(key)))
            entry = tk.Entry(form, textvariable=variable, width=width)
            entry.grid(row=row, column=1, sticky="we", padx=(10, 0), pady=3)
            self.vars[key] = variable
            if row == 0:
                self._first_entry = entry

        self._hint = tk.Label(
            form, text="Напряжение можно не заполнять — тогда блок Voltage не пишется.",
            fg="#808080", font=("Arial", 8), anchor="w")
        self._hint.grid(row=len(self.FIELDS), column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._error = tk.Label(form, text="", fg="#b00020", font=("Arial", 8), anchor="w")
        self._error.grid(row=len(self.FIELDS) + 1, column=0, columnspan=2, sticky="w")

        buttons = tk.Frame(self)
        buttons.pack(fill=tk.X, padx=12, pady=(0, 10))
        tk.Button(buttons, text="Отмена", width=10, command=self._cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Экспорт", width=12,
                  command=self._accept).pack(side=tk.RIGHT, padx=(0, 6))

        self.bind("<Return>", lambda event: self._accept())
        self.bind("<KP_Enter>", lambda event: self._accept())
        self.bind("<Escape>", lambda event: self._cancel())
        self._center(parent)

    def _center(self, parent):
        self.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 3)
        self.geometry("+{}+{}".format(x, y))

    def show(self):
        # update() нужен, чтобы окно успело отобразиться: grab_set работает
        # только для видимого окна (иначе TclError — просто не ставим захват).
        self.update()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.lift()
        self._first_entry.focus_set()
        self.wait_window(self)
        return self.result

    def _fail(self, message):
        self._error.config(text=message)

    def _cancel(self):
        self.result = None
        self.destroy()

    def _accept(self):
        values = {key: variable.get().strip() for key, variable in self.vars.items()}
        if not values["substation"]:
            self._fail("Укажите имя подстанции.")
            return
        if not values["voltage_level"]:
            self._fail("Укажите имя РУ (VoltageLevel).")
            return
        if not values["bay"]:
            self._fail("Укажите имя отсека (Bay).")
            return

        voltage = None
        if values["voltage_kv"]:
            try:
                voltage = float(values["voltage_kv"].replace(",", "."))
            except ValueError:
                self._fail("Напряжение должно быть числом, например 110.")
                return
            if voltage <= 0:
                self._fail("Напряжение должно быть больше нуля.")
                return

        try:
            frequency = float(values["frequency_hz"].replace(",", ".")) if values["frequency_hz"] else 50.0
        except ValueError:
            self._fail("Частота должна быть числом, например 50.")
            return
        if frequency <= 0:
            self._fail("Частота должна быть больше нуля.")
            return

        self.result = {
            "substation": values["substation"],
            "voltage_level": values["voltage_level"],
            "bay": values["bay"],
            "voltage_kv": voltage,
            "frequency_hz": frequency,
        }
        self.destroy()


class CircuitEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Редактор электрических схем v16")
        
        self.elements = {}    
        self.connections = [] 
        
        # --- ВЫДЕЛЕНИЕ И БУФЕР ОБМЕНА ---
        self.current_tool = "select"
        self.selected_elements = []  
        self.link_start = None  
        # Панорамирование средней кнопкой мыши
        self._pan_active = False
        self._pan_last = (0, 0)
        
        # Рамка выделения
        self.selection_start = None       
        self.selection_start_screen = None 
        self.selection_rect_id = None     
        
        # Перетаскивание группы
        self.dragging_group = False
        self.drag_offsets = {}
        # Состояние до начала перетаскивания/ресайза: пишем в историю,
        # только если элемент действительно сдвинулся
        self._pre_change_state = None
        self._drag_changed = False
        self._resize_changed = False

        # Перетаскивание подписи элемента
        self._dragging_label = None
        self._label_drag_start = (0, 0)
        self._label_drag_offset = [0.0, 0.0]
        self._label_drag_changed = False
        
        # Буфер обмена
        self.clipboard = None          
        self.clipboard_connections = []
        
        # Изменение размера шины
        self.resizing_element = None
        self.resize_handle = None
        
        # Менеджер отмены/повтора
        self.undo_manager = UndoManager()

        self.grid_size = 10
        self.grid_color = "#e0e0e0"
        self.snap_to_grid = True
        
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        
        self.show_all_nodes = True

        # Подложка из PDF (векторная графика под схемой)
        self.underlay = None
        self.underlay_scale = 2.0
        self.show_underlay = True
        self._underlay_needs_fit = False

        # Защита: шкафы РЗА, комплекты, защитные узлы оборудования и связи комплект→узел
        self.protection_links = []
        self.analog_links = []          # [{"from": "id#комплект", "to": ref}]
        self.show_analog = True         # линии аналоговых цепей и порты «AI»
        self._analog_start = None       # ("komplekt", id, index) | ("equipment", id, None)
        self.show_protection = True     # стрелки комплект→узел и ромбы-узлы
        self.show_cabinets = True       # сами шкафы
        self.show_containers = True     # контейнеры КЭТ (под шкафами)
        self._protection_start = None    # ("komplekt", cabinet_id, port) | ("element", id)
        self._bind_start = None          # ("slot", container_id, index) | ("cabinet", id, None)
        self._analog_start = None        # начало связи аналоговых цепей
        self._pending_cabinet = None

        self.setup_ui()
        self.draw_grid()
        self.bind_events()

    def setup_ui(self):
        self._build_ribbon()

        # === ЛЕВАЯ ПАЛИТРА (прокручиваемая: элементов стало больше) ===
        palette_wrap = tk.Frame(self.root, width=200, bg="#f0f0f0")
        palette_wrap.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        palette_wrap.pack_propagate(False)

        self.palette_canvas = tk.Canvas(palette_wrap, width=188, bg="#f0f0f0",
                                        highlightthickness=0, takefocus=False)
        palette_scroll = tk.Scrollbar(palette_wrap, orient="vertical",
                                      command=self.palette_canvas.yview)
        self.palette_canvas.configure(yscrollcommand=palette_scroll.set)
        palette_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        palette = tk.Frame(self.palette_canvas, bg="#f0f0f0")
        self.palette_canvas.create_window((0, 0), window=palette, anchor="nw", width=180)
        palette.bind("<Configure>",
                     lambda e: self.palette_canvas.configure(scrollregion=self.palette_canvas.bbox("all")))
        self.palette_canvas.bind("<MouseWheel>", self._scroll_palette)

        tk.Label(palette, text="Элементы схемы", font=("Arial", 12, "bold"), bg="#f0f0f0").pack(pady=5)

        # Иконки элементов: 3 колонки, подсказка при наведении
        self._tool_icons = {}
        icons_frame = tk.Frame(palette, bg="#f0f0f0")
        icons_frame.pack(fill=tk.X, padx=2, pady=2)
        for index, (label, etype) in enumerate(PALETTE_ITEMS):
            icon = self._make_tool_icon(icons_frame, etype, label)
            icon.grid(row=index // 3, column=index % 3, padx=2, pady=2)
            self._tool_icons[etype] = icon

        tk.Frame(palette, height=2, bg="gray").pack(fill=tk.X, pady=6)
        tk.Button(palette, text="Связать элементы", width=18,
                  command=lambda: self.set_tool("connect")).pack(pady=2)
        tk.Button(palette, text="Удалить выбранное", width=18,
                  command=lambda: self.set_tool("delete")).pack(pady=2)
        tk.Label(palette, text="Подсказка: наведите на иконку\nСредняя кнопка мыши — панорама",
                 bg="#f0f0f0", fg="#8a8a8a", font=("Arial", 7), justify="left").pack(anchor="w", padx=4, pady=(10, 0))

        self.canvas = tk.Canvas(self.root, bg="white", width=800, height=700,
                                takefocus=True, highlightthickness=0)
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._bind_palette_wheel(palette)

    # ================= ЛЕНТА (RIBBON) =================
    def _build_ribbon(self):
        ribbon = tk.Frame(self.root, bg="#f3f3f3")
        ribbon.pack(side=tk.TOP, fill=tk.X)

        tabbar = tk.Frame(ribbon, bg="#e4e4e4")
        tabbar.pack(side=tk.TOP, fill=tk.X)

        content = tk.Frame(ribbon, bg="#f3f3f3")
        content.pack(side=tk.TOP, fill=tk.X)

        self._ribbon_pages = {}
        self._ribbon_tab_buttons = {}
        for name, builder in (("Главная", self._build_ribbon_home),
                              ("Вид", self._build_ribbon_view),
                              ("Шкафы", self._build_ribbon_cabinets),
                              ("Комплекты", self._build_ribbon_komplekts),
                              ("Контейнеры", self._build_ribbon_containers),
                              ("Отчёты", self._build_ribbon_reports)):
            self._ribbon_pages[name] = builder(content)
            button = tk.Button(tabbar, text=name, relief=tk.FLAT, bd=0,
                               padx=16, pady=3, font=("Arial", 9),
                               bg="#e4e4e4", activebackground="#f3f3f3",
                               command=lambda n=name: self._show_ribbon_tab(n))
            button.pack(side=tk.LEFT, padx=(2, 0))
            self._ribbon_tab_buttons[name] = button

        self._show_ribbon_tab("Главная")

    def _show_ribbon_tab(self, name):
        for page in self._ribbon_pages.values():
            page.pack_forget()
        self._ribbon_pages[name].pack(side=tk.TOP, fill=tk.X)
        for tab_name, button in self._ribbon_tab_buttons.items():
            active = (tab_name == name)
            button.config(bg="#f3f3f3" if active else "#e4e4e4",
                          font=("Arial", 9, "bold" if active else "normal"))

    def _ribbon_group(self, parent, title, build_row):
        group = tk.Frame(parent, bg="#f3f3f3")
        group.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        row = tk.Frame(group, bg="#f3f3f3")
        row.pack(side=tk.TOP)
        build_row(row)
        tk.Label(group, text=title, bg="#f3f3f3", fg="#808080",
                 font=("Arial", 7)).pack(side=tk.BOTTOM, pady=(0, 2))
        tk.Frame(parent, width=1, bg="#d8d8d8").pack(side=tk.LEFT, fill=tk.Y, pady=6)

    def _ribbon_button(self, parent, text, command, icon, width=64):
        """Крупная кнопка ленты: иконка сверху, подпись снизу."""
        cell = tk.Frame(parent, bg="#f3f3f3", cursor="hand2")
        canvas = tk.Canvas(cell, width=32, height=32, bg="#f3f3f3",
                           highlightthickness=0, takefocus=False)
        canvas.pack(pady=(4, 0), padx=6)
        try:
            icon(canvas)
        except Exception:
            pass
        label = tk.Label(cell, text=text, bg="#f3f3f3", font=("Arial", 8),
                         justify="center")
        label.pack(padx=3, pady=(1, 4))
        cell._label = label
        cell._base_text = text

        def on_click(event=None):
            command()

        def on_enter(event=None):
            for widget in (cell, canvas, label):
                widget.config(bg="#dce9f7")

        def on_leave(event=None):
            for widget in (cell, canvas, label):
                widget.config(bg="#f3f3f3")

        for widget in (cell, canvas, label):
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
        return cell

    def _register_tool(self, cell, tool):
        """Запоминает кнопку инструмента, чтобы подсвечивать активный режим."""
        if not hasattr(self, "_ribbon_tool_cells"):
            self._ribbon_tool_cells = {}
        self._ribbon_tool_cells[tool] = cell
        return cell

    def _ribbon_toggle(self, parent, text, variable, command, icon, width=64):
        def toggle():
            variable.set(not variable.get())
            command()
            self._refresh_ribbon_toggles()

        cell = self._ribbon_button(parent, text, toggle, icon, width)
        cell._variable = variable
        self._ribbon_toggle_cells.append(cell)
        return cell

    def _refresh_ribbon_toggles(self):
        for cell in getattr(self, "_ribbon_toggle_cells", []):
            mark = "☑ " if cell._variable.get() else "☐ "
            cell._label.config(text=mark + cell._base_text)

    def _build_ribbon_home(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")
        self._ribbon_group(page, "Инструменты", lambda row: self._register_tool(
            self._ribbon_button(row, "Выбрать/Двигать",
                                lambda: self.set_tool("select"),
                                _ri_select, 76), "select").pack(side=tk.LEFT))
        self._ribbon_group(page, "История", lambda row: [
            self._ribbon_button(row, "Назад", self.undo_last_action, _ri_undo, 52).pack(side=tk.LEFT),
            self._ribbon_button(row, "Вперёд", self.redo_last_action, _ri_redo, 52).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Буфер обмена", lambda row: [
            self._ribbon_button(row, "Копировать", self.copy_selection, _ri_copy, 64).pack(side=tk.LEFT),
            self._ribbon_button(row, "Вставить", self.paste_selection, _ri_paste, 58).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Файл", lambda row: [
            self._ribbon_button(row, "Сохранить", self.save_json, _ri_save, 62).pack(side=tk.LEFT),
            self._ribbon_button(row, "Загрузить", self.load_json, _ri_load, 62).pack(side=tk.LEFT),
            self._ribbon_button(row, "Из файла", self.insert_from_json, _ri_insert, 60).pack(side=tk.LEFT),
            self._ribbon_button(row, "Очистить", self.clear_all, _ri_clear, 60).pack(side=tk.LEFT),
            self._ribbon_button(row, "В PDF", self.export_pdf, _ri_pdf, 56).pack(side=tk.LEFT),
            self._ribbon_button(row, "В SSD", self.export_ssd, _ri_ssd, 56).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Защита", lambda row: [
            self._ribbon_button(row, "Шкаф…", self.add_cabinet, _ri_shield, 58).pack(side=tk.LEFT),
            self._register_tool(self._ribbon_button(
                row, "Связь РЗА", lambda: self.set_tool("protection"),
                _ri_protlink, 66), "protection").pack(side=tk.LEFT),
            self._register_tool(self._ribbon_button(
                row, "Аналог. цепи", lambda: self.set_tool("analog"),
                _ri_analog, 74), "analog").pack(side=tk.LEFT),
        ])
        return page

    def _build_ribbon_view(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")
        self._ribbon_toggle_cells = []

        def build_grid(row):
            self.snap_var = tk.BooleanVar(value=True)
            self.show_nodes_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Привязка к сетке", self.snap_var,
                                self.toggle_snap, _ri_grid, 70).pack(side=tk.LEFT)
            self._ribbon_toggle(row, "Показать узлы", self.show_nodes_var,
                                self.toggle_show_nodes, _ri_nodes, 66).pack(side=tk.LEFT)

            cell = tk.Frame(row, bg="#f3f3f3")
            cell.pack(side=tk.LEFT, padx=(8, 4))
            tk.Label(cell, text="Шаг сетки", bg="#f3f3f3", font=("Arial", 8)).pack(pady=(6, 0))
            self.grid_spin = tk.Spinbox(cell, from_=5, to=100, increment=5,
                                        command=self.change_grid_size, width=5)
            self.grid_spin.delete(0, "end")
            self.grid_spin.insert(0, str(self.grid_size))
            self.grid_spin.pack(pady=2)
            self.grid_spin.bind("<Return>", lambda e: self.change_grid_size())
            self.grid_spin.bind("<KP_Enter>", lambda e: self.change_grid_size())
            self.grid_spin.bind("<FocusOut>", lambda e: self.change_grid_size())

        self._ribbon_group(page, "Сетка", build_grid)

        def build_protection(row):
            self.show_cabinets_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Шкафы", self.show_cabinets_var,
                                self.toggle_cabinets, _ri_shield, 56).pack(side=tk.LEFT)
            self.show_containers_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Контейнеры", self.show_containers_var,
                                self.toggle_containers, _ri_container, 74).pack(side=tk.LEFT)
            self.show_protection_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Связи РЗА", self.show_protection_var,
                                self.toggle_protection, _ri_protlink, 72).pack(side=tk.LEFT)
            self.show_analog_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Аналог. цепи", self.show_analog_var,
                                self.toggle_analog, _ri_analog, 74).pack(side=tk.LEFT)

        self._ribbon_group(page, "Защита", build_protection)

        def build_scale(row):
            self._ribbon_button(row, "Уменьшить", lambda: self._zoom_step(0.8),
                                _ri_minus, 58).pack(side=tk.LEFT)
            self._ribbon_button(row, "Увеличить", lambda: self._zoom_step(1.25),
                                _ri_plus, 58).pack(side=tk.LEFT)
            self._ribbon_button(row, "Сбросить", self.reset_view, _ri_fit, 58).pack(side=tk.LEFT)

            cell = tk.Frame(row, bg="#f3f3f3")
            cell.pack(side=tk.LEFT, padx=(8, 6))
            self.zoom_label = tk.Label(cell, text=f"{int(self.zoom * 100)}%",
                                       bg="#f3f3f3", fg="#1f4e79",
                                       font=("Arial", 11, "bold"), width=5)
            self.zoom_label.pack(pady=(8, 0))
            tk.Label(cell, text="масштаб", bg="#f3f3f3", fg="#808080",
                     font=("Arial", 7)).pack()

        self._ribbon_group(page, "Масштаб", build_scale)

        def build_underlay(row):
            self._ribbon_button(row, "PDF…", self.load_underlay, _ri_pdf, 56).pack(side=tk.LEFT)
            self.underlay_visible_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Показать", self.underlay_visible_var,
                                self.toggle_underlay, _ri_eye, 62).pack(side=tk.LEFT)
            self._ribbon_button(row, "Убрать", self.clear_underlay, _ri_clear, 58).pack(side=tk.LEFT)

            cell = tk.Frame(row, bg="#f3f3f3")
            cell.pack(side=tk.LEFT, padx=(8, 4))
            tk.Label(cell, text="масштаб", bg="#f3f3f3", font=("Arial", 8)).pack(pady=(6, 0))
            self.underlay_spin = tk.Spinbox(cell, from_=0.5, to=5.0, increment=0.5, width=4,
                                            command=self.change_underlay_scale)
            self.underlay_spin.delete(0, "end")
            self.underlay_spin.insert(0, str(self.underlay_scale))
            self.underlay_spin.pack(pady=2)
            self.underlay_spin.bind("<Return>", lambda e: self.change_underlay_scale())
            self.underlay_spin.bind("<KP_Enter>", lambda e: self.change_underlay_scale())
            self.underlay_spin.bind("<FocusOut>", lambda e: self.change_underlay_scale())

        self._ribbon_group(page, "Подложка", build_underlay)
        self._refresh_ribbon_toggles()
        return page

    # ---------- вкладка «Шкафы»: управление каталогом ----------
    def _build_ribbon_cabinets(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")
        self._ribbon_group(page, "Каталог", lambda row: [
            self._ribbon_button(row, "Каталог…", self.open_cabinet_catalog,
                                _ri_shield, 66).pack(side=tk.LEFT),
            self._ribbon_button(row, "Новый шкаф", self.create_cabinet_type,
                                _ri_plus, 76).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Данные", lambda row: [
            self._ribbon_button(row, "Сбросить", self.reset_cabinet_catalog,
                                _ri_clear, 64).pack(side=tk.LEFT),
        ])
        tk.Label(page, text="Создание, изменение и удаление шкафов.\n"
                            "Пользовательские шкафы и правки хранятся\n"
                            "в cabinets.json рядом с cabs.py",
                 bg="#f3f3f3", fg="#808080", font=("Arial", 7),
                 justify="left").pack(side=tk.LEFT, padx=12)
        return page

    def open_cabinet_catalog(self):
        """Окно каталога: список шкафов и кнопки управления."""
        window = tk.Toplevel(self.root)
        window.title("Каталог шкафов РЗА")
        window.transient(self.root)

        header = tk.Label(window, text="", anchor="w", fg="#555555")
        header.pack(fill=tk.X, padx=10, pady=(8, 4))

        filters = tk.Frame(window)
        filters.pack(fill=tk.X, padx=10, pady=(0, 4))
        tk.Label(filters, text="Группа:").pack(side=tk.LEFT)
        all_cabinets = cabs.all_cabinets()
        groups = sorted({cabinet.get("group") or "Прочие"
                         for cabinet in all_cabinets})
        group_variable = tk.StringVar(value="Все группы")
        tk.OptionMenu(filters, group_variable, "Все группы",
                      *groups).pack(side=tk.LEFT, padx=(6, 12))
        tk.Label(filters, text="Поиск:").pack(side=tk.LEFT)
        search_variable = tk.StringVar()
        tk.Entry(filters, textvariable=search_variable, width=24).pack(
            side=tk.LEFT, padx=(6, 0))

        frame = tk.Frame(window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=86, height=18, activestyle="dotbox",
                             exportselection=False)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        state = {"cabinets": [], "visible": []}

        def cabinet_label(cabinet):
            group = cabinet.get("group")
            prefix = f"[{group}] " if group else ""
            code = cabinet.get("code")
            name = cabinet.get("name", "Шкаф")
            mark = "" if cabs.is_builtin(cabinet.get("key")) else " •"
            return f"{prefix}{code} — {name}{mark}" if code else prefix + name + mark

        def refresh():
            state["cabinets"] = cabs.all_cabinets()
            group = group_variable.get()
            needle = search_variable.get().strip().lower()
            visible = []
            for cabinet in state["cabinets"]:
                if group != "Все группы" and (cabinet.get("group") or "Прочие") != group:
                    continue
                if needle:
                    haystack = " ".join(str(cabinet.get(field, "")) for field in
                                        ("code", "name", "title", "description",
                                         "group", "source")).lower()
                    if needle not in haystack:
                        continue
                visible.append(cabinet)
            state["visible"] = visible
            listbox.delete(0, "end")
            for cabinet in visible:
                listbox.insert("end", cabinet_label(cabinet))
            header.config(text=f"Шкафов в каталоге: {len(state['cabinets'])} "
                               f"(показано {len(visible)}; встроенных "
                               f"{len(cabs.CABINETS)}, точка • — пользовательский)")

        def selected():
            selection = listbox.curselection()
            if not selection:
                return None
            return state["visible"][selection[0]]

        def on_new():
            self.edit_cabinet_type(None)
            refresh()

        def on_edit(event=None):
            cabinet = selected()
            if cabinet is None:
                return
            self.edit_cabinet_type(cabinet, cabinet.get("key"))
            refresh()

        def on_duplicate():
            cabinet = selected()
            if cabinet is None:
                return
            new_key = cabs.duplicate_cabinet(cabinet.get("key"))
            refresh()
            if new_key is None:
                return
            for index, entry in enumerate(state["visible"]):
                if entry.get("key") == new_key:
                    listbox.selection_clear(0, "end")
                    listbox.selection_set(index)
                    listbox.activate(index)
                    listbox.see(index)
                    break
            title = (cabs.find_cabinet(new_key) or {}).get("name", "копия")
            header.config(text=f"Создана копия: {title}. "
                               f"Шкафов в каталоге: {len(state['cabinets'])}")

        def on_delete():
            cabinet = selected()
            if cabinet is None:
                return
            title = cabinet.get("code") or cabinet.get("name")
            if not messagebox.askyesno("Каталог шкафов",
                                       f"Удалить шкаф «{title}» из каталога?\n"
                                       "Размещённые на схеме шкафы останутся."):
                return
            cabs.delete_cabinet(cabinet.get("key"))
            refresh()

        buttons = tk.Frame(window)
        buttons.pack(fill=tk.X, padx=10, pady=8)
        tk.Button(buttons, text="Закрыть", width=10,
                  command=window.destroy).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Удалить", width=10,
                  command=on_delete).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Дублировать", width=12,
                  command=on_duplicate).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Изменить", width=10,
                  command=on_edit).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Новый", width=10,
                  command=on_new).pack(side=tk.RIGHT, padx=(0, 6))

        listbox.bind("<Double-Button-1>", on_edit)
        window.bind("<Escape>", lambda event: window.destroy())
        group_variable.trace_add("write", lambda *args: refresh())
        search_variable.trace_add("write", lambda *args: refresh())
        refresh()

        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 4)
        window.geometry(f"+{x}+{y}")
        try:
            window.grab_set()
        except tk.TclError:
            pass

    def create_cabinet_type(self):
        """Создание нового шкафа в каталоге."""
        self.edit_cabinet_type(None)

    def reset_cabinet_catalog(self):
        if not messagebox.askyesno(
                "Каталог шкафов",
                "Удалить все пользовательские шкафы и правки?\n"
                "Встроенный каталог из cabs.py останется."):
            return
        cabs.reset_user_catalog()
        messagebox.showinfo("Каталог шкафов",
                            f"Каталог сброшен к встроенному: {len(cabs.all_cabinets())} шкафов.")

    # ================= ВКЛАДКА «КОМПЛЕКТЫ»: КАТАЛОГ И РЕДАКТОР =================
    def _build_ribbon_komplekts(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")
        self._ribbon_group(page, "Каталог", lambda row: [
            self._ribbon_button(row, "Каталог…", self.open_komplekt_catalog,
                                _ri_komplekt, 66).pack(side=tk.LEFT),
            self._ribbon_button(row, "Новый комплект", self.create_komplekt_type,
                                _ri_plus, 84).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Данные", lambda row: [
            self._ribbon_button(row, "Сбросить", self.reset_komplekt_catalog,
                                _ri_clear, 64).pack(side=tk.LEFT),
        ])
        tk.Label(page, text="Типовые комплекты берутся из типовых шкафов каталога,\n"
                            "нетиповые и прочие хранятся в komplekts.json.\n"
                            "В комплекте: ИЭУ, функции и испытательные блоки U/I.",
                 bg="#f3f3f3", fg="#808080", font=("Arial", 7),
                 justify="left").pack(side=tk.LEFT, padx=12)
        return page

    def open_komplekt_catalog(self):
        """Окно каталога комплектов: список и управление."""
        window = tk.Toplevel(self.root)
        window.title("Каталог комплектов РЗА")
        window.transient(self.root)

        header = tk.Label(window, text="", anchor="w", fg="#555555")
        header.pack(fill=tk.X, padx=10, pady=(8, 4))

        filters = tk.Frame(window)
        filters.pack(fill=tk.X, padx=10, pady=(0, 4))
        tk.Label(filters, text="Вид:").pack(side=tk.LEFT)
        kind_variable = tk.StringVar(value="Все виды")
        tk.OptionMenu(filters, kind_variable, "Все виды",
                      *komplekts.KINDS.values()).pack(side=tk.LEFT, padx=(6, 12))
        tk.Label(filters, text="Поиск:").pack(side=tk.LEFT)
        search_variable = tk.StringVar()
        tk.Entry(filters, textvariable=search_variable, width=26).pack(
            side=tk.LEFT, padx=(6, 0))

        frame = tk.Frame(window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=96, height=18, activestyle="dotbox",
                             exportselection=False)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info = tk.Label(window, text="", anchor="w", justify="left",
                        fg="#333333", wraplength=660)
        info.pack(fill=tk.X, padx=10, pady=6)

        state = {"kits": [], "visible": []}
        kind_by_label = {title: key for key, title in komplekts.KINDS.items()}

        def kit_info(kit):
            lines = ["Вид: " + komplekts.kind_title(kit)]
            if kit.get("kind") == "typical":
                cabinet = cabs.find_cabinet(kit.get("cabinet_key"))
                cabinet_text = (komplekts.cabinet_label(cabinet) if cabinet
                                else kit.get("cabinet_key") or "—")
                lines.append("Типовой шкаф: " + cabinet_text)
            elif kit.get("cabinet_key"):
                cabinet = cabs.find_cabinet(kit.get("cabinet_key"))
                lines.append("Шкаф-источник: " + (
                    komplekts.cabinet_label(cabinet) if cabinet
                    else kit.get("cabinet_key")))
            if kit.get("functions"):
                lines.append("Функции: " + ", ".join(kit["functions"]))
            ieds = komplekts.effective_ieds(kit)
            if ieds:
                lines.append("ИЭУ: " + ", ".join(
                    ied.get("name") or "ИЭУ" for ied in ieds))
            elif kit.get("has_ied"):
                lines.append("ИЭУ: есть (устройства не указаны)")
            else:
                lines.append("ИЭУ: нет")
            if komplekts.has_test_blocks(kit):
                lines.append("Испытательные блоки: " +
                             komplekts.test_blocks_text(kit))
            if kit.get("desc"):
                lines.append("Примечание: " + kit["desc"])
            return "\n".join(lines)

        def refresh(select_key=None):
            state["kits"] = komplekts.all_komplekts()
            kind_label = kind_variable.get()
            kind = kind_by_label.get(kind_label)
            needle = search_variable.get().strip().lower()
            visible = []
            for kit in state["kits"]:
                if kind and kit.get("kind") != kind:
                    continue
                if needle:
                    haystack = " ".join([
                        kit.get("name") or "", kit.get("desc") or "",
                        kit.get("cabinet_code") or "",
                        kit.get("cabinet_name") or "",
                        ", ".join(kit.get("functions") or []),
                        ", ".join(ied.get("name") or ""
                                  for ied in kit.get("ieds") or []),
                    ]).lower()
                    if needle not in haystack:
                        continue
                visible.append(kit)
            state["visible"] = visible
            listbox.delete(0, "end")
            for kit in visible:
                listbox.insert("end", komplekts.kit_label(kit))
            counts = {key: 0 for key in komplekts.KIND_ORDER}
            for kit in state["kits"]:
                counts[kit["kind"]] = counts.get(kit["kind"], 0) + 1
            header.config(
                text="Комплектов: {} (типовых {}, нетиповых {}, прочих {}; "
                     "показано {})".format(
                         len(state["kits"]), counts.get("typical", 0),
                         counts.get("custom", 0), counts.get("other", 0),
                         len(visible)))
            if visible:
                index = 0
                if select_key:
                    for position, kit in enumerate(visible):
                        if kit.get("key") == select_key:
                            index = position
                            break
                listbox.selection_clear(0, "end")
                listbox.selection_set(index)
                listbox.activate(index)
                listbox.see(index)
                info.config(text=kit_info(visible[index]))
            else:
                info.config(text="Комплектов не найдено.")

        def selected():
            selection = listbox.curselection()
            if not selection:
                return None
            return state["visible"][selection[0]]

        def on_new():
            key = self.create_komplekt_type()
            refresh(key)

        def on_edit(event=None):
            kit = selected()
            if kit is None:
                return
            key = self.edit_komplekt_type(kit, kit.get("key"))
            refresh(key or kit.get("key"))

        def on_duplicate():
            kit = selected()
            if kit is None:
                return
            key = komplekts.duplicate_komplekt(kit.get("key"))
            refresh(key)

        def on_delete():
            kit = selected()
            if kit is None:
                return
            if kit.get("source") == "cabinet":
                messagebox.showinfo(
                    "Каталог комплектов",
                    "Комплект входит в шкаф каталога и меняется вместе с ним.\n"
                    "Можно сделать нетиповую копию кнопкой «Дублировать».")
                return
            title = kit.get("name") or "комплект"
            if not messagebox.askyesno(
                    "Каталог комплектов",
                    "Удалить комплект «{}» из каталога?".format(title)):
                return
            komplekts.delete_komplekt(kit.get("key"))
            refresh()

        def on_to_cabinet():
            kit = selected()
            if kit is not None:
                self.add_komplekt_to_cabinet(kit)

        buttons = tk.Frame(window)
        buttons.pack(fill=tk.X, padx=10, pady=8)
        tk.Button(buttons, text="Закрыть", width=10,
                  command=window.destroy).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Удалить", width=10,
                  command=on_delete).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Дублировать", width=12,
                  command=on_duplicate).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Изменить", width=10,
                  command=on_edit).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Новый", width=10,
                  command=on_new).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="В шкаф…", width=10,
                  command=on_to_cabinet).pack(side=tk.LEFT)

        listbox.bind("<<ListboxSelect>>",
                     lambda event: info.config(text=kit_info(selected()))
                     if selected() else None)
        listbox.bind("<Double-Button-1>", on_edit)
        window.bind("<Escape>", lambda event: window.destroy())
        kind_variable.trace_add("write", lambda *args: refresh())
        search_variable.trace_add("write", lambda *args: refresh())
        refresh()

        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 4)
        window.geometry(f"+{x}+{y}")
        try:
            window.grab_set()
        except tk.TclError:
            pass

    def create_komplekt_type(self):
        """Создание нового комплекта в каталоге. Возвращает ключ или None."""
        return self.edit_komplekt_type(None)

    def edit_komplekt_type(self, definition=None, original_key=None):
        """Редактор комплекта каталога: сохраняет в komplekts.json.

        Возвращает ключ сохранённого комплекта (или None при отмене).
        """
        value = self._komplekt_form(
            definition,
            title="Комплект РЗА — " + ("изменение" if original_key else "новый"))
        if value is None:
            return None
        try:
            return komplekts.save_komplekt(value, original_key)
        except Exception as exc:
            messagebox.showerror("Каталог комплектов",
                                 "Не удалось сохранить комплект:\n{}".format(exc))
            return None

    def reset_komplekt_catalog(self):
        if not messagebox.askyesno(
                "Каталог комплектов",
                "Удалить все нетиповые комплекты и правки типовых?\n"
                "Типовые комплекты из каталога шкафов останутся."):
            return
        komplekts.reset_user_catalog()
        messagebox.showinfo(
            "Каталог комплектов",
            "Каталог сброшен: {} комплектов.".format(
                len(komplekts.all_komplekts())))

    def _choose_komplekt(self, title="Выбор комплекта"):
        """Диалог выбора комплекта из каталога. Возвращает dict или None."""
        kits = komplekts.all_komplekts()
        if not kits:
            messagebox.showinfo("Комплекты", "Каталог комплектов пуст.")
            return None

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)

        filters = tk.Frame(dialog)
        filters.pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(filters, text="Вид:").pack(side=tk.LEFT)
        kind_variable = tk.StringVar(value="Все виды")
        tk.OptionMenu(filters, kind_variable, "Все виды",
                      *komplekts.KINDS.values()).pack(side=tk.LEFT, padx=(6, 12))
        tk.Label(filters, text="Поиск:").pack(side=tk.LEFT)
        search_variable = tk.StringVar()
        tk.Entry(filters, textvariable=search_variable, width=22).pack(
            side=tk.LEFT, padx=(6, 0))

        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=88, height=15, activestyle="dotbox",
                             exportselection=False)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info = tk.Label(dialog, text="", anchor="w", justify="left",
                        fg="#333333", wraplength=640)
        info.pack(fill=tk.X, padx=10, pady=6)

        state = {"visible": list(kits)}
        result = {"value": None}
        kind_by_label = {title: key for key, title in komplekts.KINDS.items()}

        def describe(kit):
            lines = ["Вид: " + komplekts.kind_title(kit)]
            if kit.get("functions"):
                lines.append("Функции: " + ", ".join(kit["functions"]))
            ieds = komplekts.effective_ieds(kit)
            lines.append("ИЭУ: " + (", ".join(ied.get("name") or "ИЭУ"
                                              for ied in ieds)
                                    if ieds else "нет"))
            if komplekts.has_test_blocks(kit):
                lines.append("Испытательные блоки: " +
                             komplekts.test_blocks_text(kit))
            if kit.get("desc"):
                lines.append("Примечание: " + kit["desc"])
            return "\n".join(lines)

        def refresh():
            kind = kind_by_label.get(kind_variable.get())
            needle = search_variable.get().strip().lower()
            visible = []
            for kit in kits:
                if kind and kit.get("kind") != kind:
                    continue
                if needle:
                    haystack = " ".join([
                        kit.get("name") or "",
                        ", ".join(kit.get("functions") or []),
                        kit.get("cabinet_code") or "",
                        kit.get("cabinet_name") or "",
                    ]).lower()
                    if needle not in haystack:
                        continue
                visible.append(kit)
            state["visible"] = visible
            listbox.delete(0, "end")
            for kit in visible:
                listbox.insert("end", komplekts.kit_label(kit))
            if visible:
                listbox.selection_clear(0, "end")
                listbox.selection_set(0)
                listbox.activate(0)
                info.config(text=describe(visible[0]))
            else:
                info.config(text="Комплектов не найдено.")

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
        buttons.pack(fill=tk.X, padx=10, pady=8)
        tk.Button(buttons, text="Отмена", width=10,
                  command=dialog.destroy).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Выбрать", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))

        listbox.bind("<<ListboxSelect>>", on_select)
        listbox.bind("<Double-Button-1>", accept)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        kind_variable.trace_add("write", lambda *args: refresh())
        search_variable.trace_add("write", lambda *args: refresh())
        refresh()

        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        return result["value"]

    def _komplekt_form(self, definition=None, title="Комплект РЗА",
                       allow_no_cabinet=False):
        """Редактор комплекта. Возвращает нормализованный dict или None.

        allow_no_cabinet — для комплектов внутри шкафа схемы: вид «типовой»
        не требует ссылки, ссылка на шкаф и так подразумевается самим шкафом.
        """
        data = komplekts.normalize_komplekt(
            copy.deepcopy(dict(definition or {})), "custom")
        derived = data.get("source") == "cabinet"

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)

        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        result = {"value": None}
        rows = {"row": 0}

        def add_line(label, widget):
            tk.Label(form, text=label, anchor="w").grid(
                row=rows["row"], column=0, sticky="w", pady=2)
            widget.grid(row=rows["row"], column=1, sticky="we",
                        padx=(8, 0), pady=2)
            rows["row"] += 1
            return widget

        name_var = tk.StringVar(value=data["name"])
        name_entry = add_line("Название", tk.Entry(form, textvariable=name_var,
                                                   width=50))
        type_var = tk.StringVar(value=data["type"])
        add_line("Тип", tk.Entry(form, textvariable=type_var, width=32))

        kind_by_label = {komplekts.KINDS[key]: key
                         for key in komplekts.KIND_ORDER}
        kind_var = tk.StringVar(value=komplekts.KINDS[data["kind"]])
        kind_menu = tk.OptionMenu(form, kind_var, *komplekts.KINDS.values(),
                                  command=lambda value: on_kind_change())
        add_line("Вид комплекта", kind_menu)

        functions_var = tk.StringVar(value=", ".join(data["functions"]))
        add_line("Функции (через запятую)",
                 tk.Entry(form, textvariable=functions_var, width=50))

        cabinets = komplekts.typical_cabinets()
        cabinet_lookup = {}
        cabinet_labels = ["— не указан —"]
        for cabinet in cabinets:
            label = komplekts.cabinet_label(cabinet)
            if label in cabinet_lookup:
                label = "{} ({})".format(label, cabinet.get("key"))
            cabinet_lookup[label] = cabinet
            cabinet_labels.append(label)
        initial_label = "— не указан —"
        for label, cabinet in cabinet_lookup.items():
            if cabinet.get("key") == data.get("cabinet_key"):
                initial_label = label
                break
        cabinet_var = tk.StringVar(value=initial_label)
        cabinet_menu = tk.OptionMenu(form, cabinet_var, *cabinet_labels,
                                     command=lambda value: on_cabinet_change())
        add_line("Типовой шкаф", cabinet_menu)

        kit_row = tk.Frame(form)
        index_var = tk.StringVar(
            value=str(int(data.get("cabinet_index") or 0) + 1))
        index_spin = tk.Spinbox(kit_row, from_=1, to=1, width=5,
                                textvariable=index_var)
        index_spin.pack(side=tk.LEFT)
        take_button = tk.Button(kit_row, text="Взять данные из шкафа",
                                command=lambda: load_from_cabinet())
        take_button.pack(side=tk.LEFT, padx=(6, 0))
        add_line("Комплект шкафа", kit_row)

        desc_var = tk.StringVar(value=data["desc"])
        add_line("Примечание", tk.Entry(form, textvariable=desc_var, width=50))

        has_ied_var = tk.BooleanVar(value=data["has_ied"])
        tk.Checkbutton(form, text="Есть ИЭУ в комплекте",
                       variable=has_ied_var,
                       command=lambda: sync_ied_state()).grid(
            row=rows["row"], column=0, columnspan=2, sticky="w",
            pady=(8, 2))
        rows["row"] += 1

        ieds = [dict(ied) for ied in data["ieds"]]
        ied_frame = tk.Frame(form)
        ied_frame.grid(row=rows["row"], column=0, columnspan=2, sticky="we")
        rows["row"] += 1
        ied_list = tk.Listbox(ied_frame, width=42, height=4,
                              activestyle="dotbox", exportselection=False)
        ied_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ied_side = tk.Frame(ied_frame)
        ied_side.pack(side=tk.LEFT, padx=(6, 0), fill=tk.Y)
        ied_name_var = tk.StringVar()
        ied_type_var = tk.StringVar(value="МП РЗА")
        ied_name_entry = tk.Entry(ied_side, textvariable=ied_name_var, width=16)
        ied_name_entry.pack(pady=1)
        ied_type_entry = tk.Entry(ied_side, textvariable=ied_type_var, width=16)
        ied_type_entry.pack(pady=1)
        add_ied_button = tk.Button(ied_side, text="+ ИЭУ", width=14,
                                   command=lambda: add_ied())
        add_ied_button.pack(pady=(4, 1))
        remove_ied_button = tk.Button(ied_side, text="− ИЭУ", width=14,
                                      command=lambda: remove_ied())
        remove_ied_button.pack(pady=1)

        blocks_frame = tk.LabelFrame(form, text="Испытательные блоки",
                                     padx=8, pady=4)
        blocks_frame.grid(row=rows["row"], column=0, columnspan=2,
                          sticky="we", pady=(8, 2))
        rows["row"] += 1

        blocks = komplekts.normalize_test_blocks(data.get("test_blocks"))
        volt_count_var = tk.StringVar(value=str(blocks["voltage"]["count"]))
        volt_circuits_var = tk.StringVar(
            value=", ".join(blocks["voltage"]["circuits"]))
        curr_count_var = tk.StringVar(value=str(blocks["current"]["count"]))
        curr_circuits_var = tk.StringVar(
            value=", ".join(blocks["current"]["circuits"]))

        def add_block_row(label, count_var, circuits_var, presets):
            line = tk.Frame(blocks_frame)
            line.pack(fill=tk.X, pady=(3, 0))
            tk.Label(line, text=label, width=17, anchor="w").pack(side=tk.LEFT)
            tk.Label(line, text="блоков").pack(side=tk.LEFT)
            tk.Spinbox(line, from_=0, to=komplekts.MAX_TEST_BLOCKS, width=4,
                       textvariable=count_var).pack(side=tk.LEFT, padx=(4, 10))
            tk.Label(line, text="цепи:").pack(side=tk.LEFT)
            tk.Entry(line, textvariable=circuits_var, width=30).pack(
                side=tk.LEFT, fill=tk.X, expand=True)
            buttons = tk.Frame(blocks_frame)
            buttons.pack(fill=tk.X, padx=(150, 0))
            for position, preset in enumerate(presets):
                def toggle(name=preset, variable=circuits_var):
                    tokens = komplekts.split_list(variable.get())
                    if name in tokens:
                        tokens.remove(name)
                    else:
                        tokens.append(name)
                    variable.set(", ".join(tokens))

                tk.Button(buttons, text=preset, width=6, font=("Arial", 8),
                          command=toggle).grid(row=position // 6,
                                               column=position % 6,
                                               padx=(0, 2), pady=(0, 2),
                                               sticky="w")

        add_block_row("Напряжение (U):", volt_count_var, volt_circuits_var,
                      komplekts.VOLTAGE_PRESETS)
        add_block_row("Ток (I):", curr_count_var, curr_circuits_var,
                      komplekts.CURRENT_PRESETS)
        tk.Label(blocks_frame,
                 text="Например: Ua, Ub, Uc · 3U0 · Ia, Ib, Ic · 3I0 "
                      "(как в связях аналоговых цепей)",
                 fg="#999999", font=("Arial", 7), anchor="w").pack(
            fill=tk.X, pady=(4, 0))

        hint = tk.Label(form, text="", fg="#808080", font=("Arial", 7),
                        anchor="w", justify="left", wraplength=620)
        hint.grid(row=rows["row"], column=0, columnspan=2, sticky="w",
                  pady=(4, 0))
        rows["row"] += 1
        if derived:
            hint.config(text="Название, вид и типовой шкаф берутся из каталога "
                             "шкафов; здесь меняются функции, ИЭУ и "
                             "испытательные блоки.")

        error = tk.Label(form, text="", fg="#b00020", anchor="w")
        error.grid(row=rows["row"], column=0, columnspan=2, sticky="w",
                   pady=(4, 0))
        rows["row"] += 1

        def _int(text, default=0):
            try:
                value = int(str(text).strip() or 0)
            except (TypeError, ValueError):
                return default
            return max(0, min(komplekts.MAX_TEST_BLOCKS, value))

        def refresh_ieds():
            ied_list.delete(0, "end")
            for ied in ieds:
                ied_list.insert("end", "{} — {}".format(
                    ied.get("name", "ИЭУ"), ied.get("type", "")))

        def sync_ied_state(*_args):
            state = tk.NORMAL if has_ied_var.get() else tk.DISABLED
            ied_list.config(state=state)
            ied_name_entry.config(state=state)
            ied_type_entry.config(state=state)
            add_ied_button.config(state=state)
            remove_ied_button.config(state=state)

        def add_ied():
            name = ied_name_var.get().strip()
            if not name:
                error.config(text="Укажите название ИЭУ.")
                return
            ieds.append({"name": name,
                         "type": ied_type_var.get().strip() or "МП РЗА",
                         "desc": ""})
            has_ied_var.set(True)
            ied_name_var.set("")
            error.config(text="")
            refresh_ieds()
            sync_ied_state()

        def remove_ied():
            selection = ied_list.curselection()
            if not selection:
                return
            ieds.pop(selection[0])
            refresh_ieds()

        def kits_of(cabinet):
            return (cabinet.get("komplets") or []) if cabinet else []

        def set_index_bounds():
            cabinet = cabinet_lookup.get(cabinet_var.get())
            count = max(1, len(kits_of(cabinet)))
            index_spin.config(to=count)
            index = _int(index_var.get(), 1)
            index_var.set(str(max(1, min(index, count))))

        def load_from_cabinet(event=None):
            cabinet = cabinet_lookup.get(cabinet_var.get())
            if cabinet is None:
                return
            index = max(0, _int(index_var.get(), 1) - 1)
            kit = komplekts.kit_from_cabinet(cabinet, index)
            if kit is None:
                return
            name_var.set(kit["name"])
            type_var.set(kit["type"])
            functions_var.set(", ".join(kit["functions"]))
            desc_var.set(kit["desc"])
            has_ied_var.set(kit["has_ied"])
            del ieds[:]
            ieds.extend(copy.deepcopy(kit["ieds"]))
            refresh_ieds()
            sync_ied_state()
            blocks = komplekts.normalize_test_blocks(kit.get("test_blocks"))
            volt_count_var.set(str(blocks["voltage"]["count"]))
            volt_circuits_var.set(", ".join(blocks["voltage"]["circuits"]))
            curr_count_var.set(str(blocks["current"]["count"]))
            curr_circuits_var.set(", ".join(blocks["current"]["circuits"]))

        def on_cabinet_change(value=None):
            set_index_bounds()
            if kind_var.get() == komplekts.KINDS["typical"]:
                load_from_cabinet()

        def sync_kind_state():
            typical = kind_var.get() == komplekts.KINDS["typical"]
            state = tk.NORMAL if typical else tk.DISABLED
            cabinet_menu.config(state=state)
            index_spin.config(state=state)
            take_button.config(state=state)
            if derived:
                kind_menu.config(state=tk.DISABLED)
                name_entry.config(state=tk.DISABLED)
                cabinet_menu.config(state=tk.DISABLED)
                index_spin.config(state=tk.DISABLED)
                take_button.config(state=tk.DISABLED)

        def on_kind_change(value=None):
            sync_kind_state()
            if (kind_var.get() == komplekts.KINDS["typical"] and not derived
                    and cabinet_var.get() not in cabinet_lookup
                    and len(cabinet_labels) > 1):
                cabinet_var.set(cabinet_labels[1])
                set_index_bounds()
                load_from_cabinet()

        def accept(event=None):
            name = name_var.get().strip()
            if not name:
                error.config(text="Укажите название комплекта.")
                return
            kind = kind_by_label.get(kind_var.get(), "custom")
            cabinet = cabinet_lookup.get(cabinet_var.get())
            cabinet_key = ""
            if kind == "typical":
                if cabinet is None and not (allow_no_cabinet or derived):
                    error.config(
                        text="Выберите типовой шкаф для типового комплекта.")
                    return
                cabinet_key = ((cabinet.get("key") or "") if cabinet
                               else data.get("cabinet_key") or "")
            cabinet_code = ((cabinet.get("code") or "") if cabinet
                            else data.get("cabinet_code") or "")
            cabinet_name = ((cabinet.get("name") or "") if cabinet
                            else data.get("cabinet_name") or "")
            cabinet_group = ((cabinet.get("group") or "") if cabinet
                             else data.get("cabinet_group") or "")
            entry = {
                "key": data.get("key") or "",
                "kind": kind,
                "name": name,
                "type": type_var.get().strip(),
                "functions": komplekts.split_list(functions_var.get()),
                "desc": desc_var.get().strip(),
                "has_ied": has_ied_var.get(),
                "ieds": [dict(ied) for ied in ieds],
                "test_blocks": {
                    "voltage": {
                        "count": _int(volt_count_var.get()),
                        "circuits": komplekts.split_list(
                            volt_circuits_var.get()),
                    },
                    "current": {
                        "count": _int(curr_count_var.get()),
                        "circuits": komplekts.split_list(
                            curr_circuits_var.get()),
                    },
                },
                "cabinet_key": cabinet_key,
                "cabinet_index": max(0, _int(index_var.get(), 1) - 1) if
                kind == "typical" else 0,
                "cabinet_code": cabinet_code if kind == "typical" else "",
                "cabinet_name": cabinet_name if kind == "typical" else "",
                "cabinet_group": cabinet_group if kind == "typical" else "",
            }
            result["value"] = komplekts.normalize_komplekt(entry)
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=dialog.destroy).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))

        def on_index_enter(event=None):
            # Enter в номере комплекта берёт данные из шкафа, а не сохраняет
            load_from_cabinet()
            return "break"

        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        index_spin.bind("<Return>", on_index_enter)
        index_spin.bind("<KP_Enter>", on_index_enter)
        index_spin.bind("<FocusOut>", lambda event: set_index_bounds())

        refresh_ieds()
        sync_ied_state()
        sync_kind_state()
        set_index_bounds()
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        return result["value"]

    def add_komplekt_to_cabinet(self, kit):
        """Добавляет комплект из каталога в выбранный на схеме шкаф."""
        if not kit:
            return
        cabinet = None
        for element_id in self.selected_elements:
            element = self.elements.get(element_id)
            if element is not None and element.type == "cabinet":
                cabinet = element
                break
        if cabinet is None:
            messagebox.showinfo(
                "Комплекты",
                "Выберите на схеме шкаф РЗА, в который добавить комплект.")
            return
        if len(cabinet.komplets) >= library.CABINET_MAX_KOMPLETS:
            messagebox.showinfo(
                "Комплекты",
                "В шкафу уже {} комплектов — больше нельзя.".format(
                    library.CABINET_MAX_KOMPLETS))
            return
        entry = komplekts.for_cabinet(kit)
        names = {item.get("name") for item in cabinet.komplets}
        if entry.get("name") in names:
            entry["name"] = "{} ({})".format(
                entry.get("name"), len(cabinet.komplets) + 1)
        self._push_undo()
        cabinet.komplets.append(entry)
        cabinet.generate_ports()
        self.redraw_all()
        messagebox.showinfo(
            "Комплекты",
            "Комплект «{}» добавлен в шкаф {}.".format(
                entry.get("name"), cabinet.name))

    def edit_cabinet_type(self, definition=None, original_key=None):
        """Редактор шкафа: поля каталога, до 7 комплектов и ИЭУ в каждом."""
        definition = cabs.normalize_cabinet(copy.deepcopy(dict(definition or {})))
        dialog = tk.Toplevel(self.root)
        dialog.title("Шкаф РЗА — " + ("изменение" if original_key else "новый шкаф"))
        dialog.transient(self.root)
        dialog.resizable(False, False)

        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)

        fields = (
            ("code", "Шифр шкафа", 26),
            ("name", "Название (кратко)", 34),
            ("title", "Полное наименование", 56),
            ("voltage", "Напряжение", 26),
            ("protected", "Защищаемый элемент", 56),
            ("controlled", "Управляемые (через запятую)", 56),
            ("its_functions", "Функции ИТС (через запятую)", 56),
            ("applicability", "Применимость", 56),
            ("source", "Источник (раздел СТО)", 34),
        )
        variables = {}
        row = 0
        for key, label, width in fields:
            tk.Label(form, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            value = definition.get(key, "")
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(item) for item in value)
            variable = tk.StringVar(value=str(value))
            tk.Entry(form, textvariable=variable, width=width).grid(
                row=row, column=1, sticky="we", padx=(8, 0), pady=2)
            variables[key] = variable
            row += 1

        tk.Label(form, text="Стандарт", anchor="w").grid(row=row, column=0, sticky="w", pady=2)
        standard_labels = ["Прочие (без СТО)"]
        standard_keys = [""]
        for standard_key, standard in cabs.STANDARDS.items():
            standard_keys.append(standard_key)
            standard_labels.append(f'{standard["group"]} — {standard["code"]}')
        current_key = definition.get("standard_key", "")
        current_label = (standard_labels[standard_keys.index(current_key)]
                         if current_key in standard_keys else standard_labels[0])
        standard_variable = tk.StringVar(value=current_label)
        tk.OptionMenu(form, standard_variable, *standard_labels).grid(
            row=row, column=1, sticky="we", padx=(8, 0), pady=2)
        row += 1

        tk.Label(form, text="Комплекты (1–{}, в каждом 0..N ИЭУ):".format(cabs.MAX_KOMPLETS),
                 anchor="w").grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row += 1

        default_kind = "typical" if definition.get("standard_key") else "custom"
        komplets = komplekts.normalize_komplets(
            (definition.get("komplets") or [])[:cabs.MAX_KOMPLETS], default_kind)
        if not komplets:
            komplets = [komplekts.normalize_komplekt(
                {"name": "Комплект 1"}, default_kind)]

        box = tk.Frame(form)
        box.grid(row=row, column=0, columnspan=2, sticky="we")
        row += 1

        left = tk.Frame(box)
        left.pack(side=tk.LEFT, fill=tk.Y)
        komplekt_list = tk.Listbox(left, width=46, height=8, activestyle="dotbox",
                                   exportselection=False)
        komplekt_list.pack(fill=tk.BOTH, expand=True)
        komplekt_buttons = tk.Frame(left)
        komplekt_buttons.pack(fill=tk.X, pady=(4, 0))
        tk.Button(komplekt_buttons, text="+ Комплект", width=12,
                  command=lambda: add_komplekt()).pack(side=tk.LEFT)
        tk.Button(komplekt_buttons, text="+ Из каталога…", width=14,
                  command=lambda: add_from_catalog()).pack(side=tk.LEFT, padx=(4, 0))
        tk.Button(komplekt_buttons, text="− Комплект", width=12,
                  command=lambda: remove_komplekt()).pack(side=tk.LEFT, padx=(4, 0))

        right = tk.Frame(box, padx=10)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary = tk.Label(right, text="", anchor="nw", justify="left",
                           wraplength=430, fg="#333333", font=("Arial", 9))
        summary.pack(fill=tk.BOTH, expand=True)
        tk.Button(right, text="Изменить комплект…", width=20,
                  command=lambda: edit_komplekt()).pack(anchor="w", pady=(6, 0))
        tk.Label(right, text="Вид комплекта (типовой / нетиповой / прочий), "
                             "типовой шкаф,\nфункции, ИЭУ и испытательные блоки "
                             "задаются в редакторе комплекта.",
                 fg="#808080", font=("Arial", 7), justify="left").pack(
            anchor="w", pady=(6, 0))

        error = tk.Label(form, text="", fg="#b00020", anchor="w")
        error.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        state = {"index": 0}

        def split_list(text):
            return komplekts.split_list(text)

        def komplekt_caption(index):
            kit = komplets[index]
            parts = [kit.get("name") or "Комплект {}".format(index + 1),
                     komplekts.kind_title(kit)]
            ieds = komplekts.effective_ieds(kit)
            parts.append("{} ИЭУ".format(len(ieds)) if ieds else "без ИЭУ")
            blocks = komplekts.test_blocks_summary(kit)
            if blocks:
                parts.append("БИ " + blocks)
            return " · ".join(parts)

        def summary_text(kit):
            lines = ["Вид: " + komplekts.kind_title(kit)]
            if kit.get("kind") == "typical":
                lines.append("Типовой шкаф: " + komplekts.cabinet_ref_text(kit))
            if kit.get("functions"):
                lines.append("Функции: " + ", ".join(kit["functions"]))
            ieds = komplekts.effective_ieds(kit)
            if ieds:
                lines.append("ИЭУ: " + ", ".join(
                    "{} ({})".format(ied.get("name") or "ИЭУ",
                                     ied.get("type") or "МП РЗА")
                    for ied in ieds))
            elif kit.get("has_ied"):
                lines.append("ИЭУ: есть (устройства не указаны)")
            else:
                lines.append("ИЭУ: нет")
            if komplekts.has_test_blocks(kit):
                lines.append("Испытательные блоки: " +
                             komplekts.test_blocks_text(kit))
            if kit.get("desc"):
                lines.append("Примечание: " + kit["desc"])
            return "\n".join(lines)

        def refresh_komplekts(select=None):
            komplekt_list.delete(0, "end")
            for index in range(len(komplets)):
                komplekt_list.insert("end", komplekt_caption(index))
            if select is not None:
                state["index"] = select
            state["index"] = max(0, min(state["index"], len(komplets) - 1))
            komplekt_list.selection_clear(0, "end")
            komplekt_list.selection_set(state["index"])
            komplekt_list.activate(state["index"])
            komplekt_list.see(state["index"])
            summary.config(text=summary_text(komplets[state["index"]]))

        def on_select(event=None):
            selection = komplekt_list.curselection()
            if not selection:
                return
            state["index"] = selection[0]
            summary.config(text=summary_text(komplets[state["index"]]))

        def add_komplekt():
            if len(komplets) >= cabs.MAX_KOMPLETS:
                error.config(text="В шкафу не может быть больше {} комплектов.".format(
                    cabs.MAX_KOMPLETS))
                return
            default = komplekts.normalize_komplekt({
                "name": "Комплект {}".format(len(komplets) + 1),
                "kind": default_kind,
            }, default_kind)
            edited = self._komplekt_form(default, title="Новый комплект",
                                         allow_no_cabinet=True)
            if edited is None:
                return
            komplets.append(edited)
            error.config(text="")
            refresh_komplekts(len(komplets) - 1)

        def add_from_catalog():
            if len(komplets) >= cabs.MAX_KOMPLETS:
                error.config(text="В шкафу не может быть больше {} комплектов.".format(
                    cabs.MAX_KOMPLETS))
                return
            picked = self._choose_komplekt("Комплект в шкаф")
            if picked is None:
                return
            entry = komplekts.for_cabinet(picked)
            names = {kit.get("name") for kit in komplets}
            if entry.get("name") in names:
                entry["name"] = "{} ({})".format(entry.get("name"),
                                                 len(komplets) + 1)
            komplets.append(entry)
            error.config(text="")
            refresh_komplekts(len(komplets) - 1)

        def edit_komplekt():
            selection = komplekt_list.curselection()
            if not selection:
                return
            index = selection[0]
            edited = self._komplekt_form(
                copy.deepcopy(komplets[index]), title="Комплект — изменение",
                allow_no_cabinet=True)
            if edited is None:
                return
            komplets[index] = edited
            error.config(text="")
            refresh_komplekts(index)

        def remove_komplekt():
            selection = komplekt_list.curselection()
            if not selection:
                return
            if len(komplets) <= 1:
                error.config(text="В шкафу должен остаться хотя бы один комплект.")
                return
            index = selection[0]
            del komplets[index]
            error.config(text="")
            refresh_komplekts(max(0, index - 1))

        komplekt_list.bind("<<ListboxSelect>>", on_select)
        komplekt_list.bind("<Double-Button-1>", lambda event: edit_komplekt())

        def accept(event=None):
            name = variables["name"].get().strip()
            if not name:
                error.config(text="Укажите название шкафа.")
                return
            cleaned = [komplekts.for_cabinet(komplekt) for komplekt in komplets]
            standard_key = standard_keys[standard_labels.index(standard_variable.get())]
            data = {
                "key": original_key or "",
                "standard_key": standard_key,
                "code": variables["code"].get().strip(),
                "name": name,
                "title": variables["title"].get().strip() or name,
                "description": variables["title"].get().strip() or name,
                "voltage": variables["voltage"].get().strip(),
                "protected": variables["protected"].get().strip(),
                "controlled": split_list(variables["controlled"].get()),
                "its_functions": split_list(variables["its_functions"].get()),
                "applicability": variables["applicability"].get().strip(),
                "source": variables["source"].get().strip(),
                "goose": True,
                "komplets": cleaned,
            }
            try:
                cabs.save_cabinet(data, original_key)
            except Exception as exc:
                error.config(text="Не удалось сохранить: {}".format(exc))
                return
            dialog.destroy()
            messagebox.showinfo("Каталог шкафов",
                                "Шкаф сохранён: {}".format(data["code"] or data["name"]))

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Button(buttons, text="Отмена", width=10, command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12, command=accept).pack(side=tk.RIGHT, padx=(0, 6))

        dialog.bind("<Return>", lambda event: accept())
        dialog.bind("<Escape>", cancel)

        refresh_komplekts(0)
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 6)
        dialog.geometry(f"+{x}+{y}")
        try:
            dialog.grab_set()
        except tk.TclError:
            pass
        dialog.wait_window(dialog)

    # ================= ВКЛАДКА «КОНТЕЙНЕРЫ» И ПРИВЯЗКА ШКАФОВ =================
    def _build_ribbon_containers(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")
        self._ribbon_group(page, "Каталог", lambda row: [
            self._ribbon_button(row, "Каталог…", self.open_container_catalog,
                                _ri_container, 66).pack(side=tk.LEFT),
            self._ribbon_button(row, "Новый КЭТ", self.create_container_type,
                                _ri_plus, 72).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Размещение", lambda row: [
            self._ribbon_button(row, "Контейнер…", self.add_container,
                                _ri_container, 76).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Привязка слотов", lambda row: [
            self._register_tool(self._ribbon_button(
                row, "Связь КЭТ", lambda: self.set_tool("bind"),
                _ri_ket_link, 70), "bind").pack(side=tk.LEFT),
            self._ribbon_button(row, "По составу", self.expand_container_by_composition,
                                _ri_plus, 66).pack(side=tk.LEFT),
        ])
        self._ribbon_group(page, "Данные", lambda row: [
            self._ribbon_button(row, "Сбросить", self.reset_container_catalog,
                                _ri_clear, 64).pack(side=tk.LEFT),
        ])
        tk.Label(page, text="Связь КЭТ: клик по свободному слоту (●), затем по □ шкафа.\n"
                            "Ctrl+клик по линии или точке — отвязать.\n"
                            "Слоты сверху вниз: 7 (20’) / 14 (40’).",
                 bg="#f3f3f3", fg="#808080", font=("Arial", 7),
                 justify="left").pack(side=tk.LEFT, padx=12)
        return page

    def _center_dialog(self, dialog):
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 5)
        dialog.geometry(f"+{x}+{y}")
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

    def _pick_from_list(self, title, hint, items, multi=False, width=80,
                        height=14, accept_text="ОК"):
        """Простой диалог выбора из списка [(ключ, подпись), …]."""
        if not items:
            return []
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        tk.Label(dialog, text=hint, anchor="w", fg="#555555", justify="left",
                 wraplength=620).pack(fill=tk.X, padx=10, pady=(8, 4))
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=width,
                             height=max(3, min(height, len(items))),
                             activestyle="dotbox",
                             selectmode=tk.MULTIPLE if multi else tk.BROWSE)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for _key, label in items:
            listbox.insert("end", label)
        if multi:
            listbox.selection_set(0)
        else:
            listbox.selection_set(0)
            listbox.activate(0)
        result = {"keys": []}

        def accept(event=None):
            result["keys"] = [items[index][0] for index in listbox.curselection()]
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=8)
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text=accept_text, width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        listbox.bind("<Double-Button-1>", accept)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        return result["keys"]

    # ---------- каталог контейнеров ----------
    def open_container_catalog(self):
        """Окно каталога КЭТ: список контейнеров и кнопки управления."""
        window = tk.Toplevel(self.root)
        window.title("Каталог контейнеров КЭТ")
        window.transient(self.root)

        header = tk.Label(window, text="", anchor="w", fg="#555555")
        header.pack(fill=tk.X, padx=10, pady=(8, 4))

        body = tk.Frame(window)
        body.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(body, width=64, height=18, activestyle="dotbox",
                             exportselection=False)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info = tk.Label(window, text="", anchor="nw", justify="left",
                        fg="#333333", wraplength=760, height=10)
        info.pack(fill=tk.BOTH, padx=10, pady=(6, 0))

        state = {"containers": []}

        def container_label(container):
            group = container.get("group")
            prefix = f"[{group}] " if group else ""
            code = container.get("code")
            name = container.get("name", "КЭТ")
            mark = "" if ketlib.is_builtin(container.get("key")) else " •"
            text = f"{prefix}{code} — {name}" if code else prefix + name
            return text + mark

        def refresh():
            state["containers"] = ketlib.all_containers()
            listbox.delete(0, "end")
            for container in state["containers"]:
                listbox.insert("end", container_label(container))
            header.config(
                text=f"Контейнеров в каталоге: {len(state['containers'])} "
                     f"(встроенных {len(ketlib.CONTAINERS)}, точка • — "
                     f"пользовательский)")
            if state["containers"]:
                listbox.selection_set(0)
                show_info()

        def selected():
            selection = listbox.curselection()
            if not selection:
                return None
            return state["containers"][selection[0]]

        def show_info(event=None):
            container = selected()
            if container is None:
                info.config(text="")
                return
            lines = []
            if container.get("description"):
                lines.append(container["description"])
            lines.append("Типоразмер: {} ({})".format(
                container.get("size_title", ""), container.get("dimensions", "")))
            lines.append("Вместимость: {} шкафов".format(container.get("slots")))
            lines.append("Климат: {}, степень защиты {}".format(
                container.get("climate", ""), container.get("ip", "")))
            if container.get("standard_title"):
                lines.append("НД: {} ({})".format(container["standard_title"],
                                                  container.get("standard")))
            functions = container.get("functions") or []
            if functions:
                lines.append("Функции: " + ", ".join(functions))
            cabinets = container.get("cabinets") or []
            if cabinets:
                names = []
                for key in cabinets:
                    found = cabs.find_cabinet(key)
                    names.append((found or {}).get("code") or key)
                lines.append("Шкафы: " + ", ".join(names))
            if container.get("note"):
                lines.append("Примечание: " + container["note"])
            if container.get("source"):
                lines.append("Источник: " + container["source"])
            info.config(text="\n".join(lines))

        def on_new():
            self.edit_container_type(None)
            refresh()

        def on_edit(event=None):
            container = selected()
            if container is None:
                return
            self.edit_container_type(container, container.get("key"))
            refresh()

        def on_duplicate():
            container = selected()
            if container is None:
                return
            new_key = ketlib.duplicate_container(container.get("key"))
            refresh()
            if new_key is None:
                return
            for index, entry in enumerate(state["containers"]):
                if entry.get("key") == new_key:
                    listbox.selection_clear(0, "end")
                    listbox.selection_set(index)
                    listbox.see(index)
                    break
            show_info()

        def on_delete():
            container = selected()
            if container is None:
                return
            title = container.get("code") or container.get("name")
            if not messagebox.askyesno(
                    "Каталог контейнеров",
                    f"Удалить контейнер «{title}» из каталога?\n"
                    "Размещённые на схеме контейнеры останутся."):
                return
            ketlib.delete_container(container.get("key"))
            refresh()

        def on_place():
            container = selected()
            if container is None:
                return
            window.destroy()
            self._place_container(container, expand=False)

        buttons = tk.Frame(window)
        buttons.pack(fill=tk.X, padx=10, pady=8)
        tk.Button(buttons, text="Закрыть", width=10,
                  command=window.destroy).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Удалить", width=10,
                  command=on_delete).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Дублировать", width=12,
                  command=on_duplicate).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Изменить", width=10,
                  command=on_edit).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Новый", width=10,
                  command=on_new).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="На схему", width=12,
                  command=on_place).pack(side=tk.RIGHT, padx=(0, 6))

        listbox.bind("<<ListboxSelect>>", show_info)
        listbox.bind("<Double-Button-1>", on_edit)
        window.bind("<Escape>", lambda event: window.destroy())
        refresh()
        self._center_dialog(window)

    def create_container_type(self):
        """Создание нового контейнера в каталоге."""
        self.edit_container_type(None)

    def reset_container_catalog(self):
        if not messagebox.askyesno(
                "Каталог контейнеров",
                "Удалить все пользовательские контейнеры и правки?\n"
                "Встроенный каталог из containers.py останется."):
            return
        ketlib.reset_user_catalog()
        messagebox.showinfo(
            "Каталог контейнеров",
            "Каталог сброшен к встроенному: {} контейнеров.".format(
                len(ketlib.all_containers())))

    def edit_container_type(self, definition=None, original_key=None):
        """Редактор контейнера: поля каталога, типоразмер и состав шкафов."""
        definition = ketlib.normalize_container(copy.deepcopy(dict(definition or {})))
        dialog = tk.Toplevel(self.root)
        dialog.title("КЭТ — " + ("изменение" if original_key else "новый контейнер"))
        dialog.transient(self.root)
        dialog.resizable(False, False)

        form = tk.Frame(dialog, padx=10, pady=8)
        form.pack(fill=tk.BOTH, expand=True)

        variables = {}
        row = 0
        for key, label, width in (
                ("code", "Маркировка КЭТ", 26),
                ("name", "Название (кратко)", 46),
                ("description", "Назначение", 56),
                ("functions", "Функции (через запятую)", 56),
                ("source", "Источник (раздел стандарта)", 40)):
            tk.Label(form, text=label, anchor="w").grid(row=row, column=0,
                                                        sticky="w", pady=2)
            value = definition.get(key, "")
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(item) for item in value)
            variable = tk.StringVar(value=str(value))
            tk.Entry(form, textvariable=variable, width=width).grid(
                row=row, column=1, sticky="we", padx=(8, 0), pady=2)
            variables[key] = variable
            row += 1

        # --- нормативный документ ---
        tk.Label(form, text="Нормативный документ", anchor="w").grid(
            row=row, column=0, sticky="w", pady=2)
        standard_labels = ["Прочие (без НД)"]
        standard_keys = [""]
        for standard_key, standard in ketlib.STANDARDS.items():
            standard_keys.append(standard_key)
            standard_labels.append(f'{standard["group"]} — {standard["code"]}')
        current_key = definition.get("standard_key", "")
        current_label = (standard_labels[standard_keys.index(current_key)]
                         if current_key in standard_keys else standard_labels[0])
        standard_variable = tk.StringVar(value=current_label)
        tk.OptionMenu(form, standard_variable, *standard_labels).grid(
            row=row, column=1, sticky="we", padx=(8, 0), pady=2)
        row += 1

        # --- группа ---
        tk.Label(form, text="Группа оборудования", anchor="w").grid(
            row=row, column=0, sticky="w", pady=2)
        current_group = definition.get("group") or "Прочие"
        group_labels = list(ketlib.GROUPS)
        if current_group not in group_labels:
            group_labels.append(current_group)
        group_variable = tk.StringVar(value=current_group)
        tk.OptionMenu(form, group_variable, *group_labels).grid(
            row=row, column=1, sticky="we", padx=(8, 0), pady=2)
        row += 1

        # --- типоразмер и вместимость ---
        size_row = tk.Frame(form)
        size_row.grid(row=row, column=0, columnspan=2, sticky="we", pady=2)
        tk.Label(size_row, text="Типоразмер", anchor="w", width=22).pack(side=tk.LEFT)
        size_labels = [f'{size["code"]} — {size["title"]}'
                       for size in ketlib.SIZES.values()]
        size_keys = list(ketlib.SIZES.keys())
        current_size = definition.get("size") or "20dc"
        size_variable = tk.StringVar(
            value=size_labels[size_keys.index(current_size)]
            if current_size in size_keys else size_labels[0])
        tk.OptionMenu(size_row, size_variable, *size_labels).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        row += 1

        slots_row = tk.Frame(form)
        slots_row.grid(row=row, column=0, columnspan=2, sticky="we", pady=2)
        tk.Label(slots_row, text="Вместимость, шкафов", anchor="w",
                 width=22).pack(side=tk.LEFT)
        slots_variable = tk.StringVar(value=str(definition.get("slots") or 7))
        tk.Spinbox(slots_row, from_=1, to=ketlib.MAX_SLOTS, width=6,
                   textvariable=slots_variable).pack(side=tk.LEFT)
        tk.Label(slots_row, text="    20’DC/20’HC — до 7, 40’ — до 14",
                 fg="#808080", font=("Arial", 8)).pack(side=tk.LEFT)
        row += 1

        # --- состав шкафов ---
        tk.Label(form, text="Состав шкафов в контейнере (привязка к каталогу "
                            "шкафов):", anchor="w").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row += 1

        state = {"cabinets": list(definition.get("cabinets") or [])}
        box = tk.Frame(form)
        box.grid(row=row, column=0, columnspan=2, sticky="we")
        row += 1

        left = tk.Frame(box)
        left.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(left, text="В контейнере", anchor="w",
                 fg="#555555").pack(fill=tk.X)
        composition_list = tk.Listbox(left, width=44, height=9,
                                      activestyle="dotbox", exportselection=False)
        composition_list.pack(fill=tk.BOTH, expand=True)
        composition_buttons = tk.Frame(left)
        composition_buttons.pack(fill=tk.X, pady=(4, 0))
        tk.Button(composition_buttons, text="− Убрать", width=10,
                  command=lambda: remove_cabinet()).pack(side=tk.LEFT)
        tk.Button(composition_buttons, text="↑", width=3,
                  command=lambda: move_cabinet(-1)).pack(side=tk.LEFT, padx=(4, 0))
        tk.Button(composition_buttons, text="↓", width=3,
                  command=lambda: move_cabinet(1)).pack(side=tk.LEFT, padx=(2, 0))

        right = tk.Frame(box, padx=10)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(right, text="Каталог шкафов", anchor="w",
                 fg="#555555").pack(fill=tk.X)

        catalog_filter = tk.Frame(right)
        catalog_filter.pack(fill=tk.X, pady=(0, 2))
        tk.Label(catalog_filter, text="Группа:", font=("Arial", 8)).pack(side=tk.LEFT)
        editor_groups = sorted({cabinet.get("group") or "Прочие"
                                for cabinet in cabs.all_cabinets()})
        editor_group_variable = tk.StringVar(value="Все группы")
        tk.OptionMenu(catalog_filter, editor_group_variable, "Все группы",
                      *editor_groups).pack(side=tk.LEFT, padx=(4, 0))
        editor_search_variable = tk.StringVar()
        tk.Entry(catalog_filter, textvariable=editor_search_variable,
                 width=12).pack(side=tk.LEFT, padx=(6, 0))

        catalog_frame = tk.Frame(right)
        catalog_frame.pack(fill=tk.BOTH, expand=True)
        catalog_list = tk.Listbox(catalog_frame, width=54, height=9,
                                  activestyle="dotbox", exportselection=False)
        catalog_scroll = tk.Scrollbar(catalog_frame, orient="vertical",
                                      command=catalog_list.yview)
        catalog_list.configure(yscrollcommand=catalog_scroll.set)
        catalog_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        catalog_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(right, text="Добавить в контейнер →", width=24,
                  command=lambda: add_cabinet()).pack(anchor="w", pady=(4, 0))

        tk.Label(form, text="Справочный состав по стандарту (только чтение):",
                 anchor="w", fg="#555555").grid(row=row, column=0,
                                                columnspan=2, sticky="w",
                                                pady=(8, 2))
        row += 1
        reference = tk.Text(form, width=96, height=7, wrap="word",
                            font=("Arial", 8), bg="#f7f7f7")
        reference.grid(row=row, column=0, columnspan=2, sticky="we")
        reference.insert("1.0", "\n".join(definition.get("composition") or []))
        reference.config(state="disabled")
        row += 1

        error = tk.Label(form, text="", fg="#b00020", anchor="w")
        error.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        catalog_entries = cabs.all_cabinets()

        def catalog_caption(cabinet):
            group = cabinet.get("group")
            prefix = f"[{group}] " if group else ""
            code = cabinet.get("code")
            name = cabinet.get("name", "Шкаф")
            return (prefix + code + " — " + name) if code else prefix + name

        def cabinet_caption(key):
            found = cabs.find_cabinet(key)
            if found is None:
                return f"⚠ {key} — нет в каталоге шкафов"
            return catalog_caption(found)

        def refresh_composition(select=None):
            composition_list.delete(0, "end")
            for key in state["cabinets"]:
                composition_list.insert("end", cabinet_caption(key))
            if state["cabinets"]:
                index = select if select is not None else 0
                index = max(0, min(index, len(state["cabinets"]) - 1))
                composition_list.selection_clear(0, "end")
                composition_list.selection_set(index)
                composition_list.see(index)

        def add_cabinet(event=None):
            selection = catalog_list.curselection()
            if not selection:
                error.config(text="Выберите шкаф в каталоге.")
                return
            key = state["catalog_visible"][selection[0]].get("key")
            state["cabinets"].append(key)
            error.config(text="")
            refresh_composition(len(state["cabinets"]) - 1)

        def remove_cabinet():
            selection = composition_list.curselection()
            if not selection:
                error.config(text="Выберите шкаф в составе контейнера.")
                return
            del state["cabinets"][selection[0]]
            error.config(text="")
            refresh_composition(max(0, selection[0] - 1) if state["cabinets"] else None)

        def move_cabinet(delta):
            selection = composition_list.curselection()
            if not selection:
                return
            index = selection[0]
            target = index + delta
            if not (0 <= target < len(state["cabinets"])):
                return
            state["cabinets"][index], state["cabinets"][target] = (
                state["cabinets"][target], state["cabinets"][index])
            refresh_composition(target)

        state["catalog_visible"] = list(catalog_entries)

        def refresh_catalog():
            """Перестраивает каталог шкафов с учётом группы и поиска."""
            group = editor_group_variable.get()
            needle = editor_search_variable.get().strip().lower()
            visible = []
            for cabinet in catalog_entries:
                if group != "Все группы" and (cabinet.get("group") or "Прочие") != group:
                    continue
                if needle:
                    haystack = " ".join(str(cabinet.get(field, "")) for field in
                                        ("code", "name", "title", "description",
                                         "group", "source")).lower()
                    if needle not in haystack:
                        continue
                visible.append(cabinet)
            state["catalog_visible"] = visible
            catalog_list.delete(0, "end")
            for cabinet in visible:
                catalog_list.insert("end", catalog_caption(cabinet))

        editor_group_variable.trace_add("write", lambda *args: refresh_catalog())
        editor_search_variable.trace_add("write", lambda *args: refresh_catalog())
        refresh_catalog()

        def on_size_change(label):
            size_key = size_keys[size_labels.index(label)]
            slots_variable.set(str(ketlib.size_slots(size_key)))

        size_variable.trace_add("write", lambda *args: on_size_change(size_variable.get()))

        def split_list(text):
            return [item.strip() for item in text.replace(";", ",").split(",")
                    if item.strip()]

        def accept(event=None):
            name = variables["name"].get().strip()
            if not name:
                error.config(text="Укажите название контейнера.")
                return
            try:
                slots = int(slots_variable.get())
            except ValueError:
                error.config(text="Вместимость должна быть числом.")
                return
            slots = max(1, min(ketlib.MAX_SLOTS, slots))
            size_key = size_keys[size_labels.index(size_variable.get())]
            data = {
                "key": original_key or "",
                "standard_key": standard_keys[standard_labels.index(
                    standard_variable.get())],
                "code": variables["code"].get().strip(),
                "name": name,
                "title": name,
                "description": variables["description"].get().strip() or name,
                "group": group_variable.get(),
                "size": size_key,
                "slots": slots,
                "functions": split_list(variables["functions"].get()),
                "cabinets": list(state["cabinets"]),
                "composition": list(definition.get("composition") or []),
                "source": variables["source"].get().strip(),
            }
            try:
                ketlib.save_container(data, original_key)
            except Exception as exc:
                error.config(text="Не удалось сохранить: {}".format(exc))
                return
            dialog.destroy()
            messagebox.showinfo("Каталог контейнеров",
                                "Контейнер сохранён: {}".format(
                                    data["code"] or data["name"]))

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        dialog.bind("<Escape>", cancel)
        refresh_composition(0)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)

    # ---------- размещение контейнера на схеме ----------
    def _container_label(self, container):
        group = container.get("group")
        prefix = f"[{group}] " if group else ""
        code = container.get("code")
        name = container.get("name", "КЭТ")
        return (prefix + code + " — " + name) if code else prefix + name

    def add_container(self):
        """Добавляет контейнер из каталога КЭТ в центр видимой области."""
        choice = self._choose_container()
        if not choice:
            return
        definition, expand = choice
        self._place_container(definition, expand=expand)

    def _place_container(self, definition, expand=False):
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 50:
            width = 800
        if height < 50:
            height = 700
        wx, wy = self.screen_to_world(width / 2, height / 2)
        wx, wy = self.snap(wx, wy)

        self._push_undo()
        container = library.create_component(
            "container", f"KE{uuid.uuid4().hex[:4]}", wx, wy, self.grid_size)
        container.set_container(definition)
        container.name = self.get_next_name(
            PREFIX_BY_TYPE["container"], "container")
        self.elements[container.id] = container
        self.selected_elements = [container.id]

        placed, missing = (0, [])
        if expand:
            placed, missing = self._expand_container(container, definition)
        self._sync_containers()
        self.current_tool = "select"
        self.canvas.config(cursor="arrow")
        self._mark_active_tool()
        self.redraw_all()

        if expand:
            text = ("Контейнер размещён, привязано шкафов: {}.".format(placed))
            if missing:
                text += ("\nНе найдены в каталоге шкафов: " + ", ".join(missing)
                         + "\nДобавьте их в каталог на вкладке «Шкафы».")
            messagebox.showinfo("Контейнеры", text)
        else:
            # Сразу включаем «Связь КЭТ»: следующий клик по слоту начнёт привязку
            self.set_tool("bind")
            messagebox.showinfo(
                "Контейнер размещён",
                "Режим «Связь КЭТ» включён.\n\n"
                "1. Щёлкните по слоту — точка ● на правой стенке контейнера "
                "(или по строке слота).\n"
                "2. Щёлкните по точке □ на левой грани шкафа.\n\n"
                "Слот соединится со шкафом линией.\n"
                "Ctrl+клик по линии или точке — отвязать.")

    def _choose_container(self):
        """Диалог выбора контейнера из каталога; возвращает (описание, флаг состава)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Контейнер КЭТ")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        tk.Label(dialog,
                 text="Типовые контейнеры КЭТ (архитектура II типа). "
                      "Контейнер привязывает к себе шкафы РЗА:",
                 anchor="w", fg="#555555").pack(fill=tk.X, padx=10, pady=(8, 4))
        container_list = ketlib.all_containers()
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=86,
                             height=max(3, min(16, len(container_list))),
                             activestyle="dotbox")
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for container in container_list:
            listbox.insert("end", self._container_label(container))

        info = tk.Label(dialog, text="", anchor="w", justify="left",
                        fg="#333333", wraplength=640)
        info.pack(fill=tk.X, padx=10, pady=6)

        footer = tk.Label(dialog, text="", anchor="w", fg="#808080",
                          font=("Arial", 7), wraplength=640)
        footer.pack(fill=tk.X, padx=10, pady=(0, 4))

        expand_variable = tk.BooleanVar(value=False)
        expand_check = tk.Checkbutton(
            dialog, text="Разместить шкафы по составу контейнера",
            variable=expand_variable, anchor="w")
        expand_check.pack(fill=tk.X, padx=8)

        result = {"value": None, "expand": False}

        def update_info(event=None):
            selection = listbox.curselection()
            if not selection:
                return
            container = container_list[selection[0]]
            lines = []
            if container.get("description"):
                lines.append(container["description"])
            lines.append("Типоразмер: {} ({}) · {} шкафов".format(
                container.get("size_title", ""), container.get("dimensions", ""),
                container.get("slots")))
            if container.get("functions"):
                lines.append("Функции: " + ", ".join(container["functions"]))
            cabinets = container.get("cabinets") or []
            if cabinets:
                names = []
                for key in cabinets:
                    found = cabs.find_cabinet(key)
                    names.append((found or {}).get("code") or key)
                lines.append("Состав: " + ", ".join(names))
            info.config(text="\n".join(lines))
            if cabinets:
                expand_check.config(
                    state="normal",
                    text=f"Разместить шкафы по составу контейнера "
                         f"({len(cabinets)} шт.)")
            else:
                expand_variable.set(False)
                expand_check.config(
                    state="disabled",
                    text="Состав шкафов не задан — привяжите шкафы вручную")
            footer.config(text="{} · климат {} · {}".format(
                container.get("standard", ""), container.get("climate", ""),
                container.get("source", "")))

        listbox.bind("<<ListboxSelect>>", update_info)
        if container_list:
            listbox.selection_set(0)
            update_info()

        def accept(event=None):
            selection = listbox.curselection()
            if selection:
                result["value"] = container_list[selection[0]]
                result["expand"] = bool(expand_variable.get())
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(4, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Разместить", width=14,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        listbox.bind("<Double-Button-1>", accept)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        self._center_dialog(dialog)
        dialog.wait_window(dialog)
        if not result["value"]:
            return None
        return result["value"], result["expand"]

    def toggle_containers(self):
        self.show_containers = self.show_containers_var.get()
        if not self.show_containers:
            self._bind_start = None
            self.selected_elements = [
                el_id for el_id in self.selected_elements
                if el_id in self.elements and self.elements[el_id].type != "container"
            ]
        self.redraw_all()

    def _containers(self):
        return [el for el in self.elements.values() if el.type == "container"]

    def _selected_container(self):
        if len(self.selected_elements) != 1:
            return None
        element = self.elements.get(self.selected_elements[0])
        if element is not None and element.type == "container":
            return element
        return None

    def _container_of(self, cabinet_id):
        """Контейнер, к которому привязан шкаф (или None)."""
        for container in self._containers():
            if container.slot_of(cabinet_id) is not None:
                return container
        return None

    # ---------- привязка слотов линией ----------
    def _sync_containers(self, elements=None):
        """Обновляет подписи слотов и убирает ссылки на удалённые шкафы."""
        elements = elements if elements is not None else self.elements
        for container in elements.values():
            if container.type != "container":
                continue
            for index in range(container.slot_count()):
                cabinet_id = (container.cabinets[index]
                              if index < len(container.cabinets) else "")
                cabinet = elements.get(cabinet_id) if cabinet_id else None
                if cabinet_id and (cabinet is None or cabinet.type != "cabinet"):
                    container.cabinets[index] = ""
                    cabinet = None
                if cabinet is None:
                    container.set_slot_label(index, "")
                else:
                    title = getattr(cabinet, "title", "") or ""
                    container.set_slot_label(
                        index, "{} · {}".format(cabinet.name, title)
                        if title else str(cabinet.name))

    @staticmethod
    def _cabinet_bind_point(cabinet):
        """Точка привязки шкафа к контейнеру (левая грань, середина)."""
        point = getattr(cabinet, "bind_point", None)
        if callable(point):
            return point()
        bx1, by1, _bx2, by2 = cabinet.get_bounding_box()
        return (bx1, (by1 + by2) / 2.0)

    def _bind_cabinet_at(self, sx, sy):
        """Шкаф под курсором для привязки: сначала точка, потом корпус."""
        if not self.show_cabinets:
            return None
        tolerance = max(8.0, 14.0 * self.zoom)
        best, best_dist = None, tolerance
        for element in self.elements.values():
            if element.type != "cabinet":
                continue
            px, py = self.world_to_screen(*self._cabinet_bind_point(element))
            dist = math.hypot(sx - px, sy - py)
            if dist <= best_dist:
                best, best_dist = element, dist
        if best is not None:
            return best
        element_id = self._element_at(sx, sy)
        element = self.elements.get(element_id) if element_id else None
        if element is not None and element.type == "cabinet":
            return element
        return None

    def _draw_bind_points(self):
        """Квадратики привязки на левой грани шкафов (если есть контейнеры)."""
        if not self.show_containers or not self.show_cabinets:
            return
        if not any(el.type == "container" for el in self.elements.values()):
            return
        r = max(2.5, 3.2 * self.zoom)
        width = max(1, int(1.2 * self.zoom))
        for element in self.elements.values():
            if element.type != "cabinet":
                continue
            px, py = self.world_to_screen(*self._cabinet_bind_point(element))
            bound = self._container_of(element.id) is not None
            self.canvas.create_rectangle(px - r, py - r, px + r, py + r,
                                         fill="#a0522d" if bound else "white",
                                         outline="#a0522d", width=width,
                                         tags="bind_point")

    def _slot_at(self, sx, sy):
        """Ближайший слот контейнера: (id контейнера, номер слота) или None."""
        if not self.show_containers:
            return None
        tolerance = max(8.0, 13.0 * self.zoom)
        best, best_dist = None, tolerance
        for container in self._containers():
            for index in range(container.slot_count()):
                slot_x, slot_y = container.slot_center(index)
                px, py = self.world_to_screen(slot_x, slot_y)
                dist = math.hypot(sx - px, sy - py)
                if dist <= best_dist:
                    best, best_dist = (container.id, index), dist
        if best is not None:
            return best
        # Клик по самой строке слота тоже годится: попасть в точку на стенке
        # при мелком масштабе неудобно.
        for container in self._containers():
            for index in range(container.slot_count()):
                left, top, right, bottom = container.slot_rect(index)
                rx1, ry1 = self.world_to_screen(left, top)
                rx2, ry2 = self.world_to_screen(right, bottom)
                if rx1 <= sx <= rx2 and ry1 <= sy <= ry2:
                    return (container.id, index)
        return None

    def _container_link_segment(self, container, index, cabinet):
        """Отрезок линии привязки в экранных координатах: слот → шкаф."""
        slot_x, slot_y = container.slot_center(index)
        end_x, end_y = self._cabinet_bind_point(cabinet)
        return (self.world_to_screen(slot_x, slot_y),
                self.world_to_screen(end_x, end_y))

    def _container_link_at(self, sx, sy):
        """Линия привязки под курсором: (id контейнера, номер слота) или None."""
        if not self.show_containers:
            return None
        tolerance = max(4.0, 5.0 * self.zoom)
        for container in self._containers():
            for index in range(container.slot_count()):
                cabinet_id = (container.cabinets[index]
                              if index < len(container.cabinets) else "")
                cabinet = self.elements.get(cabinet_id) if cabinet_id else None
                if cabinet is None or cabinet.type != "cabinet":
                    continue
                (x1, y1), (x2, y2) = self._container_link_segment(
                    container, index, cabinet)
                if self._point_segment_distance(sx, sy, x1, y1, x2, y2) <= tolerance:
                    return (container.id, index)
        return None

    def _draw_container_links(self):
        """Линии привязки слот → шкаф и подсветка начатой привязки."""
        if not self.show_containers:
            return
        color = "#a0522d"
        width = max(1, int(1.5 * self.zoom))
        radius = max(2.0, 2.5 * self.zoom)
        for container in self._containers():
            for index in range(container.slot_count()):
                cabinet_id = (container.cabinets[index]
                              if index < len(container.cabinets) else "")
                cabinet = self.elements.get(cabinet_id) if cabinet_id else None
                if cabinet is None or cabinet.type != "cabinet":
                    continue
                (x1, y1), (x2, y2) = self._container_link_segment(
                    container, index, cabinet)
                self.canvas.create_line(x1, y1, x2, y2, fill=color,
                                        width=width, tags="container_link")
                self.canvas.create_oval(x1 - radius, y1 - radius,
                                        x1 + radius, y1 + radius,
                                        fill=color, outline="white",
                                        tags="container_link")

        if self._bind_start is not None:
            kind, first, index = self._bind_start
            point = None
            if kind == "slot":
                container = self.elements.get(first)
                if container is not None:
                    point = container.slot_center(index)
            else:
                cabinet = self.elements.get(first)
                if cabinet is not None:
                    point = (cabinet.x, cabinet.y)
            if point is not None:
                px, py = self.world_to_screen(*point)
                r = max(4.0, 6.0 * self.zoom)
                self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                        outline="red", width=2,
                                        tags="container_link_start")

    @staticmethod
    def _ctrl_click(event):
        """Ctrl (Command на macOS) удерживается при клике."""
        try:
            state = int(event.state)
        except (TypeError, ValueError, AttributeError):
            return False
        mask = 0x0004
        if sys.platform == "darwin":
            mask |= 0x0008 | 0x0010
        return bool(state & mask)

    def _show_toast(self, text, event=None, duration=2400):
        """Короткая подсказка на схеме (без модального окна)."""
        canvas = self.canvas
        canvas.delete("toast")
        if getattr(self, "_toast_job", None) is not None:
            try:
                self.root.after_cancel(self._toast_job)
            except Exception:
                pass
            self._toast_job = None
        if event is not None:
            x, y = event.x + 16, event.y + 20
        else:
            x, y = 24, 24
        item = canvas.create_text(x + 9, y + 7, text=text, anchor="nw",
                                  font=("Arial", 8), fill="#333333",
                                  tags="toast")
        left, top, right, bottom = canvas.bbox(item)
        frame = canvas.create_rectangle(left - 9, top - 7, right + 9,
                                        bottom + 7, fill="#fffde7",
                                        outline="#c8b560", tags="toast")
        canvas.tag_lower(frame, item)
        # не даём подсказке уехать за край окна
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if right + 9 > width:
            canvas.move("toast", width - (right + 9) - 4, 0)
        if bottom + 7 > height:
            canvas.move("toast", 0, height - (bottom + 7) - 4)
        self._toast_job = self.root.after(duration, self._clear_toast)

    def _clear_toast(self):
        self.canvas.delete("toast")
        self._toast_job = None

    def _hint_ctrl_delete(self, title, what, event=None):
        """Подсказка: удаление связи — только Ctrl+клик."""
        self._show_toast("Ctrl+клик — {}".format(what), event)

    def _on_bind_click(self, event):
        """Клик в режиме «Привязка»: слот ↔ шкаф, клик по линии — отвязка."""
        if not self.show_containers:
            messagebox.showinfo(
                "Контейнеры", "Контейнеры скрыты — включите их на вкладке «Вид».")
            return

        slot = self._slot_at(event.x, event.y)
        cabinet = self._bind_cabinet_at(event.x, event.y)
        ctrl = self._ctrl_click(event)

        # Отвязка — только Ctrl+клик: по линии или по её концам-точкам.
        if slot is None and cabinet is None and self._bind_start is None:
            link = self._container_link_at(event.x, event.y)
            if link is not None:
                if not ctrl:
                    self._hint_ctrl_delete("Контейнеры",
                                           "отвязать шкаф от слота", event)
                    return
                container = self.elements.get(link[0])
                if container is not None:
                    self._push_undo()
                    container.cabinets[link[1]] = ""
                    self._sync_containers()
                    self.redraw_all()
                return

        if ctrl and self._bind_start is None:
            # Ctrl+клик по занятому слоту или привязанному шкафу — отвязка
            if slot is not None:
                container = self.elements.get(slot[0])
                if container is not None and container.cabinets[slot[1]]:
                    self._push_undo()
                    container.cabinets[slot[1]] = ""
                    self._sync_containers()
                    self.redraw_all()
                    return
            if cabinet is not None:
                container = self._container_of(cabinet.id)
                if container is not None:
                    self._push_undo()
                    container.unbind(cabinet.id)
                    self._sync_containers()
                    self.redraw_all()
                    return

        if self._bind_start is None:
            if slot is not None:
                container = self.elements.get(slot[0])
                if container is not None and container.cabinets[slot[1]]:
                    # занятый слот: привязку не сдвигаем, удаление — Ctrl+клик
                    self._hint_ctrl_delete("Контейнеры",
                                           "отвязать шкаф от слота", event)
                    return
                self._bind_start = ("slot", slot[0], slot[1])
            elif cabinet is not None:
                self._bind_start = ("cabinet", cabinet.id, None)
            self.redraw_all()
            return

        kind, first, index = self._bind_start
        if kind == "slot" and cabinet is not None:
            self._bind_cabinet_slot(first, index, cabinet.id)
        elif kind == "cabinet" and slot is not None:
            self._bind_cabinet_slot(slot[0], slot[1], first)
        elif kind == "slot" and slot is not None:
            # повторный клик по другому слоту переносит начало привязки
            self._bind_start = ("slot", slot[0], slot[1])
            self.redraw_all()
            return
        elif kind == "cabinet" and cabinet is not None:
            self._bind_start = ("cabinet", cabinet.id, None)
            self.redraw_all()
            return
        self._bind_start = None
        self.redraw_all()

    def _bind_cabinet_slot(self, container_id, index, cabinet_id):
        """Привязывает шкаф к конкретному слоту контейнера."""
        container = self.elements.get(container_id)
        cabinet = self.elements.get(cabinet_id)
        if container is None or container.type != "container":
            return
        if cabinet is None or cabinet.type != "cabinet":
            return
        self._push_undo()
        # шкаф может быть привязан только к одному контейнеру
        for other in self._containers():
            if other.id != container.id:
                other.unbind(cabinet_id)
        container.bind_slot(cabinet_id, index)
        self.selected_elements = [container.id]
        self._sync_containers()
        self.redraw_all()

    def _place_beside_slot(self, container, index, cabinet, gap=14.0, dx=160.0):
        """Ставит шкаф справа от контейнера — напротив его слота."""
        _slot_x, slot_y = container.slot_center(index)
        right = container.get_bounding_box()[2]
        _bx1, by1, _bx2, by2 = cabinet.get_bounding_box()
        height = by2 - by1
        x = right + dx + library.Cabinet.WIDTH / 2.0
        y = slot_y

        spans = []
        for other_id in container.bound_ids():
            other = self.elements.get(other_id)
            if other is None or other.id == cabinet.id:
                continue
            bounds = other.get_bounding_box()
            spans.append((bounds[1], bounds[3]))
        for _attempt in range(40):
            clashes = [span for span in spans
                       if not (y + height / 2.0 + gap <= span[0]
                               or y - height / 2.0 - gap >= span[1])]
            if not clashes:
                break
            y = max(span[1] for span in clashes) + height / 2.0 + gap

        cabinet.x, cabinet.y = x, y
        cabinet.generate_ports()

    def _auto_bind_cabinet(self, cabinet, container=None):
        """Привязывает только что добавленный шкаф к выбранному контейнеру."""
        if container is None:
            container = self._selected_container()
        if container is None:
            return False
        index = container.free_slot()
        if index is None:
            return False
        container.bind_slot(cabinet.id, index)
        self._place_beside_slot(container, index, cabinet)
        self._sync_containers()
        return True

    def _container_label_from_element(self, container):
        title = container.info.get("name") or container.title or "КЭТ"
        return f"{container.name} — {container.code} — {title}"

    def expand_container_by_composition(self):
        """Размещает в контейнере шкафы по составу из каталога КЭТ."""
        target = self._selected_container()
        if target is None:
            containers = self._containers()
            if not containers:
                messagebox.showinfo(
                    "Контейнеры",
                    "На схеме нет контейнеров.\nДобавьте контейнер кнопкой "
                    "«Контейнер…» на вкладке «Контейнеры».")
                return
            keys = self._pick_from_list(
                "Состав КЭТ",
                "Для какого контейнера разместить шкафы по составу?",
                [(el.id, self._container_label_from_element(el))
                 for el in containers], accept_text="Выбрать")
            if not keys:
                return
            target = self.elements.get(keys[0])
            if target is None:
                return

        definition = ketlib.find_container(target.container_key)
        if definition is None:
            messagebox.showinfo(
                "Контейнеры",
                "Для этого контейнера нет описания в каталоге КЭТ — "
                "состав шкафов неизвестен.")
            return
        cabinets = definition.get("cabinets") or []
        if not cabinets:
            messagebox.showinfo(
                "Контейнеры",
                f"В каталоге для «{definition.get('code')}» состав шкафов "
                "не задан.\nПривяжите слоты линиями: инструмент «Привязка».")
            return

        self._push_undo()
        placed, missing = self._expand_container(target, definition)
        self._sync_containers()
        self.selected_elements = [target.id]
        self.redraw_all()

        text = (f"Контейнер «{target.code}»: привязано шкафов {placed} "
                f"из {len(cabinets)}.")
        if missing:
            text += ("\nНе найдены в каталоге шкафов: "
                     + ", ".join(missing)
                     + "\nДобавьте их на вкладке «Шкафы».")
        messagebox.showinfo("Контейнеры", text)

    def _expand_container(self, container, definition):
        """Создаёт шкафы по составу контейнера и привязывает их к слотам."""
        placed = 0
        missing = []
        for key in definition.get("cabinets") or []:
            index = container.free_slot()
            if index is None:
                break
            cabinet_definition = cabs.find_cabinet(key)
            if cabinet_definition is None:
                missing.append(key)
                continue
            cabinet = library.create_component(
                "cabinet", f"CA{uuid.uuid4().hex[:4]}",
                container.x, container.y, self.grid_size)
            cabinet.set_cabinet(cabinet_definition)
            cabinet.name = self.get_next_name(
                PREFIX_BY_TYPE["cabinet"], "cabinet")
            self.elements[cabinet.id] = cabinet
            container.bind_slot(cabinet.id, index)
            self._place_beside_slot(container, index, cabinet)
            placed += 1
        self._sync_containers()
        return placed, missing


    def _zoom_step(self, factor):
        w = self.canvas.winfo_width() or 800
        h = self.canvas.winfo_height() or 700
        mx, my = self.screen_to_world(w / 2, h / 2)
        new_zoom = self.zoom * factor
        if 0.08 < new_zoom < 5.0:
            self.zoom = new_zoom
            self.offset_x = w / 2 - mx * self.zoom
            self.offset_y = h / 2 - my * self.zoom
            self.redraw_all()
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")

    # ================= ПОДЛОЖКА PDF =================
    def toggle_underlay(self):
        self.show_underlay = self.underlay_visible_var.get()
        self.redraw_all()

    def change_underlay_scale(self):
        try:
            value = float(self.underlay_spin.get().replace(",", "."))
        except ValueError:
            value = self.underlay_scale
        self.underlay_scale = max(0.2, min(5.0, value))
        self.underlay_spin.delete(0, "end")
        self.underlay_spin.insert(0, f"{self.underlay_scale:g}")
        self.redraw_all()

    def _read_underlay(self, filepath):
        """Читает PDF и подписи, возвращает структуру подложки (без изменения состояния)."""
        width, height, lines = pdfunderlay.load_pdf(filepath)
        labels = []
        if pdf2json is not None:
            try:
                tool = pdf2json.find_pdftotext()
                if tool:
                    words = pdf2json.extract_words(filepath, tool)
                    for label in pdf2json.group_labels(words):
                        labels.append((label["text"], label["x1"], label["cy"]))
            except Exception:
                labels = []
        return {
            "path": filepath,
            "width": width,
            "height": height,
            "lines": lines,
            "labels": labels,
        }

    def load_underlay(self, event=None):
        filepath = filedialog.askopenfilename(
            title="Выберите PDF для подложки",
            filetypes=[("PDF files", "*.pdf")])
        if not filepath:
            return
        try:
            self.underlay = self._read_underlay(filepath)
        except Exception as error:
            messagebox.showerror("Подложка", f"Не удалось прочитать PDF:\n{error}")
            return

        self.show_underlay = True
        if hasattr(self, "underlay_visible_var"):
            self.underlay_visible_var.set(True)
            self._refresh_ribbon_toggles()
        self._underlay_needs_fit = True
        self.root.update_idletasks()
        if self.canvas.winfo_width() > 50 and self.canvas.winfo_height() > 50:
            self._underlay_needs_fit = False
            self._fit_view_to_underlay()
        else:
            # окно ещё не разложено — подгоним при первом Configure
            self.redraw_all()
        messagebox.showinfo(
            "Подложка",
            f"Загружено: {os.path.basename(filepath)}\n"
            f"линий: {len(self.underlay['lines'])}, подписей: {len(self.underlay['labels'])}\n"
            f"масштаб подложки: {self.underlay_scale:g}")

    def _restore_underlay(self, info, base_dir=None):
        """Восстанавливает подложку из JSON схемы."""
        path = info.get("path")
        if not path:
            return
        if not os.path.isabs(path):
            path = os.path.join(base_dir or os.getcwd(), path)
        path = os.path.abspath(path)
        try:
            self.underlay_scale = float(info.get("scale", self.underlay_scale))
        except (TypeError, ValueError):
            pass
        self.show_underlay = bool(info.get("visible", True))

        if not os.path.exists(path):
            self.underlay = None
            messagebox.showwarning(
                "Подложка",
                f"Файл подложки не найден:\n{path}\nСхема открыта без подложки.")
            return

        try:
            self.underlay = self._read_underlay(path)
        except Exception as error:
            self.underlay = None
            messagebox.showwarning(
                "Подложка", f"Не удалось прочитать подложку:\n{error}")
            return

        if hasattr(self, "underlay_visible_var"):
            self.underlay_visible_var.set(self.show_underlay)
        if hasattr(self, "underlay_spin"):
            self.underlay_spin.delete(0, "end")
            self.underlay_spin.insert(0, f"{self.underlay_scale:g}")
        self._refresh_ribbon_toggles()

    def _on_canvas_resize(self, event=None):
        """Перерисовка при изменении размера; первая — с подгонкой подложки."""
        if self._underlay_needs_fit and self.underlay:
            if self.canvas.winfo_width() > 50 and self.canvas.winfo_height() > 50:
                self._underlay_needs_fit = False
                self._fit_view_to_underlay()
                return
        self.redraw_all()

    def _fit_view_to_underlay(self):
        """Подгоняет вид под загруженную подложку."""
        if not self.underlay:
            return
        w = self.canvas.winfo_width() or 800
        h = self.canvas.winfo_height() or 700
        pw = self.underlay["width"] * self.underlay_scale
        ph = self.underlay["height"] * self.underlay_scale
        if pw <= 0 or ph <= 0:
            return
        self.zoom = max(0.08, min(5.0, min(w / pw, h / ph) * 0.95))
        self.offset_x = (w - pw * self.zoom) / 2
        self.offset_y = (h - ph * self.zoom) / 2
        self.redraw_all()
        if hasattr(self, "zoom_label"):
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")

    def clear_underlay(self, event=None):
        if self.underlay is None:
            return
        self.underlay = None
        self.redraw_all()

    def _draw_underlay(self):
        """Рисует подложку под сеткой: линии серым, подписи — мелким шрифтом."""
        if not self.underlay or not self.show_underlay:
            return
        zoom = self.zoom
        scale = self.underlay_scale
        ox, oy = self.offset_x, self.offset_y
        line_width = max(1, int(zoom))

        for points in self.underlay["lines"]:
            coords = []
            for x, y in points:
                coords.append(x * scale * zoom + ox)
                coords.append(y * scale * zoom + oy)
            self.canvas.create_line(*coords, fill="#9a9a9a",
                                    width=line_width, tags="underlay")

        if scale * zoom >= 0.55:
            font = ("Arial", max(1, int(5 * scale * zoom)))
            for text, x, y in self.underlay["labels"]:
                self.canvas.create_text(x * scale * zoom + ox,
                                        y * scale * zoom + oy,
                                        text=text, anchor="w",
                                        fill="#a8a8a8", font=font,
                                        tags="underlay")

    # ================= ЗАЩИТА: ШКАФЫ, КОМПЛЕКТЫ И СВЯЗИ РЗА =================
    def toggle_protection(self):
        self.show_protection = self.show_protection_var.get()
        if not self.show_protection:
            self._protection_start = None
        self.redraw_all()

    def toggle_cabinets(self):
        self.show_cabinets = self.show_cabinets_var.get()
        if not self.show_cabinets:
            self._protection_start = None
            # скрытый шкаф нельзя случайно удалить — снимаем его с выделения
            self.selected_elements = [
                eid for eid in self.selected_elements
                if eid in self.elements and self.elements[eid].type != "cabinet"
            ]
        self.redraw_all()

    def add_cabinet(self):
        """Добавляет шкаф из каталога cabs.py в центр видимой области.

        Если на схеме выбран контейнер, новый шкаф сразу привязывается к нему.
        """
        # контейнер запоминаем до выбора шкафа: выделение сменится на шкаф
        target_container = self._selected_container()
        definition = self._choose_cabinet()
        if not definition:
            return
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 50:
            width = 800
        if height < 50:
            height = 700
        wx, wy = self.screen_to_world(width / 2, height / 2)
        wx, wy = self.snap(wx, wy)

        self._push_undo()
        cabinet = library.create_component("cabinet", f"CA{uuid.uuid4().hex[:4]}",
                                           wx, wy, self.grid_size)
        cabinet.set_cabinet(definition)
        cabinet.name = self.get_next_name(
            PREFIX_BY_TYPE["cabinet"], "cabinet")
        self.elements[cabinet.id] = cabinet
        self.selected_elements = [cabinet.id]
        # Выбран контейнер — новый шкаф сразу встаёт в его свободный слот
        bound = self._auto_bind_cabinet(cabinet, target_container)
        self.current_tool = "select"
        self.canvas.config(cursor="arrow")
        self._mark_active_tool()
        self.redraw_all()
        if bound and target_container is not None:
            self.selected_elements = [target_container.id]

    def _choose_cabinet(self):
        """Диалог выбора шкафа из cabs.py."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Шкаф РЗА")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        tk.Label(dialog,
                 text="Типовые шкафы ШЭТ по СТО ПАО «ФСК ЕЭС» — Т/АТ, СКРМ, "
                      "ЛЭП, СШ, ПА, УПАСК, ПДС, КЭТ (архитектура II типа):",
                 anchor="w", fg="#555555").pack(fill=tk.X, padx=10, pady=(8, 4))
        cabinet_list = cabs.all_cabinets()

        filters = tk.Frame(dialog)
        filters.pack(fill=tk.X, padx=10, pady=(0, 4))
        tk.Label(filters, text="Группа:").pack(side=tk.LEFT)
        groups = sorted({cabinet.get("group") or "Прочие"
                         for cabinet in cabinet_list})
        group_variable = tk.StringVar(value="Все группы")
        tk.OptionMenu(filters, group_variable, "Все группы",
                      *groups).pack(side=tk.LEFT, padx=(6, 12))
        tk.Label(filters, text="Поиск:").pack(side=tk.LEFT)
        search_variable = tk.StringVar()
        tk.Entry(filters, textvariable=search_variable, width=24).pack(
            side=tk.LEFT, padx=(6, 0))

        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=78, height=16, activestyle="dotbox")
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def cabinet_label(cabinet):
            group = cabinet.get("group")
            prefix = f"[{group}] " if group else ""
            code = cabinet.get("code")
            name = cabinet.get("name", "Шкаф")
            return f"{prefix}{code} — {name}" if code else prefix + name

        state = {"visible": list(cabinet_list)}

        info = tk.Label(dialog, text="", anchor="w", justify="left",
                        fg="#333333", wraplength=620)
        info.pack(fill=tk.X, padx=10, pady=6)

        footer = tk.Label(dialog, text="", anchor="w", fg="#808080",
                          font=("Arial", 7), wraplength=620)
        footer.pack(fill=tk.X, padx=10, pady=(0, 6))

        result = {"value": None}

        def update_info(event=None):
            selection = listbox.curselection()
            if not selection:
                return
            cabinet = state["visible"][selection[0]]
            lines = []
            if cabinet.get("description"):
                lines.append(cabinet["description"])
            if cabinet.get("standard_title"):
                lines.append(f'Стандарт: {cabinet["standard_title"]} '
                             f'({cabinet.get("standard")})')
            if cabinet.get("voltage"):
                lines.append(f'Напряжение: {cabinet["voltage"]}')
            if cabinet.get("protected"):
                lines.append(f'Защищаемый элемент: {cabinet["protected"]}')
            if cabinet.get("controlled"):
                lines.append("Управляемые: " + ", ".join(cabinet["controlled"]))
            if cabinet.get("its_functions"):
                lines.append("Функции ИТС: " + ", ".join(cabinet["its_functions"]))
            komplekt_parts = []
            for index, komplekt in enumerate(cabinet.get("komplets", [])):
                functions = ", ".join(komplekt.get("functions", []))
                name = komplekt.get("name") or f"Комплект {index + 1}"
                name = "{} · {}".format(name,
                                        komplekts.kind_title(komplekt))
                ieds = komplekts.effective_ieds(komplekt)
                if ieds:
                    names = ", ".join(ied.get("name", "") for ied in ieds)
                    name = f"{name} (ИЭУ: {names})"
                if komplekts.has_test_blocks(komplekt):
                    name += " [БИ {}]".format(
                        komplekts.test_blocks_text(komplekt, compact=True))
                komplekt_parts.append(name + (f" — {functions}" if functions else ""))
            if komplekt_parts:
                lines.append("Комплекты: " + "; ".join(komplekt_parts))
            if cabinet.get("applicability"):
                lines.append(f'Применимость: {cabinet["applicability"]}')
            if cabinet.get("source"):
                lines.append(f'Источник: {cabinet["source"]}')
            info.config(text="\n".join(lines))

            standard = cabs.standard_for(cabinet)
            if standard:
                footer.config(text="{} · габариты {} · порты {}".format(
                    standard["code"], standard["dimensions"],
                    ", ".join(standard["ports"])))
            else:
                footer.config(text="Произвольный шкаф · типовые НКУ: габариты {} · "
                                   "порты {}".format(cabs.STANDARD["dimensions"],
                                                     ", ".join(cabs.STANDARD["ports"])))

        def refresh_list(select=0):
            """Перестраивает список с учётом группы и строки поиска."""
            group = group_variable.get()
            needle = search_variable.get().strip().lower()
            visible = []
            for cabinet in cabinet_list:
                if group != "Все группы" and (cabinet.get("group") or "Прочие") != group:
                    continue
                if needle:
                    haystack = " ".join(str(cabinet.get(field, "")) for field in
                                        ("code", "name", "title", "description",
                                         "group", "source")).lower()
                    if needle not in haystack:
                        continue
                visible.append(cabinet)
            state["visible"] = visible
            listbox.delete(0, "end")
            for cabinet in visible:
                listbox.insert("end", cabinet_label(cabinet))
            if visible:
                index = max(0, min(select, len(visible) - 1))
                listbox.selection_set(index)
                listbox.activate(index)
                listbox.see(index)
                update_info()
            else:
                info.config(text="Ничего не найдено — измените группу или запрос.")
                footer.config(text="")

        listbox.bind("<<ListboxSelect>>", update_info)
        group_variable.trace_add("write", lambda *args: refresh_list(0))
        search_variable.trace_add("write", lambda *args: refresh_list(0))
        refresh_list(0)

        def accept(event=None):
            selection = listbox.curselection()
            if selection:
                result["value"] = state["visible"][selection[0]]
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Button(buttons, text="Отмена", width=10, command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Добавить", width=12, command=accept).pack(side=tk.RIGHT, padx=(0, 6))

        listbox.bind("<Double-Button-1>", accept)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 4)
        dialog.geometry(f"+{x}+{y}")
        try:
            dialog.grab_set()
        except tk.TclError:
            pass
        dialog.wait_window(dialog)
        return result["value"]

    # ---------------------------------------------------------- связи
    def _komplekt_port_at(self, sx, sy):
        """Ближайший порт комплекта на шкафах: (id шкафа, имя порта)."""
        tolerance = max(6.0, 12.0 * self.zoom)
        best = None
        best_dist = tolerance
        for element in self.elements.values():
            if element.type != "cabinet":
                continue
            if not self.show_cabinets:
                continue
            for port_name, port in element.ports.items():
                if not (port_name.startswith("komplekt") or port_name.startswith("ied")):
                    continue
                px, py = self.world_to_screen(port["x"], port["y"])
                dist = math.hypot(sx - px, sy - py)
                if dist <= best_dist:
                    best_dist = dist
                    best = (element.id, port_name)
        return best

    @staticmethod
    def _link_ref(link):
        """Ссылка «шкаф#комплект» (с поддержкой старых файлов)."""
        return link.get("komplekt") or link.get("ied") or ""

    @staticmethod
    def _port_index(port_name):
        for prefix in ("komplekt", "ied"):
            if port_name.startswith(prefix):
                return port_name[len(prefix):]
        return ""

    def _komplekt_port(self, cabinet, index):
        return (cabinet.ports.get(f"komplekt{index}")
                or cabinet.ports.get(f"ied{index}"))

    def _protection_link_at(self, sx, sy):
        if not self.show_protection or not self.show_cabinets:
            return None
        tolerance = max(4.0, 5.0 * self.zoom)
        for link in self.protection_links:
            cabinet_id, _, index = self._link_ref(link).partition("#")
            cabinet = self.elements.get(cabinet_id)
            element = self.elements.get(link["element"])
            if not cabinet or not element:
                continue
            port = self._komplekt_port(cabinet, index)
            if not port:
                continue
            x1, y1 = self.world_to_screen(port["x"], port["y"])
            x2, y2 = self.world_to_screen(element.x, element.y)
            if self._point_segment_distance(sx, sy, x1, y1, x2, y2) <= tolerance:
                return link
        return None

    def _on_protection_click(self, event):
        """Клик в режиме «Связь РЗА»: комплект → защитный узел (или наоборот)."""
        komplekt = self._komplekt_port_at(event.x, event.y)

        # Линию удаляем только Ctrl+кликом и только когда под курсором
        # нет порта комплекта или элемента: иначе конец стрелки перекрывал бы
        # точку, с которой начинают следующую связь.
        if (self._protection_start is None and komplekt is None
                and not self._element_at(event.x, event.y)):
            link = self._protection_link_at(event.x, event.y)
            if link is not None:
                if not self._ctrl_click(event):
                    self._hint_ctrl_delete("Связь РЗА", "удалить связь РЗА",
                                           event)
                    return
                self._push_undo()
                self.protection_links.remove(link)
                self.redraw_all()
                return
        if komplekt is not None:
            cabinet_id, port_name = komplekt
            if self._protection_start is None:
                self._protection_start = ("komplekt", cabinet_id, port_name)
            elif self._protection_start[0] == "element":
                self._add_protection_link(
                    f"{cabinet_id}#{self._port_index(port_name)}",
                    self._protection_start[1])
                self._protection_start = None
            else:
                self._protection_start = None
            self.redraw_all()
            return

        element_id = self._element_at(event.x, event.y)
        if element_id:
            element = self.elements.get(element_id)
            if element and element.type != "cabinet":
                if self._protection_start is None:
                    self._protection_start = ("element", element_id)
                elif self._protection_start[0] == "komplekt":
                    _, cabinet_id, port_name = self._protection_start
                    self._add_protection_link(
                        f"{cabinet_id}#{self._port_index(port_name)}", element_id)
                    self._protection_start = None
                else:
                    self._protection_start = None
                self.redraw_all()
                return

        if self._protection_start is not None:
            self._protection_start = None
            self.redraw_all()

    def _add_protection_link(self, komplekt_ref, element_id):
        cabinet_id, _, index = komplekt_ref.partition("#")
        cabinet = self.elements.get(cabinet_id)
        element = self.elements.get(element_id)
        if not cabinet or cabinet.type != "cabinet" or not element:
            return
        if not self._komplekt_port(cabinet, index):
            return
        for link in self.protection_links:
            if self._link_ref(link) == komplekt_ref and link["element"] == element_id:
                return
        self._push_undo()
        self.protection_links.append({"komplekt": komplekt_ref, "element": element_id})

    def _draw_protection(self):
        """Защитные узлы на оборудовании и стрелки комплект → узел."""
        if not self.show_protection:
            return
        node_r = max(3.0, 4.5 * self.zoom)
        for element in self.elements.values():
            if element.type in ("cabinet", "container", "corner", "node",
                                "bushing_monitor"):
                continue
            x, y = self.world_to_screen(element.x, element.y)
            self.canvas.create_polygon(
                x, y - node_r, x + node_r, y, x, y + node_r, x - node_r, y,
                fill="#1f4e79", outline="white",
                width=1, tags="protection_node")

        if self.show_cabinets:
            for link in self.protection_links:
                cabinet_id, _, index = self._link_ref(link).partition("#")
                cabinet = self.elements.get(cabinet_id)
                element = self.elements.get(link["element"])
                if not cabinet or not element or cabinet.type != "cabinet":
                    continue
                port = self._komplekt_port(cabinet, index)
                if not port:
                    continue
                x1, y1 = self.world_to_screen(port["x"], port["y"])
                x2, y2 = self.world_to_screen(element.x, element.y)
                self.canvas.create_line(x1, y1, x2, y2, fill="#1f4e79",
                                        width=max(1, int(1.5 * self.zoom)),
                                        arrow=tk.LAST, tags="protection_link")

        if self._protection_start is not None:
            if self._protection_start[0] == "komplekt":
                _, cabinet_id, port_name = self._protection_start
                cabinet = self.elements.get(cabinet_id)
                port = cabinet.ports.get(port_name) if cabinet else None
                if port:
                    px, py = self.world_to_screen(port["x"], port["y"])
                    r = max(4.0, 6.0 * self.zoom)
                    self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                            outline="red", width=2, tags="protection_start")
            else:
                element = self.elements.get(self._protection_start[1])
                if element:
                    px, py = self.world_to_screen(element.x, element.y)
                    r = max(4.0, 6.0 * self.zoom)
                    self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                            outline="red", width=2, tags="protection_start")

    # ================= АНАЛОГОВЫЕ ЦЕПИ (КОМПЛЕКТ ↔ ТТ/ТН ИЛИ КОМПЛЕКТ) =========
    # Связь аналоговых цепей — направленная: у каждого комплекта шкафа есть
    # порт «AI» на левой грани, от него фиолетовая линия со стрелкой идёт
    # к трансформатору тока/напряжения или к комплекту другого шкафа, где
    # эти цепи резервируются. Электрической связью (connections) не является.
    ANALOG_COLOR = "#7b1fa2"
    ANALOG_TARGET_TYPES = ("current_transformer", "voltage_transformer",
                           "bushing_monitor")

    def toggle_analog(self):
        self.show_analog = self.show_analog_var.get()
        if not self.show_analog:
            self._analog_start = None
        self.redraw_all()

    @staticmethod
    def _split_ref(ref):
        """«id#3» → (id, 3); «id» → (id, None)."""
        element_id, sep, index = str(ref or "").partition("#")
        if sep and index.isdigit():
            return element_id, int(index)
        return element_id, None

    def _analog_ref_point(self, ref):
        """Мировая точка конца связи: порт комплекта или центр ТТ/ТН."""
        element_id, index = self._split_ref(ref)
        element = self.elements.get(element_id)
        if element is None:
            return None
        if index is not None and element.type == "cabinet":
            point = getattr(element, "analog_point", None)
            if callable(point):
                return point(index)
        return (element.x, element.y)

    def _analog_ports(self):
        """Порты аналоговых цепей всех комплектов: (шкаф, номер, точка)."""
        for element in self.elements.values():
            if element.type != "cabinet":
                continue
            for index in range(len(getattr(element, "komplets", []))):
                yield element, index, self._analog_ref_point(
                    "{}#{}".format(element.id, index))

    def _analog_port_at(self, sx, sy):
        """Ближайший порт «AI» комплекта: (id шкафа, номер комплекта)."""
        if not self.show_cabinets:
            return None
        tolerance = max(8.0, 12.0 * self.zoom)
        best, best_dist = None, tolerance
        for cabinet, index, point in self._analog_ports():
            if point is None:
                continue
            px, py = self.world_to_screen(*point)
            dist = math.hypot(sx - px, sy - py)
            if dist <= best_dist:
                best, best_dist = (cabinet.id, index), dist
        return best

    def _analog_equipment_at(self, sx, sy):
        """ТТ или ТН под курсором — источник аналоговых цепей."""
        element_id = self._element_at(sx, sy)
        element = self.elements.get(element_id) if element_id else None
        if element is not None and element.type in self.ANALOG_TARGET_TYPES:
            return element
        return None

    def _analog_link_at(self, sx, sy):
        """Связь аналоговых цепей под курсором (для удаления кликом)."""
        if not self.show_analog:
            return None
        tolerance = max(6.0, 7.0 * self.zoom)
        best = None
        best_distance = None
        for link in self.analog_links:
            start = self._analog_ref_point(link.get("from"))
            end = self._analog_ref_point(link.get("to"))
            if start is None or end is None:
                continue
            x1, y1 = self.world_to_screen(*start)
            x2, y2 = self.world_to_screen(*end)
            distance = self._point_segment_distance(sx, sy, x1, y1, x2, y2)
            if distance <= tolerance and (best_distance is None
                                          or distance < best_distance):
                best, best_distance = link, distance
        return best

    def _on_analog_click(self, event):
        """Клик в режиме «Аналоговые цепи»: комплект ↔ ТТ/ТН или комплект."""
        if not self.show_analog:
            messagebox.showinfo(
                "Аналоговые цепи",
                "Линии аналоговых цепей скрыты — включите их на вкладке «Вид».")
            return

        port = self._analog_port_at(event.x, event.y)
        equipment = self._analog_equipment_at(event.x, event.y)

        if self._analog_start is None:
            link = self._analog_link_at(event.x, event.y)
            if link is not None and port is None and equipment is None:
                if not self._ctrl_click(event):
                    self._hint_ctrl_delete(
                        "Аналоговые цепи",
                        "удалить связь (двойной клик — свойства)", event)
                    return
                self._push_undo()
                self.analog_links.remove(link)
                self.redraw_all()
                return
            if port is not None:
                self._analog_start = ("komplekt", port[0], port[1])
            elif equipment is not None:
                self._analog_start = ("equipment", equipment.id, None)
            else:
                element_id = self._element_at(event.x, event.y)
                element = self.elements.get(element_id) if element_id else None
                if element is not None:
                    messagebox.showinfo(
                        "Аналоговые цепи",
                        "Аналоговые цепи подключаются к комплекту шкафа "
                        "(порт «AI» на левой грани), трансформатору тока (ТТ), "
                        "трансформатору напряжения (ТН) или к КИВ "
                        "(узел посередине).")
            self.redraw_all()
            return

        kind, first_id, first_index = self._analog_start
        start_ref = ("{}#{}".format(first_id, first_index)
                     if kind == "komplekt" else first_id)
        other_ref = None
        if port is not None:
            other_ref = "{}#{}".format(port[0], port[1])
        elif equipment is not None:
            other_ref = equipment.id
        if other_ref is None:
            # второй клик мимо порта/ТТ-ТН — отменяем начатую связь
            self._analog_start = None
            if self._element_at(event.x, event.y):
                messagebox.showinfo(
                    "Аналоговые цепи",
                    "Связь аналоговых цепей заканчивается на комплекте шкафа "
                    "(порт «AI»), трансформаторе тока или напряжения (ТТ/ТН) "
                    "либо на КИВ.")
            self.redraw_all()
            return
        created = self._add_analog_link(start_ref, other_ref)
        self._analog_start = None
        self.redraw_all()
        if created is not None:
            # сразу предлагаем указать цепи напряжения и тока
            self.edit_analog_link(created)

    def _add_analog_link(self, first_ref, second_ref):
        """Создаёт связь; комплекты — по порядку кликов, ТТ/ТН — источник."""
        first_id, first_index = self._split_ref(first_ref)
        second_id, second_index = self._split_ref(second_ref)
        first = self.elements.get(first_id)
        second = self.elements.get(second_id)
        if first is None or second is None:
            return
        if first_id == second_id and first_index == second_index:
            return
        first_equipment = first.type in self.ANALOG_TARGET_TYPES
        second_equipment = second.type in self.ANALOG_TARGET_TYPES
        # каждый конец — либо порт комплекта, либо ТТ/ТН
        if first_index is None and not first_equipment:
            return
        if second_index is None and not second_equipment:
            return
        if first_equipment:
            # аналоговые цепи идут от ТТ/ТН к комплекту
            from_ref, to_ref = first_ref, second_ref
        elif second_equipment:
            from_ref, to_ref = second_ref, first_ref
        else:
            from_ref, to_ref = first_ref, second_ref
        if from_ref == to_ref:
            return
        self._push_undo()
        link = {"from": from_ref, "to": to_ref}
        self.analog_links.append(link)
        return link

    def _analog_signals_text(self, link):
        """Подпись связи: цепи напряжения и тока."""
        parts = []
        voltage = (link.get("voltage") or "").strip()
        current = (link.get("current") or "").strip()
        if voltage:
            parts.append(voltage)
        if current:
            parts.append(current)
        return " / ".join(parts)

    def _draw_arrowhead(self, x1, y1, x2, y2, color, size, tags):
        """Треугольная стрелка у конца линии — направление аналоговых цепей."""
        length = float(x2) - float(x1)
        height = float(y2) - float(y1)
        norm = math.hypot(length, height)
        if norm < 1e-6:
            return
        ux, uy = length / norm, height / norm
        base_x, base_y = x2 - ux * size, y2 - uy * size
        half = size * 0.45
        left_x, left_y = base_x - uy * half, base_y + ux * half
        right_x, right_y = base_x + uy * half, base_y - ux * half
        self.canvas.create_polygon(x2, y2, left_x, left_y, right_x, right_y,
                                   fill=color, outline=color, tags=tags)

    def _draw_analog_links(self):
        """Порты «AI», фиолетовые связи со стрелкой и подписями цепей."""
        if not self.show_analog:
            return
        color = self.ANALOG_COLOR
        width = max(1, int(1.4 * self.zoom))

        # 1. Порты комплектов — первыми, чтобы стрелка на конце была видна
        if self.show_cabinets:
            linked = set()
            for link in self.analog_links:
                linked.add(link.get("from"))
                linked.add(link.get("to"))
            radius = max(2.5, 3.2 * self.zoom)
            port_font = max(1, int(6 * self.zoom))
            for cabinet, index, point in self._analog_ports():
                if point is None:
                    continue
                ref = "{}#{}".format(cabinet.id, index)
                active = ref in linked
                px, py = self.world_to_screen(*point)
                self.canvas.create_oval(
                    px - radius, py - radius, px + radius, py + radius,
                    fill=color if active else "white", outline=color,
                    width=max(1, int(1.2 * self.zoom)), tags="analog_port")
                if self.current_tool == "analog":
                    self.canvas.create_text(px - 5 * self.zoom, py, text="AI",
                                            font=("Arial", port_font),
                                            fill=color, anchor="e",
                                            tags="analog_port")

        # 2. Линии со стрелкой и подписью цепей
        dot = max(2.0, 2.6 * self.zoom)
        arrow_size = max(7.0, 9.0 * self.zoom)
        font_size = max(1, int(6 * self.zoom))
        seen_pairs = {}
        for link in self.analog_links:
            start = self._analog_ref_point(link.get("from"))
            end = self._analog_ref_point(link.get("to"))
            if start is None or end is None:
                continue
            x1, y1 = self.world_to_screen(*start)
            x2, y2 = self.world_to_screen(*end)
            distance = math.hypot(x2 - x1, y2 - y1)
            if distance < 1e-6:
                continue
            # между одними узлами может быть несколько связей —
            # разводим их параллельно, чтобы все были видны
            pair = tuple(sorted((str(link.get("from")), str(link.get("to")))))
            index = seen_pairs.get(pair, 0)
            seen_pairs[pair] = index + 1
            ux, uy = (x2 - x1) / distance, (y2 - y1) / distance
            if index:
                side = 1 if index % 2 else -1
                step = 4.5 * self.zoom * ((index + 1) // 2) * side
                x1 += -uy * step
                y1 += ux * step
                x2 += -uy * step
                y2 += ux * step
            line_x = x2 - ux * arrow_size * 0.9
            line_y = y2 - uy * arrow_size * 0.9
            self.canvas.create_line(x1, y1, line_x, line_y, fill=color,
                                    width=width, dash=(6, 3),
                                    tags="analog_link")
            self._draw_arrowhead(x1, y1, x2, y2, color, arrow_size,
                                 "analog_link")
            self.canvas.create_oval(x1 - dot, y1 - dot, x1 + dot, y1 + dot,
                                    fill=color, outline="white",
                                    tags="analog_link")
            signals = self._analog_signals_text(link)
            if signals:
                mid_x = (x1 + x2) / 2.0
                mid_y = (y1 + y2) / 2.0
                self.canvas.create_text(mid_x - uy * 11 * self.zoom,
                                        mid_y + ux * 11 * self.zoom,
                                        text=signals, fill=color,
                                        font=("Arial", font_size),
                                        anchor="center",
                                        tags="analog_label")

        # 3. Подсветка начатой связи
        if self._analog_start is not None:
            kind, element_id, index = self._analog_start
            ref = ("{}#{}".format(element_id, index)
                   if kind == "komplekt" else element_id)
            point = self._analog_ref_point(ref)
            if point is not None:
                px, py = self.world_to_screen(*point)
                r = max(4.0, 6.0 * self.zoom)
                self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                        outline="red", width=2,
                                        tags="analog_start")

    def _hover_analog(self, event):
        """Подсветка порта/ТТ-ТН и «резиновая» линия при создании связи."""
        if not self.show_analog:
            return
        r = max(4.0, 6.0 * self.zoom)
        port = self._analog_port_at(event.x, event.y)
        if port is not None:
            point = self._analog_ref_point("{}#{}".format(port[0], port[1]))
            px, py = self.world_to_screen(*point)
            self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                    outline=self.ANALOG_COLOR, width=2,
                                    tags="analog_hover")
        equipment = self._analog_equipment_at(event.x, event.y)
        if equipment is not None:
            px, py = self.world_to_screen(equipment.x, equipment.y)
            self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                    outline=self.ANALOG_COLOR, width=2,
                                    tags="analog_hover")
        if self._analog_start is None:
            return
        kind, element_id, index = self._analog_start
        ref = ("{}#{}".format(element_id, index)
               if kind == "komplekt" else element_id)
        point = self._analog_ref_point(ref)
        if point is None:
            return
        sx, sy = self.world_to_screen(*point)
        self.canvas.create_line(sx, sy, event.x, event.y,
                                fill=self.ANALOG_COLOR, dash=(6, 3),
                                width=max(1, int(1.2 * self.zoom)),
                                tags="analog_preview")

    ANALOG_VOLTAGE_PRESETS = ("Ua", "Ub", "Uc", "Uab", "Ubc", "Uca", "3U0",
                              "Uшон", "Uн", "Uи", "Uф", "Uк")
    ANALOG_CURRENT_PRESETS = ("Ia", "Ib", "Ic", "3I0")

    def _analog_ref_label(self, ref):
        """Подпись конца связи для диалога свойств."""
        element_id, index = self._split_ref(ref)
        element = self.elements.get(element_id)
        if element is None:
            return "—"
        if index is not None:
            return "{} · комплект {}".format(element.name, index + 1)
        kind = {"current_transformer": "ТТ",
                "voltage_transformer": "ТН",
                "bushing_monitor": "КИВ",
                "cabinet": "шкаф"}.get(element.type, element.type)
        title = getattr(element, "title", "") or ""
        return "{} ({}{})".format(element.name, kind,
                                  ", " + title if title and title != kind else "")

    def edit_analog_link(self, link):
        """Свойства связи аналоговых цепей: цепи напряжения и тока."""
        if link is None:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Аналоговые цепи — свойства связи")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        tk.Label(dialog, anchor="w", fg="#4a148c",
                 font=("Arial", 9, "bold"),
                 text="{}   →   {}".format(
                     self._analog_ref_label(link.get("from")),
                     self._analog_ref_label(link.get("to")))).pack(
            fill=tk.X, padx=10, pady=(8, 0))
        tk.Label(dialog, anchor="w", fg="#777777", font=("Arial", 7),
                 text="Стрелка на схеме показывает направление передачи цепей"
                 ).pack(fill=tk.X, padx=10)

        voltage_var = tk.StringVar(value=link.get("voltage") or "")
        current_var = tk.StringVar(value=link.get("current") or "")

        form = tk.Frame(dialog, padx=10, pady=4)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(0, weight=1)

        def add_field(row, title, variable, presets, hint):
            line = tk.Frame(form)
            line.grid(row=row, column=0, sticky="we", pady=(8, 0))
            tk.Label(line, text=title, width=22, anchor="w").pack(side=tk.LEFT)
            entry = tk.Entry(line, textvariable=variable, width=34)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(form, text=hint, fg="#999999", font=("Arial", 7),
                     anchor="w").grid(row=row + 1, column=0, sticky="w",
                                      padx=(150, 0))
            buttons = tk.Frame(form)
            buttons.grid(row=row + 2, column=0, sticky="w", padx=(150, 0),
                         pady=(2, 0))
            for position, preset in enumerate(presets):
                def toggle(name=preset, var=variable):
                    tokens = [token.strip() for token in
                              var.get().replace(";", ",").split(",")
                              if token.strip()]
                    if name in tokens:
                        tokens.remove(name)
                    else:
                        tokens.append(name)
                    var.set(", ".join(tokens))

                tk.Button(buttons, text=preset, width=7,
                          font=("Arial", 8), command=toggle
                          ).grid(row=position // 6, column=position % 6,
                                 padx=(0, 2), pady=(0, 2), sticky="w")
            return entry

        voltage_entry = add_field(
            0, "Цепи напряжения (U):", voltage_var,
            self.ANALOG_VOLTAGE_PRESETS,
            "например: Ua, Ub, Uc · Uab, Ubc, Uca · 3U0 · Uшон · "
            "Uн, Uи, Uф, Uк")
        add_field(
            3, "Цепи тока (I):", current_var, self.ANALOG_CURRENT_PRESETS,
            "например: Ia, Ib, Ic  ·  3I0")

        result = {"ok": False, "delete": False}

        def accept(event=None):
            result["ok"] = True
            dialog.destroy()

        def cancel(event=None):
            dialog.destroy()

        def remove():
            result["delete"] = True
            dialog.destroy()

        buttons = tk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=10, pady=(6, 8))
        tk.Button(buttons, text="Отмена", width=10,
                  command=cancel).pack(side=tk.RIGHT)
        tk.Button(buttons, text="Сохранить", width=12,
                  command=accept).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(buttons, text="Удалить связь", width=14,
                  command=remove).pack(side=tk.LEFT)
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", cancel)
        try:
            voltage_entry.focus_set()
        except tk.TclError:
            pass
        self._center_dialog(dialog)
        dialog.wait_window(dialog)

        if result["delete"]:
            if link in self.analog_links:
                self._push_undo()
                self.analog_links.remove(link)
                self.redraw_all()
            return
        if not result["ok"]:
            return
        voltage = voltage_var.get().strip()
        current = current_var.get().strip()
        if (voltage == (link.get("voltage") or "").strip()
                and current == (link.get("current") or "").strip()):
            return
        self._push_undo()
        link["voltage"] = voltage
        link["current"] = current
        self.redraw_all()

    def _build_analog_links(self, links, id_mapping=None):
        """Проверяет и (при вставке) переназначает связи аналоговых цепей."""
        result = []
        for link in links or []:
            if not isinstance(link, dict):
                continue
            from_ref = str(link.get("from") or "")
            to_ref = str(link.get("to") or "")
            if id_mapping is not None:
                from_id, from_index = self._split_ref(from_ref)
                to_id, to_index = self._split_ref(to_ref)
                from_id = id_mapping.get(from_id, "")
                to_id = id_mapping.get(to_id, "")
                if not from_id or not to_id:
                    continue
                from_ref = (from_id if from_index is None
                            else "{}#{}".format(from_id, from_index))
                to_ref = (to_id if to_index is None
                          else "{}#{}".format(to_id, to_index))
            from_id, from_index = self._split_ref(from_ref)
            to_id, to_index = self._split_ref(to_ref)
            start = self.elements.get(from_id)
            end = self.elements.get(to_id)
            if start is None or end is None:
                continue
            if from_id == to_id and from_index == to_index:
                continue
            if from_index is not None and (
                    start.type != "cabinet"
                    or from_index >= len(getattr(start, "komplets", []))):
                continue
            if to_index is not None and (
                    end.type != "cabinet"
                    or to_index >= len(getattr(end, "komplets", []))):
                continue
            if from_index is None and start.type not in self.ANALOG_TARGET_TYPES:
                continue
            if to_index is None and end.type not in self.ANALOG_TARGET_TYPES:
                continue
            entry = {"from": from_ref, "to": to_ref}
            for field in ("voltage", "current"):
                value = link.get(field)
                if isinstance(value, str) and value.strip():
                    entry[field] = value.strip()
            result.append(entry)
        return result

    # ================= ПАЛИТРА =================

    def _scroll_palette(self, event):
        self.palette_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _bind_palette_wheel(self, widget):
        """Колесо мыши прокручивает палитру, не задевая зум схемы."""
        for child in widget.winfo_children():
            if not isinstance(child, (tk.Entry, tk.Spinbox)):
                child.bind("<MouseWheel>", self._scroll_palette)
            self._bind_palette_wheel(child)

    def _make_tool_icon(self, parent, etype, label, size=46):
        """Кнопка-иконка: символ элемента, нарисованный на маленьком canvas."""
        canvas = tk.Canvas(parent, width=size, height=size, bg="white",
                           highlightthickness=1, highlightbackground="#b0b0b0",
                           takefocus=False)
        try:
            comp = library.create_component(etype, f"icon_{etype}", 0, 0, self.grid_size)
            bx1, by1, bx2, by2 = comp.get_bounding_box()
            bw = max(bx2 - bx1, 1.0)
            bh = max(by2 - by1, 1.0)
            zoom = min(0.85 * min(size / bw, size / bh), 1.2)
            cx = (bx1 + bx2) / 2.0
            cy = (by1 + by2) / 2.0
            comp.draw(canvas, zoom, size / 2.0 - cx * zoom, size / 2.0 - cy * zoom)
        except Exception:
            canvas.create_text(size / 2, size / 2, text="?", fill="#a00000")

        canvas.bind("<Button-1>", lambda e, t=etype: self.set_tool(t))
        ToolTip(canvas, label)
        return canvas

    def _mark_active_tool(self):
        for etype, canvas in getattr(self, "_tool_icons", {}).items():
            active = (etype == self.current_tool)
            canvas.config(highlightbackground="#1f4e79" if active else "#b0b0b0",
                          highlightthickness=2 if active else 1)
        for tool, cell in getattr(self, "_ribbon_tool_cells", {}).items():
            active = (tool == self.current_tool)
            cell._label.config(text=("▶ " if active else "") + cell._base_text)

    # ================= ПАНОРАМИРОВАНИЕ (средняя кнопка) =================
    def on_pan_start(self, event):
        self._pan_active = True
        self._pan_last = (event.x, event.y)
        self.canvas.config(cursor="fleur")
        return "break"

    def on_pan_move(self, event):
        if not self._pan_active:
            return "break"
        dx = event.x - self._pan_last[0]
        dy = event.y - self._pan_last[1]
        if dx or dy:
            self.canvas.move("all", dx, dy)
            self.offset_x += dx
            self.offset_y += dy
            self._pan_last = (event.x, event.y)
        return "break"

    def on_pan_end(self, event):
        if not self._pan_active:
            return "break"
        self._pan_active = False
        self.canvas.config(cursor="crosshair" if self.current_tool != "select" else "arrow")
        # Полная перерисовка: подтягивает сетку и линии к новым краям полотна
        self.redraw_all()
        return "break"

    def bind_events(self):
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self.on_zoom)
        self.canvas.bind("<Button-4>", self.on_zoom)
        self.canvas.bind("<Button-5>", self.on_zoom)
        self.canvas.bind("<Motion>", self.on_hover)
        # Панорамирование, как в AutoCAD: зажали среднюю кнопку и тянем чертёж
        self.canvas.bind("<Button-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self.on_pan_end)
        # Клавиши схемы вешаем на полотно, а не на окно: иначе R/Delete срабатывали
        # при вводе в поле «Шаг сетки» и портили схему.
        self.canvas.bind("<r>", self.rotate_selected)
        self.canvas.bind("<R>", self.rotate_selected)
        self.canvas.bind("<Delete>", self.delete_selected)
        self.canvas.bind("<BackSpace>", self.delete_selected)
        self.root.bind("<Escape>", self.deselect_all)
        
        self.root.bind("<Control-c>", self.copy_selection)
        self.root.bind("<Control-v>", self.paste_selection)
        self.root.bind("<Control-z>", self.undo_last_action)
        self.root.bind("<Control-y>", self.redo_last_action)
        self.root.bind("<Control-Shift-Z>", self.redo_last_action)
        self.root.bind("<Control-Shift-S>", self.export_ssd)

    # ================= ОТМЕНА / ПОВТОР =================
    def _reset_transient(self):
        """Сбрасывает незавершённые операции (перетаскивание, рамка, ресайз)."""
        self.selected_elements = []
        self.link_start = None
        self.dragging_group = False
        self.drag_offsets = {}
        self.resizing_element = None
        self.resize_handle = None
        self.selection_start = None
        self.selection_start_screen = None
        self._pre_change_state = None
        self._drag_changed = False
        self._resize_changed = False
        self._dragging_label = None
        self._label_drag_changed = False
        self._protection_start = None
        self._bind_start = None
        self._analog_start = None
        if self.selection_rect_id:
            self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None

    def _apply_state(self, state):
        if state is None:
            return

        self.elements = state["elements"]
        self.connections = state["connections"]
        self.protection_links = state.get("protection", [])
        self.analog_links = state.get("analog", [])
        self._reset_transient()
        self.selected_elements = list(state["selected_elements"])

        self.redraw_all()

    def _push_undo(self):
        """Снимок состояния для отмены: элементы, связи, РЗА и аналоговые цепи."""
        self.undo_manager.save_state(self.elements, self.connections,
                                     self.selected_elements,
                                     self.protection_links, self.analog_links)

    def _capture_state(self):
        return {
            "elements": copy.deepcopy(self.elements),
            "connections": copy.deepcopy(self.connections),
            "selected_elements": list(self.selected_elements),
            "protection": copy.deepcopy(self.protection_links),
            "analog": copy.deepcopy(self.analog_links),
        }

    def undo_last_action(self, event=None):
        state = self.undo_manager.undo(self._capture_state())
        self._apply_state(state)

    def redo_last_action(self, event=None):
        state = self.undo_manager.redo(self._capture_state())
        self._apply_state(state)

    # ================= МАСШТАБИРОВАНИЕ И СЕТКА =================
    def on_zoom(self, event):
        if event.num == 4 or event.delta > 0: factor = 1.1
        elif event.num == 5 or event.delta < 0: factor = 0.9
        else: return
        mx = (event.x - self.offset_x) / self.zoom
        my = (event.y - self.offset_y) / self.zoom
        new_zoom = self.zoom * factor
        if 0.08 < new_zoom < 5.0:
            self.zoom = new_zoom
            self.offset_x = event.x - mx * self.zoom
            self.offset_y = event.y - my * self.zoom
            self.redraw_all()
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")

    def reset_view(self):
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.redraw_all()
        self.zoom_label.config(text=f"{int(self.zoom * 100)}%")

    def screen_to_world(self, sx, sy):
        return (sx - self.offset_x) / self.zoom, (sy - self.offset_y) / self.zoom

    def world_to_screen(self, wx, wy):
        return wx * self.zoom + self.offset_x, wy * self.zoom + self.offset_y

    def draw_grid(self):
        self.canvas.delete("grid")
        w = self.canvas.winfo_width() or 800
        h = self.canvas.winfo_height() or 700
        wx_min, wy_min = self.screen_to_world(0, 0)
        wx_max, wy_max = self.screen_to_world(w, h)
        if self.grid_size * self.zoom < 5: return
        start_x = int(wx_min // self.grid_size) * self.grid_size
        for x in range(start_x, int(wx_max) + self.grid_size, self.grid_size):
            sx, _ = self.world_to_screen(x, 0)
            self.canvas.create_line(sx, 0, sx, h, fill=self.grid_color, tags="grid")
        start_y = int(wy_min // self.grid_size) * self.grid_size
        for y in range(start_y, int(wy_max) + self.grid_size, self.grid_size):
            _, sy = self.world_to_screen(0, y)
            self.canvas.create_line(0, sy, w, sy, fill=self.grid_color, tags="grid")
        self.canvas.tag_lower("grid")

    def snap(self, x, y):
        if self.snap_to_grid:
            return round(x / self.grid_size) * self.grid_size, round(y / self.grid_size) * self.grid_size
        return x, y

    def toggle_snap(self):
        self.snap_to_grid = self.snap_var.get()

    def toggle_show_nodes(self):
        self.show_all_nodes = self.show_nodes_var.get()
        self.redraw_all()

    def change_grid_size(self):
        """Шаг сетки влияет только на привязку и вид сетки, но не на размеры элементов.

        Геометрия элементов задаётся константой library.CELL, поэтому изменение шага
        больше не «масштабирует» схему и не сдвигает порты уже созданных элементов.
        """
        try:
            value = int(float(self.grid_spin.get().replace(",", ".")))
        except ValueError:
            value = self.grid_size
        self.grid_size = max(2, min(200, value))
        self.grid_spin.delete(0, "end")
        self.grid_spin.insert(0, str(self.grid_size))
        self.redraw_all()

    def rotate_selected(self, event):
        self._push_undo()
        
        for el_id in list(self.selected_elements):
            if el_id in self.elements:
                el = self.elements[el_id]
                if hasattr(el, 'rotation'):
                    el.rotation = (el.rotation + 90) % 360
                    el.generate_ports()
                elif el.type == "corner":
                    orientations = ["bottom_right", "bottom_left", "top_left", "top_right"]
                    current_idx = orientations.index(el.orientation)
                    next_idx = (current_idx + 1) % 4
                    el.orientation = orientations[next_idx]
                    el.generate_ports()
        self.redraw_all()

    def deselect_all(self, event=None):
        self.selected_elements = []
        self.redraw_all()

    # ================= КОПИРОВАНИЕ / ВСТАВКА =================
    def copy_selection(self, event=None):
        if not self.selected_elements:
            return
            
        self.clipboard = {}
        for el_id in self.selected_elements:
            if el_id in self.elements:
                el = self.elements[el_id]
                el_copy = copy.deepcopy(el)
                el_copy.id = None 
                self.clipboard[el_id] = el_copy
        
        self.clipboard_connections = []
        selected_set = set(self.selected_elements)
        
        for c in self.connections:
            if c["from"] in selected_set and c["to"] in selected_set:
                conn_copy = copy.deepcopy(c)
                conn_copy["canvas_id"] = None
                self.clipboard_connections.append(conn_copy)

        self.clipboard_analog = []
        for link in self.analog_links:
            first = self._split_ref(link.get("from"))[0]
            second = self._split_ref(link.get("to"))[0]
            if first in selected_set and second in selected_set:
                self.clipboard_analog.append(dict(link))

    def paste_selection(self, event=None):
        if self.clipboard is None:
            return
        
        self._push_undo()
            
        w = self.canvas.winfo_width() or 800
        h = self.canvas.winfo_height() or 700
        center_wx, center_wy = self.screen_to_world(w/2, h/2)

        live_selection = [eid for eid in self.selected_elements if eid in self.elements]
        if live_selection:
            orig_cx = sum(self.elements[eid].x for eid in live_selection) / len(live_selection)
            orig_cy = sum(self.elements[eid].y for eid in live_selection) / len(live_selection)
            offset_x = center_wx - orig_cx
            offset_y = center_wy - orig_cy
        else:
            offset_x, offset_y = 0, 0
            
        if self.snap_to_grid:
            offset_x = round(offset_x / self.grid_size) * self.grid_size
            offset_y = round(offset_y / self.grid_size) * self.grid_size

        id_mapping = {}
        new_selected = []
        pasted_containers = []
        
        for old_id, el_template in self.clipboard.items():
            new_id = f"{el_template.type[:2].upper()}{str(uuid.uuid4())[:4]}"
            
            new_el = library.create_component(
                el_template.type, new_id, 
                el_template.x + offset_x, 
                el_template.y + offset_y, 
                self.grid_size
            )
            
            new_el.name = self.get_next_name(
                PREFIX_BY_TYPE.get(el_template.type, "EL"), el_template.type)
            
            if hasattr(el_template, 'rotation'): new_el.rotation = el_template.rotation
            if hasattr(el_template, 'orientation'): new_el.orientation = el_template.orientation
            if hasattr(el_template, 'length'): new_el.length = el_template.length
            if hasattr(el_template, 'label_offset'):
                new_el.label_offset = list(el_template.label_offset)
            if el_template.type == "cabinet":
                new_el.cabinet_key = getattr(el_template, "cabinet_key", "")
                new_el.title = getattr(el_template, "title", new_el.title)
                new_el.info = dict(getattr(el_template, "info", {}))
                new_el.komplets = library.normalize_komplets(
                    getattr(el_template, "komplets", []))
            if el_template.type == "container":
                new_el.container_key = getattr(el_template, "container_key", "")
                new_el.code = getattr(el_template, "code", "КЭТ")
                new_el.title = getattr(el_template, "title", "КЭТ")
                new_el.size = getattr(el_template, "size", "20dc")
                new_el.slots = getattr(el_template, "slots", 7)
                new_el.info = dict(getattr(el_template, "info", {}))
                new_el.cabinets = list(getattr(el_template, "cabinets", []))
                new_el.slot_labels = [""] * new_el.slot_count()
                pasted_containers.append(new_el)

            new_el.generate_ports()
            self.elements[new_id] = new_el
            id_mapping[old_id] = new_id
            new_selected.append(new_id)
            
        for conn in self.clipboard_connections:
            old_from = conn["from"]
            old_to = conn["to"]
            
            if old_from in id_mapping and old_to in id_mapping:
                new_from = id_mapping[old_from]
                new_to = id_mapping[old_to]
                
                port_from = conn.get("port_from")
                port_to = conn.get("port_to")
                
                # Проверка, что порты существуют (на случай смены схемы портов)
                if port_from not in self.elements[new_from].ports:
                    port_from = None
                if port_to not in self.elements[new_to].ports:
                    port_to = None
                
                if port_from and port_to:
                    self.create_connection(new_from, new_to, port_from, port_to)

        # Привязка шкафов внутри скопированного контейнера — по новым id
        for container in pasted_containers:
            container.cabinets = [id_mapping.get(cabinet_id, "")
                                  for cabinet_id in container.cabinets]
            while len(container.cabinets) < container.slot_count():
                container.cabinets.append("")
        self._sync_containers()

        # Аналоговые цепи внутри вставленного фрагмента
        self.analog_links.extend(
            self._build_analog_links(getattr(self, "clipboard_analog", []),
                                     id_mapping))

        self.selected_elements = new_selected
        self.redraw_all()

    # ================= ПЕРЕРИСОВКА =================
    def redraw_all(self):
        self.canvas.delete("all")
        self._draw_underlay()
        self.draw_grid()
        
        # 1. Связи
        valid_connections = []
        for c in self.connections:
            if c["from"] in self.elements and c["to"] in self.elements:
                valid_connections.append(c)
                el1 = self.elements[c["from"]]
                el2 = self.elements[c["to"]]
                
                p1_data = el1.ports.get(c.get("port_from"), {"x": el1.x, "y": el1.y})
                p2_data = el2.ports.get(c.get("port_to"), {"x": el2.x, "y": el2.y})
                
                x1, y1 = self.world_to_screen(p1_data["x"], p1_data["y"])
                x2, y2 = self.world_to_screen(p2_data["x"], p2_data["y"])
                c["canvas_id"] = self.canvas.create_line(x1, y1, x2, y2, width=max(1, int(2*self.zoom)), fill="black")
        self.connections = valid_connections
                
        # 2. Контейнеры КЭТ и линии привязки слотов к шкафам
        if self.show_containers:
            self._sync_containers()
            for el in self.elements.values():
                if el.type == "container":
                    el.draw(self.canvas, self.zoom, self.offset_x, self.offset_y)
            self._draw_container_links()

        # 2а. Остальные элементы
        for el in self.elements.values():
            if el.type == "container":
                continue
            if el.type == "cabinet" and not self.show_cabinets:
                continue
            el.draw(self.canvas, self.zoom, self.offset_x, self.offset_y)
            
        # 3. Маркеры шины
        for el_id in self.selected_elements:
            if el_id in self.elements:
                el = self.elements[el_id]
                if el.type == "bus":
                    self.draw_handles(el)
                    
        # 4. Все узлы (с цветовой индикацией занятости)
        if self.show_all_nodes:
            used_node_ids = set()
            for c in self.connections:
                el1 = self.elements.get(c["from"])
                el2 = self.elements.get(c["to"])
                if el1 and el2:
                    p1 = el1.ports.get(c.get("port_from"))
                    p2 = el2.ports.get(c.get("port_to"))
                    if p1: used_node_ids.add(p1["node_id"])
                    if p2: used_node_ids.add(p2["node_id"])

            for el in self.elements.values():
                for p_name, p_data in el.ports.items():
                    sx, sy = self.world_to_screen(p_data["x"], p_data["y"])
                    r = 3 * self.zoom
                    
                    node_id = p_data["node_id"]
                    
                    if node_id in used_node_ids:
                        fill_color = "red2"
                        outline_color = "red4"
                    else:
                        fill_color = "green2"
                        outline_color = "green4"

                    self.canvas.create_oval(
                        sx-r, sy-r, sx+r, sy+r, 
                        outline=outline_color, 
                        fill=fill_color,
                        width=max(1, int(1.5*self.zoom))
                    )

        # 4a. Защитные узлы и стрелки комплект → узел
        self._draw_protection()

        # 4б. Аналоговые цепи: комплект → ТТ/ТН (или комплект), фиолетовым
        self._draw_analog_links()

        # 5. Рамка выделения
        highlight_color = "wheat4"
        highlight_width = max(1, int(2 * self.zoom))
        margin = 4 * self.zoom
        
        for el_id in self.selected_elements:
            if el_id in self.elements:
                el = self.elements[el_id]
                if el.type == "cabinet" and not self.show_cabinets:
                    continue
                if el.type == "container" and not self.show_containers:
                    continue
                bx1, by1, bx2, by2 = el.get_bounding_box()
                
                sx1, sy1 = self.world_to_screen(bx1, by1)
                sx2, sy2 = self.world_to_screen(bx2, by2)
                
                self.canvas.create_rectangle(
                    sx1 - margin, sy1 - margin,
                    sx2 + margin, sy2 + margin,
                    outline=highlight_color,
                    width=highlight_width,
                    dash=(4, 2),
                    tags="selection_highlight"
                )
                
                corner_size = 5 * self.zoom
                corners = [
                    (sx1 - margin, sy1 - margin),
                    (sx2 + margin, sy1 - margin),
                    (sx1 - margin, sy2 + margin),
                    (sx2 + margin, sy2 + margin),
                ]
                for cx, cy in corners:
                    self.canvas.create_rectangle(
                        cx - corner_size/2, cy - corner_size/2,
                        cx + corner_size/2, cy + corner_size/2,
                        fill=highlight_color,
                        outline="white",
                        width=1,
                        tags="selection_highlight"
                    )

        # 6. Точки привязки шкафов к контейнерам КЭТ
        self._draw_bind_points()

        # Подложка всегда под сеткой и элементами
        self.canvas.tag_lower("underlay")

    def draw_handles(self, el):
        lx, ly = self.world_to_screen(el.x - el.length, el.y)
        r = 5 * self.zoom
        self.canvas.create_rectangle(lx-r, ly-r, lx+r, ly+r, fill="cyan", outline="blue", tags="handle")
        rx, ry = self.world_to_screen(el.x + el.length, el.y)
        self.canvas.create_rectangle(rx-r, ry-r, rx+r, ry+r, fill="cyan", outline="blue", tags="handle")

    def find_resize_handle(self, el_id, sx, sy):
        el = self.elements[el_id]
        if el.type != "bus": return None
        lx, ly = self.world_to_screen(el.x - el.length, el.y)
        rx, ry = self.world_to_screen(el.x + el.length, el.y)
        handle_r = 10 * self.zoom
        if math.hypot(sx - lx, sy - ly) < handle_r: return "left"
        if math.hypot(sx - rx, sy - ry) < handle_r: return "right"
        return None

    def on_hover(self, event):
        self.canvas.delete("port_highlight")
        self.canvas.delete("bind_hover")
        self.canvas.delete("bind_preview")
        self.canvas.delete("analog_hover")
        self.canvas.delete("analog_preview")

        if self.current_tool == "bind":
            self._hover_bind(event)
            return

        if self.current_tool == "analog":
            self._hover_analog(event)
            return

        if self.current_tool == "select":
            cursor = "arrow"
            for el_id in self.selected_elements:
                if el_id in self.elements and self.elements[el_id].type == "bus":
                    if self.find_resize_handle(el_id, event.x, event.y):
                        cursor = "sb_h_double_arrow"
                        break
            self.canvas.config(cursor=cursor)
            return

        if self.current_tool != "connect": return
        
        for el in self.elements.values():
            ex, ey = self.world_to_screen(el.x, el.y)
            if math.hypot(event.x - ex, event.y - ey) < 60 * self.zoom:
                for p_name, p_data in el.ports.items():
                    sx, sy = self.world_to_screen(p_data["x"], p_data["y"])
                    r = 4 * self.zoom
                    self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, outline="blue", fill="cyan", tags="port_highlight")
                    
                    if el.type in ["transformer", "split_transformer", "three_winding_transformer", "autotransformer"]:
                        label = {"HV": "ВН", "LV": "НН", "LV1": "НН1", "LV2": "НН2", "MV": "СН", "N": "0"}.get(p_name, p_name)
                        self.canvas.create_text(sx + 10, sy, text=label, anchor="w", font=("Arial", int(10*self.zoom)), fill="blue", tags="port_highlight")

    def _hover_bind(self, event):
        """Подсветка слота/точки шкафа и «резиновая» линия при привязке."""
        if not self.show_containers:
            return
        r = max(4.0, 6.0 * self.zoom)
        slot = self._slot_at(event.x, event.y)
        if slot is not None:
            container = self.elements.get(slot[0])
            if container is not None:
                px, py = self.world_to_screen(*container.slot_center(slot[1]))
                self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                        outline="#a0522d", width=2,
                                        tags="bind_hover")
        cabinet = self._bind_cabinet_at(event.x, event.y)
        if cabinet is not None:
            px, py = self.world_to_screen(*self._cabinet_bind_point(cabinet))
            self.canvas.create_rectangle(px - r, py - r, px + r, py + r,
                                         outline="#a0522d", width=2,
                                         tags="bind_hover")
        if self._bind_start is None:
            return
        kind, first, index = self._bind_start
        start = None
        if kind == "slot":
            container = self.elements.get(first)
            if container is not None:
                start = container.slot_center(index)
        else:
            element = self.elements.get(first)
            if element is not None:
                start = self._cabinet_bind_point(element)
        if start is not None:
            sx, sy = self.world_to_screen(*start)
            self.canvas.create_line(sx, sy, event.x, event.y, fill="#a0522d",
                                    dash=(4, 3),
                                    width=max(1, int(1.2 * self.zoom)),
                                    tags="bind_preview")

    # ================= КЛИКИ =================
    def set_tool(self, tool):
        if tool == "delete":
            self.delete_selected()
            return
        had_protection_start = (self._protection_start is not None
                                or self._bind_start is not None
                                or self._analog_start is not None)
        self._protection_start = None
        self._bind_start = None
        self._analog_start = None
        self.current_tool = tool
        self.canvas.config(cursor="crosshair" if tool != "select" else "arrow")
        self._mark_active_tool()
        if had_protection_start:
            self.redraw_all()

    def delete_selected(self, event=None):
        """Удаляет выделенные элементы (и все их связи) одним действием."""
        if not self.selected_elements:
            return
        self._push_undo()
        for el_id in list(self.selected_elements):
            self.delete_element(el_id)
        self._reset_transient()
        self.redraw_all()

    def _element_at(self, sx, sy):
        """id элемента под курсором (верхний в порядке отрисовки) или None.

        Контейнеры проверяются последними: шкаф, стоящий внутри контейнера,
        всегда выбирается раньше самого контейнера.
        """
        items = list(self.elements.values())
        groups = ([el for el in items if el.type != "container"],
                  [el for el in items if el.type == "container"])
        for group in groups:
            for el in reversed(group):
                if el.type == "cabinet" and not self.show_cabinets:
                    continue
                if el.type == "container" and not self.show_containers:
                    continue
                bx1, by1, bx2, by2 = el.get_bounding_box()
                sx1, sy1 = self.world_to_screen(bx1, by1)
                sx2, sy2 = self.world_to_screen(bx2, by2)
                if sx1 <= sx <= sx2 and sy1 <= sy <= sy2:
                    return el.id
        return None

    def _label_at(self, sx, sy):
        """id элемента, чья подпись под курсором (bbox обновляется при отрисовке)."""
        for el in reversed(list(self.elements.values())):
            if el.type == "cabinet" and not self.show_cabinets:
                continue
            if el.type == "container" and not self.show_containers:
                continue
            box = getattr(el, "_label_bbox", None)
            if box and box[0] <= sx <= box[2] and box[1] <= sy <= box[3]:
                return el.id
        return None

    @staticmethod
    def _point_segment_distance(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    def _connection_at(self, sx, sy):
        """Связь, проходящая в пределах нескольких пикселей от курсора.

        Раньше здесь использовался canvas.find_closest без порога: любой клик
        «где-то рядом» с проводом удалял связь. Теперь попадание строго по линии.
        """
        tolerance = max(4.0, 6.0 * self.zoom)
        best, best_dist = None, tolerance
        for c in self.connections:
            el1 = self.elements.get(c.get("from"))
            el2 = self.elements.get(c.get("to"))
            if not el1 or not el2:
                continue
            p1 = el1.ports.get(c.get("port_from"))
            p2 = el2.ports.get(c.get("port_to"))
            if not p1 or not p2:
                continue
            x1, y1 = self.world_to_screen(p1["x"], p1["y"])
            x2, y2 = self.world_to_screen(p2["x"], p2["y"])
            dist = self._point_segment_distance(sx, sy, x1, y1, x2, y2)
            if dist <= best_dist:
                best, best_dist = c, dist
        return best

    def on_left_click(self, event):
        self.canvas.focus_set()
        wx, wy = self.screen_to_world(event.x, event.y)
        wx, wy = self.snap(wx, wy)

        # ОБРАБОТКА ИНСТРУМЕНТА SELECT
        if self.current_tool == "select":

            # А) ПРОВЕРКА МАРКЕРОВ ИЗМЕНЕНИЯ РАЗМЕРА ШИНЫ
            for el_id in list(self.selected_elements):
                if el_id in self.elements and self.elements[el_id].type == "bus":
                    handle = self.find_resize_handle(el_id, event.x, event.y)
                    if handle:
                        self.resizing_element = el_id
                        self.resize_handle = handle
                        self._pre_change_state = self._capture_state()
                        self._resize_changed = False
                        return

            # Б) ПОДПИСЬ ЭЛЕМЕНТА — перетаскивается мышкой отдельно от символа
            label_el = self._label_at(event.x, event.y)
            if label_el is not None:
                self._dragging_label = label_el
                self._label_drag_start = (event.x, event.y)
                self._label_drag_offset = list(self.elements[label_el].label_offset)
                self._label_drag_changed = False
                self._pre_change_state = self._capture_state()
                self.canvas.config(cursor="fleur")
                return

            clicked_el = self._element_at(event.x, event.y)

            # В) УДАЛЕНИЕ СВЯЗИ — только при точном попадании в линию
            #    и только если под курсором нет элемента
            if clicked_el is None:
                conn_to_delete = self._connection_at(event.x, event.y)
                if conn_to_delete is not None:
                    self._push_undo()
                    self.connections.remove(conn_to_delete)
                    self.redraw_all()
                    return

            # В) КЛИК ПО ЭЛЕМЕНТУ
            if clicked_el:
                ctrl_pressed = bool(event.state & 0x0004)

                if ctrl_pressed:
                    if clicked_el in self.selected_elements:
                        self.selected_elements.remove(clicked_el)
                    else:
                        self.selected_elements.append(clicked_el)
                    self.redraw_all()
                    return

                if clicked_el not in self.selected_elements:
                    self.selected_elements = [clicked_el]

                self.dragging_group = True
                self._pre_change_state = self._capture_state()
                self._drag_changed = False
                self.drag_offsets = {}
                for el_id in self.selected_elements:
                    el = self.elements[el_id]
                    self.drag_offsets[el_id] = (wx - el.x, wy - el.y)

                self.redraw_all()
                return

            # Г) КЛИК ПО ПУСТОМУ МЕСТУ — рамка выделения
            self.selection_start = (wx, wy)
            self.selection_start_screen = (event.x, event.y)
            sx_start, sy_start = event.x, event.y
            self.selection_rect_id = self.canvas.create_rectangle(
                sx_start, sy_start, sx_start, sy_start,
                outline="wheat3", fill="wheat1", stipple="gray12", width=2
            )
            return

        # ИНСТРУМЕНТ CONNECT
        if self.current_tool == "connect":
            best_port_el = None
            best_port_name = None
            min_dist = float('inf')
            
            for el in self.elements.values():
                for p_name, p_data in el.ports.items():
                    px, py = self.world_to_screen(p_data["x"], p_data["y"])
                    dist = math.hypot(event.x - px, event.y - py)
                    if dist < 15 * self.zoom and dist < min_dist:
                        min_dist = dist
                        best_port_el = el.id
                        best_port_name = p_name
            
            if best_port_el:
                if not self.link_start:
                    self.link_start = (best_port_el, best_port_name)
                    el = self.elements[best_port_el]
                    p_data = el.ports[best_port_name]
                    px, py = self.world_to_screen(p_data["x"], p_data["y"])
                    self.canvas.create_oval(px-6, py-6, px+6, py+6, outline="red", width=2, tags="link_start")
                else:
                    start_id, start_port = self.link_start
                    if best_port_el != start_id:
                        self._push_undo()
                        self.create_connection(start_id, best_port_el, start_port, best_port_name)
                    self.canvas.delete("link_start")
                    self.link_start = None
                    self.redraw_all()
            return

        # ИНСТРУМЕНТ «СВЯЗЬ РЗА»: комплект ↔ защитный узел оборудования
        if self.current_tool == "protection":
            self._on_protection_click(event)
            return

        # ИНСТРУМЕНТ «ПРИВЯЗКА»: слот контейнера ↔ шкаф (линией)
        if self.current_tool == "bind":
            self._on_bind_click(event)
            return

        # ИНСТРУМЕНТ «АНАЛОГОВЫЕ ЦЕПИ»: комплект ↔ ТТ/ТН или комплект
        if self.current_tool == "analog":
            self._on_analog_click(event)
            return

        # ДОБАВЛЕНИЕ НОВЫХ ЭЛЕМЕНТОВ
        tool = self.current_tool
        if tool in library.COMPONENT_TYPES:
            self._push_undo()
            self.add_element(tool, wx, wy)

    def get_next_name(self, prefix, el_type=None):
        """Следующий свободный номер по префиксу.

        Уникальность проверяется по всей схеме, а не внутри одного типа:
        иначе трансформатор, трёхобмоточный и расщеплённый получали одинаковые T1/T2.
        """
        existing_numbers = []
        for el in self.elements.values():
            if not el.name.startswith(prefix):
                continue
            num_part = el.name[len(prefix):]
            if num_part.isdigit():
                existing_numbers.append(int(num_part))

        if not existing_numbers:
            return f"{prefix}1"

        next_num = max(existing_numbers) + 1
        return f"{prefix}{next_num}"

    def on_double_click(self, event):
        # Двойной клик по линии аналоговых цепей — свойства связи (U/I)
        link = self._analog_link_at(event.x, event.y)
        if link is not None:
            self.edit_analog_link(link)
            return

        clicked_el = None
        for el in reversed(list(self.elements.values())):
            bx1, by1, bx2, by2 = el.get_bounding_box()
            sx1, sy1 = self.world_to_screen(bx1, by1)
            sx2, sy2 = self.world_to_screen(bx2, by2)
            if sx1 <= event.x <= sx2 and sy1 <= event.y <= sy2:
                clicked_el = el
                break
        
        if clicked_el is not None and clicked_el.type == "container":
            # Двойной клик по контейнеру — сразу режим привязки слотов
            self.selected_elements = [clicked_el.id]
            self._show_ribbon_tab("Контейнеры")
            self.set_tool("bind")
            self._mark_active_tool()
            self.redraw_all()
            return

        if clicked_el:
            new_name = simpledialog.askstring("Переименование", f"Введите новое имя для {clicked_el.type}:", initialvalue=clicked_el.name)
            
            if new_name is not None:
                new_name = new_name.strip()
                
                # Пустые имена разрешены, но не участвуют в проверке уникальности
                for other_el in self.elements.values():
                    if new_name and other_el.id != clicked_el.id and other_el.name.lower() == new_name.lower():
                        messagebox.showerror("Ошибка", f"Элемент с именем '{new_name}' уже существует на схеме!\nИмена должны быть уникальными.")
                        return
                
                self._push_undo()
                clicked_el.name = new_name
                self.redraw_all()

    def on_drag(self, event):
        # ПЕРЕТАСКИВАНИЕ ПОДПИСИ
        if self._dragging_label is not None:
            el = self.elements.get(self._dragging_label)
            if el is not None:
                dx = (event.x - self._label_drag_start[0]) / self.zoom
                dy = (event.y - self._label_drag_start[1]) / self.zoom
                el.label_offset = [round(self._label_drag_offset[0] + dx, 1),
                                   round(self._label_drag_offset[1] + dy, 1)]
                self._label_drag_changed = True
                self.redraw_all()
            return

        # ПЕРЕТАСКИВАНИЕ ГРУППЫ
        if self.current_tool == "select" and self.dragging_group:
            wx, wy = self.screen_to_world(event.x, event.y)
            wx, wy = self.snap(wx, wy)
            
            for el_id in self.selected_elements:
                if el_id in self.elements:
                    el = self.elements[el_id]
                    off_x, off_y = self.drag_offsets.get(el_id, (0, 0))
                    new_x = wx - off_x
                    new_y = wy - off_y
                    
                    if self.snap_to_grid:
                        new_x = round(new_x / self.grid_size) * self.grid_size
                        new_y = round(new_y / self.grid_size) * self.grid_size
                    
                    if new_x != el.x or new_y != el.y:
                        el.x, el.y = new_x, new_y
                        el.generate_ports()
                        self._drag_changed = True

            self.redraw_all()
            return

        # РИСОВАНИЕ РАМКИ ВЫДЕЛЕНИЯ
        if self.selection_start is not None and self.selection_rect_id is not None:
            sx_end, sy_end = event.x, event.y
            self.canvas.coords(self.selection_rect_id, 
                             self.selection_start_screen[0], self.selection_start_screen[1],
                             sx_end, sy_end)
            return

        # ИЗМЕНЕНИЕ РАЗМЕРА ШИНЫ
        if self.current_tool == "select" and self.resizing_element:
            el = self.elements[self.resizing_element]
            wx, wy = self.screen_to_world(event.x, event.y)
            wx, wy = self.snap(wx, wy)
            
            if self.resize_handle == "right":
                fixed_edge = el.x - el.length
                new_length = wx - fixed_edge
                if new_length < self.grid_size: new_length = self.grid_size
                if new_length != el.length:
                    self._resize_changed = True
                el.length = new_length
                el.x = fixed_edge + new_length
            elif self.resize_handle == "left":
                fixed_edge = el.x + el.length
                new_length = fixed_edge - wx
                if new_length < self.grid_size: new_length = self.grid_size
                if new_length != el.length:
                    self._resize_changed = True
                el.length = new_length
                el.x = fixed_edge - new_length
            el.generate_ports()
            self.redraw_all()
            return

    def on_release(self, event):
        # ЗАВЕРШЕНИЕ ПЕРЕТАСКИВАНИЯ ПОДПИСИ
        if self._dragging_label is not None:
            if self._label_drag_changed:
                self.undo_manager.push_state(self._pre_change_state)
            self._dragging_label = None
            self._label_drag_changed = False
            self._pre_change_state = None
            self.canvas.config(cursor="arrow" if self.current_tool == "select"
                               else "crosshair")
            return

        # ЗАВЕРШЕНИЕ РАМКИ ВЫДЕЛЕНИЯ
        if self.selection_start is not None and self.selection_start_screen is not None:
            sx1, sy1 = self.selection_start_screen
            sx2, sy2 = event.x, event.y
            
            rx1, rx2 = min(sx1, sx2), max(sx1, sx2)
            ry1, ry2 = min(sy1, sy2), max(sy1, sy2)
            
            wx1, wy1 = self.screen_to_world(rx1, ry1)
            wx2, wy2 = self.screen_to_world(rx2, ry2)
            
            new_selection = []
            for el_id, el in self.elements.items():
                bx1, by1, bx2, by2 = el.get_bounding_box()
                if bx1 <= wx2 and bx2 >= wx1 and by1 <= wy2 and by2 >= wy1:
                    new_selection.append(el_id)
            
            self.selected_elements = new_selection
            self.selection_start = None
            self.selection_start_screen = None
            if self.selection_rect_id:
                self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None
            self.redraw_all()
            return

        # ЗАВЕРШЕНИЕ ПЕРЕТАСКИВАНИЯ
        if self.dragging_group:
            # Состояние «до» записываем в историю только если что-то реально сдвинулось,
            # иначе обычный клик по элементу засорял бы стек отмены пустыми шагами.
            if self._drag_changed:
                self.undo_manager.push_state(self._pre_change_state)
            self.dragging_group = False
            self._drag_changed = False
            self._pre_change_state = None
            self.drag_offsets = {}
            return

        # ЗАВЕРШЕНИЕ ИЗМЕНЕНИЯ РАЗМЕРА ШИНЫ
        if self.resizing_element:
            if self._resize_changed:
                self.undo_manager.push_state(self._pre_change_state)
            self.resizing_element = None
            self.resize_handle = None
            self._resize_changed = False
            self._pre_change_state = None
            self.redraw_all()

    def on_right_click(self, event):
        clicked_el = self._element_at(event.x, event.y)
        if clicked_el:
            self._push_undo()
            self.delete_element(clicked_el)
            if clicked_el in self.selected_elements:
                self.selected_elements.remove(clicked_el)
            self.redraw_all()

    # ================= ДОБАВЛЕНИЕ / УДАЛЕНИЕ =================
    def add_element(self, etype, x, y):
        el_id = f"{etype[:2].upper()}{str(uuid.uuid4())[:4]}"
        el = library.create_component(etype, el_id, x, y, self.grid_size)

        el.name = self.get_next_name(PREFIX_BY_TYPE.get(etype, "EL"), etype)

        self.elements[el_id] = el
        self.redraw_all()

    def delete_element(self, el_id):
        if el_id not in self.elements: return
        # Контейнер удаляем отдельно: его шкафы остаются на схеме
        deleted = self.elements.get(el_id)
        del self.elements[el_id]
        if deleted is not None and deleted.type == "container":
            deleted.cabinets = [""] * deleted.slot_count()
        # Удалённый шкаф вынимаем из слота контейнера
        for container in self._containers():
            if container.slot_of(el_id) is not None:
                container.unbind(el_id)
        self._sync_containers()
        self.connections = [c for c in self.connections if c["from"] != el_id and c["to"] != el_id]
        # Защитные связи удалённого оборудования/шкафа
        self.protection_links = [
            link for link in self.protection_links
            if link["element"] != el_id
            and self._link_ref(link).split("#")[0] != el_id
        ]
        # Аналоговые цепи удалённого шкафа/ТТ/ТН
        self.analog_links = [
            link for link in self.analog_links
            if self._split_ref(link.get("from"))[0] != el_id
            and self._split_ref(link.get("to"))[0] != el_id
        ]

    def create_connection(self, id1, id2, port1, port2):
        for c in self.connections:
            if (c["from"] == id1 and c["to"] == id2 and c.get("port_from") == port1 and c.get("port_to") == port2):
                return
        self.connections.append({
            "from": id1, "to": id2, 
            "port_from": port1, "port_to": port2, 
            "canvas_id": None
        })

    def clear_all(self):
        if messagebox.askyesno("Очистить", "Удалить всю схему?"):
            self._push_undo()
            self.elements = {}
            self.connections = []
            self._reset_transient()
            self.clipboard = None
            self.clipboard_connections = []
            self.redraw_all()

    # ================= ОТЧЁТЫ =================
    def _build_ribbon_reports(self, parent):
        page = tk.Frame(parent, bg="#f3f3f3")
        self._ribbon_group(page, "Схема", lambda row: [
            self._ribbon_button(row, "По схеме", self.report_by_scheme,
                                _ri_report, 76).pack(side=tk.LEFT),
        ])
        tk.Label(page, text="Формирует документ Word (.docx) с ведомостями:\n"
                            "шкафы РЗА, контейнеры КЭТ, типы шкафов,\n"
                            "аналоговые цепи и первичное оборудование.",
                 bg="#f3f3f3", fg="#808080", font=("Arial", 7),
                 justify="left").pack(side=tk.LEFT, padx=12)
        return page

    @staticmethod
    def _natural_key(text):
        """Ключ сортировки: EL2 раньше EL10."""
        parts = re.split(r"(\d+)", str(text or ""))
        return [int(part) if part.isdigit() else part.lower() for part in parts]

    def _report_cabinet_type(self, cabinet):
        """Код и наименование типа шкафа по каталогу."""
        definition = cabs.find_cabinet(getattr(cabinet, "cabinet_key", ""))
        if definition:
            return (definition.get("code") or "—",
                    definition.get("name") or definition.get("title") or "—",
                    definition.get("group") or "—")
        return (getattr(cabinet, "title", "") or "—",
                getattr(cabinet, "title", "") or "—", "—")

    def _collect_scheme_report(self):
        """Готовит данные для отчёта по схеме."""
        cabinets = sorted((el for el in self.elements.values()
                           if el.type == "cabinet"),
                          key=lambda el: self._natural_key(el.name))
        containers = sorted((el for el in self.elements.values()
                             if el.type == "container"),
                            key=lambda el: self._natural_key(el.name))
        equipment = [el for el in self.elements.values()
                     if el.type not in ("cabinet", "container", "node", "corner")]
        equipment.sort(key=lambda el: self._natural_key(el.name))

        total_komplets = sum(len(getattr(el, "komplets", [])) for el in cabinets)
        total_ieds = sum(len(komplekts.effective_ieds(komplekt))
                         for el in cabinets
                         for komplekt in getattr(el, "komplets", []))
        bound = sum(len(container.bound_ids()) for container in containers)

        # --- шкафы ---
        cabinet_rows = []
        type_totals = {}
        for index, cabinet in enumerate(cabinets, 1):
            code, name, group = self._report_cabinet_type(cabinet)
            container = self._container_of(cabinet.id)
            if container is not None:
                slot = container.slot_of(cabinet.id) or 0
                place = "{} · слот {}".format(container.name, slot + 1)
            else:
                place = "—"
            cabinet_rows.append([
                str(index), cabinet.name or "—", code, name, group,
                str(len(getattr(cabinet, "komplets", []))),
                str(sum(len(komplekts.effective_ieds(k)) for k in
                        getattr(cabinet, "komplets", []))),
                place,
            ])
            entry = type_totals.setdefault(code, {"name": name, "names": []})
            entry["names"].append(cabinet.name or "—")

        # --- комплекты в шкафах ---
        komplekt_rows = []
        for cabinet in cabinets:
            for index, kit in enumerate(getattr(cabinet, "komplets", []), 1):
                ieds = komplekts.effective_ieds(kit)
                komplekt_rows.append([
                    str(len(komplekt_rows) + 1),
                    cabinet.name or "—",
                    kit.get("name") or "Комплект {}".format(index),
                    komplekts.kind_title(kit),
                    (komplekts.cabinet_ref_text(kit)
                     if kit.get("kind") == "typical" else "—"),
                    ("есть — " + ", ".join(ied.get("name") or "ИЭУ"
                                           for ied in ieds)) if ieds else "нет",
                    ", ".join(kit.get("functions") or []) or "—",
                    komplekts.test_blocks_text(kit),
                ])

        # --- контейнеры ---
        container_rows = []
        for index, container in enumerate(containers, 1):
            info = getattr(container, "info", {}) or {}
            bound_names = [self.elements[cabinet_id].name
                           for cabinet_id in container.bound_ids()
                           if cabinet_id in self.elements]
            container_rows.append([
                str(index), container.name or "—",
                getattr(container, "code", "—") or "—",
                info.get("name") or getattr(container, "title", "—"),
                info.get("size_code") or "—",
                str(container.slot_count()),
                str(len(bound_names)),
                ", ".join(bound_names) if bound_names else "—",
            ])

        # --- сводная ведомость по типам ---
        type_rows = []
        for number, (code, entry) in enumerate(
                sorted(type_totals.items(),
                       key=lambda item: (-len(item[1]["names"]),
                                         self._natural_key(item[0]))), 1):
            type_rows.append([
                str(number), code, entry["name"], str(len(entry["names"])),
                ", ".join(entry["names"]),
            ])

        # --- аналоговые цепи ---
        analog_rows = []
        for index, link in enumerate(self.analog_links, 1):
            analog_rows.append([
                str(index),
                self._analog_ref_label(link.get("from")),
                self._analog_ref_label(link.get("to")),
                link.get("voltage") or "—",
                link.get("current") or "—",
            ])

        # --- первичное оборудование ---
        by_type = {}
        for element in equipment:
            by_type.setdefault(element.type, []).append(element.name or "—")
        equipment_rows = []
        for number, (etype, names) in enumerate(
                sorted(by_type.items(),
                       key=lambda item: (-len(item[1]),
                                         self._natural_key(item[0]))), 1):
            equipment_rows.append([
                str(number),
                ELEMENT_TYPE_TITLES.get(etype, etype),
                str(len(names)),
                ", ".join(sorted(names, key=self._natural_key)),
            ])

        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        report = {
            "title": "Отчёт по схеме",
            "subtitle": [
                "Сформирован: {}".format(now),
                "Источник: текущая схема редактора",
            ],
            "sections": [
                {
                    "title": "1. Сводка по схеме",
                    "header": ["Показатель", "Значение"],
                    "rows": [
                        ["Шкафов РЗА (EL)", str(len(cabinets))],
                        ["Контейнеров КЭТ (EK)", str(len(containers))],
                        ["Шкафов привязано к контейнерам", str(bound)],
                        ["Комплектов РЗА в шкафах", str(total_komplets)],
                        ["Устройств ИЭУ в шкафах", str(total_ieds)],
                        ["Связей РЗА (комплект ↔ оборудование)",
                         str(len(self.protection_links))],
                        ["Аналоговых цепей (комплект ↔ ТТ/ТН или комплект)",
                         str(len(self.analog_links))],
                        ["Единиц первичного оборудования", str(len(equipment))],
                        ["Всего элементов на схеме", str(len(self.elements))],
                    ],
                    "widths": [6200, 3438],
                    "aligns": ["left", "center"],
                },
                {
                    "title": "2. Ведомость шкафов РЗА",
                    "header": ["№", "Обозначение", "Тип ШЭТ", "Наименование",
                               "Группа", "Компл.", "ИЭУ", "Контейнер"],
                    "rows": cabinet_rows,
                    "widths": [500, 1100, 1300, 2900, 1000, 800, 700, 1338],
                    "aligns": ["center", "center", "center", "left", "left",
                               "center", "center", "left"],
                },
                {
                    "title": "3. Ведомость комплектов РЗА",
                    "header": ["№", "Шкаф", "Комплект", "Вид", "Типовой шкаф",
                               "ИЭУ", "Функции", "Испытательные блоки U/I"],
                    "rows": komplekt_rows,
                    "widths": [420, 900, 1200, 900, 1700, 1500, 1300, 1718],
                    "aligns": ["center", "center", "left", "center", "left",
                               "left", "left", "left"],
                    "font_size": 8,
                },
                {
                    "title": "4. Ведомость контейнеров КЭТ",
                    "header": ["№", "Обозначение", "Тип КЭТ", "Наименование",
                               "Типоразмер", "Слотов", "Шкафов", "Состав"],
                    "rows": container_rows,
                    "widths": [500, 1100, 1000, 3000, 1000, 800, 800, 1438],
                    "aligns": ["center", "center", "center", "left", "center",
                               "center", "center", "left"],
                },
                {
                    "title": "5. Сводная ведомость типов шкафов",
                    "header": ["№", "Тип ШЭТ", "Наименование", "Количество",
                               "Обозначения на схеме"],
                    "rows": type_rows,
                    "widths": [500, 1400, 3300, 1000, 3438],
                    "aligns": ["center", "center", "left", "center", "left"],
                },
                {
                    "title": "6. Ведомость аналоговых цепей",
                    "header": ["№", "Откуда", "Куда", "Цепи напряжения (U)",
                               "Цепи тока (I)"],
                    "rows": analog_rows,
                    "widths": [500, 2400, 2400, 2169, 2169],
                    "aligns": ["center", "left", "left", "left", "left"],
                },
                {
                    "title": "7. Ведомость первичного оборудования",
                    "header": ["№", "Тип оборудования", "Количество",
                               "Обозначения на схеме"],
                    "rows": equipment_rows,
                    "widths": [500, 2600, 1200, 5338],
                    "aligns": ["center", "left", "center", "left"],
                },
            ],
            "footer": [
                "Отчёт сформирован автоматически редактором схем."
                " Ведомости отражают текущее состояние схемы.",
            ],
        }
        return report

    @staticmethod
    def _open_document(path):
        """Открывает документ приложением системы (если возможно)."""
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    def report_by_scheme(self):
        """Отчёт по схеме в формате DOCX."""
        if not self.elements:
            messagebox.showinfo("Отчёты", "Схема пуста — нечего выгружать.")
            return
        default_name = "Отчёт по схеме {}.docx".format(
            datetime.now().strftime("%d.%m.%Y"))
        path = filedialog.asksaveasfilename(
            title="Сохранить отчёт по схеме",
            defaultextension=".docx",
            initialfile=default_name,
            filetypes=[("Документ Word", "*.docx")])
        if not path:
            return
        try:
            report = self._collect_scheme_report()
            docxreport.build_scheme_report(path, report)
        except Exception as error:
            messagebox.showerror(
                "Отчёты",
                "Не удалось сформировать отчёт:\n{}".format(error))
            return
        cabinets = len([el for el in self.elements.values()
                        if el.type == "cabinet"])
        containers = len([el for el in self.elements.values()
                          if el.type == "container"])
        if messagebox.askyesno(
                "Отчёты",
                "Отчёт сохранён:\n{}\n\nШкафов: {} · контейнеров: {} · "
                "аналоговых цепей: {}\n\nОткрыть документ?".format(
                    path, cabinets, containers, len(self.analog_links))):
            self._open_document(path)

    # ================= ЭКСПОРТ PDF =================
    def export_pdf(self, event=None):
        """Сохраняет текущий вид схемы (подложка + элементы) в PDF."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not filepath:
            return

        margin = 40.0
        xs, ys = [], []
        if self.underlay:
            xs += [0.0, self.underlay["width"] * self.underlay_scale]
            ys += [0.0, self.underlay["height"] * self.underlay_scale]
        for element in self.elements.values():
            if element.type == "cabinet" and not self.show_cabinets:
                continue
            if element.type == "container" and not self.show_containers:
                continue
            bx1, by1, bx2, by2 = element.get_bounding_box()
            xs += [bx1, bx2]
            ys += [by1, by2]
        if not xs:
            xs, ys = [0.0, 800.0], [0.0, 600.0]

        min_x, max_x = min(xs) - margin, max(xs) + margin
        min_y, max_y = min(ys) - margin, max(ys) + margin

        # Масштаб экспорта: при подложке приводим лист к размеру исходного PDF
        export_scale = 1.0
        if self.underlay and self.underlay_scale > 0:
            export_scale = 1.0 / self.underlay_scale
        width = max(50.0, (max_x - min_x) * export_scale)
        height = max(50.0, (max_y - min_y) * export_scale)

        # Слишком маленький лист поднимаем до A4 (альбом), содержимое центрируем
        offset_x, offset_y = -min_x, -min_y
        if width < 842 or height < 595:
            sheet_w = max(width, 842) / export_scale
            sheet_h = max(height, 595) / export_scale
            offset_x = -min_x + (sheet_w - (max_x - min_x)) / 2.0
            offset_y = -min_y + (sheet_h - (max_y - min_y)) / 2.0
            width = sheet_w * export_scale
            height = sheet_h * export_scale

        try:
            document = pdfexport.PdfDocument(width, height, offset_x, offset_y,
                                             scale=export_scale)
        except Exception as error:
            messagebox.showerror("PDF", f"Не удалось подготовить экспорт:\n{error}")
            return

        canvas = document.canvas
        if self.underlay and self.show_underlay:
            scale = self.underlay_scale
            for points in self.underlay["lines"]:
                coords = []
                for x, y in points:
                    coords.extend((x * scale, y * scale))
                canvas.create_line(*coords, fill="#6f6f6f", width=1)
            for text, x, y in self.underlay["labels"]:
                canvas.create_text(x * scale, y * scale, text=text,
                                   anchor="w", font=("Arial", 6), fill="#8a8a8a")

        visible = [element for element in self.elements.values()
                   if not (element.type == "cabinet" and not self.show_cabinets)
                   and not (element.type == "container" and not self.show_containers)]
        # Контейнеры и линии привязки слотов — под остальными элементами
        self._sync_containers()
        for element in visible:
            if element.type == "container":
                element.draw(canvas, 1.0, 0.0, 0.0)
        if self.show_containers:
            for container in visible:
                if container.type != "container":
                    continue
                for index in range(container.slot_count()):
                    cabinet_id = (container.cabinets[index]
                                  if index < len(container.cabinets) else "")
                    cabinet = self.elements.get(cabinet_id) if cabinet_id else None
                    if cabinet is None or cabinet.type != "cabinet":
                        continue
                    slot_x, slot_y = container.slot_center(index)
                    end_x, end_y = self._cabinet_bind_point(cabinet)
                    canvas.create_line(slot_x, slot_y, end_x, end_y,
                                       fill="#a0522d", width=1)
        for element in visible:
            if element.type != "container":
                element.draw(canvas, 1.0, 0.0, 0.0)
        if self.show_containers:
            for element in visible:
                if element.type != "cabinet":
                    continue
                px, py = self._cabinet_bind_point(element)
                bound = self._container_of(element.id) is not None
                canvas.create_rectangle(px - 3, py - 3, px + 3, py + 3,
                                        fill="#a0522d" if bound else "white",
                                        outline="#a0522d", width=1)
        if self.show_analog:
            for link in self.analog_links:
                start = self._analog_ref_point(link.get("from"))
                end = self._analog_ref_point(link.get("to"))
                if start is None or end is None:
                    continue
                x1, y1 = start
                x2, y2 = end
                distance = math.hypot(x2 - x1, y2 - y1)
                if distance < 1e-6:
                    continue
                ux, uy = (x2 - x1) / distance, (y2 - y1) / distance
                arrow_size = 9.0
                canvas.create_line(x1, y1, x2 - ux * arrow_size * 0.9,
                                   y2 - uy * arrow_size * 0.9,
                                   fill=self.ANALOG_COLOR, width=1,
                                   dash=(6, 3))
                base_x, base_y = x2 - ux * arrow_size, y2 - uy * arrow_size
                half = arrow_size * 0.45
                canvas.create_polygon(
                    x2, y2,
                    base_x - uy * half, base_y + ux * half,
                    base_x + uy * half, base_y - ux * half,
                    fill=self.ANALOG_COLOR, outline=self.ANALOG_COLOR)
                signals = self._analog_signals_text(link)
                if signals:
                    canvas.create_text((x1 + x2) / 2.0 - uy * 11,
                                       (y1 + y2) / 2.0 + ux * 11,
                                       text=signals, fill=self.ANALOG_COLOR,
                                       font=("Arial", 6), anchor="center")

        try:
            document.save(filepath)
        except Exception as error:
            messagebox.showerror("PDF", f"Не удалось сохранить PDF:\n{error}")
            return

        messagebox.showinfo("PDF", f"Сохранено: {os.path.basename(filepath)}")

    # ================= ЭКСПОРТ SSD (МЭК 61850-6) =================
    def export_ssd(self, event=None):
        """Сохраняет схему в SSD (System Specification Description, МЭК 61850-6)."""
        if not self.elements:
            messagebox.showinfo("SSD", "Схема пуста — экспортировать нечего.")
            return

        underlay_path = self.underlay["path"] if self.underlay else None
        options = SsdOptionsDialog(self.root,
                                   ssdexport.suggest_options(underlay_path)).show()
        if not options:
            return

        filepath = filedialog.asksaveasfilename(
            title="Экспорт в SSD (МЭК 61850-6)",
            defaultextension=".ssd",
            initialfile=ssdexport.safe_file_name(options["substation"]) + ".ssd",
            filetypes=[("SSD (IEC 61850)", "*.ssd"),
                       ("SCL/XML", "*.xml"),
                       ("Все файлы", "*.*")])
        if not filepath:
            return

        try:
            stats = ssdexport.export_ssd(
                self.elements, self.connections, filepath,
                substation=options["substation"],
                voltage_level=options["voltage_level"],
                bay=options["bay"],
                voltage_kv=options["voltage_kv"],
                frequency_hz=options["frequency_hz"])
        except Exception as error:
            messagebox.showerror("SSD", f"Не удалось сохранить SSD:\n{error}")
            return

        message = ("Сохранено: {}\nОборудование: {}\nУзлы (ConnectivityNode): {}\n"
                   "Выводы (Terminal): {}").format(
            os.path.basename(filepath), stats["equipment"],
            stats["connectivity_nodes"], stats["terminals"])
        warnings = stats["warnings"]
        if warnings:
            shown = warnings[:8]
            message += "\n\nПредупреждения:\n" + "\n".join(shown)
            if len(warnings) > len(shown):
                message += f"\n… и ещё {len(warnings) - len(shown)}."
        messagebox.showinfo("SSD", message)

    # ================= СОХРАНЕНИЕ / ЗАГРУЗКА =================
    def save_json(self):
        data = {"elements": [], "connections": []}

        for el in self.elements.values():
            item = {
                "id": el.id,
                "type": el.type,
                "name": el.name,
                "x": el.x,
                "y": el.y
            }
            if el.type == "bus":
                item["length"] = el.length
            if hasattr(el, "rotation"):
                item["rotation"] = el.rotation
            if el.type == "corner":
                item["orientation"] = el.orientation
            offset = getattr(el, "label_offset", (0.0, 0.0))
            if offset and (offset[0] or offset[1]):
                item["label"] = [round(offset[0], 2), round(offset[1], 2)]
            if el.type == "cabinet":
                item["cabinet"] = {
                    "key": getattr(el, "cabinet_key", ""),
                    "title": getattr(el, "title", "Шкаф РЗА"),
                    "info": dict(getattr(el, "info", {})),
                    "komplets": copy.deepcopy(
                        getattr(el, "komplets", [])),
                }
            if el.type == "container":
                item["container"] = {
                    "key": getattr(el, "container_key", ""),
                    "code": getattr(el, "code", "КЭТ"),
                    "title": getattr(el, "title", "КЭТ"),
                    "size": getattr(el, "size", "20dc"),
                    "slots": el.slot_count(),
                    "info": dict(getattr(el, "info", {})),
                    "cabinets": list(getattr(el, "cabinets", [])),
                }
            data["elements"].append(item)

        for c in self.connections:
            el1 = self.elements.get(c.get("from"))
            el2 = self.elements.get(c.get("to"))
            if not el1 or not el2:
                continue
            p1 = el1.ports.get(c.get("port_from"))
            p2 = el2.ports.get(c.get("port_to"))
            if not p1 or not p2:
                continue
            data["connections"].append({
                "node_from": p1["node_id"],
                "node_to": p2["node_id"],
                "port_from": c["port_from"],
                "port_to": c["port_to"],
                "element_from": el1.id,
                "element_to": el2.id
            })

        # Ссылка на подложку: по ней схема открывается вместе с чертежом
        if self.underlay:
            data["underlay"] = {
                "path": os.path.abspath(self.underlay["path"]),
                "scale": self.underlay_scale,
                "visible": bool(self.show_underlay),
            }
        if self.protection_links:
            data["protection_links"] = [dict(link) for link in self.protection_links]
        if self.analog_links:
            data["analog_links"] = [dict(link) for link in self.analog_links]
        data["view"] = {
            "zoom": round(self.zoom, 4),
            "offset_x": round(self.offset_x, 2),
            "offset_y": round(self.offset_y, 2),
        }

        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath:
            # путь к подложке храним относительно файла схемы, чтобы папку можно было переносить
            if "underlay" in data:
                try:
                    base = os.path.dirname(os.path.abspath(filepath))
                    data["underlay"]["path"] = os.path.relpath(
                        data["underlay"]["path"], base)
                except ValueError:
                    pass
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                messagebox.showinfo("Успех", "Схема сохранена!")
            except OSError as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{e}")

    def load_json(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать файл:\n{e}")
            return

        # Схема собирается отдельно: при ошибке текущая схема остаётся нетронутой
        # (раньше файл сначала стирал полотно диалогом clear_all).
        try:
            elements = self._build_elements(data)
            connections = self._build_connections(data, elements)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить схему:\n{e}")
            return

        self._push_undo()
        self.elements = elements
        self.connections = connections
        self.protection_links = self._build_protection_links(
            data.get("protection_links", []))
        self.analog_links = self._build_analog_links(
            data.get("analog_links", []))
        self._reset_transient()

        underlay_info = data.get("underlay")
        if isinstance(underlay_info, dict):
            self._restore_underlay(
                underlay_info, os.path.dirname(os.path.abspath(filepath)))

        view_info = data.get("view")
        if isinstance(view_info, dict):
            try:
                self.zoom = float(view_info.get("zoom", self.zoom))
                self.offset_x = float(view_info.get("offset_x", self.offset_x))
                self.offset_y = float(view_info.get("offset_y", self.offset_y))
            except (TypeError, ValueError):
                pass

        self.redraw_all()
        if hasattr(self, "zoom_label"):
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")
        messagebox.showinfo("Успех", "Схема загружена!")

    @staticmethod
    def _cabinet_payload_meta(payload):
        """Данные шкафа из JSON схемы — для вида комплектов и ссылки на шкаф."""
        info = payload.get("info") or {}
        key = payload.get("key") or ""
        standard_key = "1" if (info.get("standard") or
                               info.get("standard_title")) else ""
        source = {}
        if not standard_key and key:
            source = cabs.find_cabinet(key) or {}
            standard_key = source.get("standard_key") or ""
        return {
            "key": key,
            "code": info.get("code") or source.get("code") or "",
            "name": info.get("name") or source.get("name") or "",
            "group": info.get("group") or source.get("group") or "",
            "standard_key": standard_key,
        }

    def _restore_cabinet(self, el, payload):
        """Восстанавливает шкаф из JSON схемы (поля каталога и комплекты)."""
        el.cabinet_key = payload.get("key", "")
        el.title = payload.get("title", el.title)
        el.info = dict(payload.get("info") or {})
        komplets = payload.get("komplets")
        if not isinstance(komplets, list):
            komplets = library.komplets_from_ieds(payload.get("ieds", []))
        meta = self._cabinet_payload_meta(payload)
        el.komplets = library.normalize_komplets(
            komplets, komplekts.cabinet_kit_kind(meta), meta)

    def _build_elements(self, data):
        """Создаёт элементы схемы из разобранного JSON, не трогая текущее полотно."""
        elements = {}
        for item in data.get("elements", []):
            el = library.create_component(item["type"], item["id"],
                                          item.get("x", 0), item.get("y", 0), self.grid_size)
            el.name = item.get("name", item["id"])

            if hasattr(el, "rotation") and item.get("rotation") is not None:
                el.rotation = item["rotation"]
            if el.type == "corner" and item.get("orientation"):
                el.orientation = item["orientation"]
            if el.type == "bus" and item.get("length"):
                el.length = item["length"]
            label = item.get("label")
            if isinstance(label, (list, tuple)) and len(label) == 2:
                el.label_offset = [float(label[0]), float(label[1])]
            if el.type == "cabinet":
                self._restore_cabinet(el, item.get("cabinet") or {})
            if el.type == "container":
                self._restore_container(el, item.get("container") or {})

            el.generate_ports()
            elements[item["id"]] = el

        # Подписи слотов — после того, как собраны все элементы
        self._sync_containers(elements)
        return elements

    def _restore_container(self, el, payload):
        """Восстанавливает контейнер из JSON (поля каталога и привязку шкафов)."""
        el.container_key = payload.get("key", "")
        el.code = payload.get("code") or el.code
        el.title = payload.get("title") or el.title
        el.size = payload.get("size", el.size)
        try:
            el.set_slots(payload.get("slots") or el.slots)
        except (TypeError, ValueError):
            pass
        cabinets = payload.get("cabinets") or []
        el.cabinets = [str(cabinet_id) for cabinet_id in cabinets
                       if cabinet_id][:el.slot_count()]
        while len(el.cabinets) < el.slot_count():
            el.cabinets.append("")
        el.slot_labels = [""] * el.slot_count()
        el.info = dict(payload.get("info") or {})

    def _build_protection_links(self, links, id_mapping=None):
        """Проверяет и (при вставке) переназначает защитные связи."""
        result = []
        for link in links or []:
            if not isinstance(link, dict):
                continue
            ied_ref = link.get("komplekt") or link.get("ied") or ""
            element_id = link.get("element") or ""
            cabinet_id, sep, index = ied_ref.partition("#")
            if not sep:
                continue
            if id_mapping is not None:
                cabinet_id = id_mapping.get(cabinet_id, "")
                element_id = id_mapping.get(element_id, "")
            cabinet = self.elements.get(cabinet_id)
            element = self.elements.get(element_id)
            if not cabinet or cabinet.type != "cabinet":
                continue
            if not element or not (
                    f"komplekt{index}" in cabinet.ports
                    or f"ied{index}" in cabinet.ports):
                continue
            result.append({"komplekt": f"{cabinet_id}#{index}",
                           "element": element_id})
        return result

    def _build_connections(self, data, elements):
        connections = []
        for c in data.get("connections", []):
            el1 = elements.get(c.get("element_from"))
            el2 = elements.get(c.get("element_to"))
            if not el1 or not el2:
                continue

            port1 = self._resolve_port(el1, c.get("port_from"), c.get("node_from"))
            port2 = self._resolve_port(el2, c.get("port_to"), c.get("node_to"))
            if port1 and port2:
                connections.append({
                    "from": el1.id, "to": el2.id,
                    "port_from": port1, "port_to": port2,
                    "canvas_id": None
                })
        return connections

    @staticmethod
    def _resolve_port(el, port_name, node_id):
        """Имя порта: прямое совпадение, затем поиск по node_id (совместимость со старыми файлами)."""
        if port_name in el.ports:
            return port_name
        if node_id:
            for p_name, p_data in el.ports.items():
                if p_data.get("node_id") == node_id:
                    return p_name
        return None

    def insert_from_json(self, event=None):
        """Вставляет схему из JSON-файла на текущее полотно"""
        filepath = filedialog.askopenfilename(
            title="Выберите файл схемы для вставки",
            filetypes=[("JSON files", "*.json")]
        )
        if not filepath:
            return
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if "elements" not in data or "connections" not in data:
                messagebox.showerror("Ошибка", "Неверный формат файла.")
                return

            if not data["elements"]:
                return

            # Состояние сохраняем ДО вставки, иначе Undo возвращал уже вставленную схему
            self._push_undo()

            # 1. Вычисляем смещение
            xs = [el["x"] for el in data["elements"]]
            ys = [el["y"] for el in data["elements"]]
            src_cx = sum(xs) / len(xs)
            src_cy = sum(ys) / len(ys)

            w = self.canvas.winfo_width() or 800
            h = self.canvas.winfo_height() or 700
            dst_cx, dst_cy = self.screen_to_world(w/2, h/2)
            
            offset_x = dst_cx - src_cx
            offset_y = dst_cy - src_cy
            
            if self.snap_to_grid:
                offset_x = round(offset_x / self.grid_size) * self.grid_size
                offset_y = round(offset_y / self.grid_size) * self.grid_size

            id_mapping = {}
            new_selected = []
            inserted_containers = []

            # 2. Вставляем элементы
            for item in data["elements"]:
                old_id = item["id"]
                new_id = f"{item['type'][:2].upper()}{str(uuid.uuid4())[:4]}"
                
                new_el = library.create_component(
                    item["type"], new_id, 
                    item["x"] + offset_x, 
                    item["y"] + offset_y, 
                    self.grid_size
                )
                
                new_el.name = self.get_next_name(
                    PREFIX_BY_TYPE.get(item["type"], "EL"),
                    item["type"]
                )
                
                if item.get("length") and hasattr(new_el, "length"):
                    new_el.length = item["length"]
                if item.get("rotation") is not None and hasattr(new_el, "rotation"):
                    new_el.rotation = item["rotation"]
                if item.get("orientation") and hasattr(new_el, "orientation"):
                    new_el.orientation = item["orientation"]
                label = item.get("label")
                if isinstance(label, (list, tuple)) and len(label) == 2:
                    new_el.label_offset = [float(label[0]), float(label[1])]
                if new_el.type == "cabinet":
                    self._restore_cabinet(new_el, item.get("cabinet") or {})
                if new_el.type == "container":
                    self._restore_container(new_el, item.get("container") or {})
                    inserted_containers.append(new_el)

                new_el.generate_ports()
                self.elements[new_id] = new_el
                id_mapping[old_id] = new_id
                new_selected.append(new_id)

            # 3. Восстанавливаем связи
            for conn in data["connections"]:
                old_from = conn.get("element_from")
                old_to = conn.get("element_to")
                
                if old_from in id_mapping and old_to in id_mapping:
                    new_from = id_mapping[old_from]
                    new_to = id_mapping[old_to]

                    # id пересоздан, поэтому node_id не совпадёт — ищем по имени порта
                    port_from = self._resolve_port(self.elements[new_from],
                                                   conn.get("port_from"), conn.get("node_from"))
                    port_to = self._resolve_port(self.elements[new_to],
                                                 conn.get("port_to"), conn.get("node_to"))

                    if port_from and port_to:
                        self.create_connection(new_from, new_to, port_from, port_to)

            # 3-бис. Привязка шкафов внутри вставленных контейнеров
            for container in inserted_containers:
                container.cabinets = [id_mapping.get(cabinet_id, "")
                                      for cabinet_id in container.cabinets]
                while len(container.cabinets) < container.slot_count():
                    container.cabinets.append("")
            self._sync_containers()

            # 3-бис. Аналоговые цепи внутри вставленного фрагмента
            inserted_analog = self._build_analog_links(
                data.get("analog_links", []), id_mapping)
            existing_analog = {(link["from"], link["to"])
                               for link in self.analog_links}
            for link in inserted_analog:
                key = (link["from"], link["to"])
                if key not in existing_analog:
                    self.analog_links.append(link)
                    existing_analog.add(key)

            # 3a. Защитные связи внутри вставленного фрагмента
            inserted_links = self._build_protection_links(
                data.get("protection_links", []), id_mapping)
            existing = {(self._link_ref(link), link["element"])
                        for link in self.protection_links}
            for link in inserted_links:
                key = (self._link_ref(link), link["element"])
                if key not in existing:
                    self.protection_links.append(link)
                    existing.add(key)

            # 4. Выделяем вставленное
            self.selected_elements = new_selected
            self.redraw_all()
            messagebox.showinfo("Успех", f"Вставлено {len(new_selected)} элементов.")
            
        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Файл поврежден или не является корректным JSON.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось вставить файл:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = CircuitEditor(root)
    root.mainloop()