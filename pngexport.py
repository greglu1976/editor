# -*- coding: utf-8 -*-
"""Экспорт сцены редактора в PNG (через Pillow).

Модуль необязательный: если Pillow не установлен, редактор сообщает об
этом подсказкой, а остальная работа продолжается. Примитивы повторяют
вызовы Tk-canvas (create_line, create_polygon, create_oval, create_arc,
create_text), поэтому сцена рисуется тем же кодом, что и в PDF.

Растр строится в два приёма: экранные координаты схемы умножаются на
масштаб экспорта (для подложки — 1/подложка) и на разрешение, а подписи
рисуются системным шрифтом (тот же, что встраивается в PDF).
"""

from PIL import Image, ImageDraw, ImageFont

import pdfexport

#: Ограничение размера картинки по большей стороне, пикселей.
MAX_SIDE = 8000

#: Разрешение по умолчанию, пикселей на пункт (144 dpi).
DEFAULT_RESOLUTION = 2.0

#: Anchor Tk → anchor Pillow.
_ANCHORS = {
    "center": "mm",
    "n": "ma", "s": "md", "e": "rm", "w": "lm",
    "nw": "la", "ne": "ra", "sw": "ld", "se": "rd",
}


class RasterCanvas:
    """Канва с набором примитивов Tk-canvas, рисующая в растр Pillow."""

    def __init__(self, image, draw, scale, offset_x, offset_y, resolution,
                 font_path):
        self.image = image
        self.draw = draw
        self.scale = scale
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.resolution = resolution
        self.k = scale * resolution
        self.font_path = font_path
        self._fonts = {}

    # ------------------------------------------------------------ сервис
    def _point(self, x, y):
        return ((x + self.offset_x) * self.k, (y + self.offset_y) * self.k)

    def _points(self, coords):
        return [self._point(x, y)
                for x, y in zip(coords[0::2], coords[1::2])]

    def _box(self, x1, y1, x2, y2):
        p1 = self._point(x1, y1)
        p2 = self._point(x2, y2)
        return (min(p1[0], p2[0]), min(p1[1], p2[1]),
                max(p1[0], p2[0]), max(p1[1], p2[1]))

    @staticmethod
    def _color(name, default=(0, 0, 0)):
        if name in (None, ""):
            return None
        red, green, blue = pdfexport.color_rgb(name if name else default)
        return (int(round(red * 255)), int(round(green * 255)),
                int(round(blue * 255)))

    def _line_width(self, kwargs):
        try:
            width = float(kwargs.get("width", 1))
        except (TypeError, ValueError):
            width = 1.0
        return max(1, int(round(width * self.k)))

    def _font(self, size):
        key = size
        if key not in self._fonts:
            pixel = max(4, int(round(size * self.k)))
            try:
                self._fonts[key] = ImageFont.truetype(self.font_path, pixel)
            except Exception:
                self._fonts[key] = ImageFont.load_default()
        return self._fonts[key]

    # ---------------------------------------------------------- примитивы
    def create_line(self, *coords, **kwargs):
        points = self._points(coords)
        if len(points) < 2:
            return None
        color = self._color(kwargs.get("fill", "black"))
        if color is None:
            return None
        width = self._line_width(kwargs)
        dash = kwargs.get("dash")
        if dash:
            self._dashed(points, color, width, dash)
        else:
            self.draw.line(points, fill=color, width=width, joint="curve")
        return None

    def _dashed(self, points, color, width, dash):
        """Штриховая линия: режем каждый отрезок на штрихи."""
        try:
            on = float(dash[0])
            off = float(dash[1] if len(dash) > 1 else dash[0])
        except (TypeError, ValueError, IndexError):
            self.draw.line(points, fill=color, width=width)
            return
        on *= self.k
        off *= self.k
        if on <= 0:
            self.draw.line(points, fill=color, width=width)
            return
        for start, end in zip(points, points[1:]):
            x1, y1 = start
            x2, y2 = end
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if length < 1e-6:
                continue
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            position = 0.0
            while position < length:
                piece = min(on, length - position)
                if piece > 0.01:
                    self.draw.line(
                        [(x1 + ux * position, y1 + uy * position),
                         (x1 + ux * (position + piece),
                          y1 + uy * (position + piece))],
                        fill=color, width=width)
                position += piece + off

    def create_rectangle(self, x1, y1, x2, y2, **kwargs):
        box = self._box(x1, y1, x2, y2)
        if box[2] - box[0] < 0.5:
            box = (box[0], box[1], box[0] + 0.5, box[3])
        if box[3] - box[1] < 0.5:
            box = (box[0], box[1], box[2], box[1] + 0.5)
        self.draw.rectangle(box, fill=self._color(kwargs.get("fill")),
                            outline=self._color(kwargs.get("outline")),
                            width=self._line_width(kwargs))
        return None

    def create_polygon(self, *coords, **kwargs):
        points = self._points(coords)
        if len(points) < 2:
            return None
        fill = self._color(kwargs.get("fill"))
        outline = self._color(kwargs.get("outline"))
        width = self._line_width(kwargs)
        if fill is not None:
            self.draw.polygon(points, fill=fill)
        if outline is not None:
            self.draw.line(points + [points[0]], fill=outline, width=width,
                           joint="curve")
        return None

    def create_oval(self, x1, y1, x2, y2, **kwargs):
        box = self._box(x1, y1, x2, y2)
        if box[2] - box[0] < 1:
            box = (box[0], box[1], box[0] + 1, box[3])
        if box[3] - box[1] < 1:
            box = (box[0], box[1], box[2], box[1] + 1)
        self.draw.ellipse(box, fill=self._color(kwargs.get("fill")),
                          outline=self._color(kwargs.get("outline", "black")),
                          width=self._line_width(kwargs))
        return None

    def create_arc(self, x1, y1, x2, y2, **kwargs):
        box = self._box(x1, y1, x2, y2)
        start = float(kwargs.get("start", 0))
        extent = float(kwargs.get("extent", 90))
        # Tk считает углы против часовой стрелки, Pillow — по часовой
        self.draw.arc(box, start=-(start + extent), end=-start,
                      fill=self._color(kwargs.get("outline", "black")),
                      width=self._line_width(kwargs))
        return None

    def create_text(self, x, y, **kwargs):
        text = kwargs.get("text") or ""
        if not text:
            return None
        size = pdfexport.font_size(kwargs.get("font"))
        anchor = kwargs.get("anchor", "center")
        point = self._point(x, y)
        self.draw.text(point, text, font=self._font(size),
                       fill=self._color(kwargs.get("fill", "black")),
                       anchor=_ANCHORS.get(anchor, "mm"))
        return None

    def bbox(self, item):
        """Как у Tk-canvas: у растровой канвы элементов нет."""
        return None


def export_png(path, recorder, width, height, offset_x, offset_y,
               scale=1.0, resolution=DEFAULT_RESOLUTION, font_path=None):
    """Рисует записанную сцену в PNG. Возвращает размер картинки (w, h)."""
    resolution = max(0.2, float(resolution))
    longest = max(width * resolution, height * resolution)
    if longest > MAX_SIDE:
        resolution = max(0.2, resolution * MAX_SIDE / longest)

    font_path = font_path or pdfexport.find_font()
    if not font_path:
        raise RuntimeError("не найден системный шрифт для подписей")

    image_w = max(1, int(round(width * resolution)))
    image_h = max(1, int(round(height * resolution)))
    image = Image.new("RGB", (image_w, image_h), "white")
    draw = ImageDraw.Draw(image)
    canvas = RasterCanvas(image, draw, scale, offset_x, offset_y, resolution,
                          font_path)
    recorder.replay(canvas)
    image.save(path, "PNG")
    return image_w, image_h
