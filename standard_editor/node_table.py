# -*- coding: utf-8 -*-
"""Динамическая таблица узла стандарта: модель и генерация операций DSL.

Модуль не зависит от tkinter — здесь только данные. При выборе узла в дереве
GUI `changes_gui.py` строит `TableModel`, показывает его в редактируемой
таблице, а по кнопке «В операции» превращает правки в обычные блоки
`*.изм.txt` (те же, что пишет человек в текстовом редакторе).

Виды узлов
    dict    -> строки «ключ / значение / тип», можно менять значения и
               добавлять/удалять ключи;
    list[dict] -> «широкая» таблица: столбцы = объединение полей всех строк
               (динамически), строки = элементы массива;
    list[скаляры] / скаляр -> одна колонка «Значение».

Адресация строк повторяет дерево GUI: если у строки есть «№», путь
строится как `№=...`, иначе `#индекс`. Удаления идут после правок и в
обратном порядке индексов, чтобы не сбить адресацию.
"""
from __future__ import annotations

import copy
import json
import re
from collections import OrderedDict

import changes_editor as ce

MAX_COLS = 24
MAX_ROWS = 2000
_MISSING = object()


# ---------------------------------------------------------------------------
# Представление значений
# ---------------------------------------------------------------------------
def value_text(v):
    """Полное редактируемое представление значения (для редактора ячейки)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def short_text(v, limit=220):
    """Однострочное представление для ячейки таблицы."""
    s = value_text(v)
    s = re.sub(r"[\r\n]+", " ⏎ ", s)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def type_text(v):
    if v is None:
        return "пусто"
    if isinstance(v, bool):
        return "логическое"
    if isinstance(v, str):
        return "строка" if v else "пустая строка"
    if isinstance(v, (int, float)):
        return "число"
    if isinstance(v, list):
        return "список (%d)" % len(v)
    if isinstance(v, dict):
        return "объект (%d)" % len(v)
    return type(v).__name__


def parse_cell(text, old=_MISSING):
    """Текст ячейки -> значение, по возможности сохраняя тип старого значения.

    Числовые/логические/JSON-ячейки редактируются как «26», «true», «[21, 22]».
    Если пользователь вводит что-то другое, значение законно становится
    строкой — DSL записывает его без искажений через `@json:`.
    """
    s = str(text)
    t = s.strip()
    if old is not _MISSING and not isinstance(old, str):
        if isinstance(old, bool):
            if t.lower() in ("true", "false", "1", "0", "да", "нет", "yes", "no"):
                return t.lower() in ("true", "1", "да", "yes")
            return s
        if isinstance(old, int) and re.fullmatch(r"[+-]?\d+", t):
            return int(t)
        if isinstance(old, float) and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t):
            return float(t)
        if old is None and t == "":
            return None
    if t.startswith(ce.JSON_PREFIX):
        try:
            return json.loads(t[len(ce.JSON_PREFIX):])
        except ValueError:
            return s
    if t in ("null", "true", "false") or t[:1] in ("[", "{"):
        try:
            return json.loads(t)
        except ValueError:
            return s
    return s


def dsl_value(v, warnings=None, label="ячейка"):
    """Значение -> одна строка DSL. None, если значение нельзя записать честно.

    Многострочные строки кодируются как `@json:"..."`, поэтому остаются
    многострочными в собранном JSON и не ломают построчный формат файла.
    """
    if isinstance(v, str) and re.search(r"[\r\n]", v):
        s = ce.JSON_PREFIX + json.dumps(v, ensure_ascii=False)
        if warnings is not None:
            warnings.append("%s: многострочное значение записано как @json" % label)
    else:
        s = ce.render_payload_value(v)
    try:
        back = ce.parse_value(s)
    except ce.TextError:
        back = None
    if type(back) is not type(v) or back != v:
        if warnings is not None:
            warnings.append("%s: значение %r не представимо в DSL, правка пропущена"
                            % (label, short_text(v, 60)))
        return None
    return s


def key_ok(key, warnings=None):
    """Имя поля должно быть одним DSL-ключом (без ':' и перевода строки)."""
    k = str(key)
    ok = bool(k.strip()) and ":" not in k and not re.search(r"[\r\n]", k)
    if not ok and warnings is not None:
        warnings.append("поле %r нельзя записать в DSL (пустое, с ':' или с переносом)"
                        % short_text(k, 60))
    return ok


def path_text(segs):
    """Канонический массив сегментов -> строка пути DSL."""
    s = ce.render_path(list(segs))
    # render_path(['Содержимое стандарта']) даёт '' — такой путь не запишешь
    # в строку операции, поэтому пишем имя узла явно.
    return s if s else "Содержимое стандарта"


def one_line(s):
    return re.sub(r"\s+", " ", str(s)).strip()


# ---------------------------------------------------------------------------
# Модель таблицы
# ---------------------------------------------------------------------------
class Row:
    def __init__(self, cells, seg=None, key=None, new=False):
        self.cells = OrderedDict(cells)
        self.orig = OrderedDict(cells)     # база для diff
        self.seg = seg                     # сегмент пути до строки
        self.key = key                     # исходный ключ (для kind == 'dict')
        self.new = new
        self.deleted = False

    def changed_cols(self):
        out = []
        for col, v in self.cells.items():
            if self.model_skip(col):
                continue
            old = self.orig.get(col, _MISSING)
            if old is _MISSING:
                if v not in ("", None):
                    out.append(col)        # новый столбец, заполненный у старой строки
            elif old != v or type(old) is not type(v):
                out.append(col)
        return out

    @staticmethod
    def model_skip(col):
        return col == "Тип"

    def dirty(self):
        return self.new or self.deleted or bool(self.changed_cols())


class TableModel:
    def __init__(self, source, kind, columns, rows, notes=None):
        self.source = source
        self.kind = kind                  # dict / table / values / scalar
        self.columns = list(columns)
        self.rows = rows
        self.notes = list(notes or [])

    def add_row(self):
        if self.kind == "scalar":
            return None
        cells = OrderedDict()
        for c in self.columns:
            cells[c] = ""
        if self.kind == "dict":
            cells["Тип"] = "строка"
        r = Row(cells, seg=None, key="", new=True)
        self.rows.append(r)
        return r

    def add_column(self, name):
        if self.kind != "table":
            return False
        name = str(name).strip()
        if not name or name in self.columns or name in ("#", "Тип"):
            return False
        self.columns.append(name)
        # orig намеренно не трогаем: пустой новый столбец не порождает операций.
        for r in self.rows:
            r.cells[name] = ""
        return True

    def stats(self):
        return {
            "rows": len(self.rows),
            "cols": len(self.columns),
            "changed": sum(1 for r in self.rows if not r.new and not r.deleted
                           and r.changed_cols()),
            "new": sum(1 for r in self.rows if r.new and not r.deleted),
            "deleted": sum(1 for r in self.rows if r.deleted and not r.new),
        }


def build_model(node, max_cols=MAX_COLS, max_rows=MAX_ROWS):
    """Построить динамическую таблицу по значению узла (базу не меняем)."""
    notes = []
    rows = []
    if isinstance(node, dict):
        kind, columns = "dict", ["Ключ", "Значение", "Тип"]
        items = list(node.items())
        for k, v in items[:max_rows]:
            rows.append(Row(OrderedDict([
                ("Ключ", k), ("Значение", copy.deepcopy(v)),
                ("Тип", type_text(v))]), seg=k, key=k))
        if len(items) > max_rows:
            notes.append("показаны первые %d ключей из %d" % (max_rows, len(items)))
    elif isinstance(node, list):
        part = node[:max_rows]
        if any(isinstance(x, dict) for x in part):
            kind = "table"
            cols = []
            for item in part:
                keys = item.keys() if isinstance(item, dict) else ["Значение"]
                for k in keys:
                    if k not in cols:
                        cols.append(k)
            if len(cols) > max_cols:
                notes.append("показаны первые %d столбцов из %d"
                             % (max_cols, len(cols)))
                cols = cols[:max_cols]
            columns = cols or ["Значение"]
            for i, item in enumerate(part):
                if isinstance(item, dict):
                    cells = OrderedDict((c, copy.deepcopy(item[c]))
                                        for c in columns if c in item)
                else:
                    cells = OrderedDict([("Значение", copy.deepcopy(item))])
                for c in columns:
                    cells.setdefault(c, "")
                seg = ({"№": str(item["№"])} if isinstance(item, dict)
                       and "№" in item else {"@index": i})
                rows.append(Row(OrderedDict((c, cells[c]) for c in columns), seg=seg))
        else:
            kind, columns = "values", ["Значение"]
            for i, v in enumerate(part):
                rows.append(Row(OrderedDict([("Значение", copy.deepcopy(v))]),
                                seg={"@index": i}))
        if len(node) > max_rows:
            notes.append("показаны первые %d строк из %d" % (max_rows, len(node)))
    else:
        kind, columns = "scalar", ["Значение"]
        rows.append(Row(OrderedDict([("Значение", copy.deepcopy(node))]), seg=None))
    return TableModel(node, kind, columns, rows, notes)


# ---------------------------------------------------------------------------
# Правки таблицы -> блоки *.изм.txt
# ---------------------------------------------------------------------------
def generate_ops(model, path, bylo=True, renumber=False, reason=""):
    """Вернуть (список блоков операций, предупреждения).

    Порядок важен: сначала правки существующих строк, затем добавления,
    затем удаления (по убыванию индекса). Так индексные пути `#N` не
    сдвигаются раньше, чем будут применены правки.
    """
    blocks, warnings = [], []
    base = path_text(path)
    reason_line = ("  ПРИЧИНА: %s" % one_line(reason)) if one_line(reason) else None

    def emit(lines):
        if reason_line:
            lines.append(reason_line)
        blocks.append("\n".join(lines))

    def bylo_lines(lines, pairs):
        if not bylo:
            return
        for key, old in pairs:
            if not key_ok(key, warnings):
                continue
            text = dsl_value(old, warnings, "БЫЛО.%s" % key)
            if text is not None:
                lines.append("  БЫЛО.%s: %s" % (key, text))

    def field_lines(lines, pairs):
        for key, new in pairs:
            if not key_ok(key, warnings):
                continue
            text = dsl_value(new, warnings, "поле %s" % key)
            if text is not None:
                lines.append("  > %s: %s" % (key, text))

    edited, added, removed = [], [], []
    for r in model.rows:
        if r.new:
            if not r.deleted:
                added.append(r)
        elif r.deleted:
            removed.append(r)
        elif r.changed_cols():
            edited.append(r)

    if model.kind == "dict":
        patches = [(r.key, r.orig.get("Значение", ""),
                    r.cells.get("Значение", "")) for r in edited]
        patches = [(k, o, n) for k, o, n in patches if key_ok(k, warnings)]
        if patches:
            lines = ["ИЗМЕНИТЬ ПОЛЯ %s" % base]
            bylo_lines(lines, [(k, o) for k, o, _ in patches])
            field_lines(lines, [(k, n) for k, _, n in patches])
            if len(lines) > 1:
                emit(lines)
        for r in added:
            key = one_line(r.cells.get("Ключ", ""))
            if not key or not key_ok(key, warnings):
                warnings.append("новая строка без ключа пропущена")
                continue
            text = dsl_value(r.cells.get("Значение", ""), warnings, "КЛЮЧ " + key)
            if text is None:
                continue
            emit(["ДОБАВИТЬ %s" % base,
                  "  КЛЮЧ: %s" % key,
                  "  ЗНАЧЕНИЕ: %s" % text])
        for r in removed:
            key = r.key
            if not key_ok(key, warnings):
                continue
            lines = ["УДАЛИТЬ %s" % path_text(list(path) + [key])]
            # «БЫЛО.Поле» требует объект, а удаляемое значение может быть
            # скаляром — поэтому здесь скалярная форма «БЫЛО:».
            if bylo:
                text = dsl_value(r.orig.get("Значение", ""), warnings, "БЫЛО")
                if text is not None:
                    lines.append("  БЫЛО: %s" % text)
            emit(lines)

    elif model.kind == "table":
        for r in edited:
            cols = [c for c in r.changed_cols() if key_ok(c, warnings)]
            if not cols:
                continue
            lines = ["ИЗМЕНИТЬ ПОЛЯ %s" % path_text(list(path) + [r.seg])]
            bylo_lines(lines, [(c, r.orig.get(c, "")) for c in cols])
            field_lines(lines, [(c, r.cells.get(c, "")) for c in cols])
            if len(lines) > 1:
                emit(lines)
        for r in added:
            pairs = [(c, r.cells.get(c, "")) for c in model.columns
                     if c not in ("#", "Тип") and r.cells.get(c, "") not in ("", None)]
            pairs = [(c, v) for c, v in pairs if key_ok(c, warnings)]
            if not pairs:
                warnings.append("новая пустая строка пропущена")
                continue
            lines = ["ДОБАВИТЬ %s" % base]
            field_lines(lines, pairs)
            if len(lines) > 1:
                if renumber and "№" in model.columns:
                    lines.append("  ПЕРЕНУМЕРОВАТЬ: да")
                emit(lines)
        for r in sorted(removed, key=lambda x: x.seg.get("@index", 0), reverse=True):
            lines = ["УДАЛИТЬ %s" % path_text(list(path) + [r.seg])]
            sample = [(c, r.orig.get(c, "")) for c in model.columns
                      if r.orig.get(c, "") not in ("", None)]
            bylo_lines(lines, sample[:1])
            if renumber and "№" in model.columns:
                lines.append("  ПЕРЕНУМЕРОВАТЬ: да")
            emit(lines)

    else:   # values / scalar
        for r in edited:
            old = r.orig.get("Значение", "")
            new = r.cells.get("Значение", "")
            lines = ["ЗАМЕНИТЬ %s" % (path_text(list(path) + [r.seg])
                                      if r.seg is not None else base)]
            if bylo:
                text = dsl_value(old, warnings, "БЫЛО")
                if text is not None:
                    lines.append("  БЫЛО: %s" % text)
            text = dsl_value(new, warnings, "СТАЛО")
            if text is not None:
                lines.append("  СТАЛО: %s" % text)
                emit(lines)
        for r in added:
            text = dsl_value(r.cells.get("Значение", ""), warnings, "ЗНАЧЕНИЕ")
            if text is not None:
                emit(["ДОБАВИТЬ %s" % base, "  ЗНАЧЕНИЕ: %s" % text])
        for r in sorted(removed, key=lambda x: x.seg.get("@index", 0), reverse=True):
            lines = ["УДАЛИТЬ %s" % path_text(list(path) + [r.seg])]
            if bylo:
                text = dsl_value(r.orig.get("Значение", ""), warnings, "БЫЛО")
                if text is not None:
                    lines.append("  БЫЛО: %s" % text)
            if renumber:
                lines.append("  ПЕРЕНУМЕРОВАТЬ: да")
            emit(lines)

    return blocks, warnings


def summary(blocks):
    """Короткая сводка по сгенерированным операциям (для журнала GUI)."""
    from collections import Counter
    c = Counter()
    for b in blocks:
        first = b.splitlines()[0] if b.splitlines() else ""
        c[first.split(" ", 1)[0]] += 1
    return ", ".join("%s %d" % (k, v) for k, v in c.items()) or "нет операций"
