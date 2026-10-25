# library.py

import math
import tkinter as tk

# Базовая единица геометрии элементов в мировых координатах.
# Не зависит от шага сетки: изменение шага меняет только привязку и вид сетки,
# но не размеры и пропорции элементов схемы.
CELL = 20


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

    def _draw_label(self, canvas, zoom, offset_x, offset_y):
        """Подпись справа от габарита: не наезжает на провода при любом повороте."""
        if not self.name:
            return
        bx1, by1, bx2, by2 = self.get_bounding_box()
        tx = (bx2 + 6) * zoom + offset_x
        ty = ((by1 + by2) / 2) * zoom + offset_y
        canvas.create_text(tx, ty, text=self.name, anchor="w",
                           font=("Arial", int(10 * zoom)), fill="black")

    def _draw_name_at(self, canvas, zoom, offset_x, offset_y, local_x, local_y=0.0):
        """Подпись в фиксированной локальной точке — исходное место символа."""
        if not self.name:
            return
        wx, wy = self._local_rotated(local_x, local_y)
        canvas.create_text(wx * zoom + offset_x, wy * zoom + offset_y,
                           text=self.name, anchor="w",
                           font=("Arial", int(10 * zoom)), fill="black")

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
        
        if self.name:
            canvas.create_text(sx + r_port + 5*zoom, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

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

        if self.name:
            canvas.create_text(sx + r_port + 5*zoom, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

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
        if self.name:
            canvas.create_text(sx, sy - 15*zoom, text=self.name, anchor="s", font=("Arial", int(10*zoom)), fill="black")

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
            canvas.create_text(end_x + 15*zoom, end_y + length/2, text=self.name, anchor="w", font=("Arial", int(9*zoom)), fill="black")

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
        
        def draw_ground(gx, gy):
            canvas.create_line(gx - 10*zoom, gy, gx + 10*zoom, gy, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(gx - 6*zoom, gy + 5*zoom, gx + 6*zoom, gy + 5*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(gx - 2*zoom, gy + 10*zoom, gx + 2*zoom, gy + 10*zoom, width=max(1, int(3*zoom)), fill="black")

        if self.rotation == 0:
            canvas.create_line(sx, sy - r_out, sx, sy - blade_len*0.3, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy - blade_len*0.3, sx + blade_len*0.6, sy + blade_len*0.3, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx, sy + blade_len*0.3, sx, sy + r_inner, width=max(1, int(2*zoom)), fill="black")
            draw_ground(sx, sy + r_inner + 2*zoom)
            
        elif self.rotation == 180:
            canvas.create_line(sx, sy + r_out, sx, sy + blade_len*0.3, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx, sy + blade_len*0.3, sx + blade_len*0.6, sy - blade_len*0.3, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx, sy - blade_len*0.3, sx, sy - r_inner, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx - 10*zoom, sy - r_inner - 2*zoom, sx + 10*zoom, sy - r_inner - 2*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx - 6*zoom, sy - r_inner - 7*zoom, sx + 6*zoom, sy - r_inner - 7*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx - 2*zoom, sy - r_inner - 12*zoom, sx + 2*zoom, sy - r_inner - 12*zoom, width=max(1, int(3*zoom)), fill="black")

        elif self.rotation == 90:
            canvas.create_line(sx + r_out, sy, sx + blade_len*0.3, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx + blade_len*0.3, sy, sx - blade_len*0.3, sy - blade_len*0.6, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx - blade_len*0.3, sy, sx - r_inner, sy, width=max(1, int(2*zoom)), fill="black")
            gx = sx - r_inner - 5*zoom
            canvas.create_line(gx, sy - 10*zoom, gx, sy + 10*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(gx - 5*zoom, sy - 6*zoom, gx - 5*zoom, sy + 6*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(gx - 10*zoom, sy - 2*zoom, gx - 10*zoom, sy + 2*zoom, width=max(1, int(3*zoom)), fill="black")

        elif self.rotation == 270:
            canvas.create_line(sx - r_out, sy, sx - blade_len*0.3, sy, width=max(1, int(2*zoom)), fill="black")
            canvas.create_line(sx - blade_len*0.3, sy, sx + blade_len*0.3, sy - blade_len*0.6, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(sx + blade_len*0.3, sy, sx + r_inner, sy, width=max(1, int(2*zoom)), fill="black")
            gx = sx + r_inner + 5*zoom
            canvas.create_line(gx, sy - 10*zoom, gx, sy + 10*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(gx + 5*zoom, sy - 6*zoom, gx + 5*zoom, sy + 6*zoom, width=max(1, int(3*zoom)), fill="black")
            canvas.create_line(gx + 10*zoom, sy - 2*zoom, gx + 10*zoom, sy + 2*zoom, width=max(1, int(3*zoom)), fill="black")

        if self.name:
            canvas.create_text(sx + r_out + 15*zoom, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

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
        x2, y2 = scr(0, -g * 0.4)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        # 2. Три штриха
        strokes = [
            (-g * 0.8, -g * 0.4, g * 0.8, -g * 0.4),
            (-g * 0.5,  g * 0.1, g * 0.5,  g * 0.1),
            (-g * 0.2,  g * 0.6, g * 0.2,  g * 0.6),
        ]
        for lx1, ly1, lx2, ly2 in strokes:
            cx1, cy1 = scr(lx1, ly1)
            cx2, cy2 = scr(lx2, ly2)
            canvas.create_line(cx1, cy1, cx2, cy2, width=lw, fill="black")

        # 3. Подпись
        if self.name:
            tx, ty = scr(g * 1.2, 0)
            canvas.create_text(tx, ty, text=self.name, anchor="w",
                               font=("Arial", int(10 * zoom)), fill="black")

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

        if self.name:
            tx, ty = scr(g * 1.2, 0)
            canvas.create_text(tx, ty, text=self.name, anchor="w",
                               font=("Arial", int(10 * zoom)), fill="black")

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
        if self.name:
            tx, ty = scr(g * 0.8, 0)
            canvas.create_text(tx, ty, text=self.name, anchor="w",
                               font=("Arial", int(10 * zoom)), fill="black")

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

        for dx1, dy1, dx2, dy2 in ((0, -2 * c, 0, -0.8 * c), (0, 0.8 * c, 0, 2 * c)):
            x1, y1 = scr(dx1, dy1)
            x2, y2 = scr(dx2, dy2)
            canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        box = [(-0.8 * c, -0.8 * c), (0.8 * c, -0.8 * c),
               (0.8 * c, 0.8 * c), (-0.8 * c, 0.8 * c)]
        pts = [v for dx, dy in box for v in scr(dx, dy)]
        canvas.create_polygon(*pts, fill="white", outline="black", width=lw)

        # Диагональ (условное обозначение фильтра)
        x1, y1 = scr(-0.45 * c, 0.45 * c)
        x2, y2 = scr(0.45 * c, -0.45 * c)
        canvas.create_line(x1, y1, x2, y2, width=lw, fill="black")

        if rotation == 0:
            self._draw_name_at(canvas, zoom, offset_x, offset_y, c + 15)
        else:
            self._draw_label(canvas, zoom, offset_x, offset_y)

    def get_bounding_box(self):
        c = self.cell
        return self._rotated_bbox((-0.8 * c, -2 * c, 0.8 * c, 2 * c))


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


COMPONENT_TYPES = (
    "breaker", "disconnector", "bus", "transformer", "split_transformer",
    "three_winding_transformer", "autotransformer", "reactor", "line",
    "voltage_transformer", "current_transformer", "node", "corner",
    "grounding_switch", "ground", "opn", "coupling_capacitor", "line_trap",
    "connection_filter", "av_breaker", "fuse",
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
    else: raise ValueError(f"Неизвестный тип элемента: {comp_type}")