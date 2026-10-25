#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Извлечение векторной графики из PDF для подложки в редакторе схем.

Без внешних зависимостей: разбирает объекты PDF, потоки контента и формы,
возвращает ломаные линии в координатах страницы (y вниз, как в редакторе).

Поддерживается то, что встречается в чертежах: m/l/c/v/y/re/h, S/s/f/B/b/n,
q/Q, cm, Do (формы), вложенные ресурсы. Текст не разбирается — подписи
берутся отдельно (pdftotext) или не нужны.
"""

from __future__ import annotations

import re
import zlib

NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
TOKEN = re.compile(
    rb"/(?:[^\s/<>\[\](){}]+)"          # имя
    rb"|[+-]?(?:\d+\.?\d*|\.\d+)"      # число
    rb"|[A-Za-z*'\"]+"                  # оператор
    rb"|<<|>>|\[|\]"
    rb"|\((?:\\.|[^\\()])*\)"          # строка
    rb"|<[0-9A-Fa-f\s]*>"              # hex-строка
)

PATH_OPS = {b"m", b"l", b"c", b"v", b"y", b"re", b"h"}
PAINT_OPS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"}


# ---------------------------------------------------------------- объекты PDF

def read_objects(data):
    objects = {}
    for match in re.finditer(rb"(\d+)\s+\d+\s+obj\b(.*?)\bendobj", data, re.S):
        number = int(match.group(1))
        body = match.group(2)
        stream = None
        index = body.find(b"stream")
        if index != -1:
            head = body[:index]
            rest = body[index + len(b"stream"):]
            if rest.startswith(b"\r\n"):
                rest = rest[2:]
            elif rest[:1] in (b"\n", b"\r"):
                rest = rest[1:]
            end = rest.rfind(b"endstream")
            if end != -1:
                rest = rest[:end]
            stream = rest
            body = head
        objects[number] = (body, stream)
    return objects


def decode_stream(body, stream):
    if stream is None:
        return b""
    if b"/FlateDecode" in body:
        try:
            return zlib.decompress(stream)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(stream)
            except zlib.error:
                return b""
    return stream


def find_page(objects):
    for number, (body, _stream) in objects.items():
        if re.search(rb"/Type\s*/Page\b", body) and not re.search(rb"/Type\s*/Pages\b", body):
            return number
    return None


def resolve_ref(body, key):
    match = re.search(rb"/" + key + rb"\s+(\d+)\s+\d+\s+R", body)
    return int(match.group(1)) if match else None


def page_size(objects, page_number):
    body = objects[page_number][0]
    match = re.search(rb"/MediaBox\s*\[\s*([^\]]*)\]", body)
    if not match:
        return 595.0, 842.0
    nums = [float(x) for x in NUMBER.findall(match.group(1))[:4]]
    if len(nums) != 4:
        return 595.0, 842.0
    x0, y0, x1, y1 = nums
    return abs(x1 - x0), abs(y1 - y0)


def content_stream(objects, page_number):
    body = objects[page_number][0]
    refs = []
    array = re.search(rb"/Contents\s*\[([^\]]*)\]", body)
    if array:
        refs = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", array.group(1))]
    else:
        single = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", body)
        if single:
            refs = [int(single.group(1))]
    chunks = []
    for ref in refs:
        obj_body, stream = objects.get(ref, (b"", None))
        chunks.append(decode_stream(obj_body, stream))
    return b"\n".join(chunks)


def resource_xobjects(objects, resources_body):
    """Имя -> номер объекта для /XObject из ресурсов."""
    match = re.search(rb"/XObject\s*<<(.*?)>>", resources_body, re.S)
    if not match:
        return {}
    result = {}
    for name, num in re.findall(rb"/([^\s/<>\[\]]+)\s+(\d+)\s+\d+\s+R", match.group(1)):
        result[name] = int(num)
    return result


def page_resources(objects, page_number):
    body = objects[page_number][0]
    ref = resolve_ref(body, b"Resources")
    if ref is not None and ref in objects:
        return objects[ref][0]
    return body


# ---------------------------------------------------------------- матрицы

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


# ---------------------------------------------------------------- интерпретатор

class _PathState:
    def __init__(self):
        self.points = []
        self.subpaths = []
        self.current = []

    def move_to(self, x, y):
        self.flush()
        self.current = [(x, y)]
        self.points.append((x, y))

    def line_to(self, x, y):
        if not self.current:
            self.move_to(x, y)
            return
        self.current.append((x, y))
        self.points.append((x, y))

    def flush(self):
        if len(self.current) >= 2:
            self.subpaths.append(self.current)
        self.current = []

    def done(self):
        self.flush()
        return self.subpaths


def _bezier(p0, p1, p2, p3, steps=6):
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = (mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0]
             + 3 * mt * t * t * p2[0] + t ** 3 * p3[0])
        y = (mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1]
             + 3 * mt * t * t * p2[1] + t ** 3 * p3[1])
        points.append((x, y))
    return points


def run_content(content, ctm, xobjects, resources_body, objects, out, depth=0):
    if depth > 12:
        return
    stack = []
    operands = []
    path = _PathState()

    for match in TOKEN.finditer(content):
        token = match.group(0)

        if NUMBER.fullmatch(token):
            operands.append(float(token))
            continue

        if token.startswith(b"/") or token.startswith(b"(") or token.startswith(b"<"):
            operands.append(token)
            continue

        op = token.rstrip(b"*'\"")
        op_raw = token
        if op_raw in (b"<<", b">>", b"[", b"]"):
            operands.append(op_raw)
            continue

        if op_raw in PATH_OPS:
            if op_raw == b"m" and len(operands) >= 2:
                x, y = operands[-2], operands[-1]
                path.move_to(*apply(ctm, x, y))
            elif op_raw == b"l" and len(operands) >= 2:
                x, y = operands[-2], operands[-1]
                path.line_to(*apply(ctm, x, y))
            elif op_raw == b"c" and len(operands) >= 6:
                p0 = path.current[-1] if path.current else apply(ctm, *operands[-6:-4])
                p1 = apply(ctm, *operands[-6:-4])
                p2 = apply(ctm, *operands[-4:-2])
                p3 = apply(ctm, *operands[-2:])
                for point in _bezier(p0, p1, p2, p3):
                    path.line_to(*point)
            elif op_raw in (b"v", b"y") and len(operands) >= 4:
                p0 = path.current[-1] if path.current else apply(ctm, *operands[-4:-2])
                if op_raw == b"v":
                    p1, p2, p3 = p0, apply(ctm, *operands[-4:-2]), apply(ctm, *operands[-2:])
                else:
                    p1, p2, p3 = apply(ctm, *operands[-4:-2]), apply(ctm, *operands[-2:]), apply(ctm, *operands[-2:])
                for point in _bezier(p0, p1, p2, p3):
                    path.line_to(*point)
            elif op_raw == b"re" and len(operands) >= 4:
                x, y, w, h = operands[-4:]
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                first = apply(ctm, *corners[0])
                path.move_to(*first)
                for corner in corners[1:]:
                    path.line_to(*apply(ctm, *corner))
                path.line_to(*first)
            elif op_raw == b"h":
                if path.current:
                    path.line_to(*path.current[0])
            operands = []
            continue

        if op_raw in PAINT_OPS:
            subpaths = path.done()
            path = _PathState()
            if op_raw != b"n":
                out.extend(subpaths)
            operands = []
            continue

        if op_raw == b"q":
            stack.append(ctm)
            operands = []
            continue
        if op_raw == b"Q":
            if stack:
                ctm = stack.pop()
            operands = []
            continue
        if op_raw == b"cm" and len(operands) >= 6:
            m = tuple(operands[-6:])
            ctm = multiply(m, ctm)
            operands = []
            continue
        if op_raw == b"Do" and operands:
            name = operands[-1]
            if isinstance(name, bytes) and name.startswith(b"/"):
                ref = xobjects.get(name[1:])
                if ref is not None and ref in objects:
                    obj_body, obj_stream = objects[ref]
                    if b"/Subtype" in obj_body and b"/Form" in obj_body:
                        form_ctm = ctm
                        matrix = re.search(rb"/Matrix\s*\[([^\]]*)\]", obj_body)
                        if matrix:
                            nums = [float(x) for x in NUMBER.findall(matrix.group(1))[:6]]
                            if len(nums) == 6:
                                form_ctm = multiply(tuple(nums), ctm)
                        form_res = b""
                        res_ref = resolve_ref(obj_body, b"Resources")
                        if res_ref is not None and res_ref in objects:
                            form_res = objects[res_ref][0]
                        else:
                            form_res = resources_body
                        run_content(decode_stream(obj_body, obj_stream), form_ctm,
                                    resource_xobjects(objects, form_res),
                                    form_res, objects, out, depth + 1)
            operands = []
            continue
        if op_raw == b"BT":
            # текст пропускаем до ET
            end = content.find(b"ET", match.end())
            if end == -1:
                break
            # перезапуск обхода после ET
            tail = content[end + 2:]
            run_content(tail, ctm, xobjects, resources_body, objects, out, depth)
            return
        if op_raw == b"BI":
            end = content.find(b"EI", match.end())
            if end == -1:
                break
            tail = content[end + 2:]
            run_content(tail, ctm, xobjects, resources_body, objects, out, depth)
            return

        operands = []


def load_pdf(path):
    """Возвращает (ширина, высота, ломаные) в координатах страницы, y вниз."""
    data = open(path, "rb").read()
    objects = read_objects(data)
    page = find_page(objects)
    if page is None:
        raise ValueError("в PDF не найдена страница")
    width, height = page_size(objects, page)
    resources = page_resources(objects, page)
    xobjects = resource_xobjects(objects, resources)
    out = []
    run_content(content_stream(objects, page), IDENTITY, xobjects, resources, objects, out)

    polylines = []
    for subpath in out:
        points = [(x, height - y) for x, y in subpath]
        if len(points) >= 2:
            polylines.append(points)
    return width, height, polylines


if __name__ == "__main__":
    import sys
    import time

    for pdf in sys.argv[1:]:
        start = time.time()
        w, h, lines = load_pdf(pdf)
        points = sum(len(l) for l in lines)
        print(f"{pdf}: {w:.0f}x{h:.0f} pt, ломаных {len(lines)}, точек {points}, "
              f"{time.time() - start:.2f} c")
