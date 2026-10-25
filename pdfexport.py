#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Экспорт сцены редактора в PDF (без внешних зависимостей).

Пишет одностраничный PDF: подложка (если загружена), элементы схемы и подписи.
Кириллица работает за счёт встраивания TrueType-шрифта (Arial/Segoe UI/DejaVu)
в виде Type0/CIDFontType2 с кодировкой Identity-H.
"""

from __future__ import annotations

import os
import struct
import zlib

# ---------------------------------------------------------------- TrueType


def _u16(data, offset):
    return struct.unpack_from(">H", data, offset)[0]


def _s16(data, offset):
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


class TrueTypeFont:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as handle:
            self.data = handle.read()
        self.tables = {}
        count = _u16(self.data, 4)
        for index in range(count):
            offset = 12 + index * 16
            tag = self.data[offset:offset + 4].decode("latin-1")
            table_offset = _u32(self.data, offset + 8)
            length = _u32(self.data, offset + 12)
            self.tables[tag] = (table_offset, length)

        head = self.tables["head"][0]
        self.units_per_em = _u16(self.data, head + 18)
        self.bbox = (_s16(self.data, head + 36), _s16(self.data, head + 38),
                     _s16(self.data, head + 40), _s16(self.data, head + 42))

        hhea = self.tables["hhea"][0]
        self.ascent = _s16(self.data, hhea + 4)
        self.descent = _s16(self.data, hhea + 6)
        self.num_hmetrics = _u16(self.data, hhea + 34)

        maxp = self.tables["maxp"][0]
        self.num_glyphs = _u16(self.data, maxp + 4)

        self.cmap = self._parse_cmap()
        self.widths = self._parse_widths()

    # ---------------------------------------------------------- cmap
    def _parse_cmap(self):
        offset = self.tables["cmap"][0]
        count = _u16(self.data, offset + 2)
        candidates = []
        for index in range(count):
            record = offset + 4 + index * 8
            platform = _u16(self.data, record)
            encoding = _u16(self.data, record + 2)
            sub = offset + _u32(self.data, record + 4)
            fmt = _u16(self.data, sub)
            if platform == 3 and encoding in (1, 10):
                candidates.append((fmt, sub))
            elif platform == 0:
                candidates.append((fmt, sub))
        for fmt, sub in candidates:
            if fmt == 4:
                return self._cmap_format4(sub)
            if fmt == 12:
                return self._cmap_format12(sub)
        return {}

    def _cmap_format4(self, offset):
        seg_count = _u16(self.data, offset + 6) // 2
        ends_at = offset + 14
        starts_at = ends_at + seg_count * 2 + 2
        deltas_at = starts_at + seg_count * 2
        ranges_at = deltas_at + seg_count * 2
        mapping = {}
        for index in range(seg_count):
            end = _u16(self.data, ends_at + index * 2)
            start = _u16(self.data, starts_at + index * 2)
            delta = _s16(self.data, deltas_at + index * 2)
            range_offset = _u16(self.data, ranges_at + index * 2)
            if start > end or end == 0xFFFF:
                continue
            for code in range(start, end + 1):
                if range_offset == 0:
                    glyph = (code + delta) & 0xFFFF
                else:
                    address = (ranges_at + index * 2) + range_offset + (code - start) * 2
                    if address + 1 >= len(self.data):
                        continue
                    glyph = _u16(self.data, address)
                    if glyph:
                        glyph = (glyph + delta) & 0xFFFF
                if glyph:
                    mapping[code] = glyph
        return mapping

    def _cmap_format12(self, offset):
        groups = _u32(self.data, offset + 12)
        mapping = {}
        for index in range(groups):
            base = offset + 16 + index * 12
            start = _u32(self.data, base)
            end = _u32(self.data, base + 4)
            glyph = _u32(self.data, base + 8)
            for code in range(start, end + 1):
                mapping[code] = glyph + (code - start)
        return mapping

    # ---------------------------------------------------------- hmtx
    def _parse_widths(self):
        offset = self.tables["hmtx"][0]
        widths = {}
        last = 0
        for index in range(min(self.num_hmetrics, self.num_glyphs)):
            last = _u16(self.data, offset + index * 4)
            widths[index] = last
        for index in range(self.num_hmetrics, self.num_glyphs):
            widths[index] = last
        return widths

    def glyph(self, character):
        return self.cmap.get(ord(character), 0)

    def cmap_reverse(self, glyph_id):
        if not hasattr(self, "_reverse"):
            self._reverse = {}
            for code, gid in self.cmap.items():
                self._reverse.setdefault(gid, code)
        return self._reverse.get(glyph_id, 0)

    def width1000(self, glyph_id):
        return int(round(self.widths.get(glyph_id, 0) * 1000.0 / self.units_per_em))


def find_font():
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\verdana.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    for folder in (r"C:\Program Files\Python38",):
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower() in ("dejavusans.ttf", "liberationsans-regular.ttf"):
                    return os.path.join(root, name)
    return None


# ---------------------------------------------------------------- PDF

class PdfWriter:
    def __init__(self):
        self.objects = []

    def add(self, payload):
        self.objects.append(payload)
        return len(self.objects)

    def reserve(self):
        """Резервирует номер объекта (для ссылок вперёд)."""
        self.objects.append(b"")
        return len(self.objects)

    def set(self, index, payload):
        self.objects[index - 1] = payload

    def stream(self, data, extra=b""):
        if isinstance(data, str):
            data = data.encode("latin-1")
        body = b"<< /Length %d %s >>\nstream\n" % (len(data), extra) + data + b"\nendstream"
        return self.add(body)

    def save(self, path):
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, payload in enumerate(self.objects, start=1):
            offsets.append(len(output))
            output += b"%d 0 obj\n" % index + payload + b"\nendobj\n"
        xref = len(output)
        output += b"xref\n0 %d\n" % (len(self.objects) + 1)
        output += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            output += b"%010d 00000 n \n" % offset
        output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(self.objects) + 1, xref)
        with open(path, "wb") as handle:
            handle.write(output)


class PageCanvas:
    """Подменяет Tk-canvas и превращает вызовы рисования в операторы PDF."""

    def __init__(self, font, scale, offset_x, offset_y, page_height):
        self.font = font
        self.scale = scale
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.page_height = page_height
        self.ops = []
        self.used_glyphs = set()
        self._stroke = (0, 0, 0)
        self._width = 1.0

    # ---------------------------------------------------------- transform
    def _x(self, x):
        return (x + self.offset_x) * self.scale

    def _y(self, y):
        return self.page_height - (y + self.offset_y) * self.scale

    def _set_style(self, fill=None, outline=None, width=None):
        color = fill or outline or "black"
        if width:
            self._width = max(0.3, width * self.scale)
        self._stroke = _color_rgb(color)

    def _stroke_ops(self):
        r, g, b = self._stroke
        return f"{r:.3f} {g:.3f} {b:.3f} RG {self._width:.3f} w\n"

    # ---------------------------------------------------------- primitives
    def create_line(self, *coords, **kwargs):
        if kwargs.get("fill") in ("", None) and "fill" in kwargs:
            return
        self._set_style(fill=kwargs.get("fill", "black"), width=kwargs.get("width", 1))
        ops = [self._stroke_ops()]
        points = list(zip(coords[0::2], coords[1::2]))
        if len(points) < 2:
            return
        ops.append(f"{self._x(points[0][0]):.2f} {self._y(points[0][1]):.2f} m\n")
        for x, y in points[1:]:
            ops.append(f"{self._x(x):.2f} {self._y(y):.2f} l\n")
        ops.append("S\n")
        self.ops.append("".join(ops))

    def create_rectangle(self, x1, y1, x2, y2, **kwargs):
        self.create_polygon(x1, y1, x2, y1, x2, y2, x1, y2, **kwargs)

    def create_polygon(self, *coords, **kwargs):
        points = list(zip(coords[0::2], coords[1::2]))
        if len(points) < 2:
            return
        fill = kwargs.get("fill")
        outline = kwargs.get("outline")
        self._set_style(fill=outline or fill or "black", width=kwargs.get("width", 1))
        ops = []
        if fill:
            r, g, b = _color_rgb(fill)
            ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg\n")
        ops.append(f"{self._x(points[0][0]):.2f} {self._y(points[0][1]):.2f} m\n")
        for x, y in points[1:]:
            ops.append(f"{self._x(x):.2f} {self._y(y):.2f} l\n")
        ops.append("h ")
        if fill and outline:
            ops.append("B\n")
        elif fill:
            ops.append("f\n")
        else:
            ops.append("S\n")
        self.ops.append(self._stroke_ops() + "".join(ops))

    def create_oval(self, x1, y1, x2, y2, **kwargs):
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        rx, ry = abs(x2 - x1) / 2.0, abs(y2 - y1) / 2.0
        k = 0.5522847498
        points = [
            (cx + rx, cy), (cx + rx, cy + k * ry), (cx + k * rx, cy + ry), (cx, cy + ry),
            (cx - k * rx, cy + ry), (cx - rx, cy + k * ry), (cx - rx, cy),
            (cx - rx, cy - k * ry), (cx - k * rx, cy - ry), (cx, cy - ry),
            (cx + k * rx, cy - ry), (cx + rx, cy - k * ry), (cx + rx, cy),
        ]
        fill = kwargs.get("fill")
        outline = kwargs.get("outline", "black")
        ops = []
        if fill:
            r, g, b = _color_rgb(fill)
            ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg\n")
        self._set_style(fill=outline, width=kwargs.get("width", 1))
        ops.append(self._stroke_ops())
        ops.append(f"{self._x(points[0][0]):.2f} {self._y(points[0][1]):.2f} m\n")
        for index in range(1, len(points), 3):
            p1, p2, p3 = points[index], points[index + 1], points[index + 2]
            ops.append(
                f"{self._x(p1[0]):.2f} {self._y(p1[1]):.2f} "
                f"{self._x(p2[0]):.2f} {self._y(p2[1]):.2f} "
                f"{self._x(p3[0]):.2f} {self._y(p3[1]):.2f} c\n")
        ops.append("h ")
        ops.append("B\n" if (fill and outline) else ("f\n" if fill else "S\n"))
        self.ops.append("".join(ops))

    def create_arc(self, x1, y1, x2, y2, **kwargs):
        import math
        start = float(kwargs.get("start", 0))
        extent = float(kwargs.get("extent", 90))
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        rx, ry = abs(x2 - x1) / 2.0, abs(y2 - y1) / 2.0
        steps = max(4, int(abs(extent) / 6))
        coords = []
        for index in range(steps + 1):
            angle = math.radians(start + extent * index / steps)
            coords.append((cx + rx * math.cos(angle), cy - ry * math.sin(angle)))
        self._set_style(fill=kwargs.get("outline", "black"), width=kwargs.get("width", 1))
        ops = [self._stroke_ops(),
               f"{self._x(coords[0][0]):.2f} {self._y(coords[0][1]):.2f} m\n"]
        for x, y in coords[1:]:
            ops.append(f"{self._x(x):.2f} {self._y(y):.2f} l\n")
        ops.append("S\n")
        self.ops.append("".join(ops))

    def create_text(self, x, y, **kwargs):
        text = kwargs.get("text", "")
        if not text:
            return
        font_spec = kwargs.get("font", ("Arial", 10))
        size = 10
        if isinstance(font_spec, (tuple, list)):
            for part in font_spec:
                if isinstance(part, int):
                    size = part
                    break
        elif isinstance(font_spec, str):
            import re
            match = re.search(r"(\d+)", font_spec)
            if match:
                size = int(match.group(1))

        anchor = kwargs.get("anchor", "center")
        width = _measure(text, size)
        ascent, descent = _metrics(size)
        px, py = x, y
        if "w" in anchor:
            left = px
        elif "e" in anchor:
            left = px - width
        else:
            left = px - width / 2.0
        if "n" in anchor:
            baseline = py + ascent
        elif "s" in anchor:
            baseline = py - descent
        else:
            baseline = py + (ascent - descent) / 2.0

        glyphs = []
        for character in text:
            glyph = self.font.glyph(character)
            if glyph == 0:
                glyph = self.font.glyph("?")
            glyphs.append(glyph)
            self.used_glyphs.add(glyph)
        hexed = "".join("%04X" % glyph for glyph in glyphs)
        color = _color_rgb(kwargs.get("fill", "black"))
        self.ops.append(
            f"BT /F1 {size * max(1.0, self.scale):.2f} Tf "
            f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
            f"{self._x(left):.2f} {self._y(baseline):.2f} Td "
            f"<{hexed}> Tj ET\n")


def _color_rgb(name):
    table = {
        "black": (0, 0, 0), "white": (1, 1, 1), "gray": (0.5, 0.5, 0.5),
        "grey": (0.5, 0.5, 0.5), "red": (0.8, 0, 0), "blue": (0, 0, 0.8),
        "green": (0, 0.5, 0), "cyan": (0, 0.7, 0.7), "wheat4": (0.55, 0.48, 0.38),
        "#9a9a9a": (0.6, 0.6, 0.6), "#a8a8a8": (0.66, 0.66, 0.66),
    }
    if name in table:
        return table[name]
    if isinstance(name, str) and name.startswith("#") and len(name) == 7:
        try:
            return tuple(int(name[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
        except ValueError:
            pass
    return (0, 0, 0)


_font_cache = {}


def _tkfont(size):
    key = ("font", size)
    if key not in _font_cache:
        import tkinter.font as tkfont
        _font_cache[key] = tkfont.Font(family="Arial", size=-size)
    return _font_cache[key]


def _metrics(size):
    font = _tkfont(size)
    return font.metrics("ascent"), font.metrics("descent")


def _measure(text, size):
    return _tkfont(size).measure(text)


def build_font_objects(writer, font, used_glyphs):
    font_file = writer.add(
        b"<< /Length %d /Length1 %d >>\nstream\n" % (len(font.data), len(font.data))
        + font.data + b"\nendstream")

    widths = " ".join(f"{gid} [{font.width1000(gid)}]"
                      for gid in sorted(used_glyphs))
    descriptor = writer.add((
        "<< /Type /FontDescriptor /FontName /EmbeddedSans /Flags 32 "
        f"/FontBBox [{font.bbox[0]} {font.bbox[1]} {font.bbox[2]} {font.bbox[3]}] "
        "/ItalicAngle 0 "
        f"/Ascent {font.ascent} /Descent {font.descent} /CapHeight {font.ascent} "
        "/StemV 80 "
        f"/FontFile2 {font_file} 0 R >>").encode("latin-1"))

    cid = writer.add((
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /EmbeddedSans "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {descriptor} 0 R /DW 1000 /W [{widths}] "
        "/CIDToGIDMap /Identity >>").encode("latin-1"))

    pairs = [(gid, font.cmap_reverse(gid)) for gid in sorted(used_glyphs)
             if font.cmap_reverse(gid)]
    blocks = []
    for start in range(0, len(pairs), 100):
        chunk = pairs[start:start + 100]
        body = "".join(f"<{gid:04X}> <{code:04X}>\n" for gid, code in chunk)
        blocks.append(f"{len(chunk)} beginbfchar\n{body}endbfchar\n")
    tounicode = writer.stream((
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        + "".join(blocks) +
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend").encode("latin-1"))

    return writer.add((
        "<< /Type /Font /Subtype /Type0 /BaseFont /EmbeddedSans "
        "/Encoding /Identity-H "
        f"/DescendantFonts [{cid} 0 R] /ToUnicode {tounicode} 0 R >>").encode("latin-1"))


class PdfDocument:
    """Одностраничный PDF: канва-адаптер + запись файла."""

    def __init__(self, width, height, offset_x=0.0, offset_y=0.0, scale=1.0, font_path=None):
        self.width = width
        self.height = height
        self.scale = scale
        self.writer = PdfWriter()
        self.font = TrueTypeFont(font_path or find_font())
        self.canvas = PageCanvas(self.font, scale, offset_x, offset_y, height)

    def save(self, path):
        writer = self.writer
        # Каталог и Pages резервируем первыми: в trailer /Root всегда 1 0 R
        catalog = writer.reserve()
        pages = writer.reserve()
        content_bytes = "".join(self.canvas.ops).encode("latin-1")
        content = writer.stream(content_bytes)
        font_obj = build_font_objects(writer, self.font, self.canvas.used_glyphs)
        page = writer.add((
            f"<< /Type /Page /Parent {pages} 0 R "
            f"/MediaBox [0 0 {self.width:.2f} {self.height:.2f}] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
            f"/Contents {content} 0 R >>").encode("latin-1"))
        writer.set(pages, f"<< /Type /Pages /Kids [{page} 0 R] /Count 1 >>".encode("latin-1"))
        writer.set(catalog, f"<< /Type /Catalog /Pages {pages} 0 R >>".encode("latin-1"))
        writer.save(path)
