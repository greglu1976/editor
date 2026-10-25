import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import uuid
import math
import copy
import os
import library
import pdfunderlay
import pdfexport
import ssdexport
import cabs

try:
    import pdf2json
except Exception:  # подписи в подложке необязательны
    pdf2json = None


# Префиксы имён по типу элемента — единый источник для добавления, копирования и вставки.
PREFIX_BY_TYPE = {
    "breaker": "Q", "disconnector": "QS", "transformer": "T",
    "split_transformer": "T", "three_winding_transformer": "T",
    "autotransformer": "AT", "reactor": "R", "line": "W",
    "bus": "BB", "node": "N", "corner": "C", "grounding_switch": "QSG",
    "ground": "G", "voltage_transformer": "TV", "current_transformer": "TA",
    "opn": "ОПН", "coupling_capacitor": "КС", "line_trap": "ВЧЗ",
    "connection_filter": "ФП", "av_breaker": "АВ", "fuse": "ПР",
    "cabinet": "Ш",
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

    def save_state(self, elements, connections, selected_elements, protection_links=None):
        """Сохраняет состояние и очищает стек redo (т.к. создана новая ветка)"""
        state = {
            "elements": copy.deepcopy(elements),
            "connections": copy.deepcopy(connections),
            "selected_elements": list(selected_elements),
            "protection": copy.deepcopy(protection_links or []),
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


def _ri_protlink(c):
    c.create_line(6, 26, 24, 8, width=2, arrow=tk.LAST)
    c.create_oval(22, 4, 28, 10, outline="black", width=1)


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
        self.root.title("Редактор электрических схем (Pro)")
        
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

        # Защита: шкафы РЗА, защитные узлы первичного оборудования и связи IED→узел
        self.protection_links = []
        self.show_protection = True     # стрелки IED→узел и ромбы-узлы
        self.show_cabinets = True       # сами шкафы
        self._protection_start = None    # ("ied", cabinet_id, index) | ("element", id)
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
                              ("Вид", self._build_ribbon_view)):
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
        self._ribbon_group(page, "Инструменты", lambda row: self._ribbon_button(
            row, "Выбрать/Двигать", lambda: self.set_tool("select"), _ri_select, 76).pack(side=tk.LEFT))
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
            self._ribbon_button(row, "Связь РЗА", lambda: self.set_tool("protection"),
                                _ri_protlink, 66).pack(side=tk.LEFT),
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
            self.show_protection_var = tk.BooleanVar(value=True)
            self._ribbon_toggle(row, "Связи РЗА", self.show_protection_var,
                                self.toggle_protection, _ri_protlink, 72).pack(side=tk.LEFT)

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

    # ================= ЗАЩИТА: ШКАФЫ, IED И ЗАЩИТНЫЕ СВЯЗИ =================
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
        """Добавляет шкаф из каталога cabs.py в центр видимой области."""
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

        self.undo_manager.save_state(self.elements, self.connections,
                                     self.selected_elements, self.protection_links)
        cabinet = library.create_component("cabinet", f"CA{uuid.uuid4().hex[:4]}",
                                           wx, wy, self.grid_size)
        cabinet.set_cabinet(definition)
        cabinet.name = self.get_next_name("Ш", "cabinet")
        self.elements[cabinet.id] = cabinet
        self.selected_elements = [cabinet.id]
        self.current_tool = "select"
        self.canvas.config(cursor="arrow")
        self._mark_active_tool()
        self.redraw_all()

    def _choose_cabinet(self):
        """Диалог выбора шкафа из cabs.py."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Шкаф РЗА")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        tk.Label(dialog,
                 text="Типовые шкафы ШЭТ по СТО ПАО «ФСК ЕЭС» — "
                      "Т/АТ, СКРМ, ЛЭП, СШ (архитектура II типа):",
                 anchor="w", fg="#555555").pack(fill=tk.X, padx=10, pady=(8, 4))
        frame = tk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        listbox = tk.Listbox(frame, width=78, height=max(3, min(16, len(cabs.CABINETS))),
                             activestyle="dotbox")
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

        for cabinet in cabs.CABINETS:
            listbox.insert("end", cabinet_label(cabinet))

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
            cabinet = cabs.CABINETS[selection[0]]
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
            ied_parts = []
            for ied in cabinet.get("ieds", []):
                functions = ", ".join(ied.get("functions", [])) or ied.get("desc", "")
                ied_parts.append(f'{ied.get("name", "IED")} ({functions})')
            if ied_parts:
                lines.append("IED: " + "; ".join(ied_parts))
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

        listbox.bind("<<ListboxSelect>>", update_info)
        if cabs.CABINETS:
            listbox.selection_set(0)
            update_info()

        def accept(event=None):
            selection = listbox.curselection()
            if selection:
                result["value"] = cabs.CABINETS[selection[0]]
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
    def _ied_port_at(self, sx, sy):
        """Ближайший порт IED на шкафах: (id шкафа, имя порта)."""
        tolerance = max(6.0, 12.0 * self.zoom)
        best = None
        best_dist = tolerance
        for element in self.elements.values():
            if element.type != "cabinet":
                continue
            if not self.show_cabinets:
                continue
            for port_name, port in element.ports.items():
                px, py = self.world_to_screen(port["x"], port["y"])
                dist = math.hypot(sx - px, sy - py)
                if dist <= best_dist:
                    best_dist = dist
                    best = (element.id, port_name)
        return best

    def _protection_link_at(self, sx, sy):
        if not self.show_protection or not self.show_cabinets:
            return None
        tolerance = max(4.0, 5.0 * self.zoom)
        for link in self.protection_links:
            cabinet_id, _, index = link["ied"].partition("#")
            cabinet = self.elements.get(cabinet_id)
            element = self.elements.get(link["element"])
            if not cabinet or not element:
                continue
            port = cabinet.ports.get(f"ied{index}")
            if not port:
                continue
            x1, y1 = self.world_to_screen(port["x"], port["y"])
            x2, y2 = self.world_to_screen(element.x, element.y)
            if self._point_segment_distance(sx, sy, x1, y1, x2, y2) <= tolerance:
                return link
        return None

    def _on_protection_click(self, event):
        """Клик в режиме «Связь РЗА»: IED → защитный узел (или наоборот)."""
        if self._protection_start is None:
            link = self._protection_link_at(event.x, event.y)
            if link is not None:
                self.undo_manager.save_state(self.elements, self.connections,
                                             self.selected_elements, self.protection_links)
                self.protection_links.remove(link)
                self.redraw_all()
                return

        ied = self._ied_port_at(event.x, event.y)
        if ied is not None:
            cabinet_id, port_name = ied
            if self._protection_start is None:
                self._protection_start = ("ied", cabinet_id, port_name)
            elif self._protection_start[0] == "element":
                self._add_protection_link(f"{cabinet_id}#{port_name[3:]}",
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
                elif self._protection_start[0] == "ied":
                    _, cabinet_id, port_name = self._protection_start
                    self._add_protection_link(f"{cabinet_id}#{port_name[3:]}", element_id)
                    self._protection_start = None
                else:
                    self._protection_start = None
                self.redraw_all()
                return

        if self._protection_start is not None:
            self._protection_start = None
            self.redraw_all()

    def _add_protection_link(self, ied_ref, element_id):
        cabinet_id, _, index = ied_ref.partition("#")
        cabinet = self.elements.get(cabinet_id)
        element = self.elements.get(element_id)
        if not cabinet or cabinet.type != "cabinet" or not element:
            return
        if f"ied{index}" not in cabinet.ports:
            return
        for link in self.protection_links:
            if link["ied"] == ied_ref and link["element"] == element_id:
                return
        self.undo_manager.save_state(self.elements, self.connections,
                                     self.selected_elements, self.protection_links)
        self.protection_links.append({"ied": ied_ref, "element": element_id})

    def _draw_protection(self):
        """Защитные узлы на оборудовании и стрелки IED → узел."""
        if not self.show_protection:
            return
        node_r = max(3.0, 4.5 * self.zoom)
        for element in self.elements.values():
            if element.type in ("cabinet", "corner", "node"):
                continue
            x, y = self.world_to_screen(element.x, element.y)
            self.canvas.create_polygon(
                x, y - node_r, x + node_r, y, x, y + node_r, x - node_r, y,
                fill="#1f4e79", outline="white",
                width=1, tags="protection_node")

        if self.show_cabinets:
            for link in self.protection_links:
                cabinet_id, _, index = link["ied"].partition("#")
                cabinet = self.elements.get(cabinet_id)
                element = self.elements.get(link["element"])
                if not cabinet or not element or cabinet.type != "cabinet":
                    continue
                port = cabinet.ports.get(f"ied{index}")
                if not port:
                    continue
                x1, y1 = self.world_to_screen(port["x"], port["y"])
                x2, y2 = self.world_to_screen(element.x, element.y)
                self.canvas.create_line(x1, y1, x2, y2, fill="#1f4e79",
                                        width=max(1, int(1.5 * self.zoom)),
                                        arrow=tk.LAST, tags="protection_link")

        if self._protection_start is not None:
            if self._protection_start[0] == "ied":
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
        if self.selection_rect_id:
            self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None

    def _apply_state(self, state):
        if state is None:
            return

        self.elements = state["elements"]
        self.connections = state["connections"]
        self.protection_links = state.get("protection", [])
        self._reset_transient()
        self.selected_elements = list(state["selected_elements"])

        self.redraw_all()

    def _capture_state(self):
        return {
            "elements": copy.deepcopy(self.elements),
            "connections": copy.deepcopy(self.connections),
            "selected_elements": list(self.selected_elements),
            "protection": copy.deepcopy(self.protection_links),
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
        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
        
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

    def paste_selection(self, event=None):
        if self.clipboard is None:
            return
        
        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
            
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
        
        prefix_map = {
            "breaker":"Q", "disconnector":"QS", "transformer":"T", 
            "split_transformer":"T", "three_winding_transformer":"T",
            "autotransformer":"AT", "reactor":"R", "line":"W", 
            "bus":"BB", "node":"N", "corner":"C", "grounding_switch":"QSG",
            "ground":"G", "voltage_transformer":"TV", "current_transformer":"TA"
        }
        
        for old_id, el_template in self.clipboard.items():
            new_id = f"{el_template.type[:2].upper()}{str(uuid.uuid4())[:4]}"
            
            new_el = library.create_component(
                el_template.type, new_id, 
                el_template.x + offset_x, 
                el_template.y + offset_y, 
                self.grid_size
            )
            
            new_el.name = self.get_next_name(
                prefix_map.get(el_template.type, "EL"),
                el_template.type
            )
            
            if hasattr(el_template, 'rotation'): new_el.rotation = el_template.rotation
            if hasattr(el_template, 'orientation'): new_el.orientation = el_template.orientation
            if hasattr(el_template, 'length'): new_el.length = el_template.length
            if hasattr(el_template, 'label_offset'):
                new_el.label_offset = list(el_template.label_offset)
            if el_template.type == "cabinet":
                new_el.cabinet_key = getattr(el_template, "cabinet_key", "")
                new_el.title = getattr(el_template, "title", new_el.title)
                new_el.info = dict(getattr(el_template, "info", {}))
                new_el.ieds = [dict(ied) for ied in getattr(el_template, "ieds", [])][:3]

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
                
        # 2. Элементы
        for el in self.elements.values():
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

        # 4a. Защитные узлы и стрелки IED → узел
        self._draw_protection()

        # 5. Рамка выделения
        highlight_color = "wheat4"
        highlight_width = max(1, int(2 * self.zoom))
        margin = 4 * self.zoom
        
        for el_id in self.selected_elements:
            if el_id in self.elements:
                el = self.elements[el_id]
                if el.type == "cabinet" and not self.show_cabinets:
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

    # ================= КЛИКИ =================
    def set_tool(self, tool):
        if tool == "delete":
            self.delete_selected()
            return
        had_protection_start = self._protection_start is not None
        self._protection_start = None
        self.current_tool = tool
        self.canvas.config(cursor="crosshair" if tool != "select" else "arrow")
        self._mark_active_tool()
        if had_protection_start:
            self.redraw_all()

    def delete_selected(self, event=None):
        """Удаляет выделенные элементы (и все их связи) одним действием."""
        if not self.selected_elements:
            return
        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
        for el_id in list(self.selected_elements):
            self.delete_element(el_id)
        self._reset_transient()
        self.redraw_all()

    def _element_at(self, sx, sy):
        """id элемента под курсором (верхний в порядке отрисовки) или None."""
        for el in reversed(list(self.elements.values())):
            if el.type == "cabinet" and not self.show_cabinets:
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
                    self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
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
                        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
                        self.create_connection(start_id, best_port_el, start_port, best_port_name)
                    self.canvas.delete("link_start")
                    self.link_start = None
                    self.redraw_all()
            return

        # ИНСТРУМЕНТ «СВЯЗЬ РЗА»: IED ↔ защитный узел оборудования
        if self.current_tool == "protection":
            self._on_protection_click(event)
            return

        # ДОБАВЛЕНИЕ НОВЫХ ЭЛЕМЕНТОВ
        tool = self.current_tool
        if tool in library.COMPONENT_TYPES:
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
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
        clicked_el = None
        for el in reversed(list(self.elements.values())):
            bx1, by1, bx2, by2 = el.get_bounding_box()
            sx1, sy1 = self.world_to_screen(bx1, by1)
            sx2, sy2 = self.world_to_screen(bx2, by2)
            if sx1 <= event.x <= sx2 and sy1 <= event.y <= sy2:
                clicked_el = el
                break
        
        if clicked_el:
            new_name = simpledialog.askstring("Переименование", f"Введите новое имя для {clicked_el.type}:", initialvalue=clicked_el.name)
            
            if new_name is not None:
                new_name = new_name.strip()
                
                # Пустые имена разрешены, но не участвуют в проверке уникальности
                for other_el in self.elements.values():
                    if new_name and other_el.id != clicked_el.id and other_el.name.lower() == new_name.lower():
                        messagebox.showerror("Ошибка", f"Элемент с именем '{new_name}' уже существует на схеме!\nИмена должны быть уникальными.")
                        return
                
                self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
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
        del self.elements[el_id]
        self.connections = [c for c in self.connections if c["from"] != el_id and c["to"] != el_id]
        # Защитные связи удалённого оборудования/шкафа
        self.protection_links = [
            link for link in self.protection_links
            if link["element"] != el_id and link["ied"].split("#")[0] != el_id
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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
            self.elements = {}
            self.connections = []
            self._reset_transient()
            self.clipboard = None
            self.clipboard_connections = []
            self.redraw_all()

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

        for element in self.elements.values():
            if element.type == "cabinet" and not self.show_cabinets:
                continue
            element.draw(canvas, 1.0, 0.0, 0.0)

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
                    "ieds": [dict(ied) for ied in getattr(el, "ieds", [])],
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

        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)
        self.elements = elements
        self.connections = connections
        self.protection_links = self._build_protection_links(
            data.get("protection_links", []))
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
                cabinet = item.get("cabinet") or {}
                el.cabinet_key = cabinet.get("key", "")
                el.title = cabinet.get("title", el.title)
                el.info = dict(cabinet.get("info") or {})
                el.ieds = [dict(ied) for ied in cabinet.get("ieds", [])][:3]

            el.generate_ports()
            elements[item["id"]] = el
        return elements

    def _build_protection_links(self, links, id_mapping=None):
        """Проверяет и (при вставке) переназначает защитные связи."""
        result = []
        for link in links or []:
            if not isinstance(link, dict):
                continue
            ied_ref = link.get("ied") or ""
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
            if not element or f"ied{index}" not in cabinet.ports:
                continue
            result.append({"ied": f"{cabinet_id}#{index}", "element": element_id})
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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements, self.protection_links)

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
                    cabinet = item.get("cabinet") or {}
                    new_el.cabinet_key = cabinet.get("key", "")
                    new_el.title = cabinet.get("title", new_el.title)
                    new_el.info = dict(cabinet.get("info") or {})
                    new_el.ieds = [dict(ied) for ied in cabinet.get("ieds", [])][:3]

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

            # 3a. Защитные связи внутри вставленного фрагмента
            inserted_links = self._build_protection_links(
                data.get("protection_links", []), id_mapping)
            existing = {(link["ied"], link["element"]) for link in self.protection_links}
            for link in inserted_links:
                key = (link["ied"], link["element"])
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