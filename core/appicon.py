# -*- coding: utf-8 -*-
"""Иконка приложения — рисуется кодом, внешних файлов не требует.

Мотив: однолинейная схема на фирменном синем фоне — сборная шина,
выключатель и заземление. Крупный рисунок рисуется один раз и уменьшается
сглаживанием, поэтому все размеры выглядят одинаково и старт не тормозят.
"""

import tkinter as tk

try:
    from PIL import Image, ImageDraw
except Exception:               # без Pillow окно останется со штатной иконкой
    Image = ImageDraw = None

#: Размеры, которые Tk выбирает под заголовок окна и панель задач.
#: 256 не нужен: окно и панель задач обходятся 128, а его отрисовка
#: заметно дороже остальных размеров вместе взятых.
SIZES = (16, 32, 48, 64, 128)

#: Фирменный синий (совпадает с ui_theme.ACCENT) и его светлый оттенок.
TOP = (0x1f, 0x4e, 0x79)
BOTTOM = (0x2f, 0x6d, 0xa5)

#: Мелкие размеры рисуются упрощённым мотивом (без заземления).
SMALL_LIMIT = 32

_masters = {}


def _gradient(height=256):
    """Вертикальный градиент в виде полосы 1 × height."""
    strip = Image.new("RGBA", (1, height))
    pixels = strip.load()
    for y in range(height):
        t = y / max(1, height - 1)
        pixels[0, y] = tuple(
            int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)
    return strip


def _background(size):
    """Скруглённый квадрат с вертикальным градиентом."""
    fill = _gradient().resize((size, size), Image.BILINEAR)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
    background = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    background.paste(fill, (0, 0), mask)
    return background


def _stroke(draw, scale):
    """Возвращает функцию «толстая линия с круглыми концами» в координатах 128×128."""
    white = (255, 255, 255, 255)

    def line(x1, y1, x2, y2, width):
        draw.line((x1 * scale, y1 * scale, x2 * scale, y2 * scale),
                  fill=white, width=max(1, round(width * scale)))
        radius = max(0.5, width * scale / 2.0)
        for x, y in ((x1, y1), (x2, y2)):
            draw.ellipse((x * scale - radius, y * scale - radius,
                          x * scale + radius, y * scale + radius), fill=white)

    return line


def _symbol(draw, scale):
    """Полный мотив: шина, выключатель и заземление."""
    line = _stroke(draw, scale)
    line(26, 34, 102, 34, 9)            # сборная шина
    line(64, 34, 64, 52, 7)             # ввод к выключателю
    draw.rounded_rectangle(             # выключатель
        (46 * scale, 52 * scale, 82 * scale, 88 * scale),
        radius=max(1, 2 * scale), outline=(255, 255, 255, 255),
        width=max(1, round(8 * scale)))
    line(64, 88, 64, 99, 7)             # вывод
    line(48, 101, 80, 101, 6)           # заземление: три штриха
    line(55, 109, 73, 109, 6)
    line(61, 117, 67, 117, 6)


def _symbol_small(draw, scale):
    """Упрощённый мотив для мелких размеров: шина и выключатель.

    На 16–32 px заземление сливается в пятно, поэтому детали убираются,
    а штрихи становятся толще — силуэт остаётся узнаваемым.
    """
    line = _stroke(draw, scale)
    line(22, 40, 106, 40, 14)
    line(64, 40, 64, 58, 11)
    draw.rounded_rectangle(
        (44 * scale, 58 * scale, 84 * scale, 96 * scale),
        radius=max(1, 2 * scale), outline=(255, 255, 255, 255),
        width=max(1, round(12 * scale)))


def _master(small):
    """Крупный рисунок, из которого уменьшаются все размеры."""
    if small not in _masters:
        side = 128 if small else 512
        image = _background(side)
        (symbol, scale) = ((_symbol_small, side / 128.0) if small
                           else (_symbol, side / 128.0))
        symbol(ImageDraw.Draw(image), scale)
        _masters[small] = image
    return _masters[small]


def _render(size):
    """Одна иконка заданного размера в виде PIL-изображения RGBA."""
    return _master(size <= SMALL_LIMIT).resize((size, size), Image.LANCZOS)


def _png(size):
    """PNG-данные иконки в base64 — Tk читает их без файла на диске."""
    from io import BytesIO
    import base64
    buffer = BytesIO()
    _render(size).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def images(sizes=SIZES):
    """Список PhotoImage для ``root.iconphoto``; None, если Pillow нет."""
    if Image is None:
        return None
    try:
        # Прямая передача картинки в Tk: без кодирования в PNG и base64.
        from PIL import ImageTk
        return [ImageTk.PhotoImage(_render(size)) for size in sizes]
    except Exception:
        return [tk.PhotoImage(data=_png(size)) for size in sizes]
