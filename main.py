import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import uuid
import math
import copy
import library



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
        
        # Рамка выделения
        self.selection_start = None       
        self.selection_start_screen = None 
        self.selection_rect_id = None     
        
        # Перетаскивание группы
        self.dragging_group = False
        self.drag_offsets = {}
        
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
        # === ВЕРХНЯЯ ПАНЕЛЬ ИНСТРУМЕНТОВ ===
        toolbar = tk.Frame(self.root, bg="#f0f0f0", bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        btn_select = tk.Button(toolbar, text=" Выбрать/Двигать", width=18, anchor="w", 
                               command=lambda: self.set_tool("select"))
        btn_select.pack(side=tk.LEFT, padx=5, pady=2)
        
        tk.Frame(toolbar, width=2, bg="gray").pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=4)
        
        # КНОПКИ UNDO / REDO
        self.btn_undo = tk.Button(toolbar, text="↩ Назад", width=8, command=self.undo_last_action)
        self.btn_undo.pack(side=tk.LEFT, padx=2, pady=2)
        
        self.btn_redo = tk.Button(toolbar, text=" Вперед", width=8, command=self.redo_last_action)
        self.btn_redo.pack(side=tk.LEFT, padx=2, pady=2)
        
        tk.Frame(toolbar, width=2, bg="gray").pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=4)
        
        btn_copy = tk.Button(toolbar, text="📋 Копировать", width=12, command=self.copy_selection)
        btn_copy.pack(side=tk.LEFT, padx=2, pady=2)
        
        btn_paste = tk.Button(toolbar, text="📥 Вставить", width=12, command=self.paste_selection)
        btn_paste.pack(side=tk.LEFT, padx=2, pady=2)
        
        tk.Frame(toolbar, width=2, bg="gray").pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=4)
        
        tk.Button(toolbar, text="💾 Сохранить", command=self.save_json).pack(side=tk.LEFT, padx=5, pady=2)
        tk.Button(toolbar, text="📂 Загрузить", command=self.load_json).pack(side=tk.LEFT, padx=5, pady=2)
        tk.Button(toolbar, text=" Очистить", command=self.clear_all).pack(side=tk.LEFT, padx=5, pady=2)
        tk.Button(toolbar, text=" Вставить из файла", width=16, command=self.insert_from_json).pack(side=tk.LEFT, padx=2, pady=2)

        # === ЛЕВАЯ ПАЛИТРА ===
        palette = tk.Frame(self.root, width=180, bg="#f0f0f0")
        palette.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        tk.Label(palette, text="Элементы схемы", font=("Arial", 12, "bold"), bg="#f0f0f0").pack(pady=5)
        
        tools = [
            ("Выключатель", "breaker"), ("Разъединитель", "disconnector"), ("Шина", "bus"),
            ("Трансформатор", "transformer"), ("Трансф. с расщеп.", "split_transformer"),
            ("Трехобм. трансф.", "three_winding_transformer"), ("Автотрансформатор", "autotransformer"),
            ("Реактор", "reactor"), ("ЛЭП", "line"), ("Уголок", "corner"),
            ("Зазем. разъед.", "grounding_switch"), ("Узел (голубой)", "node"),
            ("---", "separator"), ("Связать элементы", "connect"), ("Удалить выбранное", "delete")
        ]
        
        for text, tool in tools:
            if tool == "separator":
                tk.Frame(palette, height=2, bg="gray").pack(fill=tk.X, pady=5)
                continue
            btn = tk.Button(palette, text=text, width=18, anchor="w", command=lambda t=tool: self.set_tool(t))
            btn.pack(pady=2, fill=tk.X)

        tk.Label(palette, text="Настройки", font=("Arial", 10, "bold"), bg="#f0f0f0").pack(pady=(15, 2))
        self.snap_var = tk.BooleanVar(value=True)
        tk.Checkbutton(palette, text="Привязка к сетке", variable=self.snap_var, command=self.toggle_snap, bg="#f0f0f0").pack(anchor="w", padx=5)
        
        self.show_nodes_var = tk.BooleanVar(value=True)
        tk.Checkbutton(palette, text="Показать все узлы", variable=self.show_nodes_var, 
                       command=self.toggle_show_nodes, bg="#f0f0f0").pack(anchor="w", padx=5, pady=(5,0))
                       
        tk.Label(palette, text="Шаг сетки:", bg="#f0f0f0").pack(anchor="w", padx=5, pady=(5,0))
        self.grid_spin = tk.Spinbox(palette, from_=5, to=100, increment=5, command=self.change_grid_size, width=5)
        self.grid_spin.delete(0, "end")
        self.grid_spin.insert(0, str(self.grid_size))
        self.grid_spin.pack(anchor="w", padx=5, pady=2)
        
        self.zoom_label = tk.Label(palette, text="Масштаб: 100%", bg="#f0f0f0", fg="blue")
        self.zoom_label.pack(anchor="w", padx=5, pady=10)
        tk.Button(palette, text="Сбросить вид", command=self.reset_view).pack(anchor="w", padx=5, pady=2)

        self.canvas = tk.Canvas(self.root, bg="white", width=800, height=700)
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

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
        self.root.bind("<r>", self.rotate_selected)
        self.root.bind("<R>", self.rotate_selected)
        self.root.bind("<Escape>", self.deselect_all)
        
        self.root.bind("<Control-c>", self.copy_selection)
        self.root.bind("<Control-v>", self.paste_selection)
        self.root.bind("<Control-z>", self.undo_last_action)
        self.root.bind("<Control-y>", self.redo_last_action) # <--- НОВОЕ: Ctrl+Y для Redo
        self.root.bind("<Control-Shift-Z>", self.redo_last_action) # Альтернатива Ctrl+Shift+Z

    # ================= ОТМЕНА / ПОВТОР =================
    def _apply_state(self, state):
        """Применяет сохраненное состояние к редактору"""
        if state is None:
            return
            
        self.elements = state["elements"]
        self.connections = state["connections"]
        self.selected_elements = state["selected_elements"]
        
        # Сбрасываем временные состояния редактирования
        self.dragging_group = False
        self.drag_offsets = {}
        self.resizing_element = None
        self.resize_handle = None
        self.selection_start = None
        self.selection_start_screen = None
        if self.selection_rect_id:
            self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None
            
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
            self.zoom_label.config(text=f"Масштаб: {int(self.zoom * 100)}%")

    def reset_view(self):
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.redraw_all()
        self.zoom_label.config(text="Масштаб: 100%")

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
        try:
            self.grid_size = int(self.grid_spin.get())
            if self.grid_size < 2: self.grid_size = 2
            for el in self.elements.values():
                el.grid_size = self.grid_size
                el.generate_ports()
            self.draw_grid()
            self.redraw_all()
        except ValueError: pass

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
        
        if self.selected_elements:
            orig_cx = sum(self.elements[eid].x for eid in self.selected_elements if eid in self.elements) / len(self.selected_elements)
            orig_cy = sum(self.elements[eid].y for eid in self.selected_elements if eid in self.elements) / len(self.selected_elements)
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
            "bus":"BB", "node":"N", "corner":"C", "grounding_switch":"QSG"
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
                    
        # 4. Все узлы
        if self.show_all_nodes:
            for el in self.elements.values():
                for p_name, p_data in el.ports.items():
                    sx, sy = self.world_to_screen(p_data["x"], p_data["y"])
                    r = 3 * self.zoom
                    self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, outline="orange", fill="yellow")

        # 5. ФИОЛЕТОВАЯ РАМКА ВЫДЕЛЕНИЯ
        highlight_color = "#8A2BE2"
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

        # 6. Активная рамка мыши
        if self.selection_start is not None and self.selection_rect_id is not None:
            pass 

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
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            for el_id in list(self.selected_elements):
                self.delete_element(el_id)
            self.selected_elements = []
            self.redraw_all()
        else:
            self.current_tool = tool
            self.canvas.config(cursor="crosshair" if tool != "select" else "arrow")

    def on_left_click(self, event):
        wx, wy = self.screen_to_world(event.x, event.y)
        wx, wy = self.snap(wx, wy)
        
        # УДАЛЕНИЕ СВЯЗИ ТОЛЬКО В РЕЖИМЕ SELECT
        if self.current_tool == "select":
            items = self.canvas.find_closest(event.x, event.y)
            if items:
                item_id = items[0]
                conn_to_delete = None
                for c in self.connections:
                    if c.get("canvas_id") == item_id:
                        conn_to_delete = c
                        break
                if conn_to_delete:
                    self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
                    self.connections.remove(conn_to_delete)
                    self.redraw_all()
                    return
        
        # ОБРАБОТКА ИНСТРУМЕНТА SELECT
        if self.current_tool == "select":
            
            # А) ПРОВЕРКА МАРКЕРОВ ИЗМЕНЕНИЯ РАЗМЕРА ШИНЫ
            for el_id in self.selected_elements:
                if el_id in self.elements and self.elements[el_id].type == "bus":
                    handle = self.find_resize_handle(el_id, event.x, event.y)
                    if handle:
                        self.resizing_element = el_id
                        self.resize_handle = handle
                        return 

            # Б) ПРОВЕРКА КЛИКА ПО ЭЛЕМЕНТУ
            clicked_el = None
            for el in reversed(list(self.elements.values())):
                bx1, by1, bx2, by2 = el.get_bounding_box()
                sx1, sy1 = self.world_to_screen(bx1, by1)
                sx2, sy2 = self.world_to_screen(bx2, by2)
                if sx1 <= event.x <= sx2 and sy1 <= event.y <= sy2:
                    clicked_el = el.id
                    break
            
            if clicked_el:
                if clicked_el not in self.selected_elements:
                    self.selected_elements = [clicked_el]
                
                self.dragging_group = True
                mouse_wx, mouse_wy = wx, wy
                self.drag_offsets = {}
                for el_id in self.selected_elements:
                    el = self.elements[el_id]
                    self.drag_offsets[el_id] = (mouse_wx - el.x, mouse_wy - el.y)
                
                self.redraw_all()
                return
            
            # В) КЛИК ПО ПУСТОМУ МЕСТУ
            self.selection_start = (wx, wy)
            self.selection_start_screen = (event.x, event.y)
            sx_start, sy_start = event.x, event.y
            self.selection_rect_id = self.canvas.create_rectangle(
                sx_start, sy_start, sx_start, sy_start,
                outline="#8A2BE2", fill="#8A2BE2", stipple="gray50", width=2
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
        if tool in ["breaker", "disconnector", "bus", "transformer", "line", "node", "corner", 
                     "grounding_switch", "split_transformer", "three_winding_transformer", 
                     "autotransformer", "reactor"]:
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            self.add_element(tool, wx, wy)

    def get_next_name(self, prefix, el_type):
        existing_numbers = []
        for el in self.elements.values():
            if el.type == el_type and el.name.startswith(prefix):
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
                if new_name == "":
                    messagebox.showwarning("Ошибка", "Имя не может быть пустым.")
                    return
                
                for other_el in self.elements.values():
                    if other_el.id != clicked_el.id and other_el.name.lower() == new_name.lower():
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
                el.length = new_length
                el.x = fixed_edge + new_length
            elif self.resize_handle == "left":
                fixed_edge = el.x + el.length
                new_length = fixed_edge - wx
                if new_length < self.grid_size: new_length = self.grid_size
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
            self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None
            self.redraw_all()
            return

        # ЗАВЕРШЕНИЕ ПЕРЕТАСКИВАНИЯ
        if self.dragging_group:
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            self.dragging_group = False
            self.drag_offsets = {}
            return

        # ЗАВЕРШЕНИЕ ИЗМЕНЕНИЯ РАЗМЕРА ШИНЫ
        if self.resizing_element:
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            self.resizing_element = None
            self.resize_handle = None
            self.redraw_all()

    def on_right_click(self, event):
        clicked_el = None
        for el in reversed(list(self.elements.values())):
            bx1, by1, bx2, by2 = el.get_bounding_box()
            sx1, sy1 = self.world_to_screen(bx1, by1)
            sx2, sy2 = self.world_to_screen(bx2, by2)
            if sx1 <= event.x <= sx2 and sy1 <= event.y <= sy2:
                clicked_el = el.id
                break
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
        
        if etype == "breaker": prefix, el_type = "Q", "breaker"
        elif etype == "disconnector": prefix, el_type = "QS", "disconnector"
        elif etype == "transformer": prefix, el_type = "T", "transformer"
        elif etype == "split_transformer": prefix, el_type = "T", "split_transformer"
        elif etype == "three_winding_transformer": prefix, el_type = "T", "three_winding_transformer"
        elif etype == "autotransformer": prefix, el_type = "AT", "autotransformer"
        elif etype == "reactor": prefix, el_type = "R", "reactor"
        elif etype == "line": prefix, el_type = "W", "line"
        elif etype == "bus": prefix, el_type = "BB", "bus"
        elif etype == "node": prefix, el_type = "N", "node"
        elif etype == "corner": prefix, el_type = "C", "corner"
        elif etype == "grounding_switch": prefix, el_type = "QSG", "grounding_switch"
        else: prefix, el_type = "EL", etype
        
        el.name = self.get_next_name(prefix, el_type)
        
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
            self.selected_elements = []
            self.link_start = None
            self.resizing_element = None
            self.dragging_group = False
            self.selection_start = None
            self.selection_start_screen = None
            self.clipboard = None
            self.clipboard_connections = []
            if self.selection_rect_id:
                self.canvas.delete(self.selection_rect_id)
                self.selection_rect_id = None
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
            if el.type == "bus": item["length"] = el.length
            if el.type in ["disconnector", "transformer", "line", "grounding_switch", "reactor"]: 
                item["rotation"] = el.rotation
            if el.type == "corner":
                item["orientation"] = el.orientation
            data["elements"].append(item)
            
        for c in self.connections:
            el1 = self.elements[c["from"]]
            el2 = self.elements[c["to"]]
            node1 = el1.ports[c["port_from"]]["node_id"]
            node2 = el2.ports[c["port_to"]]["node_id"]
            data["connections"].append({
                "node_from": node1,
                "node_to": node2,
                "element_from": el1.id,
                "element_to": el2.id
            })
            
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            messagebox.showinfo("Успех", "Схема сохранена!")

    def load_json(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if not filepath: return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.clear_all()
            
            for item in data.get("elements", []):
                el = library.create_component(item["type"], item["id"], item["x"], item["y"], self.grid_size)
                el.name = item.get("name", item["id"])
                
                if el.type == "bus" and "length" in item:
                    el.length = item["length"]
                    el.generate_ports()
                if el.type in ["disconnector", "transformer", "line", "grounding_switch", "reactor"] and "rotation" in item:
                    el.rotation = item["rotation"]
                    el.generate_ports()
                if el.type == "corner" and "orientation" in item:
                    el.orientation = item["orientation"]
                    el.generate_ports()
                self.elements[item["id"]] = el
                
            for c in data.get("connections", []):
                el1_id = c.get("element_from")
                el2_id = c.get("element_to")
                
                if el1_id in self.elements and el2_id in self.elements:
                    el1 = self.elements[el1_id]
                    el2 = self.elements[el2_id]
                    
                    port1 = None
                    for p_name, p_data in el1.ports.items():
                        if p_data["node_id"] == c["node_from"]:
                            port1 = p_name
                            break
                    
                    port2 = None
                    for p_name, p_data in el2.ports.items():
                        if p_data["node_id"] == c["node_to"]:
                            port2 = p_name
                            break
                    
                    if port1 and port2:
                        self.connections.append({
                            "from": el1_id, "to": el2_id,
                            "port_from": port1, "port_to": port2,
                            "canvas_id": None
                        })
            
            self.redraw_all()
            messagebox.showinfo("Успех", "Схема загружена!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить файл:\n{e}")



    def insert_from_json1(self, event=None):
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
            
            prefix_map = {
                "breaker":"Q", "disconnector":"QS", "transformer":"T", 
                "split_transformer":"T", "three_winding_transformer":"T",
                "autotransformer":"AT", "reactor":"R", "line":"W", 
                "bus":"BB", "node":"N", "corner":"C", "grounding_switch":"QSG"
            }

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
                    prefix_map.get(item["type"], "EL"),
                    item["type"]
                )
                
                if item.get("length"): new_el.length = item["length"]
                if item.get("rotation") is not None: new_el.rotation = item["rotation"]
                if item.get("orientation"): new_el.orientation = item["orientation"]
                
                new_el.generate_ports()
                self.elements[new_id] = new_el
                id_mapping[old_id] = new_id
                new_selected.append(new_id)

            inserted_ids = set(id_mapping.values())
            
            for conn in data["connections"]:
                old_from = conn.get("element_from")
                old_to = conn.get("element_to")
                
                if old_from in id_mapping and old_to in id_mapping:
                    new_from = id_mapping[old_from]
                    new_to = id_mapping[old_to]
                    
                    port_from = None
                    port_to = None
                    
                    el_from = self.elements[new_from]
                    el_to = self.elements[new_to]
                    
                    target_node_from = conn.get("node_from")
                    target_node_to = conn.get("node_to")
                    
                    for p_name, p_data in el_from.ports.items():
                        if p_data["node_id"] == target_node_from:
                            port_from = p_name
                            break
                            
                    for p_name, p_data in el_to.ports.items():
                        if p_data["node_id"] == target_node_to:
                            port_to = p_name
                            break
                    
                    if port_from and port_to:
                        self.create_connection(new_from, new_to, port_from, port_to)

            self.selected_elements = new_selected
            self.redraw_all()
            messagebox.showinfo("Успех", f"Вставлено {len(new_selected)} элементов.")
            
        except json.JSONDecodeError:
            messagebox.showerror("Ошибка", "Файл поврежден или не является корректным JSON.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось вставить файл:\n{e}")


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

            # Инициализируем списки ДО цикла
            id_mapping = {}
            new_selected = [] 
            
            prefix_map = {
                "breaker":"Q", "disconnector":"QS", "transformer":"T", 
                "split_transformer":"T", "three_winding_transformer":"T",
                "autotransformer":"AT", "reactor":"R", "line":"W", 
                "bus":"BB", "node":"N", "corner":"C", "grounding_switch":"QSG"
            }

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
                    prefix_map.get(item["type"], "EL"),
                    item["type"]
                )
                
                if item.get("length"): new_el.length = item["length"]
                if item.get("rotation") is not None: new_el.rotation = item["rotation"]
                if item.get("orientation"): new_el.orientation = item["orientation"]
                
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
                    
                    port_from = None
                    port_to = None
                    
                    el_from = self.elements[new_from]
                    el_to = self.elements[new_to]
                    
                    target_node_from = conn.get("node_from")
                    target_node_to = conn.get("node_to")
                    
                    for p_name, p_data in el_from.ports.items():
                        if p_data["node_id"] == target_node_from:
                            port_from = p_name
                            break
                            
                    for p_name, p_data in el_to.ports.items():
                        if p_data["node_id"] == target_node_to:
                            port_to = p_name
                            break
                    
                    if port_from and port_to:
                        self.create_connection(new_from, new_to, port_from, port_to)

            # 4. Сохраняем состояние для Undo и выделяем
            # new_selected гарантированно существует здесь
            self.undo_manager.save_state(self.elements, self.connections, self.selected_elements)
            
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