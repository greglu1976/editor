# library.py

import math
import tkinter as tk

class Component:
    def __init__(self, comp_id, x, y, grid_size=20):
        self.id = comp_id
        self.name = ""
        self.x = x
        self.y = y
        self.grid_size = grid_size
        self.type = "base"
        self.ports = {}

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
        r = self.grid_size
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
        r_sq = (self.grid_size / 2) * zoom
        r_port = self.grid_size * zoom
        
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
        r = self.grid_size
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
        r = self.grid_size
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
        r_inner = (self.grid_size / 2) * 0.8 * zoom
        r_port = self.grid_size * zoom
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
        rx = self.grid_size * 0.3   # уже по ширине
        ry = self.grid_size * 0.5   # высоту оставляем
        return (self.x - rx, self.y - ry, self.x + rx, self.y + ry)


# ==========================================
# 3. ШИНА
# ==========================================
class Bus(Component):
    def __init__(self, comp_id, x, y, grid_size=20, length=None):
        super().__init__(comp_id, x, y, grid_size)
        self.type = "bus"
        self.length = length if length else grid_size * 4
        self.generate_ports()

    def generate_ports(self):
        self.ports = {
            "left":   {"x": self.x - self.length, "y": self.y, "node_id": f"N_{self.id}_left"},
            "right":  {"x": self.x + self.length, "y": self.y, "node_id": f"N_{self.id}_right"},
            "center": {"x": self.x, "y": self.y, "node_id": f"N_{self.id}_center"}
        }
        step = self.grid_size
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
        # Порты строго по сетке: на 2 клетки вверх и вниз
        self.ports = {
            "HV": {"x": self.x, "y": self.y - self.grid_size * 2, "node_id": f"N_{self.id}_HV"},
            "LV": {"x": self.x, "y": self.y + self.grid_size * 2, "node_id": f"N_{self.id}_LV"},
            # Нейтраль на 1 клетку влево и на 1 клетку вверх от центра
            "N":  {"x": self.x - self.grid_size, "y": self.y - self.grid_size, "node_id": f"N_{self.id}_N"} 
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        # Радиус = 1 клетка сетки (чтобы круги помещались между узлами)
        r = self.grid_size * zoom 
        
        # Центры кругов: верхний на 0.5 клетки вверх, нижний на 0.5 клетки вниз
        cy1 = sy - r * 0.5
        cy2 = sy + r * 0.5
        
        # 1. Линии выводов ВН и НН
        canvas.create_line(sx, sy - r * 2, sx, cy1 - r, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx, sy + r * 2, sx, cy2 + r, width=max(1, int(2*zoom)), fill="black")
        
        # 2. Линия нейтрали (короткая горизонтальная от левого края верхнего круга)
        canvas.create_line(sx - r, cy1, sx - r, cy1, width=max(1, int(2*zoom)), fill="black") # Точка нейтрали
        
        # 3. Рисуем два круга
        canvas.create_oval(sx-r, cy1-r, sx+r, cy1+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        canvas.create_oval(sx-r, cy2-r, sx+r, cy2+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        
        # 4. Подпись
        if self.name:
            canvas.create_text(sx + r + 15*zoom, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

    def get_bounding_box(self):
        r = self.grid_size * 1
        return (self.x - r, self.y - r, self.x + r, self.y + r)

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
        return self.grid_size * 3

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
        length = self.grid_size * 3 * zoom
        
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
        pad = self.grid_size * 0.5

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
        r = self.grid_size
        self.ports = {
            "top":    {"x": self.x, "y": self.y - r, "node_id": f"N_{self.id}_top"},
            "bottom": {"x": self.x, "y": self.y + r, "node_id": f"N_{self.id}_bot"},
            "left":   {"x": self.x - r, "y": self.y, "node_id": f"N_{self.id}_left"},
            "right":  {"x": self.x + r, "y": self.y, "node_id": f"N_{self.id}_right"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y, connections=None):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = self.grid_size * zoom
        
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
        r = self.grid_size
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
        r = self.grid_size
        if self.rotation in [0, 180]:
            self.ports = {"top": {"x": self.x, "y": self.y - r, "node_id": f"N_{self.id}_top"}}
        else:
            self.ports = {"left": {"x": self.x - r, "y": self.y, "node_id": f"N_{self.id}_left"}}

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r_inner = (self.grid_size / 2) * 0.8 * zoom
        r_out = self.grid_size * zoom
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
        r = self.grid_size * 1.2  # 120% достаточно для захвата "ножек" заземления
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
        g = self.grid_size
        # Порты LV1 и LV2 вынесены на 2 клетки в стороны и на 3 клетки вниз.
        self.ports = {
            "HV":  {"x": self.x, "y": self.y - g * 2, "node_id": f"N_{self.id}_HV"},
            "LV1": {"x": self.x - g * 2, "y": self.y + g * 3, "node_id": f"N_{self.id}_LV1"},
            "LV2": {"x": self.x + g * 2, "y": self.y + g * 3, "node_id": f"N_{self.id}_LV2"},
            "N":   {"x": self.x - g, "y": self.y - g, "node_id": f"N_{self.id}_N"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = self.grid_size * zoom 
        
        cy1 = sy - r * 0.5
        cy2 = sy + r * 0.5
        
        cx_left = sx - r * 0.75
        cx_right = sx + r * 0.75
        
        # 1. Хвостик сверху (ВН)
        canvas.create_line(sx, sy - r * 2, sx, cy1 - r, width=max(1, int(2*zoom)), fill="black")
        
        # 2. ЛЕВЫЙ ХВОСТИК (Г-образный, с правильным спуском)
        canvas.create_line(cx_left, cy2 + r, cx_left, sy + r * 2, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(cx_left, sy + r * 2, sx - r * 2, sy + r * 2, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx - r * 2, sy + r * 2, sx - r * 2, sy + r * 3, width=max(1, int(2*zoom)), fill="black")
        
        # 3. ПРАВЫЙ ХВОСТИК (Г-образный, с правильным спуском)
        canvas.create_line(cx_right, cy2 + r, cx_right, sy + r * 2, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(cx_right, sy + r * 2, sx + r * 2, sy + r * 2, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx + r * 2, sy + r * 2, sx + r * 2, sy + r * 3, width=max(1, int(2*zoom)), fill="black")
        
        # 4. Рисуем три круга
        canvas.create_oval(sx-r, cy1-r, sx+r, cy1+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        canvas.create_oval(cx_left-r, cy2-r, cx_left+r, cy2+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        canvas.create_oval(cx_right-r, cy2-r, cx_right+r, cy2+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        
        # 5. Подпись
        if self.name:
            canvas.create_text(sx + r * 3, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

    def get_bounding_box(self):
        r = self.grid_size * 1
        return (self.x - r, self.y - r, self.x + r, self.y + r)


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
        g = self.grid_size
        self.ports = {
            "HV": {"x": self.x, "y": self.y - g * 2, "node_id": f"N_{self.id}_HV"},
            "LV": {"x": self.x, "y": self.y + g * 2, "node_id": f"N_{self.id}_LV"},
            "MV": {"x": self.x + g * 2, "y": self.y, "node_id": f"N_{self.id}_MV"},
            "N":  {"x": self.x - g, "y": self.y - g, "node_id": f"N_{self.id}_N"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = self.grid_size * zoom 
        
        canvas.create_line(sx, sy - r * 2, sx, sy - r * 1.5, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx, sy + r * 1.5, sx, sy + r * 2, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx + r * 1.5, sy, sx + r * 2, sy, width=max(1, int(2*zoom)), fill="black")
        
        cy_hv = sy - r * 0.6
        canvas.create_oval(sx-r, cy_hv-r, sx+r, cy_hv+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        
        cy_lv = sy + r * 0.6
        canvas.create_oval(sx-r, cy_lv-r, sx+r, cy_lv+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        
        cx_mv = sx + r * 0.8
        canvas.create_oval(cx_mv-r, sy-r, cx_mv+r, sy+r, fill="white", outline="black", width=max(1, int(2*zoom)))
        
        if self.name:
            canvas.create_text(sx - r * 2, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

    def get_bounding_box(self):
        r = self.grid_size * 0.8
        return (self.x - r, self.y - r*2, self.x + r*2, self.y + r*2)


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
        g = self.grid_size
        self.ports = {
            "HV": {"x": self.x, "y": self.y - g * 2, "node_id": f"N_{self.id}_HV"},
            "LV": {"x": self.x, "y": self.y + g * 2, "node_id": f"N_{self.id}_LV"},
            "MV": {"x": self.x + g * 2, "y": self.y - g * 0.5, "node_id": f"N_{self.id}_MV"}, 
            "N":  {"x": self.x - g, "y": self.y - g, "node_id": f"N_{self.id}_N"}
        }
        
    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = self.grid_size * zoom 
        
        cy1 = sy - r * 0.5
        cy2 = sy + r * 0.5
        
        line_w = max(1, int(2 * zoom))

        arc_radius = r * 1.6537
        arc_center_x = sx - r * 0.6536
        arc_center_y = cy1 + r * 0.0191
        
        arc_x0 = arc_center_x - arc_radius
        arc_y0 = arc_center_y - arc_radius
        arc_x1 = arc_center_x + arc_radius
        arc_y1 = arc_center_y + arc_radius

        canvas.create_arc(arc_x0, arc_y0, arc_x1, arc_y1, 
                          start=1, extent=66, style="arc", 
                          width=line_w, outline="black")
        
        canvas.create_line(sx, sy + r * 2, sx, cy2 + r, width=line_w, fill="black")
        canvas.create_line(sx + r, cy1, sx + r * 2, cy1, width=line_w, fill="black")

        canvas.create_oval(sx - r, cy1 - r, sx + r, cy1 + r, fill="white", outline="black", width=line_w)
        canvas.create_oval(sx - r, cy2 - r, sx + r, cy2 + r, fill="white", outline="black", width=line_w)
        
        if self.name:
            canvas.create_text(sx + r * 2.5, sy, text=self.name, anchor="w", font=("Arial", int(10 * zoom)), fill="black")

    def get_bounding_box(self):
        r = self.grid_size * 0.8
        return (self.x - r, self.y - r, self.x + r, self.y + r)


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
        g = self.grid_size
        self.ports = {
            "top":    {"x": self.x, "y": self.y - g * 2, "node_id": f"N_{self.id}_top"},
            "bottom": {"x": self.x, "y": self.y + g * 2, "node_id": f"N_{self.id}_bot"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        sx = self.x * zoom + offset_x
        sy = self.y * zoom + offset_y
        r = self.grid_size * zoom 
        
        canvas.create_line(sx, sy - r * 2, sx, sy - r, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx, sy + r, sx, sy + r * 2, width=max(1, int(2*zoom)), fill="black")
        
        canvas.create_arc(sx-r, sy-r, sx+r, sy+r, 
                          start=90, extent=270, 
                          style=tk.ARC, 
                          outline="black", 
                          width=max(1, int(2*zoom)))
        
        canvas.create_line(sx, sy, sx + r, sy, width=max(1, int(2*zoom)), fill="black")
        canvas.create_line(sx, sy, sx, sy + r, width=max(1, int(2*zoom)), fill="black")
        
        if self.name:
            canvas.create_text(sx + r + 15*zoom, sy, text=self.name, anchor="w", font=("Arial", int(10*zoom)), fill="black")

    def get_bounding_box(self):
        r = self.grid_size * 0.8
        return (self.x - r, self.y - r, self.x + r, self.y + r)


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
        g = self.grid_size
        wx, wy = self._local_to_world(0, -g)
        self.ports = {
            "top": {"x": wx, "y": wy, "node_id": f"N_{self.id}_top"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.grid_size
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
        g = self.grid_size
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
        g = self.grid_size
        wx, wy = self._local_to_world(0, -g)
        self.ports = {
            "top": {"x": wx, "y": wy, "node_id": f"N_{self.id}_top"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.grid_size
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
        g = self.grid_size
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
        g = self.grid_size
        # Два порта: сверху и снизу на 1 клетку от центра
        wx_top, wy_top = self._local_to_world(0, -g)
        wx_bot, wy_bot = self._local_to_world(0, g)
        
        self.ports = {
            "top":    {"x": wx_top, "y": wy_top, "node_id": f"N_{self.id}_top"},
            "bottom": {"x": wx_bot, "y": wy_bot, "node_id": f"N_{self.id}_bot"}
        }

    def draw(self, canvas, zoom, offset_x, offset_y):
        g = self.grid_size
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
        g = self.grid_size
        return (self.x - g, self.y - g, self.x + g, self.y + g)



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
    else: raise ValueError(f"Неизвестный тип элемента: {comp_type}")