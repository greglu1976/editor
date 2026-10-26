# library.py

import math
import tkinter as tk

# Базовая единица геометрии элементов в мировых координатах.
# Не зависит от шага сетки: изменение шага меняет только привязку и вид сетки,
# но не размеры и пропорции элементов схемы.
CELL = 20


def draw_earth(canvas, gx, gy, zoom, direction="down"):
    """Символ заземления: три убывающих штриха (единый для всех элементов).

    Толщина линий и размеры штрихов одинаковы у заземления и у заземляющего
    разъединителя — символ рисуется этой функцией в обоих местах.
    """
    width = max(1, int(3 * zoom))
    lengths = (10, 6, 2)          # половина длины штриха
    gaps = (0, 5, 10)             # смещение штриха от точки подключения
    for half, gap in zip(lengths, gaps):
        if direction == "down":
            x1, y1 = gx - half * zoom, gy + gap * zoom
            x2, y2 = gx + half * zoom, gy + gap * zoom
        elif direction == "up":
            x1, y1 = gx - half * zoom, gy - gap * zoom
            x2, y2 = gx + half * zoom, gy - gap * zoom
        elif direction == "left":
            x1, y1 = gx - gap * zoom, gy - half * zoom
            x2, y2 = gx - gap * zoom, gy + half * zoom
        else:                      # right
            x1, y1 = gx + gap * zoom, gy - half * zoom
            x2, y2 = gx + gap * zoom, gy + half * zoom
        canvas.create_line(x1, y1, x2, y2, width=width, fill="black")


def rotate_point(dx, dy, rotation):
    """Поворот локального вектора (градусы, по часовой стрелке на экране)."""
    rotation %= 360
    if rotation == 0:
        return dx, dy
    angle = math.radians(rotation)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a


class Component:
    def __init__(self, comp_id, x, y, grid_size=20):
        self.id = comp_id
        self.name = ""
        self.x = x
        self.y = y
        # Шаг сетки на момент создания оставлен для совместимости; геометрию задаёт CELL.
        self.grid_size = grid_size
        self.cell = CELL
        self.type = "base"
        self.ports = {}
        # Смещение подписи относительно штатного места (мировые единицы)
        self.label_offset = [0.0, 0.0]
        # Экранный bbox подписи, обновляется при отрисовке (для перетаскивания мышкой)
        self._label_bbox = None

    def _local_rotated(self, dx, dy):
        """Локальные координаты относительно центра -> мировые с учётом поворота."""
        rdx, rdy = rotate_point(dx, dy, getattr(self, "rotation", 0))
        return self.x + rdx, self.y + rdy

    def _rotated_bbox(self, local_box):
        """Локальный прямоугольник -> габариты в мировых координатах с учётом поворота."""
        x1, y1, x2, y2 = local_box
        corners = [self._local_rotated(px, py) for px, py in
                   ((x1, y1), (x2, y1), (x1, y2), (x2, y2))]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def _label_text(self, canvas, zoom, offset_x, offset_y, world_x, world_y,
                    anchor="w", size=10):
        """Рисует подпись в мировой точке с учётом смещения, заданного мышкой."""
        if not self.name:
            self._label_bbox = None
            return
        dx, dy = self.label_offset
        sx = (world_x + dx) * zoom + offset_x
        sy = (world_y + dy) * zoom + offset_y
        item = canvas.create_text(sx, sy, text=self.name, anchor=anchor,
                                  font=("Arial", int(size * zoom)), fill="black",
                                  tags="element_label")
        # bbox нужен для перетаскивания мышкой; у экспортного адаптера его нет
        try:
            self._label_bbox = canvas.bbox(item) if item is not None else None
        except Exception:
            self._label_bbox = None

    def _draw_label(self, canvas, zoom, offset_x, offset_y):
        """Подпись справа от габарита: не наезжает на провода при любом повороте."""
        bx1, by1, bx2, by2 = self.get_bounding_box()
        self._label_text(canvas, zoom, offset_x, offset_y,
                         bx2 + 6, (by1 + by2) / 2.0)

    def _draw_name_at(self, canvas, zoom, offset_x, offset_y, local_x, local_y=0.0,
                      anchor="w", size=10):
        """Подпись в фиксированной локальной точке — исходное место символа."""
        wx, wy = self._local_rotated(local_x, local_y)
        self._label_text(canvas, zoom, offset_x, offset_y, wx, wy,
                         anchor=anchor, size=size)

    def generate_ports(self):
        pass

    def draw(self, canvas, zoom, offset_x, offset_y):
        pass

    def get_bounding_box(self):
        return (self.x - 10, self.y - 10, self.x + 10, self.y + 10)


# ==========================================
# 1. ВЫКЛЮЧАТЕЛЬ (2 порта)
# ==========================================
class Breaker(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "breaker"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        r = self.cell
        if self.rotation in [0, 180]:
            self.ports = {
                "top":    {"x": self.x, "y": self.y - r, "node_id": f"N_{self.id}_top"},
                "bottom": {"x": self.x, "y": self.y + r, "node_id": f"N_{self.id}_bot"}
            }
        else:
            self.ports = {
                "left":  {"x": self.x - r, "y": self.y, "node_id": f"N_{self.id}_left"},
                "right": {"x": self.x + r, "y": self.y, "node_id": f"N_{self.id}_right"}
            }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r_sq = (self.cell / 2) * zoom
        r_port = self.cell * zoom
        
        if self.rotation in [0, 180]:
            canvas.create_line(sx, sy - r_sq, sx, sy - r_port, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy + r_sq, sx, sy + r_port, width=max(1, int(2*zoom)), fill="black")
        else:
            canvas.create_line(sx - r_sq, sy, sx - r_port, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx + r_sq, sy, sx + r_port, sy, width=max(1, int(2*zoom)), fill="black")
            
        canvas.create_rectangle(sx-r_sq, sy-r_sq, sx+r_sq, sy+r_sq, fill="white", outline="black", width=max(1, int(2*zoom)))
        
        self._label_text(canvas, zoom, offset_x, offset_y,
                         self.x + self.cell + 5, self.y)

    def get_bounding_box(self):
        r = self.cell
        return (self.x - r, self.y - r, self.x + r, self.y + r)


# ==========================================
# 2. РАЗЪЕДИНИТЕЛЬ (2 порта)
# ==========================================
class Disconnector(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "disconnector"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        r = self.cell
        if self.rotation in [0, 180]:
            self.ports = {
                "top":    {"x": self.x, "y": self.y - r, "node_id": f"N_{self.id}_top"},
                "bottom": {"x": self.x, "y": self.y + r, "node_id": f"N_{self.id}_bot"}
            }
        else:
            self.ports = {
                "left":  {"x": self.x - r, "y": self.y, "node_id": f"N_{self.id}_left"},
                "right": {"x": self.x + r, "y": self.y, "node_id": f"N_{self.id}_right"}
            }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r_inner = (self.cell / 2) * 0.8 * zoom
        r_port = self.cell * zoom
        blade_len = 12 * zoom

        if self.rotation in [0, 180]:
            canvas.create_line(sx, sy - r_inner, sx, sy - r_port, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy + r_inner, sx, sy + r_port, width=max(1, int(2*zoom)), fill="black")
            
            canvas.create_line(sx, sy - r_inner, sx, sy - blade_len*0.3, width=max(1, int(2*zoom)), fill="black")
            if self.rotation == 0:
                canvas.create_line(sx, sy - blade_len*0.3, sx + blade_len*0.6, sy + blade_len*0.3, width=max(1, int(3*zoom)), fill="black")
            else:
                canvas.create_line(sx, sy + blade_len*0.3, sx + blade_len*0.6, sy - blade_len*0.3, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx, sy + blade_len*0.3, sx, sy + r_inner, width=max(1, int(2*zoom)), fill="black")
        else:
            canvas.create_line(sx - r_inner, sy, sx - r_port, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx + r_inner, sy, sx + r_port, sy, width=max(1, int(2*zoom)), fill="black")
            
            canvas.create_line(sx - r_inner, sy, sx - blade_len*0.3, sy, width=max(1, int(2*zoom)), fill="black")
            if self.rotation == 90:
                canvas.create_line(sx - blade_len*0.3, sy, sx + blade_len*0.3, sy - blade_len*0.6, width=max(1, int(3*zoom)), fill="black")
            else:
                canvas.create_line(sx - blade_len*0.3, sy, sx + blade_len*0.3, sy + blade_len*0.6, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx + blade_len*0.3, sy, sx + r_inner, sy, width=max(1, int(2*zoom)), fill="black")

        self._label_text(canvas, zoom, offset_x, offset_y,
                         self.x + self.cell + 5, self.y)

    def get_bounding_box(self):
        # Порты разъединителя лежат на расстоянии CELL от центра — габарит должен их включать,
        # иначе элемент нельзя выбрать/перетащить за вывод.
        r = self.cell
        return (self.x - r, self.y - r, self.x + r, self.y + r)


# ==========================================
# 3. ШИНА
# ==========================================
class Bus(Component):
    def __init__(self, comp_id, x, y, grid_size=20, length=None):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "bus"
        self.length = length if length else CELL * 4
        self.generate_ports()

    def generate_ports(self):
        self.ports = {
            "left":   {"x": self.x - self.length, "y": self.y, "node_id": f"N_{self.id}_left"},
            "right":  {"x": self.x + self.length, "y": self.y, "node_id": f"N_{self.id}_right"},
            "center": {"x": self.x, "y": self.y, "node_id": f"N_{self.id}_center"}
        }
        step = self.cell
        start_x = self.x - self.length + step
        end_x = self.x + self.length - step
        idx = 1
        cx = start_x
        while cx <= end_x:
            if abs(cx - self.x) > 0.1:
                p_name = f"p_{idx}"
                self.ports[p_name] = {"x": cx, "y": self.y, "node_id": f"N_{self.id}_{p_name}"}
                idx += 1
            cx += step

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        length = self.length * zoom
        canvas.create_line(sx-length, sy, sx+length, sy, width=max(2, int(6*zoom)), fill="black")
        self._label_text(canvas, zoom, offset_x, offset_y,
                         self.x, self.y - 15, anchor="s")

    def get_bounding_box(self):
        return (self.x - self.length, self.y - 10, self.x + self.length, self.y + 10)

# ==========================================
# 4. ТРАНСФОРМАТОР ДВУХОБМОТОЧНЫЙ
# ==========================================
class Transformer(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "transformer"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        # Нейтраль остаётся точкой подключения (узел), но без нарисованного отрезка вывода.
        for name, dx, dy in (("HV", 0, -2 * c), ("LV", 0, 2 * c), ("N", -c, -c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def _primitives(self):
        c = self.cell
        lines = [
            (0, -2 * c, 0, -1.5 * c),      # вывод ВН
            (0, 2 * c, 0, 1.5 * c),        # вывод НН
        ]
        circles = [(0, -0.5 * c, c), (0, 0.5 * c, c)]
        return lines, circles

    def draw(self, canvas, zoom, offset_x, offset_y):
        lw = max(1, int(2 * zoom))

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        lines, circles = self._primitives()
        for dx1, dy1, dx2, dy2 in lines:
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        for cdx, cdy, cr in circles:
            cx, cy = scr(cdx, cdy)
            r = cr * zoom
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill="white", outline="black", width=lw)

        if getattr(self, "rotation", 0) % 360 == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, self.cell + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -2 * c, c, 2 * c))

# ==========================================
# 5. УЗЕЛ
# ==========================================
class Node(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "node"
        self.generate_ports()

    def generate_ports(self):
        self.ports = {"center": {"x": self.x, "y": self.y, "node_id": self.id}}

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = 4 * zoom
        canvas.create_oval(sx-r, sy-r, sx+r, sy+r, fill="cyan", outline="blue")

    def get_bounding_box(self):
        return (self.x - 5, self.y - 5, self.x + 5, self.y + 5)


# ==========================================
# 6. ЛЭП
# ==========================================
class PowerLine(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "line"
        self.rotation = 0
        self.generate_ports()

    def _length(self):
        return self.cell * 3

    def generate_ports(self):
        length = self._length()
        if self.rotation == 0:
            self.ports = {
                "in":  {"x": self.x, "y": self.y - length, "node_id": f"N_{self.id}_in"},
                "out": {"x": self.x, "y": self.y, "node_id": f"N_{self.id}_out"}
            }
        elif self.rotation == 180:
            self.ports = {
                "in":  {"x": self.x, "y": self.y + length, "node_id": f"N_{self.id}_in"},
                "out": {"x": self.x, "y": self.y, "node_id": f"N_{self.id}_out"}
            }
        elif self.rotation == 90:
            self.ports = {
                "in":  {"x": self.x + length, "y": self.y, "node_id": f"N_{self.id}_in"},
                "out": {"x": self.x, "y": self.y, "node_id": f"N_{self.id}_out"}
            }
        elif self.rotation == 270:
            self.ports = {
                "in":  {"x": self.x - length, "y": self.y, "node_id": f"N_{self.id}_in"},
                "out": {"x": self.x, "y": self.y, "node_id": f"N_{self.id}_out"}
            }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        length = self.cell * 3 * zoom
        
        if self.rotation == 0:
            end_x, end_y = sx, sy - length
            arrow = [sx, sy - length, sx - 5*zoom, sy - length + 10*zoom, sx + 5*zoom, sy - length + 10*zoom]
        elif self.rotation == 180:
            end_x, end_y = sx, sy + length
            arrow = [sx, sy + length, sx - 5*zoom, sy + length - 10*zoom, sx + 5*zoom, sy + length - 10*zoom]
        elif self.rotation == 90:
            end_x, end_y = sx + length, sy
            arrow = [sx + length, sy, sx + length - 10*zoom, sy - 5*zoom, sx + length - 10*zoom, sy + 5*zoom]
        elif self.rotation == 270:
            end_x, end_y = sx - length, sy
            arrow = [sx - length, sy, sx - length + 10*zoom, sy - 5*zoom, sx - length + 10*zoom, sy + 5*zoom]

        canvas.create_line(sx, sy, end_x, end_y, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(arrow[0], arrow[1], arrow[2], arrow[3], width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(arrow[0], arrow[1], arrow[4], arrow[5], width=max(1, int(2*zoom)), fill="black")
        
        if self.name:
            world_end = {
                0: (self.x, self.y - self._length()),
                180: (self.x, self.y + self._length()),
                90: (self.x + self._length(), self.y),
                270: (self.x - self._length(), self.y),
            }.get(self.rotation, (self.x, self.y))
            self._label_text(canvas, zoom, offset_x, offset_y,
                             world_end[0] + 15,
                             world_end[1] + self._length() / 2.0,
                             size=9)

    def get_bounding_box(self):
        length = self._length()
        pad = self.cell * 0.5

        if self.rotation == 0:
            return (self.x - pad, self.y - length - pad, self.x + pad, self.y + pad)
        elif self.rotation == 180:
            return (self.x - pad, self.y - pad, self.x + pad, self.y + length + pad)
        elif self.rotation == 90:
            return (self.x - pad, self.y - pad, self.x + length + pad, self.y + pad)
        elif self.rotation == 270:
            return (self.x - length - pad, self.y - pad, self.x + pad, self.y + pad)

# ==========================================
# 7. УГОЛОК
# ==========================================
class Corner(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "corner"
        self.orientation = "bottom_right"
        self.generate_ports()

    def generate_ports(self):
        r = self.cell
        self.ports = {
            "top":    {"x": self.x, "y": self.y - r, "node_id": f"N_{self.id}_top"},
            "bottom": {"x": self.x, "y": self.y + r, "node_id": f"N_{self.id}_bot"},
            "left":   {"x": self.x - r, "y": self.y, "node_id": f"N_{self.id}_left"},
            "right":  {"x": self.x + r, "y": self.y, "node_id": f"N_{self.id}_right"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y, connections=None):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = self.cell * zoom
        
        if self.orientation == "bottom_right":
            canvas.create_line(sx, sy, sx + r, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy, sx, sy + r, width=max(1, int(2*zoom)), fill="black")
        elif self.orientation == "bottom_left":
            canvas.create_line(sx, sy, sx - r, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy, sx, sy + r, width=max(1, int(2*zoom)), fill="black")
        elif self.orientation == "top_right":
            canvas.create_line(sx, sy, sx + r, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy, sx, sy - r, width=max(1, int(2*zoom)), fill="black")
        elif self.orientation == "top_left":
            canvas.create_line(sx, sy, sx - r, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy, sx, sy - r, width=max(1, int(2*zoom)), fill="black")

    def get_bounding_box(self):
        r = self.cell
        return (self.x - r, self.y - r, self.x + r, self.y + r)


# ==========================================
# 8. ЗАЗЕМЛЯЮЩИЙ РАЗЪЕДИНИТЕЛЬ
# ==========================================
class GroundingSwitch(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "grounding_switch"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        r = self.cell
        if self.rotation in [0, 180]:
            self.ports = {"top": {"x": self.x, "y": self.y - r, "node_id": f"N_{self.id}_top"}}
        else:
            self.ports = {"left": {"x": self.x - r, "y": self.y, "node_id": f"N_{self.id}_left"}}

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r_inner = (self.cell / 2) * 0.8 * zoom
        r_out = self.cell * zoom
        blade_len = 14 * zoom
        
        def draw_ground(gx, gy, direction="down"):
            draw_earth(canvas, gx, gy, zoom, direction)

        if self.rotation == 0:
            canvas.create_line(sx, sy - r_out, sx, sy - blade_len*0.3, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy - blade_len*0.3, sx + blade_len*0.6, sy + blade_len*0.3, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx, sy + blade_len*0.3, sx, sy + r_inner, width=max(1, int(2*zoom)), fill="black")
            draw_ground(sx, sy + r_inner + 2*zoom)
            
        elif self.rotation == 180:
            canvas.create_line(sx, sy + r_out, sx, sy + blade_len*0.3, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy + blade_len*0.3, sx + blade_len*0.6, sy - blade_len*0.3, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx, sy - blade_len*0.3, sx, sy - r_inner, width=max(1, int(2*zoom)), fill="black")
            draw_ground(sx, sy - r_inner - 2*zoom, "up")

        elif self.rotation == 90:
            canvas.create_line(sx + r_out, sy, sx + blade_len*0.3, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx + blade_len*0.3, sy, sx - blade_len*0.3, sy - blade_len*0.6, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx - blade_len*0.3, sy, sx - r_inner, sy, width=max(1, int(2*zoom)), fill="black")
            draw_ground(sx - r_inner - 5*zoom, sy, "left")

        elif self.rotation == 270:
            canvas.create_line(sx - r_out, sy, sx - blade_len*0.3, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx - blade_len*0.3, sy, sx + blade_len*0.3, sy - blade_len*0.6, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx + blade_len*0.3, sy, sx + r_inner, sy, width=max(1, int(2*zoom)), fill="black")
            draw_ground(sx + r_inner + 5*zoom, sy, "right")

        self._label_text(canvas, zoom, offset_x, offset_y,
                         self.x + self.cell + 15, self.y)

    def get_bounding_box(self):
        r = self.cell * 1.2  # 120% достаточно для захвата "ножек" заземления
        return (self.x - r, self.y - r, self.x + r, self.y + r)


# ==========================================
# 9. ТРАНСФОРМАТОР С РАСЩЕПЛЕНИЕМ (ВН и два НН)
# ==========================================
class SplitTransformer(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "split_transformer"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        # Нейтраль — узел подключения без нарисованного отрезка вывода.
        for name, dx, dy in (("HV", 0, -2 * c), ("LV1", -2 * c, 3 * c),
                             ("LV2", 2 * c, 3 * c), ("N", -c, -c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def _primitives(self):
        c = self.cell
        lines = [
            (0, -2 * c, 0, -1.5 * c),                    # вывод ВН
            (-0.75 * c, 1.5 * c, -0.75 * c, 2 * c),      # левый хвостик
            (-0.75 * c, 2 * c, -2 * c, 2 * c),
            (-2 * c, 2 * c, -2 * c, 3 * c),
            (0.75 * c, 1.5 * c, 0.75 * c, 2 * c),        # правый хвостик
            (0.75 * c, 2 * c, 2 * c, 2 * c),
            (2 * c, 2 * c, 2 * c, 3 * c),
        ]
        circles = [(0, -0.5 * c, c), (-0.75 * c, 0.5 * c, c), (0.75 * c, 0.5 * c, c)]
        return lines, circles

    def draw(self, canvas, zoom, offset_x, offset_y):
        lw = max(1, int(2 * zoom))

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        lines, circles = self._primitives()
        for dx1, dy1, dx2, dy2 in lines:
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        for cdx, cdy, cr in circles:
            cx, cy = scr(cdx, cdy)
            r = cr * zoom
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill="white", outline="black", width=lw)

        if getattr(self, "rotation", 0) % 360 == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, 3 * self.cell)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-2 * c, -2 * c, 2 * c, 3 * c))


# ==========================================
# 10. ТРАНСФОРМАТОР ТРЕХОБМОТОЧНЫЙ (ВН, СН, НН)
# ==========================================
class ThreeWindingTransformer(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "three_winding_transformer"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        # Нейтраль — узел подключения без нарисованного отрезка вывода.
        for name, dx, dy in (("HV", 0, -2 * c), ("LV", 0, 2 * c),
                             ("MV", 2 * c, 0), ("N", -c, -c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def _primitives(self):
        c = self.cell
        lines = [
            (0, -2 * c, 0, -1.5 * c),
            (0, 1.5 * c, 0, 2 * c),
            (1.5 * c, 0, 2 * c, 0),
        ]
        circles = [(0, -0.6 * c, c), (0, 0.6 * c, c), (0.8 * c, 0, c)]
        return lines, circles

    def draw(self, canvas, zoom, offset_x, offset_y):
        lw = max(1, int(2 * zoom))

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        lines, circles = self._primitives()
        for dx1, dy1, dx2, dy2 in lines:
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        for cdx, cdy, cr in circles:
            cx, cy = scr(cdx, cdy)
            r = cr * zoom
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill="white", outline="black", width=lw)

        if getattr(self, "rotation", 0) % 360 == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, -2 * self.cell)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -2 * c, 2 * c, 2 * c))


# ==========================================
# 11. АВТОТРАНСФОРМАТОР (ВН, СН, НН + дуга)
# ==========================================
class Autotransformer(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "autotransformer"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        # Нейтраль — узел подключения без нарисованного отрезка вывода.
        for name, dx, dy in (("HV", 0, -2 * c), ("LV", 0, 2 * c),
                             ("MV", 2 * c, -0.5 * c), ("N", -c, -c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        line_w = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # Дуга автотрансформатора: центр и радиус неизменны, а начальный угол
        # сдвигается на угол поворота (экранный Tk-угол).
        arc_radius = 1.6537 * c
        acx, acy = scr(-0.6536 * c, -0.4809 * c)
        r_arc = arc_radius * zoom
        canvas.create_arc(acx - r_arc, acy - r_arc, acx + r_arc, acy + r_arc,
                          start=1 - rotation, extent=66, style="arc",
                          width=line_w, outline="black")

        # Вывод НН и вывод СН — ровно как в исходном символе
        for dx1, dy1, dx2, dy2 in ((0, 2 * c, 0, 1.5 * c),
                                   (c, -0.5 * c, 2 * c, -0.5 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=line_w, fill="black")

        # Обмотки
        for dy in (-0.5 * c, 0.5 * c):
            cx, cy = scr(0, dy)
            r = c * zoom
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill="white", outline="black", width=line_w)

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, 2.5 * c)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -2 * c, 2 * c, 2 * c))


# ==========================================
# 12. РЕАКТОР (2 порта)
# ==========================================
class Reactor(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "reactor"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -2 * c), ("bottom", 0, 2 * c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0)

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # Выводы
        for dx1, dy1, dx2, dy2 in ((0, -2 * c, 0, -c), (0, c, 0, 2 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # Полуокружность обмотки
        cx, cy = scr(0, 0)
        r = c * zoom
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                          start=90 - rotation, extent=270,
                          style=tk.ARC, outline="black", width=lw)

        # Символ реактора: две короткие линии от центра
        for dx1, dy1, dx2, dy2 in ((0, 0, c, 0), (0, 0, 0, c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        if getattr(self, "rotation", 0) % 360 == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, self.cell + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -2 * c, c, 2 * c))


# ==========================================
# 13. ЗАЗЕМЛЕНИЕ (1 порт)
# ==========================================
class Ground(Component):
    """Заземление: вывод и символ заземления как у заземляющего разъединителя."""

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "ground"
        self.rotation = 0
        self.generate_ports()

    def _rotate_point(self, dx, dy):
        angle = math.radians(self.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a

    def _local_to_world(self, dx, dy):
        rdx, rdy = self._rotate_point(dx, dy)
        return self.x + rdx, self.y + rdy

    def generate_ports(self):
        g = self.cell
        wx, wy = self._local_to_world(0, -g)
        self.ports = {
            "top": {"x": wx, "y": wy, "node_id": f"N_{self.id}_top"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.cell
        lw = max(1, int(2 * zoom))

        def scr(dx, dy):
            wx, wy = self._local_to_world(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # 1. Вывод от порта к первому штриху
        x1, y1 = scr(0, -g)
        x2, y2 = scr(0, -g * 0.25)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # 2. Символ заземления — тот же, что у заземляющего разъединителя
        gx, gy = scr(0, -g * 0.25)
        direction = {0: "down", 180: "up", 90: "left", 270: "right"}.get(
            getattr(self, "rotation", 0) % 360, "down")
        draw_earth(canvas, gx, gy, zoom, direction)

        # 3. Подпись
        self._draw_name_at(canvas, zoom, offset_x, offset_y, 1.2 * self.cell)

    def get_bounding_box(self):
        g = self.cell
        return (self.x - g, self.y - g, self.x + g, self.y + g)


# ==========================================
# 14. ТН (ТРАНСФОРМАТОР НАПРЯЖЕНИЯ, УПРОЩЁННО)
# ==========================================
class VoltageTransformer(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "voltage_transformer"
        self.rotation = 0
        self.generate_ports()

    def _rotate_point(self, dx, dy):
        angle = math.radians(self.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a

    def _local_to_world(self, dx, dy):
        rdx, rdy = self._rotate_point(dx, dy)
        return self.x + rdx, self.y + rdy

    def generate_ports(self):
        g = self.cell
        wx, wy = self._local_to_world(0, -g)
        self.ports = {
            "top": {"x": wx, "y": wy, "node_id": f"N_{self.id}_top"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.cell
        lw = max(1, int(2 * zoom))

        def scr(dx, dy):
            wx, wy = self._local_to_world(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        x1, y1 = scr(0, -g)
        x2, y2 = scr(0, -g / 2)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        h = g / 2
        corners = [
            scr(-h, -h), scr(h, -h),
            scr(h, h),   scr(-h, h),
        ]
        canvas.create_polygon(
            corners[0][0], corners[0][1],
            corners[1][0], corners[1][1],
            corners[2][0], corners[2][1],
            corners[3][0], corners[3][1],
            fill="white", outline="black", width=lw
        )

        cx, cy = scr(0, 0)
        canvas.create_text(cx, cy, text="ТН",
                           font=("Arial", int(9 * zoom), "bold"),
                           fill="black")

        self._draw_name_at(canvas, zoom, offset_x, offset_y, 1.2 * self.cell)

    def get_bounding_box(self):
        g = self.cell
        return (self.x - g, self.y - g, self.x + g, self.y + g)



# ==========================================
# 15. ТТ (ТРАНСФОРМАТОР ТОКА, УПРОЩЁННО)
# ==========================================
class CurrentTransformer(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "current_transformer"
        self.rotation = 0
        self.generate_ports()

    def _rotate_point(self, dx, dy):
        angle = math.radians(self.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a

    def _local_to_world(self, dx, dy):
        rdx, rdy = self._rotate_point(dx, dy)
        return self.x + rdx, self.y + rdy

    def generate_ports(self):
        g = self.cell
        # Два порта: сверху и снизу на 1 клетку от центра
        wx_top, wy_top = self._local_to_world(0, -g)
        wx_bot, wy_bot = self._local_to_world(0, g)
        
        self.ports = {
            "top":    {"x": wx_top, "y": wy_top, "node_id": f"N_{self.id}_top"},
            "bottom": {"x": wx_bot, "y": wy_bot, "node_id": f"N_{self.id}_bot"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.cell
        lw = max(1, int(2 * zoom))

        def scr(dx, dy):
            wx, wy = self._local_to_world(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        cx, cy = scr(0, 0)
        r = g * 0.4 * zoom

        # 1. Белая заливка круга (скрывает сетку)
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="white", outline="")

        # 2. Сплошная линия от верхнего порта до нижнего порта (сквозь круг)
        x1, y1 = scr(0, -g)
        x2, y2 = scr(0, g)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # 3. Контур круга (рисуем поверх линии)
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill="", outline="black", width=lw)

        # 4. Внешняя подпись (имя элемента) справа
        self._draw_name_at(canvas, zoom, offset_x, offset_y, 0.8 * self.cell)

    def get_bounding_box(self):
        g = self.cell
        return (self.x - g, self.y - g, self.x + g, self.y + g)



# ==========================================
# 16. ОПН (ОГРАНИЧИТЕЛЬ ПЕРЕНАПРЯЖЕНИЙ)
# ==========================================
class SurgeArrester(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "opn"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -2 * c), ("bottom", 0, 2 * c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # Выводы
        for dx1, dy1, dx2, dy2 in ((0, -2 * c, 0, -c), (0, c, 0, 2 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # Корпус
        box = [(-0.5 * c, -c), (0.5 * c, -c), (0.5 * c, c), (-0.5 * c, c)]
        pts = [v for dx, dy in box for v in scr(dx, dy)]
        canvas.create_polygon(*pts, fill="white", outline="black", width=lw)

        # Диагональ со стрелкой (нелинейный элемент)
        tipx, tipy = 0.35 * c, -0.6 * c
        sx0, sy0 = -0.35 * c, 0.6 * c
        x1, y1 = scr(sx0, sy0)
        x2, y2 = scr(tipx, tipy)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        dx, dy = tipx - sx0, tipy - sy0
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        bx, by = tipx - ux * 0.35 * c, tipy - uy * 0.35 * c
        px_, py_ = -uy * 0.15 * c, ux * 0.15 * c
        for ax, ay in ((bx + px_, by + py_), (bx - px_, by - py_)):
            ax_, ay_ = scr(ax, ay)
            canvas.create_line(x2, y2, ax_, ay_, width=lw, fill="black")

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -2 * c, c, 2 * c))


# ==========================================
# 17. КС (КОНДЕНСАТОР СВЯЗИ)
# ==========================================
class CouplingCapacitor(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "coupling_capacitor"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -2 * c), ("bottom", 0, 2 * c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # Выводы и две обкладки
        for dx1, dy1, dx2, dy2 in ((0, -2 * c, 0, -0.25 * c),
                                   (0, 0.25 * c, 0, 2 * c),
                                   (-0.7 * c, -0.25 * c, 0.7 * c, -0.25 * c),
                                   (-0.7 * c, 0.25 * c, 0.7 * c, 0.25 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-0.7 * c, -2 * c, 0.7 * c, 2 * c))


# ==========================================
# 18. ВЧЗ (ВЫСОКОЧАСТОТНЫЙ ЗАГРАДИТЕЛЬ)
# ==========================================
class LineTrap(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "line_trap"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -2 * c), ("bottom", 0, 2 * c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # Выводы
        for dx1, dy1, dx2, dy2 in ((0, -2 * c, 0, -1.2 * c), (0, 1.2 * c, 0, 2 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # Катушка: зигзаг из полуволн
        points = []
        steps = 24
        for i in range(steps + 1):
            t = i / steps
            dy = -1.2 * c + 2.4 * c * t
            dx = 0.35 * c * math.sin(t * math.pi * 4)
            points.extend(scr(dx, dy))
        canvas.create_line(*points, width=lw, fill="black", smooth=False)

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-0.4 * c, -2 * c, 0.4 * c, 2 * c))


# ==========================================
# 19. ФП (ФИЛЬТР ПРИСОЕДИНЕНИЯ)
# ==========================================
class ConnectionFilter(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "connection_filter"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        """Порты сверху и снизу — по габариту ТН (полклетки от центра)."""
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -c), ("bottom", 0, c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        half = 0.5 * c   # корпус как у ТН (20×20 при клетке 20)

        # Выводы: от портов к корпусу
        for dx1, dy1, dx2, dy2 in ((0, -c, 0, -half), (0, half, 0, c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # Корпус — компактный квадрат в габарите ТН
        box = [(-half, -half), (half, -half), (half, half), (-half, half)]
        pts = [v for dx, dy in box for v in scr(dx, dy)]
        canvas.create_polygon(*pts, fill="white", outline="black", width=lw)

        # Диагональ (условное обозначение фильтра)
        x1, y1 = scr(-half * 0.85, half * 0.85)
        x2, y2 = scr(half * 0.85, -half * 0.85)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, 0.7 * c)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -c, c, c))


# ==========================================
# 20. АВ (АВТОМАТИЧЕСКИЙ ВЫКЛЮЧАТЕЛЬ 0,4 кВ)
# ==========================================
class AutomaticBreaker(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "av_breaker"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -c), ("bottom", 0, c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        for dx1, dy1, dx2, dy2 in ((0, -c, 0, -0.5 * c), (0, 0.5 * c, 0, c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        box = [(-0.5 * c, -0.5 * c), (0.5 * c, -0.5 * c),
               (0.5 * c, 0.5 * c), (-0.5 * c, 0.5 * c)]
        pts = [v for dx, dy in box for v in scr(dx, dy)]
        canvas.create_polygon(*pts, fill="white", outline="black", width=lw)

        # Косая черта — признак автоматического выключателя
        x1, y1 = scr(-0.25 * c, 0.3 * c)
        x2, y2 = scr(0.25 * c, -0.3 * c)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 10)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-c, -c, c, c))


# ==========================================
# 21. ПРЕДОХРАНИТЕЛЬ
# ==========================================
class Fuse(Component):
    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "fuse"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -2 * c), ("bottom", 0, 2 * c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py, "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        for dx1, dy1, dx2, dy2 in ((0, -2 * c, 0, -0.6 * c),
                                   (0, 0.6 * c, 0, 2 * c),
                                   (0, -0.6 * c, 0, 0.6 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        box = [(-0.4 * c, -0.6 * c), (0.4 * c, -0.6 * c),
               (0.4 * c, 0.6 * c), (-0.4 * c, 0.6 * c)]
        pts = [v for dx, dy in box for v in scr(dx, dy)]
        canvas.create_polygon(*pts, fill="white", outline="black", width=lw)

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 10)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-0.4 * c, -2 * c, 0.4 * c, 2 * c))


# ==========================================
# 22. ШКАФ РЗА (1..3 IED)
# ==========================================
CABINET_MAX_KOMPLETS = 7


def komplets_from_ieds(ieds):
    """Старый формат: каждый ИЭУ становится отдельным комплектом."""
    komplets = []
    for index, ied in enumerate(ieds[:CABINET_MAX_KOMPLETS]):
        komplets.append({
            "name": "Комплект {}".format(index + 1),
            "type": ied.get("type", "МП РЗА"),
            "functions": list(ied.get("functions", [])),
            "desc": ied.get("desc", ""),
            "ieds": [dict(ied)],
        })
    return komplets


class Cabinet(Component):
    """Шкаф РЗА: до 7 комплектов, в каждом — 0..N устройств ИЭУ.

    Комплект — подключаемая единица: у него свой порт на правой грани
    (komplekt0..komplekt6), к которому идут защитные связи. Комплект может
    быть и без ИЭУ — привязка к оборудованию всё равно работает.
    """

    WIDTH = 190
    ROW_H = 30
    TOP_H = 22
    MAX_KOMPLETS = CABINET_MAX_KOMPLETS

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "cabinet"
        self.cabinet_key = ""
        self.title = "Шкаф РЗА"
        self.komplets = []
        self.info = {}
        self.generate_ports()

    def set_cabinet(self, definition):
        """Заполняет шкаф по описанию из каталога."""
        self.cabinet_key = definition.get("key", "")
        self.title = definition.get("code") or definition.get("name", "Шкаф РЗА")
        komplets = definition.get("komplets")
        if not isinstance(komplets, list):
            komplets = komplets_from_ieds(definition.get("ieds", []))
        self.komplets = []
        for index, komplekt in enumerate(komplets[:self.MAX_KOMPLETS]):
            entry = dict(komplekt)
            entry.setdefault("name", "Комплект {}".format(index + 1))
            entry["functions"] = list(entry.get("functions", []))
            entry["ieds"] = [dict(ied) for ied in entry.get("ieds", [])]
            self.komplets.append(entry)
        self.info = {
            key: definition.get(key)
            for key in ("code", "name", "title", "description", "voltage",
                        "architecture", "protected", "controlled",
                        "its_functions", "applicability", "source",
                        "standard", "standard_title", "group", "goose")
            if definition.get(key) is not None
        }
        self.generate_ports()

    def bind_point(self):
        """Точка привязки шкафа к контейнеру КЭТ — на левой грани у заголовка."""
        x1, y1, _x2, _y2 = self._rect()
        return (x1, y1 + 10)

    def analog_point(self, index=0):
        """Порт аналоговых цепей комплекта — на левой грани напротив комплекта."""
        x1, _y1, _x2, _y2 = self._rect()
        _cx, cy = self._komplekt_center(max(0, int(index)))
        return (x1, cy)

    def row_count(self):
        return max(1, len(self.komplets))

    def _rect(self):
        height = self.TOP_H + self.row_count() * self.ROW_H
        half_w = self.WIDTH / 2.0
        half_h = height / 2.0
        return (self.x - half_w, self.y - half_h,
                self.x + half_w, self.y + half_h)

    def _komplekt_center(self, index):
        x1, y1, _x2, _y2 = self._rect()
        return (self.x, y1 + self.TOP_H + index * self.ROW_H + self.ROW_H / 2.0)

    def generate_ports(self):
        self.ports = {}
        _x1, _y1, x2, _y2 = self._rect()
        for index, _komplekt in enumerate(self.komplets):
            _cx, cy = self._komplekt_center(index)
            self.ports["komplekt{}".format(index)] = {
                "x": x2,
                "y": cy,
                "node_id": "N_{}_k{}".format(self.id, index),
            }

    def draw(self, canvas, zoom, offset_x, offset_y):
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = x1 * zoom + offset_x, y1 * zoom + offset_y
        sx2, sy2 = x2 * zoom + offset_x, y2 * zoom + offset_y
        lw = max(1, int(2 * zoom))

        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="#f2f6fb",
                                outline="#1f4e79", width=lw, tags="cabinet_body")
        canvas.create_text((sx1 + sx2) / 2.0, sy1 + 9 * zoom,
                           text=self.title, font=("Arial", int(8 * zoom)),
                           fill="#1f4e79")

        for index, komplekt in enumerate(self.komplets):
            _cx, cy = self._komplekt_center(index)
            by1 = (cy - self.ROW_H / 2.0 + 2) * zoom + offset_y
            by2 = (cy + self.ROW_H / 2.0 - 2) * zoom + offset_y
            canvas.create_rectangle(sx1 + 5 * zoom, by1, sx2 - 5 * zoom, by2,
                                    fill="white", outline="#8a9bb0", width=1,
                                    tags="cabinet_body")
            ieds = komplekt.get("ieds", [])
            suffix = " · {} ИЭУ".format(len(ieds)) if ieds else ""
            name = komplekt.get("name") or "Комплект {}".format(index + 1)
            canvas.create_text(sx1 + 9 * zoom, (by1 + by2) / 2.0,
                               text=name + suffix,
                               anchor="w", font=("Arial", int(7 * zoom)),
                               fill="black")
            port = self.ports.get("komplekt{}".format(index))
            if port:
                px = port["x"] * zoom + offset_x
                py = port["y"] * zoom + offset_y
                r = max(2.0, 2.5 * zoom)
                canvas.create_oval(px - r, py - r, px + r, py + r,
                                   fill="#1f4e79", outline="white",
                                   tags="cabinet_body")

        self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        return self._rect()


# ==========================================
# 23. КОНТЕЙНЕР КЭТ (привязка шкафов)
# ==========================================
CONTAINER_MAX_SLOTS = 14


class Container(Component):
    """Контейнер электротехнический типовой (КЭТ) — вертикальный ряд слотов.

    На схеме КЭТ рисуется вертикально: сверху вниз идут пронумерованные
    слоты. Каждый слот привязывается к шкафу линией (слот → шкаф), сам шкаф
    остаётся там, где его поставили, и связывается с контейнером линией.
    Привязка хранится в контейнере: ``cabinets[i]`` — id шкафа в слоте i
    (пустая строка — слот свободен), ``slot_labels[i]`` — подпись шкафа
    в строке слота (обновляется редактором).
    """

    BODY_W = 250          # ширина корпуса контейнера
    ROW_H = 46            # высота строки слота
    TOP_H = 32            # полоса заголовка
    PAD = 20              # отступ от стенки контейнера
    MAX_SLOTS = CONTAINER_MAX_SLOTS
    LABEL_CHARS = 24      # сколько символов подписи влезает в строку

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "container"
        self.container_key = ""
        self.title = "КЭТ"
        self.code = "КЭТ"
        self.size = "20dc"
        self.slots = 7
        self.cabinets = [""] * self.slots
        self.slot_labels = [""] * self.slots
        self.info = {}
        self.generate_ports()

    # ---------------------------------------------------------- данные
    def set_container(self, definition):
        """Заполняет контейнер по описанию из каталога."""
        self.container_key = definition.get("key", "")
        self.code = definition.get("code") or definition.get("name", "КЭТ")
        self.title = definition.get("name", "КЭТ")
        self.size = definition.get("size", "20dc")
        try:
            self.slots = max(1, min(self.MAX_SLOTS,
                                    int(definition.get("slots") or 7)))
        except (TypeError, ValueError):
            self.slots = 7
        self.cabinets = [""] * self.slots
        self.slot_labels = [""] * self.slots
        self.info = {
            key: definition.get(key)
            for key in ("code", "name", "title", "description", "group",
                        "standard", "standard_title", "architecture", "size",
                        "size_code", "size_title", "dimensions", "climate",
                        "ip", "functions", "composition", "source", "note")
            if definition.get(key) not in (None, "", [])
        }
        self.generate_ports()

    def set_slots(self, slots):
        """Меняет число слотов, сохраняя привязку шкафов и подписи."""
        slots = max(1, min(self.MAX_SLOTS, int(slots or 1)))
        self.slots = slots
        self.cabinets = (list(self.cabinets) + [""] * slots)[:slots]
        self.slot_labels = (list(self.slot_labels) + [""] * slots)[:slots]

    def slot_count(self):
        return max(1, min(self.MAX_SLOTS, int(self.slots or 1)))

    def bound_ids(self):
        return [cabinet_id for cabinet_id in self.cabinets if cabinet_id]

    def bound_count(self):
        return len(self.bound_ids())

    def free_slot(self):
        for index in range(self.slot_count()):
            if not self.cabinets[index]:
                return index
        return None

    def slot_of(self, cabinet_id):
        for index, value in enumerate(self.cabinets):
            if value == cabinet_id:
                return index
        return None

    def bind(self, cabinet_id):
        """Ставит шкаф в первый свободный слот; возвращает номер слота."""
        if not cabinet_id:
            return None
        index = self.slot_of(cabinet_id)
        if index is not None:
            return index
        index = self.free_slot()
        if index is None:
            return None
        self.cabinets[index] = cabinet_id
        return index

    def bind_slot(self, cabinet_id, index):
        """Ставит шкаф в конкретный слот, освобождая его прежние слоты."""
        index = int(index)
        if not (0 <= index < self.slot_count()) or not cabinet_id:
            return None
        previous = self.slot_of(cabinet_id)
        if previous == index:
            return index
        if previous is not None:
            self.cabinets[previous] = ""
        self.cabinets[index] = cabinet_id
        return index

    def unbind(self, cabinet_id):
        """Освобождает слот шкафа; нумерация слотов не сдвигается."""
        index = self.slot_of(cabinet_id)
        if index is None:
            return False
        self.cabinets[index] = ""
        return True

    def clear_bindings(self):
        self.cabinets = [""] * self.slot_count()
        self.slot_labels = [""] * self.slot_count()

    # -------------------------------------------------------- геометрия
    def _rect(self):
        width = self.BODY_W + self.PAD * 2
        height = self.TOP_H + self.slot_count() * self.ROW_H + self.PAD
        half_w, half_h = width / 2.0, height / 2.0
        return (self.x - half_w, self.y - half_h,
                self.x + half_w, self.y + half_h)

    def content_top(self):
        return self._rect()[1] + self.TOP_H

    def slot_rect(self, index):
        """Прямоугольник строки слота в мировых координатах."""
        x1, _y1, x2, _y2 = self._rect()
        top = self.content_top() + index * self.ROW_H
        return x1 + 6, top, x2 - 6, top + self.ROW_H

    def slot_center(self, index):
        """Точка подключения слота — на правой стенке контейнера."""
        x1, _y1, x2, _y2 = self._rect()
        center_y = self.content_top() + index * self.ROW_H + self.ROW_H / 2.0
        return x2, center_y

    def set_slot_label(self, index, text):
        if 0 <= index < len(self.slot_labels):
            text = text or ""
            if len(text) > self.LABEL_CHARS:
                text = text[:self.LABEL_CHARS - 1].rstrip() + "…"
            self.slot_labels[index] = text

    def generate_ports(self):
        # У контейнера нет электрических выводов: слоты связываются со
        # шкафами отдельными линиями привязки, а не электрическими связями.
        self.ports = {}

    # -------------------------------------------------------- отрисовка
    def draw(self, canvas, zoom, offset_x, offset_y):
        x1, y1, x2, y2 = self._rect()
        sx1, sy1 = x1 * zoom + offset_x, y1 * zoom + offset_y
        sx2, sy2 = x2 * zoom + offset_x, y2 * zoom + offset_y
        lw = max(1, int(2 * zoom))

        # Корпус и внутренние стенки
        canvas.create_rectangle(sx1, sy1, sx2, sy2, fill="#eef3f8",
                                outline="#1f4e79", width=lw,
                                tags="container_body")
        inset = 5 * zoom
        canvas.create_rectangle(sx1 + inset, sy1 + inset, sx2 - inset, sy2 - inset,
                                fill="#f7fafd", outline="#9db4cc", width=1,
                                tags="container_body")

        # Заголовок: маркировка, типоразмер, счётчик шкафов
        header_h = self.TOP_H * zoom
        canvas.create_rectangle(sx1, sy1, sx2, sy1 + header_h,
                                fill="#1f4e79", outline="#1f4e79",
                                tags="container_body")
        size_code = self.info.get("size_code", "")
        caption = self.code or "КЭТ"
        if size_code:
            caption = "{} · {}".format(caption, size_code)
        canvas.create_text(sx1 + 8 * zoom, sy1 + header_h / 2.0, text=caption,
                           anchor="w", font=("Arial", int(8 * zoom), "bold"),
                           fill="white", tags="container_body")
        canvas.create_text(sx2 - 8 * zoom, sy1 + header_h / 2.0,
                           text="{} / {}".format(self.bound_count(),
                                                 self.slot_count()),
                           anchor="e", font=("Arial", int(7 * zoom)),
                           fill="#dce9f7", tags="container_body")

        # Строки слотов сверху вниз
        font_size = max(1, int(7 * zoom))
        for index in range(self.slot_count()):
            left, top, right, bottom = self.slot_rect(index)
            sl, st = left * zoom + offset_x, top * zoom + offset_y
            sr, sb = right * zoom + offset_x, bottom * zoom + offset_y
            cabinet_id = (self.cabinets[index]
                          if index < len(self.cabinets) else "")
            label = (self.slot_labels[index]
                     if index < len(self.slot_labels) else "")
            if index:
                canvas.create_line(sl, st, sr, st, fill="#c3d2e0", width=1,
                                   tags="container_slot")
            if cabinet_id:
                canvas.create_rectangle(sl, st, sr, sb, fill="#e6f0e6",
                                        outline="", tags="container_slot")
            canvas.create_text(sl + 6 * zoom, (st + sb) / 2.0,
                               text=str(index + 1), anchor="w",
                               font=("Arial", font_size),
                               fill="#1f4e79" if cabinet_id else "#9db4cc",
                               tags="container_slot")
            if cabinet_id:
                text, color = (label or "шкаф"), "black"
            else:
                text, color = "свободно", "#9db4cc"
            canvas.create_text(sl + 22 * zoom, (st + sb) / 2.0,
                               text=text, anchor="w",
                               font=("Arial", font_size), fill=color,
                               tags="container_slot")

            # Точка подключения слота на правой стенке
            port_x, port_y = self.slot_center(index)
            px = port_x * zoom + offset_x
            py = port_y * zoom + offset_y
            r = max(2.0, 2.6 * zoom)
            canvas.create_oval(px - r, py - r, px + r, py + r,
                               fill="#a0522d" if cabinet_id else "white",
                               outline="#a0522d", width=1,
                               tags="container_slot")

        self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        return self._rect()


# ==========================================
# 24. КИВ — КОНТРОЛЬ ИЗОЛЯЦИИ ВВОДОВ
# ==========================================
class BushingMonitor(Component):
    """КИВ — контроль изоляции вводов (датчик на вводе оборудования).

    Два вывода — сверху и снизу (включается в первичную цепь последовательно),
    посередине — узел подключения РЗА: к нему идут защитные связи от комплекта
    шкафа. Графически повторяет типовое обозначение: вертикальный вывод с
    залитыми узлами сверху и снизу, слоистые скобки изоляции по бокам и узел
    РЗА в центре.
    """

    HALF_H = 1.5          # половина высоты в клетках (компактный символ)
    NODE_R = 0.18         # радиус верхнего/нижнего узла
    RZA_R = 0.27          # радиус узла подключения РЗА
    RZA_COLOR = "#1f4e79"

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "bushing_monitor"
        self.rotation = 0
        self.generate_ports()

    def half_height(self):
        return self.HALF_H * self.cell

    def generate_ports(self):
        half = self.half_height()
        self.ports = {}
        for name, dy in (("top", -half), ("bottom", half)):
            px, py = self._local_rotated(0, dy)
            self.ports[name] = {"x": px, "y": py,
                                "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.cell
        half = self.half_height()
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        # 1. Центральный вывод сверху вниз
        x1, y1 = scr(0, -half)
        x2, y2 = scr(0, half)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # 2. Слои изоляции — три пары симметричных скоб
        for offset, bracket_half in ((0.38 * g, 1.05 * g),
                                     (0.68 * g, 0.70 * g),
                                     (0.98 * g, 0.42 * g)):
            for side in (-1, 1):
                bx = side * offset
                bx1, by1 = scr(bx, -bracket_half)
                bx2, by2 = scr(bx, bracket_half)
                canvas.create_line(bx1, by1, bx2, by2, width=lw, fill="black")
                for dy in (-bracket_half, bracket_half):
                    sx1, sy1 = scr(bx, dy)
                    sx2, sy2 = scr(bx - side * 0.18 * g, dy)
                    canvas.create_line(sx1, sy1, sx2, sy2, width=lw, fill="black")

        # 3. Узлы сверху и снизу
        r = self.NODE_R * g * zoom
        for dy in (-half, half):
            cx, cy = scr(0, dy)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill="black", outline="black")

        # 4. Узел подключения РЗА посередине
        rr = self.RZA_R * g * zoom
        cx, cy = scr(0, 0)
        canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                           fill=self.RZA_COLOR, outline="white", width=lw)

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, 1.9 * g)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        g = self.cell
        half = self.half_height()
        return self._rotated_bbox((-1.16 * g, -half - 0.2 * g,
                                   1.16 * g, half + 0.2 * g))


# ==========================================
# 25. БСК (БАТАРЕЯ СТАТИЧЕСКИХ КОНДЕНСАТОРОВ)
# ==========================================
class CapacitorBattery(Component):
    """БСК — батарея статических конденсаторов (2 порта, габарит как у реактора).

    Две последовательные секции конденсаторов: четыре обкладки, выводы сверху
    и снизу — узлы подключения к первичной схеме.
    """

    def __init__(self, comp_id, x, y, grid_size=20):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "capacitor_battery"
        self.rotation = 0
        self.generate_ports()

    def generate_ports(self):
        c = self.cell
        self.ports = {}
        for name, dx, dy in (("top", 0, -2 * c), ("bottom", 0, 2 * c)):
            px, py = self._local_rotated(dx, dy)
            self.ports[name] = {"x": px, "y": py,
                                "node_id": f"N_{self.id}_{name}"}

    def draw(self, canvas, zoom, offset_x, offset_y):
        c = self.cell
        lw = max(1, int(2 * zoom))
        rotation = getattr(self, "rotation", 0) % 360

        def scr(dx, dy):
            wx, wy = self._local_rotated(dx, dy)
            return wx * zoom + offset_x, wy * zoom + offset_y

        plate_half = c           # половина длины обкладки
        segments = [
            # выводы к обкладкам
            ((0, -2 * c), (0, -0.55 * c)),
            ((0, 0.55 * c), (0, 2 * c)),
            # перемычка между секциями
            ((0, -0.25 * c), (0, 0.25 * c)),
            # обкладки первой секции
            ((-plate_half, -0.55 * c), (plate_half, -0.55 * c)),
            ((-plate_half, -0.25 * c), (plate_half, -0.25 * c)),
            # обкладки второй секции
            ((-plate_half, 0.25 * c), (plate_half, 0.25 * c)),
            ((-plate_half, 0.55 * c), (plate_half, 0.55 * c)),
        ]
        for (dx1, dy1), (dx2, dy2) in segments:
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        """Габарит как у реактора: 40 × 80 px при клетке 20."""
        c = self.cell
        return self._rotated_bbox((-c, -2 * c, c, 2 * c))


COMPONENT_TYPES = (
    "breaker", "disconnector", "bus", "transformer", "split_transformer",
    "three_winding_transformer", "autotransformer", "reactor", "line",
    "voltage_transformer", "current_transformer", "node", "corner",
    "grounding_switch", "ground", "opn", "coupling_capacitor", "line_trap",
    "connection_filter", "av_breaker", "fuse", "cabinet", "container",
    "bushing_monitor", "capacitor_battery",
)


def create_component(comp_type, comp_id, x, y, grid_size=20):
    if comp_type == "breaker": return Breaker(comp_id, x, y, grid_size)
    elif comp_type == "disconnector": return Disconnector(comp_id, x, y, grid_size)
    elif comp_type == "bus": return Bus(comp_id, x, y, grid_size)
    elif comp_type == "transformer": return Transformer(comp_id, x, y, grid_size)
    elif comp_type == "split_transformer": return SplitTransformer(comp_id, x, y, grid_size)
    elif comp_type == "three_winding_transformer": return ThreeWindingTransformer(comp_id, x, y, grid_size)
    elif comp_type == "autotransformer": return Autotransformer(comp_id, x, y, grid_size)
    elif comp_type == "reactor": return Reactor(comp_id, x, y, grid_size)
    elif comp_type == "voltage_transformer": return VoltageTransformer(comp_id, x, y, grid_size)
    elif comp_type == "current_transformer": return CurrentTransformer(comp_id, x, y, grid_size)
    elif comp_type == "node": return Node(comp_id, x, y, grid_size)
    elif comp_type == "line": return PowerLine(comp_id, x, y, grid_size)
    elif comp_type == "corner": return Corner(comp_id, x, y, grid_size)
    elif comp_type == "grounding_switch": return GroundingSwitch(comp_id, x, y, grid_size)
    elif comp_type == "ground": return Ground(comp_id, x, y, grid_size)
    elif comp_type == "opn": return SurgeArrester(comp_id, x, y, grid_size)
    elif comp_type == "coupling_capacitor": return CouplingCapacitor(comp_id, x, y, grid_size)
    elif comp_type == "line_trap": return LineTrap(comp_id, x, y, grid_size)
    elif comp_type == "connection_filter": return ConnectionFilter(comp_id, x, y, grid_size)
    elif comp_type == "av_breaker": return AutomaticBreaker(comp_id, x, y, grid_size)
    elif comp_type == "fuse": return Fuse(comp_id, x, y, grid_size)
    elif comp_type == "cabinet": return Cabinet(comp_id, x, y, grid_size)
    elif comp_type == "container": return Container(comp_id, x, y, grid_size)
    elif comp_type == "bushing_monitor": return BushingMonitor(comp_id, x, y, grid_size)
    elif comp_type == "capacitor_battery": return CapacitorBattery(comp_id, x, y, grid_size)
    else: raise ValueError(f"Неизвестный тип элемента: {comp_type}")