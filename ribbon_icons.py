# -*- coding: utf-8 -*-
"""Иконки ленты: векторные рисунки, сглаженные суперсэмплингом.

Каждая иконка описана в сетке 32×32 и рисуется через Pillow в 4 раза
крупнее, а затем уменьшается фильтром Ланцоша. Это даёт гладкие линии и
скругления без внешних файлов. Если Pillow нет, ``main`` использует свои
простые canvas-иконки, поэтому лента остаётся работоспособной.
"""

from __future__ import annotations

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

BLUE = "#1f4e79"
BLUE_MID = "#2f6da5"
BLUE_LIGHT = "#9dbfdd"
BLUE_PALE = "#e8f1fa"
INK = "#33414f"
WHITE = "#ffffff"
RED = "#c0504d"
RED_PALE = "#f7e3e2"
GREEN = "#2e8b57"
GREEN_PALE = "#e2f2e8"
AMBER = "#d08a23"
AMBER_PALE = "#fbf0d9"
PURPLE = "#7b4ba8"
PURPLE_PALE = "#efe7f7"
YELLOW_PALE = "#fffbe0"
NOTE_ACCENT = "#b8860b"

GRID = 32.0
SUPERSAMPLE = 4

_ICONS = {}
_RENDERS = {}
_FONTS = {}


def _icon(name):
    def register(function):
        _ICONS[name] = function
        return function
    return register


class _Painter:
    def __init__(self, draw, scale):
        self.draw = draw
        self.scale = scale

    def point(self, x, y):
        return (x * self.scale, y * self.scale)

    def box(self, box):
        return tuple(value * self.scale for value in box)

    def width(self, width):
        return max(1, int(round(width * self.scale)))

    def line(self, points, color=BLUE, width=2.0, rounded=True):
        points = [self.point(x, y) for x, y in points]
        px = self.width(width)
        self.draw.line(points, fill=color, width=px, joint="curve")
        if rounded:
            radius = px / 2.0
            for x, y in (points[0], points[-1]):
                self.draw.ellipse((x - radius, y - radius,
                                   x + radius, y + radius), fill=color)

    def polygon(self, points, fill=None, outline=None, width=2.0):
        points = [self.point(x, y) for x, y in points]
        if fill is not None:
            self.draw.polygon(points, fill=fill)
        if outline is not None:
            px = self.width(width)
            self.draw.line(points + [points[0]], fill=outline,
                           width=px, joint="curve")
            radius = px / 2.0
            for x, y in points:
                self.draw.ellipse((x - radius, y - radius,
                                   x + radius, y + radius), fill=outline)

    def rect(self, box, radius=0.0, fill=None, outline=BLUE, width=2.0):
        box = self.box(box)
        px = self.width(width) if outline is not None else 0
        if radius:
            self.draw.rounded_rectangle(
                box, radius=radius * self.scale, fill=fill,
                outline=outline, width=px)
        else:
            self.draw.rectangle(box, fill=fill, outline=outline, width=px)

    def ellipse(self, box, fill=None, outline=BLUE, width=2.0):
        box = self.box(box)
        px = self.width(width) if outline is not None else 0
        self.draw.ellipse(box, fill=fill, outline=outline, width=px)

    def arc(self, box, start, end, color=BLUE, width=2.0):
        box = self.box(box)
        px = self.width(width)
        self.draw.arc(box, start, end, fill=color, width=px)
        radius = px / 2.0
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        rx = (box[2] - box[0]) / 2.0
        ry = (box[3] - box[1]) / 2.0
        from math import cos, radians, sin
        for angle in (start, end):
            angle = radians(angle)
            x = cx + rx * cos(angle)
            y = cy + ry * sin(angle)
            self.draw.ellipse((x - radius, y - radius,
                               x + radius, y + radius), fill=color)

    def text(self, x, y, text, size=6.0, color=WHITE, bold=True):
        font = _font(max(1, int(round(size * self.scale))), bold)
        try:
            self.draw.text(self.point(x, y), text, font=font, fill=color,
                           anchor="mm")
        except Exception:
            self.draw.text(self.point(x, y), text, font=font, fill=color)

    def dashed(self, start, end, color, width=1.4, dash=2.6, gap=1.8):
        from math import hypot
        x1, y1 = start
        x2, y2 = end
        length = hypot(x2 - x1, y2 - y1)
        if not length:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        position = 0.0
        while position < length:
            finish = min(position + dash, length)
            self.line([(x1 + ux * position, y1 + uy * position),
                       (x1 + ux * finish, y1 + uy * finish)],
                      color=color, width=width)
            position = finish + gap

    def dashed_rect(self, box, color, width=1.4, dash=2.6, gap=1.8):
        x1, y1, x2, y2 = box
        self.dashed((x1, y1), (x2, y1), color, width, dash, gap)
        self.dashed((x2, y1), (x2, y2), color, width, dash, gap)
        self.dashed((x2, y2), (x1, y2), color, width, dash, gap)
        self.dashed((x1, y2), (x1, y1), color, width, dash, gap)


def _font(size, bold):
    key = (size, bold)
    if key in _FONTS:
        return _FONTS[key]
    font = None
    if ImageFont is not None:
        names = (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                 ("arialbd.ttf" if bold else "arial.ttf"),
                 ("LiberationSans-Bold.ttf" if bold
                  else "LiberationSans-Regular.ttf"),
                 ("C:/Windows/Fonts/arialbd.ttf" if bold
                  else "C:/Windows/Fonts/arial.ttf"))
        for name in names:
            try:
                font = ImageFont.truetype(name, size)
                break
            except Exception:
                continue
        if font is None:
            try:
                font = ImageFont.load_default(size=size)
            except Exception:
                font = ImageFont.load_default()
    _FONTS[key] = font
    return font


def _page(p, box=(6, 3, 24, 29), outline=BLUE, fill=WHITE, fold=5.0):
    x1, y1, x2, y2 = box
    p.rect(box, radius=2.2, fill=fill, outline=outline, width=2.0)
    p.polygon([(x2 - fold, y1), (x2, y1 + fold), (x2 - fold, y1 + fold)],
              fill=BLUE_PALE, outline=outline, width=1.0)


def _badge(p, text, color, box=(14, 20, 29, 27.5)):
    x1, y1, x2, y2 = box
    p.rect(box, radius=2.0, fill=color, outline=WHITE, width=1.2)
    p.text((x1 + x2) / 2.0, (y1 + y2) / 2.0 + 0.2, text,
           size=max(5.0, (y2 - y1) * 0.62), color=WHITE)


def _pencil(p, tip=(13, 26), end=(27, 12)):
    ex, ey = end
    p.line([(ex, ey), (ex + 2.0, ey - 2.0)], color=RED, width=3.4)
    p.line([tip, end], color=AMBER, width=3.2)
    tx, ty = tip
    p.polygon([(tx, ty), (tx - 3.0, ty + 4.0), (tx + 2.6, ty + 2.6)],
              fill=INK, outline=None)


@_icon("select")
def _select(p):
    p.polygon([(9.5, 4.5), (9.5, 25.5), (14.5, 20.5), (18.5, 28.5),
               (22.5, 26.5), (18.5, 19.0), (25.0, 18.0)],
              fill=BLUE_PALE, outline=BLUE, width=2.0)
    p.line([(12.5, 10.0), (12.5, 18.0), (16.0, 21.0)],
           color=WHITE, width=1.0)


@_icon("connect")
def _connect(p):
    p.line([(8.0, 24.0), (14.0, 21.0), (19.0, 15.0), (24.0, 8.0)],
           color=BLUE_MID, width=2.2)
    p.ellipse((3.5, 19.5, 12.5, 28.5), fill=BLUE_PALE,
              outline=BLUE, width=2.0)
    p.ellipse((19.5, 3.5, 28.5, 12.5), fill=BLUE, outline=WHITE, width=1.4)
    p.ellipse((22.5, 6.5, 25.5, 9.5), fill=WHITE, outline=None)


@_icon("delete")
def _delete(p):
    p.rect((3.5, 8.0, 19.5, 26.0), radius=2.4, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    p.line([(21.5, 16.5), (29.0, 24.0)], color=RED, width=2.6)
    p.line([(29.0, 16.5), (21.5, 24.0)], color=RED, width=2.6)


@_icon("rotate")
def _rotate(p):
    p.arc((6.0, 5.0, 26.0, 25.0), 35, 315, color=BLUE, width=2.2)
    p.polygon([(20.0, 2.8), (27.0, 5.5), (21.8, 10.2)],
              fill=BLUE, outline=None)


@_icon("undo")
def _undo(p):
    p.line([(25.0, 16.0), (10.5, 16.0)], color=BLUE_MID, width=2.6)
    p.polygon([(6.0, 16.0), (14.0, 9.8), (14.0, 22.2)],
              fill=BLUE, outline=None)
    p.line([(25.0, 12.0), (25.0, 20.0)], color=BLUE_LIGHT, width=1.6)


@_icon("redo")
def _redo(p):
    p.line([(7.0, 16.0), (21.5, 16.0)], color=BLUE_MID, width=2.6)
    p.polygon([(26.0, 16.0), (18.0, 9.8), (18.0, 22.2)],
              fill=BLUE, outline=None)
    p.line([(7.0, 12.0), (7.0, 20.0)], color=BLUE_LIGHT, width=1.6)


@_icon("rebuild")
def _rebuild(p):
    p.arc((5.0, 5.0, 27.0, 27.0), 35, 150, color=BLUE, width=2.2)
    p.arc((5.0, 5.0, 27.0, 27.0), 215, 330, color=BLUE_MID, width=2.2)
    p.polygon([(19.0, 2.5), (26.5, 5.0), (21.5, 9.5)],
              fill=BLUE, outline=None)
    p.polygon([(13.0, 29.5), (5.5, 27.0), (10.5, 22.5)],
              fill=BLUE_MID, outline=None)


@_icon("copy")
def _copy(p):
    p.rect((4.5, 10.0, 18.5, 27.0), radius=2.4, fill=BLUE_PALE,
           outline=BLUE_LIGHT, width=2.0)
    p.rect((11.5, 4.5, 25.5, 21.5), radius=2.4, fill=WHITE,
           outline=BLUE, width=2.0)
    p.line([(15.0, 8.5), (22.0, 8.5)], color=BLUE_LIGHT, width=1.4)
    p.line([(15.0, 12.0), (22.0, 12.0)], color=BLUE_LIGHT, width=1.4)


@_icon("paste")
def _paste(p):
    p.rect((5.5, 7.0, 26.5, 28.0), radius=3.0, fill=WHITE,
           outline=BLUE, width=2.0)
    p.rect((10.0, 17.0, 22.0, 25.0), radius=1.4, fill=BLUE_PALE,
           outline=BLUE_LIGHT, width=1.2)
    p.line([(12.5, 20.0), (19.5, 20.0)], color=BLUE_LIGHT, width=1.2)
    p.line([(12.5, 22.5), (17.5, 22.5)], color=BLUE_LIGHT, width=1.2)
    p.rect((11.5, 3.0, 20.5, 9.0), radius=2.2, fill=BLUE_MID,
           outline=WHITE, width=1.4)
    p.rect((14.0, 5.0, 18.0, 6.8), radius=0.8, fill=WHITE, outline=None)


@_icon("save")
def _save(p):
    p.rect((4.5, 4.5, 27.5, 27.5), radius=3.0, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    p.rect((10.0, 4.5, 22.0, 12.5), radius=1.2, fill=BLUE,
           outline=BLUE, width=1.0)
    p.rect((15.0, 6.0, 20.0, 11.0), radius=0.8, fill=WHITE, outline=None)
    p.rect((8.5, 16.5, 23.5, 27.5), radius=1.4, fill=WHITE,
           outline=BLUE, width=1.4)
    p.line([(11.5, 20.5), (20.5, 20.5)], color=BLUE_LIGHT, width=1.3)
    p.line([(11.5, 24.0), (20.5, 24.0)], color=BLUE_LIGHT, width=1.3)


@_icon("save_as")
def _save_as(p):
    _page(p, box=(4.0, 3.0, 21.0, 29.0))
    _pencil(p, tip=(13.5, 26.0), end=(27.0, 12.5))


@_icon("load")
def _load(p):
    p.rect((4.0, 7.0, 16.5, 14.0), radius=2.0, fill=BLUE_LIGHT,
           outline=BLUE, width=2.0)
    p.rect((4.0, 10.0, 28.0, 27.0), radius=3.0, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    p.line([(8.0, 16.0), (24.0, 16.0)], color=BLUE_LIGHT, width=1.4)


@_icon("insert")
def _insert(p):
    _page(p, box=(3.5, 3.5, 19.5, 28.5))
    p.line([(19.0, 16.0), (27.5, 16.0)], color=GREEN, width=2.4)
    p.polygon([(29.0, 16.0), (23.0, 11.3), (23.0, 20.7)],
              fill=GREEN, outline=None)


@_icon("clear")
def _clear(p):
    p.line([(7.0, 8.0), (25.0, 8.0)], color=RED, width=2.4)
    p.line([(12.0, 4.8), (20.0, 4.8)], color=RED, width=2.2)
    p.polygon([(9.0, 9.5), (23.0, 9.5), (21.0, 29.0), (11.0, 29.0)],
              fill=RED_PALE, outline=RED, width=2.0)
    p.line([(13.0, 13.0), (13.0, 25.0)], color=RED, width=1.4)
    p.line([(16.0, 13.0), (16.0, 25.0)], color=RED, width=1.4)
    p.line([(19.0, 13.0), (19.0, 25.0)], color=RED, width=1.4)


@_icon("minus")
def _minus(p):
    p.ellipse((3.5, 3.5, 22.5, 22.5), fill=BLUE_PALE,
              outline=BLUE, width=2.2)
    p.line([(20.5, 20.5), (28.5, 28.5)], color=BLUE, width=3.0)
    p.line([(8.5, 13.0), (17.5, 13.0)], color=BLUE, width=2.0)
    p.line([(8.0, 8.0), (10.5, 6.0)], color=WHITE, width=1.4)


@_icon("plus")
def _plus(p):
    p.ellipse((3.5, 3.5, 22.5, 22.5), fill=BLUE_PALE,
              outline=BLUE, width=2.2)
    p.line([(20.5, 20.5), (28.5, 28.5)], color=BLUE, width=3.0)
    p.line([(8.5, 13.0), (17.5, 13.0)], color=BLUE, width=2.0)
    p.line([(13.0, 8.5), (13.0, 17.5)], color=BLUE, width=2.0)
    p.line([(8.0, 8.0), (10.5, 6.0)], color=WHITE, width=1.4)


@_icon("fit")
def _fit(p):
    p.line([(4.0, 12.0), (4.0, 4.0), (12.0, 4.0)], width=2.4)
    p.line([(20.0, 4.0), (28.0, 4.0), (28.0, 12.0)], width=2.4)
    p.line([(4.0, 20.0), (4.0, 28.0), (12.0, 28.0)], width=2.4)
    p.line([(20.0, 28.0), (28.0, 28.0), (28.0, 20.0)], width=2.4)
    p.rect((11.5, 11.5, 20.5, 20.5), radius=2.0, fill=BLUE_PALE,
           outline=BLUE, width=1.4)


@_icon("extents")
def _extents(p):
    p.dashed_rect((3.0, 4.0, 29.0, 28.0), BLUE_LIGHT, width=1.3)
    p.line([(8.5, 21.5), (13.5, 13.5), (19.5, 18.5), (24.0, 9.0)],
           color=BLUE, width=2.0)
    p.ellipse((6.5, 19.5, 10.5, 23.5), fill=WHITE, outline=BLUE, width=1.4)
    p.ellipse((22.0, 7.0, 26.0, 11.0), fill=BLUE, outline=WHITE, width=1.0)


@_icon("pdf")
def _pdf(p):
    _page(p, box=(4.0, 2.5, 22.5, 29.5))
    _badge(p, "PDF", RED, box=(13.5, 19.5, 29.0, 27.5))


@_icon("png")
def _png(p):
    p.rect((3.5, 5.5, 28.5, 26.5), radius=3.0, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    p.ellipse((18.0, 8.5, 24.5, 15.0), fill=AMBER, outline=WHITE, width=1.2)
    p.polygon([(6.5, 23.5), (12.5, 14.0), (18.0, 21.0), (21.5, 17.5),
               (26.0, 23.5)], fill=GREEN, outline=None)
    p.line([(7.5, 7.5), (11.0, 7.5)], color=WHITE, width=1.6)


@_icon("ssd")
def _ssd(p):
    _page(p, box=(4.0, 2.5, 22.5, 29.5))
    _badge(p, "SSD", BLUE, box=(13.5, 19.5, 29.0, 27.5))


@_icon("shield")
def _shield(p):
    p.rect((7.5, 3.5, 24.5, 28.5), radius=2.8, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    for x in (12.0, 16.0, 20.0):
        p.line([(x, 7.5), (x, 24.5)], color=BLUE_LIGHT, width=1.4)
    p.line([(20.5, 15.5), (22.5, 15.5), (22.5, 19.5), (20.5, 19.5)],
           color=AMBER, width=1.6)


@_icon("report")
def _report(p):
    _page(p, box=(6.0, 3.0, 26.0, 29.0))
    p.rect((9.0, 13.0, 23.0, 26.5), radius=1.2, fill=WHITE,
           outline=BLUE_LIGHT, width=1.2)
    p.rect((9.0, 9.0, 23.0, 13.0), radius=1.2, fill=BLUE, outline=None)
    p.line([(9.0, 17.0), (23.0, 17.0)], color=BLUE_LIGHT, width=1.1)
    p.line([(9.0, 20.5), (23.0, 20.5)], color=BLUE_LIGHT, width=1.1)
    p.line([(9.0, 24.0), (23.0, 24.0)], color=BLUE_LIGHT, width=1.1)
    p.line([(16.0, 17.0), (16.0, 26.5)], color=BLUE_LIGHT, width=1.1)


@_icon("unbound")
def _unbound(p):
    p.polygon([(16.0, 3.0), (30.0, 28.0), (2.0, 28.0)],
              fill=AMBER_PALE, outline=AMBER, width=2.0)
    p.line([(16.0, 10.5), (16.0, 19.5)], color=AMBER, width=2.6)
    p.ellipse((14.6, 22.4, 17.4, 25.2), fill=AMBER, outline=None)


@_icon("nir")
def _nir(p):
    _page(p, box=(4.0, 2.5, 22.5, 29.5))
    p.line([(8.0, 10.5), (19.0, 10.5)], color=BLUE_LIGHT, width=1.2)
    p.line([(8.0, 13.5), (16.0, 13.5)], color=BLUE_LIGHT, width=1.2)
    _badge(p, "НИР", PURPLE, box=(13.0, 19.5, 29.0, 27.5))


@_icon("structure")
def _structure(p):
    p.rect((3.5, 3.5, 14.5, 11.0), radius=2.0, fill=BLUE_PALE,
           outline=BLUE, width=1.8)
    p.rect((17.5, 3.5, 28.5, 11.0), radius=2.0, fill=BLUE_PALE,
           outline=BLUE, width=1.8)
    p.rect((10.0, 21.0, 22.0, 28.5), radius=2.0, fill=BLUE,
           outline=WHITE, width=1.2)
    p.line([(9.0, 11.0), (9.0, 16.0), (16.0, 16.0), (16.0, 21.0)],
           color=BLUE_LIGHT, width=1.6)
    p.line([(23.0, 11.0), (23.0, 16.0), (16.0, 16.0)],
           color=BLUE_LIGHT, width=1.6)


@_icon("check")
def _check(p):
    p.ellipse((3.5, 3.5, 28.5, 28.5), fill=GREEN, outline=None)
    p.line([(9.0, 16.0), (14.0, 21.0), (23.0, 10.5)],
           color=WHITE, width=2.8)


@_icon("about")
def _about(p):
    p.ellipse((3.5, 3.5, 28.5, 28.5), fill=BLUE, outline=None)
    p.ellipse((14.6, 8.0, 17.4, 10.8), fill=WHITE, outline=None)
    p.rect((14.8, 13.5, 17.2, 23.5), radius=1.2, fill=WHITE, outline=None)


@_icon("developer")
def _developer(p):
    p.line([(11.5, 8.5), (4.0, 16.0), (11.5, 23.5)], color=BLUE, width=2.4)
    p.line([(20.5, 8.5), (28.0, 16.0), (20.5, 23.5)], color=BLUE, width=2.4)
    p.line([(18.5, 6.5), (13.5, 25.5)], color=AMBER, width=2.0)


@_icon("find")
def _find(p):
    p.ellipse((4.0, 3.5, 22.0, 21.5), fill=BLUE_PALE,
              outline=BLUE, width=2.3)
    p.line([(20.0, 20.0), (28.5, 28.5)], color=BLUE, width=3.2)
    p.line([(8.0, 7.5), (10.5, 5.5)], color=WHITE, width=1.4)


@_icon("analog")
def _analog(p):
    from math import pi, sin
    points = []
    for step in range(19):
        x = 4.0 + step * (19.0 / 18.0)
        y = 16.0 - 4.5 * sin(step * 3.0 * pi / 18.0)
        points.append((x, y))
    p.line(points, color=PURPLE, width=2.2)


@_icon("props")
def _props(p):
    for y, knob in ((8.0, 12.0), (16.0, 22.0), (24.0, 16.0)):
        p.line([(4.0, y), (28.0, y)], color=PURPLE_PALE, width=2.4)
        p.line([(4.0, y), (knob, y)], color=PURPLE, width=2.4)
        p.ellipse((knob - 3.0, y - 3.0, knob + 3.0, y + 3.0),
                  fill=WHITE, outline=PURPLE, width=2.0)


@_icon("protlink")
def _protlink(p):
    p.line([(7.0, 25.0), (25.0, 9.0)], color=BLUE_MID, width=2.0)
    p.ellipse((3.5, 20.5, 11.5, 28.5), fill=BLUE_PALE,
              outline=BLUE, width=1.8)
    p.polygon([(24.0, 3.5), (29.0, 6.0), (29.0, 12.0), (24.0, 16.5),
               (19.0, 12.0), (19.0, 6.0)], fill=AMBER, outline=WHITE,
              width=1.2)
    p.line([(24.0, 7.0), (24.0, 10.5)], color=WHITE, width=1.4)
    p.ellipse((23.2, 12.0, 24.8, 13.6), fill=WHITE, outline=None)


@_icon("container")
def _container(p):
    p.rect((3.0, 8.5, 29.0, 25.5), radius=3.0, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    p.rect((3.0, 8.5, 29.0, 14.0), radius=3.0, fill=BLUE, outline=None)
    p.rect((3.0, 11.5, 29.0, 14.0), radius=0.0, fill=BLUE, outline=None)
    for x in (10.0, 16.0, 22.0):
        p.line([(x, 16.0), (x, 24.0)], color=BLUE_LIGHT, width=1.3)
    p.ellipse((6.0, 18.5, 8.5, 21.0), fill=AMBER, outline=None)


@_icon("komplekt")
def _komplekt(p):
    p.rect((3.5, 6.5, 22.5, 27.5), radius=2.8, fill=BLUE_PALE,
           outline=BLUE, width=2.0)
    p.line([(3.5, 13.5), (22.5, 13.5)], color=BLUE_LIGHT, width=1.3)
    p.line([(3.5, 20.0), (22.5, 20.0)], color=BLUE_LIGHT, width=1.3)
    p.line([(22.5, 17.0), (27.5, 17.0)], color=AMBER, width=2.4)
    p.rect((26.0, 13.5, 31.0, 20.5), radius=2.0, fill=AMBER,
           outline=WHITE, width=1.2)


@_icon("ket_link")
def _ket_link(p):
    p.line([(8.5, 16.0), (23.5, 16.0)], color=AMBER, width=2.0)
    p.ellipse((3.5, 11.0, 11.5, 21.0), fill=AMBER, outline=WHITE, width=1.2)
    p.rect((22.0, 10.5, 30.0, 21.5), radius=2.0, fill=WHITE,
           outline=AMBER, width=2.0)


@_icon("eye")
def _eye(p):
    p.ellipse((3.0, 8.0, 29.0, 24.0), fill=WHITE, outline=BLUE, width=2.0)
    p.ellipse((10.5, 10.5, 21.5, 21.5), fill=BLUE, outline=None)
    p.ellipse((14.0, 13.0, 17.5, 16.5), fill=WHITE, outline=None)
    p.ellipse((18.0, 17.0, 19.8, 18.8), fill=BLUE_LIGHT, outline=None)


@_icon("grid")
def _grid(p):
    p.rect((4.0, 4.0, 28.0, 28.0), radius=2.4, fill=WHITE,
           outline=BLUE, width=2.0)
    p.rect((4.0, 4.0, 12.0, 12.0), radius=0.0, fill=BLUE_PALE,
           outline=None)
    for x in (12.0, 20.0):
        p.line([(x, 5.0), (x, 27.0)], color=BLUE_LIGHT, width=1.2)
    for y in (12.0, 20.0):
        p.line([(5.0, y), (27.0, y)], color=BLUE_LIGHT, width=1.2)


@_icon("nodes")
def _nodes(p):
    p.line([(16.0, 9.5), (9.0, 23.0), (23.0, 23.0), (16.0, 9.5)],
           color=BLUE_LIGHT, width=1.6)
    p.ellipse((12.5, 6.0, 19.5, 13.0), fill=BLUE, outline=WHITE, width=1.2)
    p.ellipse((5.5, 19.5, 12.5, 26.5), fill=WHITE, outline=BLUE, width=2.0)
    p.ellipse((19.5, 19.5, 26.5, 26.5), fill=WHITE, outline=BLUE, width=2.0)


@_icon("crosshair")
def _crosshair(p):
    p.line([(16.0, 3.0), (16.0, 29.0)], color=BLUE_LIGHT, width=1.2)
    p.line([(3.0, 16.0), (29.0, 16.0)], color=BLUE_LIGHT, width=1.2)
    p.ellipse((7.0, 7.0, 25.0, 25.0), outline=BLUE, width=2.0)
    p.ellipse((14.0, 14.0, 18.0, 18.0), fill=AMBER, outline=WHITE, width=1.0)


@_icon("note")
def _note(p):
    p.polygon([(5.0, 4.0), (21.0, 4.0), (27.0, 10.0), (27.0, 28.0),
               (5.0, 28.0)], fill=YELLOW_PALE, outline=NOTE_ACCENT, width=2.0)
    p.line([(21.0, 4.0), (21.0, 10.0), (27.0, 10.0)],
           color=NOTE_ACCENT, width=1.3)
    for y in (15.0, 19.0, 23.0):
        p.line([(9.0, y), (21.0, y)], color=NOTE_ACCENT, width=1.1)


def _render(name, size):
    key = (name, size)
    if key in _RENDERS:
        return _RENDERS[key]
    side = int(round(size * SUPERSAMPLE))
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    _ICONS[name](_Painter(ImageDraw.Draw(image), side / GRID))
    image = image.resize((size, size), Image.LANCZOS)
    _RENDERS[key] = image
    return image


def painter(name, fallback=None):
    def draw(canvas):
        if Image is not None and name in _ICONS:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(_render(name, 32))
                canvas.create_image(16, 16, image=photo)
                canvas._ribbon_photo = photo
                return
            except Exception:
                pass
        if fallback is not None:
            fallback(canvas)
    return draw
