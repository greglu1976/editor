import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import uuid
import math
import copy
import library


# Префиксы имён по типу элемента — единый источник для добавления, копирования и вставки.
PREFIX_BY_TYPE = {
    "breaker": "Q", "disconnector": "QS", "transformer": "T",
    "split_transformer": "T", "three_winding_transformer": "T",
    "autotransformer": "AT", "reactor": "R", "line": "W",
    "bus": "BB", "node": "N", "corner": "C", "grounding_switch": "QSG",
    "ground": "G", "voltage_transformer": "TV", "current_transformer": "TA",
    "opn": "ОПН", "coupling_capacitor": "КС", "line_trap": "ВЧЗ",
    "connection_filter": "ФП", "av_breaker": "АВ", "fuse": "ПР",
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

    def save_state(self, elements, connections, selected_elements):
        """Сохраняет состояние и очищает стек redo (т.к. создана новая ветка)"""
        state = {
            "elements": copy.deepcopy(elements),
            "connections": copy.deepcopy(connections),
            "selected_elements": list(selected_elements)
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
        
        # Буфер обмена
        self.clipboard = None          
        self.clipboard_connections = []
        
        # Изменение размера шины
        self.resizing_element = None
        self.resize_handle = None
        
        # Менеджер отмены/повтора
        self.undo_manager = UndoManager()

        self.grid_size = 20
        self.grid_color = "#e0e0e0"
        self.snap_to_grid = True
        
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        
        self.show_all_nodes = True

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
        self._refresh_ribbon_toggles()
        return page

    def _zoom_step(self, factor):
        w = self.canvas.winfo_width() or 800
        h = self.canvas.winfo_height() or 700
        mx, my = self.screen_to_world(w / 2, h / 2)
        new_zoom = self.zoom * factor
        if 0.2 < new_zoom < 5.0:
            self.zoom = new_zoom
            self.offset_x = w / 2 - mx * self.zoom
            self.offset_y = h / 2 - my * self.zoom
            self.redraw_all()
            self.zoom_label.config(text=f"{int(self.zoom * 100)}%")

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
        self.canvas.bind("<Configure>", lambda e: self.redraw_all())
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
        if self.selection_rect_id:
            self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None

    def _apply_state(self, state):
        if state is None:
            return

        self.elements = state["elements"]
        self.connections = state["connections"]
        self._reset_transient()
        self.selected_elements = list(state["selected_elements"])

        self.redraw_all()

    def _capture_state(self):
        return {
            "elements": copy.deepcopy(self.elements),
            "connections": copy.deepcopy(self.connections),
            "selected_elements": list(self.selected_elements),
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
        if 0.2 < new_zoom < 5.0:
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
        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
        
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
        
        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            
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

        # 5. Рамка выделения
        highlight_color = "wheat4"
        highlight_width = max(1, int(2 * self.zoom))
        margin = 4 * self.zoom
        
        for el_id in self.selected_elements:
            if el_id in self.elements:
                el = self.elements[el_id]
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
        self.current_tool = tool
        self.canvas.config(cursor="crosshair" if tool != "select" else "arrow")
        self._mark_active_tool()

    def delete_selected(self, event=None):
        """Удаляет выделенные элементы (и все их связи) одним действием."""
        if not self.selected_elements:
            return
        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
        for el_id in list(self.selected_elements):
            self.delete_element(el_id)
        self._reset_transient()
        self.redraw_all()

    def _element_at(self, sx, sy):
        """id элемента под курсором (верхний в порядке отрисовки) или None."""
        for el in reversed(list(self.elements.values())):
            bx1, by1, bx2, by2 = el.get_bounding_box()
            sx1, sy1 = self.world_to_screen(bx1, by1)
            sx2, sy2 = self.world_to_screen(bx2, by2)
            if sx1 <= sx <= sx2 and sy1 <= sy <= sy2:
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

            clicked_el = self._element_at(event.x, event.y)

            # Б) УДАЛЕНИЕ СВЯЗИ — только при точном попадании в линию
            #    и только если под курсором нет элемента
            if clicked_el is None:
                conn_to_delete = self._connection_at(event.x, event.y)
                if conn_to_delete is not None:
                    self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
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
                        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
                        self.create_connection(start_id, best_port_el, start_port, best_port_name)
                    self.canvas.delete("link_start")
                    self.link_start = None
                    self.redraw_all()
            return

        # ДОБАВЛЕНИЕ НОВЫХ ЭЛЕМЕНТОВ
        tool = self.current_tool
        if tool in library.COMPONENT_TYPES:
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
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
                
                self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
                clicked_el.name = new_name
                self.redraw_all()

    def on_drag(self, event):
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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            self.elements = {}
            self.connections = []
            self._reset_transient()
            self.clipboard = None
            self.clipboard_connections = []
            self.redraw_all()

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

        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath:
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

        self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
        self.elements = elements
        self.connections = connections
        self._reset_transient()
        self.redraw_all()
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

            el.generate_ports()
            elements[item["id"]] = el
        return elements

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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)

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