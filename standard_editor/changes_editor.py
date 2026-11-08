# -*- coding: utf-8 -*-
"""Текстовый редактор изменений стандарта.

Вы пишете изменения обычным текстом в любом редакторе (Блокнот, VS Code,
Notepad++), а этот инструмент проверяет их по базовому JSON и собирает
канонический файл «СТО-изменения/1.0» для apply_changes.py.

ТЕКСТОВЫЙ ФОРМАТ (*.изм.txt)
=====================================================================
Шапка (до первой операции), затем блоки операций. `#` — комментарий,
пустые строки игнорируются. Отступ в начале строки = поле операции.

    ИЗМЕНЕНИЕ: ИЗМ-2
    ВЕРСИЯ: 1
    ДАТА: 2022-06-01
    ПОРЯДОК: 20
    СТАТУС: действует
    НАЗВАНИЕ: Добавление комплекта без ИЭУ
    ОСНОВАНИЕ: Приказ № 2
    БАЗА: СТО 56947007-33.040.20.279-2019
    ХЭШ: 8a96e50f...
    ЗАМЕНЯЕТ: ИЗМ-1

    ЗАМЕНИТЬ шкаф=ШЭТ 431.02-0 / Описание шкафа / Наименование шкафа
      БЫЛО: старое наименование
      СТАЛО: новое наименование
      ПРИЧИНА: уточнение формулировки

    ИЗМЕНИТЬ ПОЛЯ шкаф=... / Таблицы / Таблица 5.3.2 / Строки / №=1
      БЫЛО.Примечание: Фазные токи В БСК
      > Примечание: Фазные токи В БСК (В1)

    ДОБАВИТЬ шкаф=... / Таблицы / Таблица 5.3.2 / Строки
      > №: 10
      > Аналоговая цепь: Ia, Ib, Ic
      > Примечание: дополнительный ввод
      ПРИЧИНА: добавили ввод

    ОТМЕНИТЬ шкаф=... / Таблицы / Таблица 5.3.12 / Строки / №=3
      БЫЛО.Сигнал: Режим управления
      ПРИЧИНА: сигнал выведен из действия
      ДЕЙСТВУЕТ ДО: 2021-03-15

    УДАЛИТЬ шкаф=... / Таблицы / Таблица 5.3.8 / Строки / №=2
      БЫЛО.Краткое наименование ФК: Группа уставок
      ПЕРЕНУМЕРОВАТЬ: да

    ПЕРЕИМЕНОВАТЬ шкаф=... / Таблицы / Таблица 5.3.2
      КЛЮЧ: Таблица 5.3.2а

    # Дублирование любого узла: копия вставляется сразу после источника,
    # «Замены» сразу переименовывают шифр/таблицы внутри копии.
    ДУБЛИРОВАТЬ шкаф=ШЭТ 431.02-0
      КЛЮЧ: Шкаф защит и автоматики типа ШЭТ 431.07-0 для архитектуры I типа
      ЗАМЕНА: 431.02-0 => 431.07-0
      ЗАМЕНА: Таблица 5.3. => Таблица 5.8.
      > Раздел стандарта: 5.8
      ПЕРЕНУМЕРОВАТЬ: да

    # Дублирование строки таблицы (позиция — сразу после источника):
    ДУБЛИРОВАТЬ шкаф=... / Таблицы / Таблица 5.3.8 / Строки / №=2
      ЗАМЕНА.ЗНАЧЕНИЯ: Группа уставок => Группа уставок (резерв)
      ПЕРЕНУМЕРОВАТЬ: да

ГЛАГОЛЫ
    ЗАМЕНИТЬ / OVERRIDE       заменить значение (СТАЛО) или поля (> ключ: ...)
    ИЗМЕНИТЬ ПОЛЯ / PATCH     то же, но обязательно с полями
    ДОБАВИТЬ / NEW            новый объект (КЛЮЧ) или строка таблицы
    ДУБЛИРОВАТЬ / COPY        копия любого узла (КЛЮЧ / КУДА / ПОЗИЦИЯ,
                              ЗАМЕНА, > поля, ПРАВКА, ПЕРЕНУМЕРОВАТЬ)
    ОТМЕНИТЬ / DEPRECATED     пометить, не удаляя
    УДАЛИТЬ / DELETE          физически удалить (ПЕРЕНУМЕРОВАТЬ: да)
    ПЕРЕИМЕНОВАТЬ / RENAME    новое имя в КЛЮЧ

ПУТЬ
    Сегменты через `/`. Обычный текст = точный ключ JSON.
      шкаф=ШЭТ 431.02-0        найти шкаф по «Шифр шкафа»
      №=17                      найти строку таблицы по номеру
      @Поле=Значение            произвольный селектор по полю
      @{json}                   селектор по нескольким полям
      #3                        индекс массива (не рекомендуется)
      "ключ / с косой"          кавычки, если в ключе есть `/`
    Путь без ведущего `/` начинается от «Содержимое стандарта»; с `/` —
    от корня JSON (например `/Область применения стандарта`).

ПОЛЯ ОПЕРАЦИИ (строки с отступом)
    БЫЛО: текст                 ожидаемое старое значение
    БЫЛО.Поле: текст            то же для одного поля объекта
    СТАЛО: текст                новое значение для ЗАМЕНИТЬ
    > ключ: значение            поле добавляемого/изменяемого объекта
    КЛЮЧ:, ПЕРЕД:, ПОСЛЕ:, КУДА:, ПОЗИЦИЯ:, ПЕРЕНУМЕРОВАТЬ:, РАЗРЕШИТЬ:,
    ДЕЙСТВУЕТ ДО:, СТАТУС:, ПРИЧИНА:, ОСНОВАНИЕ:, ЗНАЧЕНИЕ:
    ЗАМЕНА: старое => новое     замена подстрок в ключах и значениях копии
    ЗАМЕНА.КЛЮЧИ: ...           только в именах полей
    ЗАМЕНА.ЗНАЧЕНИЯ: ...        только в строковых значениях
    УДАЛИТЬ ПОЛЕ: имя           убрать поле верхнего уровня копии
    ПРАВКА: {json}              правка внутри копии: {"Путь": [...],
                                "Значение" | "Поля" | "Удалить" | "Переименовать"}
    Значения, начинающиеся с `[` или `{`, читаются как JSON
    (например `> Функция: []`), остальные остаются строками.
    `@json:<литерал>` принудительно задаёт тип: `@json:26` (число),
    `@json:true`, `@json:null`, `@json:"текст"`. Это использует
    динамическая таблица узла в GUI, чтобы не терять типы ячеек.

КОМАНДЫ
    python changes_editor.py init --id ИЗМ-4 --base base.json --out changes/ИЗМ-4.изм.txt
    python changes_editor.py edit changes/ИЗМ-4.изм.txt --base base.json --preview
    python changes_editor.py check changes/*.изм.txt --base base.json
    python changes_editor.py build changes/ИЗМ-4.изм.txt --base base.json
    python changes_editor.py from-json changes/ИЗМ-2.json
    python changes_editor.py get "шкаф=ШЭТ 431.02-0 / Описание шкафа / Наименование шкафа" --base base.json
    python changes_editor.py preview --base base.json --changes changes --strict
    python changes_editor.py preview --base base.json --changes changes --out edition.json

`edit` открывает файл в редакторе: --editor, либо STO_EDITOR / VISUAL /
EDITOR, либо VS Code (`code --wait`) / Блокнот. Рекомендуется редактор с
ожиданием закрытия (`code --wait`), иначе проверка запустится до сохранения.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apply_changes as ac  # noqa: E402

FORMAT = ac.FORMAT
TEXT_EXT = ".изм.txt"

HEADER = OrderedDict([
    ("ИЗМЕНЕНИЕ", "Идентификатор"),
    ("ВЕРСИЯ", "Версия"),
    ("ДАТА", "Дата"),
    ("ПОРЯДОК", "Порядок"),
    ("СТАТУС", "Статус"),
    ("НАЗВАНИЕ", "Наименование"),
    ("ОСНОВАНИЕ", "Основание"),
    ("БАЗА", "@base"),
    ("ХЭШ", "@hash"),
    ("ЗАМЕНЯЕТ", "@supersedes"),
])

VERBS = {
    "ЗАМЕНИТЬ": "OVERRIDE", "OVERRIDE": "OVERRIDE",
    "ИЗМЕНИТЬ": "OVERRIDE", "PATCH": "OVERRIDE", "ИЗМЕНИТЬ ПОЛЯ": "OVERRIDE",
    "ДОБАВИТЬ": "NEW", "NEW": "NEW",
    "ДУБЛИРОВАТЬ": "COPY", "КОПИРОВАТЬ": "COPY", "COPY": "COPY",
    "DUPLICATE": "COPY",
    "ОТМЕНИТЬ": "DEPRECATED", "DEPRECATED": "DEPRECATED",
    "УДАЛИТЬ": "DELETE", "DELETE": "DELETE",
    "ПЕРЕИМЕНОВАТЬ": "RENAME", "RENAME": "RENAME",
}
# Поля, которые можно повторять (а не перезаписывать последним значением).
REPEATED = {"ЗАМЕНА", "ЗАМЕНА.КЛЮЧИ", "ЗАМЕНА.ЗНАЧЕНИЯ",
            "УДАЛИТЬ ПОЛЕ", "ПРАВКА"}
FLAG_TRUE = {"да", "yes", "true", "1", "+", "истина"}

# Явный JSON-литерал. Нужен, чтобы в текстовом DSL сохранить тип скаляра
# (число, логическое значение, null) или строку, похожую на JSON/литерал.
# Пишется только в значениях операций; шапка остаётся человекочитаемой.
JSON_PREFIX = "@json:"

TEMPLATE = """# Изменение к стандарту. Строки с # — комментарии.
# Справка по формату: python changes_editor.py --help
ИЗМЕНЕНИЕ: {id}
ВЕРСИЯ: 1
ДАТА: {date}
ПОРЯДОК: {order}
СТАТУС: действует
НАЗВАНИЕ: Краткое описание изменения
ОСНОВАНИЕ: Приказ / распоряжение
БАЗА: {base_code}
ХЭШ: {base_sha}
ЗАМЕНЯЕТ:

# --- Примеры (раскомментируйте и заполните) -------------------------------
# Подсмотреть текущее значение:
#   python changes_editor.py get "шкаф=ШЭТ 431.02-0 / Описание шкафа / Наименование шкафа" --base "{base}"
#
# ЗАМЕНИТЬ шкаф=ШЭТ 431.02-0 / Описание шкафа / Наименование шкафа
#   БЫЛО: <вставьте сюда результат команды get>
#   СТАЛО: новое наименование
#   ПРИЧИНА: уточнение формулировки
#
# ИЗМЕНИТЬ ПОЛЯ шкаф=ШЭТ 431.02-0 / Таблицы / Таблица 5.3.2 / Строки / №=1
#   БЫЛО.Примечание: Фазные токи В БСК
#   > Примечание: Фазные токи В БСК (В1)
#
# ДОБАВИТЬ шкаф=ШЭТ 431.02-0 / Таблицы / Таблица 5.3.2 / Строки
#   > №: 10
#   > Аналоговая цепь: Ia, Ib, Ic
#   > Примечание: новый ввод
#   ПРИЧИНА: добавлен ввод
#
# ДУБЛИРОВАТЬ шкаф=ШЭТ 431.02-0
#   КЛЮЧ: Шкаф защит и автоматики типа ШЭТ 431.04-0 для архитектуры I типа
#   ЗАМЕНА: 431.02-0 => 431.04-0
#   ЗАМЕНА: Таблица 5.3. => Таблица 5.4.
#   ПЕРЕНУМЕРОВАТЬ: да
#   ПРИЧИНА: новый шкаф на базе типового
#
# ДУБЛИРОВАТЬ шкаф=ШЭТ 431.02-0 / Таблицы / Таблица 5.3.2 / Строки / №=2
#   ЗАМЕНА.ЗНАЧЕНИЯ: Фазные токи => Фазные токи (резерв)
#   ПРИЧИНА: резервная строка
#
# ОТМЕНИТЬ шкаф=ШЭТ 431.02-0 / Таблицы / Таблица 5.3.12 / Строки / №=3
#   БЫЛО.Сигнал: Режим управления
#   ПРИЧИНА: сигнал выведен из действия
#   ДЕЙСТВУЕТ ДО: {date}
"""


class TextError(Exception):
    pass


# ---------------------------------------------------------------------------
# Разбор текстового формата
# ---------------------------------------------------------------------------
def split_kv(text, lineno):
    if ":" not in text:
        raise TextError("строка %d: ожидается «КЛЮЧ: значение»: %r" % (lineno, text))
    k, v = text.split(":", 1)
    return k.strip(), v.strip()


def parse_value(raw):
    """Строки остаются строками; JSON читается только для [] / {} / литералов.

    Префикс `@json:` принудительно читает остаток строки как JSON — так
    динамическая таблица узла может записать число/bool/null или строку,
    похожую на JSON, не превратив её в другой тип.
    """
    v = raw.strip()
    if v.startswith(JSON_PREFIX):
        try:
            return json.loads(v[len(JSON_PREFIX):])
        except ValueError as exc:
            raise TextError("неверный JSON после %s: %s" % (JSON_PREFIX, exc))
    if v in ("null", "true", "false") or v[:1] in ("[", "{"):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def render_payload_value(v):
    """Значение операции в DSL с сохранением типа (для compile/decompile)."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (bool, int, float)) or v is None:
        return JSON_PREFIX + json.dumps(v, ensure_ascii=False)
    if isinstance(v, str):
        suspicious = (v.startswith(JSON_PREFIX) or v in ("null", "true", "false"))
        if not suspicious and v[:1] in ("[", "{"):
            try:
                json.loads(v)
                suspicious = True
            except ValueError:
                pass
        if suspicious:
            return JSON_PREFIX + json.dumps(v, ensure_ascii=False)
    return render_value(v)


def split_segments(text):
    """Разбить путь по `/`, не трогая кавычки и фигурные скобки."""
    out, buf, quote, depth, escaped = [], [], False, 0, False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\" and quote:
            buf.append(ch)
            escaped = True
        elif ch == '"':
            quote = not quote
            buf.append(ch)
        elif ch == "{" and not quote:
            depth += 1
            buf.append(ch)
        elif ch == "}" and not quote:
            depth -= 1
            buf.append(ch)
        elif ch == "/" and not quote and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf).strip())
    if quote or depth:
        raise TextError("незакрытые кавычки/скобки в пути: %s" % text)
    return [s for s in out if s]


def parse_path(text):
    """Текстовый путь -> массив сегментов канонического формата."""
    text = text.strip()
    from_root = text.startswith("/")
    if from_root:
        text = text[1:]
    out = [] if from_root else ["Содержимое стандарта"]
    for seg in split_segments(text):
        if seg.startswith('"') and seg.endswith('"') and len(seg) > 1:
            out.append(seg[1:-1].replace('\\"', '"'))
            continue
        low = seg.lower()
        if low.startswith("шкаф="):
            out.append({"@where": {"Шифр шкафа": seg.split("=", 1)[1].strip()}})
        elif seg.startswith("№="):
            out.append({"№": seg.split("=", 1)[1].strip()})
        elif seg.startswith("@"):
            body = seg[1:].strip()
            if body.startswith("{"):
                try:
                    out.append({"@where": json.loads(body)})
                except ValueError as exc:
                    raise TextError("неверный JSON в селекторе %s: %s" % (seg, exc))
            elif "=" in body:
                k, v = body.split("=", 1)
                out.append({"@where": {k.strip(): v.strip()}})
            else:
                raise TextError("селектор должен быть @Поле=Значение: %s" % seg)
        elif seg.startswith("#") and seg[1:].isdigit():
            out.append({"@index": int(seg[1:])})
        else:
            out.append(seg)
    return out


def flag(value):
    return str(value).strip().lower() in FLAG_TRUE


def parse_text(text):
    """Текст -> (шапка, операции, список предупреждений)."""
    meta, ops, warnings = OrderedDict(), [], []
    cur = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        indented = line[:1].isspace()
        if not indented:
            if ":" in body and body.split(":", 1)[0].strip().upper() in HEADER:
                k, v = split_kv(body, lineno)
                meta[HEADER[k.strip().upper()]] = v
                continue
            parts = body.split(None, 1)
            verb = parts[0].upper()
            rest = parts[1].strip() if len(parts) > 1 else ""
            # Двухсловный глагол «ИЗМЕНИТЬ ПОЛЯ».
            words = rest.split()
            if words and words[0].upper() == "ПОЛЯ" and \
                    (verb + " ПОЛЯ") in VERBS:
                verb = verb + " ПОЛЯ"
                rest = rest.split(" ", 1)[1].strip() if " " in rest else ""
            if verb not in VERBS:
                raise TextError("строка %d: неизвестная команда %r" % (lineno, parts[0]))
            if not rest:
                raise TextError("строка %d: после %s нужен путь" % (lineno, parts[0]))
            cur = {"verb": VERBS[verb], "path": rest, "fields": OrderedDict(),
                   "bylo": OrderedDict(), "payload": OrderedDict(),
                   "repeats": [], "line": lineno}
            ops.append(cur)
            continue
        if cur is None:
            raise TextError("строка %d: поле без операции" % lineno)
        if body.startswith(">"):
            k, v = split_kv(body[1:].strip(), lineno)
            cur["payload"][k] = parse_value(v)
            continue
        k, v = split_kv(body, lineno)
        upper = k.upper()
        if upper in REPEATED:
            cur["repeats"].append((upper, v))
        elif upper.startswith("БЫЛО."):
            cur["bylo"][k[5:].strip()] = v
        else:
            cur["fields"][upper] = v
    if "Идентификатор" not in meta:
        raise TextError("нет обязательного поля ИЗМЕНЕНИЕ: в шапке")
    return meta, ops, warnings


OP_ORDER = ("Операция", "Путь", "Было", "Ключ", "Куда", "Значение", "Поля",
            "Замены", "Удалить", "Правки", "Перед", "После", "Позиция",
            "Статус", "Причина", "Действует до", "Перенумеровать", "Разрешить")


def compile_op(o, lineno):
    f, p, bylo = o["fields"], o["payload"], o["bylo"]
    code = o["verb"]
    vals = OrderedDict()
    vals["Операция"] = code
    try:
        vals["Путь"] = parse_path(o["path"])
    except TextError as exc:
        raise TextError("строка %d: %s" % (lineno, exc))
    if bylo:
        vals["Было"] = OrderedDict((k, parse_value(v)) for k, v in bylo.items())
    elif "БЫЛО" in f:
        vals["Было"] = parse_value(f["БЫЛО"])

    if code == "NEW":
        if "ЗНАЧЕНИЕ" in f and not p:
            vals["Значение"] = parse_value(f["ЗНАЧЕНИЕ"])
        elif p:
            vals["Значение"] = OrderedDict(p)
        else:
            raise TextError("строка %d: ДОБАВИТЬ: нужны строки «> ключ: значение» "
                            "или ЗНАЧЕНИЕ" % lineno)
        for src, dst in (("КЛЮЧ", "Ключ"), ("ПЕРЕД", "Перед"),
                         ("ПОЗИЦИЯ", "Позиция")):
            if src in f:
                vals[dst] = (int(f[src]) if src == "ПОЗИЦИЯ" else f[src])
        if flag(f.get("ПЕРЕНУМЕРОВАТЬ", "")):
            vals["Перенумеровать"] = True
    elif code == "OVERRIDE":
        if p:
            vals["Поля"] = OrderedDict(p)
        elif "СТАЛО" in f:
            vals["Значение"] = parse_value(f["СТАЛО"])
        elif "ЗНАЧЕНИЕ" in f:
            vals["Значение"] = parse_value(f["ЗНАЧЕНИЕ"])
        else:
            raise TextError("строка %d: ЗАМЕНИТЬ: нужно СТАЛО или «> ключ: значение»"
                            % lineno)
    elif code == "DEPRECATED":
        reason = f.get("ПРИЧИНА") or f.get("ОСНОВАНИЕ")
        if reason:
            vals["Причина"] = reason
        if "ДЕЙСТВУЕТ ДО" in f:
            vals["Действует до"] = f["ДЕЙСТВУЕТ ДО"]
        if "СТАТУС" in f:
            vals["Статус"] = f["СТАТУС"]
    elif code == "DELETE":
        if flag(f.get("ПЕРЕНУМЕРОВАТЬ", "")):
            vals["Перенумеровать"] = True
    elif code == "RENAME":
        new_key = f.get("КЛЮЧ") or f.get("НОВЫЙ КЛЮЧ")
        if not new_key:
            raise TextError("строка %d: ПЕРЕИМЕНОВАТЬ: нужно КЛЮЧ" % lineno)
        vals["Ключ"] = new_key
    elif code == "COPY":
        if p:
            vals["Поля"] = OrderedDict(p)
        for src, dst in (("КЛЮЧ", "Ключ"), ("ПЕРЕД", "Перед"),
                         ("ПОСЛЕ", "После")):
            if src in f:
                vals[dst] = f[src]
        if "КУДА" in f:
            vals["Куда"] = parse_path(f["КУДА"])
        if "ПОЗИЦИЯ" in f:
            try:
                vals["Позиция"] = int(f["ПОЗИЦИЯ"])
            except ValueError:
                raise TextError("строка %d: ПОЗИЦИЯ должна быть числом" % lineno)
        replacements, deletions, edits = [], [], []
        for key, value in o["repeats"]:
            if key == "УДАЛИТЬ ПОЛЕ":
                deletions.append(value)
                continue
            if key == "ПРАВКА":
                try:
                    item = json.loads(value)
                except ValueError as exc:
                    raise TextError("строка %d: ПРАВКА: неверный JSON: %s" %
                                    (lineno, exc))
                if not isinstance(item, dict):
                    raise TextError("строка %d: ПРАВКА: ожидается JSON-объект" %
                                    lineno)
                edits.append(item)
                continue
            scope = {"ЗАМЕНА": "все", "ЗАМЕНА.КЛЮЧИ": "ключи",
                     "ЗАМЕНА.ЗНАЧЕНИЯ": "значения"}[key]
            if value.strip().startswith("{"):
                try:
                    item = json.loads(value)
                except ValueError as exc:
                    raise TextError("строка %d: %s: неверный JSON: %s" %
                                    (lineno, key, exc))
                if not isinstance(item, dict):
                    raise TextError("строка %d: %s: ожидается JSON-объект" %
                                    (lineno, key))
                old = str(item.get("Старое", item.get("Было", "")))
                new = str(item.get("Новое", item.get("Стало", "")))
                scope = str(item.get("Где", scope)).strip().lower()
            else:
                old, sep, new = value.partition("=>")
                if not sep:
                    raise TextError("строка %d: %s: ожидается «старое => новое»" %
                                    (lineno, key))
                old, new = old.strip(), new.strip()
            if not old:
                raise TextError("строка %d: %s: пустое «старое»" % (lineno, key))
            item = OrderedDict([("Старое", old), ("Новое", new)])
            if scope != "все":
                item["Где"] = scope
            replacements.append(item)
        if replacements:
            vals["Замены"] = replacements
        if deletions:
            vals["Удалить"] = deletions
        if edits:
            vals["Правки"] = edits
        if flag(f.get("ПЕРЕНУМЕРОВАТЬ", "")):
            vals["Перенумеровать"] = True
    if "ПРИЧИНА" in f and code not in ("DEPRECATED",):
        vals["Причина"] = f["ПРИЧИНА"]
    if flag(f.get("РАЗРЕШИТЬ", "")):
        vals["Разрешить"] = True
    return OrderedDict((k, vals[k]) for k in OP_ORDER if k in vals)


CS_ORDER = ("Формат", "Идентификатор", "Версия", "Наименование", "Дата",
            "Порядок", "Статус", "Основание", "Применимо к", "Заменяет",
            "Изменения")


def compile_text(text):
    """Текст -> канонический JSON изменения."""
    meta, ops, warnings = parse_text(text)
    vals = OrderedDict()
    vals["Формат"] = FORMAT
    for key in ("Идентификатор", "Наименование", "Дата", "Статус", "Основание"):
        if key in meta:
            vals[key] = meta[key]
    for key in ("Версия", "Порядок"):
        if key in meta:
            try:
                vals[key] = int(meta[key])
            except ValueError:
                raise TextError("поле %s должно быть числом: %r" % (key, meta[key]))
    applies = OrderedDict()
    if meta.get("@base"):
        applies["Шифр стандарта"] = meta["@base"]
    if meta.get("@hash"):
        applies["SHA-256 базы"] = meta["@hash"]
    if applies:
        vals["Применимо к"] = applies
    vals["Заменяет"] = [x.strip() for x in
                        meta.get("@supersedes", "").split(",") if x.strip()]
    vals["Изменения"] = [compile_op(o, o["line"]) for o in ops]
    return OrderedDict((k, vals[k]) for k in CS_ORDER if k in vals), warnings


# ---------------------------------------------------------------------------
# Обратная сборка JSON -> текст
# ---------------------------------------------------------------------------
REVERSE_VERB = {
    "OVERRIDE": "ЗАМЕНИТЬ", "NEW": "ДОБАВИТЬ", "COPY": "ДУБЛИРОВАТЬ",
    "DEPRECATED": "ОТМЕНИТЬ", "DELETE": "УДАЛИТЬ", "RENAME": "ПЕРЕИМЕНОВАТЬ",
}


def quote_seg(seg):
    if any(c in seg for c in "/=") or seg[:1] in ("@", "#", '"'):
        return '"%s"' % seg.replace('"', '\\"')
    return seg


def render_path(path):
    segs = list(path)
    prefix = ""
    if segs and segs[0] == "Содержимое стандарта":
        segs = segs[1:]
    else:
        prefix = "/"
    parts = []
    for seg in segs:
        if isinstance(seg, str):
            parts.append(quote_seg(seg))
        elif isinstance(seg, dict):
            if "@index" in seg:
                parts.append("#%s" % seg["@index"])
                continue
            w = seg.get("@where", seg)
            if set(w) == {"Шифр шкафа"}:
                parts.append("шкаф=%s" % w["Шифр шкафа"])
            elif set(w) == {"№"}:
                parts.append("№=%s" % w["№"])
            elif len(w) == 1:
                k, v = next(iter(w.items()))
                parts.append("@%s=%s" % (k, v))
            else:
                parts.append("@" + json.dumps(w, ensure_ascii=False))
        else:
            parts.append(str(seg))
    return prefix + " / ".join(parts)


def render_value(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else str(v)


def render_replacement(rep):
    """Одна «Замена» в строку DSL: «старое => новое» либо JSON-объект."""
    if isinstance(rep, str):
        return rep
    old = "" if rep.get("Старое") is None else str(rep.get("Старое"))
    new = "" if rep.get("Новое") is None else str(rep.get("Новое"))
    scope = str(rep.get("Где", "все")).strip().lower()
    body = OrderedDict([("Старое", old), ("Новое", new)])
    if scope and scope != "все":
        body["Где"] = scope
    unsafe = (not old or "=>" in old or "=>" in new or "\n" in old
              or "\n" in new or old.startswith("{")
              or old != old.strip() or new != new.strip())
    return json.dumps(body, ensure_ascii=False) if unsafe else "%s => %s" % (old, new)


def decompile(cs):
    """Канонический JSON изменения -> текст *.изм.txt."""
    L = ["# Сгенерировано из %s (changes_editor.py from-json)" %
         cs.get("Идентификатор", ""),
         "ИЗМЕНЕНИЕ: %s" % cs.get("Идентификатор", ""),
         "ВЕРСИЯ: %s" % cs.get("Версия", 1)]
    for src, dst in (("Дата", "ДАТА"), ("Порядок", "ПОРЯДОК"),
                     ("Статус", "СТАТУС"), ("Наименование", "НАЗВАНИЕ"),
                     ("Основание", "ОСНОВАНИЕ")):
        if src in cs:
            L.append("%s: %s" % (dst, render_value(cs[src])))
    applies = cs.get("Применимо к") or {}
    if "Шифр стандарта" in applies:
        L.append("БАЗА: %s" % applies["Шифр стандарта"])
    if "SHA-256 базы" in applies:
        L.append("ХЭШ: %s" % applies["SHA-256 базы"])
    if "Заменяет" in cs:
        L.append("ЗАМЕНЯЕТ: %s" % ", ".join(cs.get("Заменяет") or []))
    L.append("")
    for op in cs.get("Изменения", []):
        code = op.get("Операция", "OVERRIDE")
        verb = REVERSE_VERB.get(code, code)
        if code == "OVERRIDE" and "Поля" in op:
            verb = "ИЗМЕНИТЬ ПОЛЯ"
        L.append("%s %s" % (verb, render_path(op.get("Путь", []))))
        bylo = op.get("Было")
        if isinstance(bylo, dict):
            for k, v in bylo.items():
                L.append("  БЫЛО.%s: %s" % (k, render_payload_value(v)))
        elif bylo is not None:
            L.append("  БЫЛО: %s" % render_payload_value(bylo))
        value = op.get("Значение")
        if code == "OVERRIDE" and "Значение" in op:
            L.append("  СТАЛО: %s" % render_payload_value(value))
        if code == "COPY" and "Куда" in op:
            L.append("  КУДА: %s" % render_path(op["Куда"]))
        for src, dst in (("Ключ", "КЛЮЧ"), ("Перед", "ПЕРЕД"),
                         ("После", "ПОСЛЕ"), ("Позиция", "ПОЗИЦИЯ")):
            if src in op:
                L.append("  %s: %s" % (dst, render_value(op[src])))
        payload = op.get("Поля")
        if not isinstance(payload, dict) and code == "NEW" and \
                isinstance(value, dict):
            payload = value
        if isinstance(payload, dict):
            for k, v in payload.items():
                L.append("  > %s: %s" % (k, render_payload_value(v)))
        elif code == "NEW" and "Значение" in op:
            L.append("  ЗНАЧЕНИЕ: %s" % render_payload_value(value))
        if code == "COPY":
            for rep in op.get("Замены") or []:
                tag = "ЗАМЕНА"
                if isinstance(rep, dict):
                    scope = str(rep.get("Где", "все")).strip().lower()
                    if scope == "ключи":
                        tag = "ЗАМЕНА.КЛЮЧИ"
                    elif scope == "значения":
                        tag = "ЗАМЕНА.ЗНАЧЕНИЯ"
                L.append("  %s: %s" % (tag, render_replacement(rep)))
            for key in op.get("Удалить") or []:
                L.append("  УДАЛИТЬ ПОЛЕ: %s" % render_value(key))
            for edit in op.get("Правки") or []:
                L.append("  ПРАВКА: %s" % json.dumps(edit, ensure_ascii=False))
        for src, dst in (("Причина", "ПРИЧИНА"), ("Статус", "СТАТУС"),
                         ("Действует до", "ДЕЙСТВУЕТ ДО")):
            if src in op:
                L.append("  %s: %s" % (dst, render_value(op[src])))
        if op.get("Перенумеровать"):
            L.append("  ПЕРЕНУМЕРОВАТЬ: да")
        if op.get("Разрешить"):
            L.append("  РАЗРЕШИТЬ: да")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Проверка путей по базовому стандарту
# ---------------------------------------------------------------------------
def check_paths(cs, base, work=None):
    """Проверить пути на копии базы, наращивая структуру операциями.

    «Было» здесь не проверяется — оно относится к состоянию *после*
    предыдущих изменений и проверяется самой сборкой. Зато пути, созданные
    операциями NEW/RENAME, становятся видимы для последующих операций.
    `work` — общая копия базы для нескольких файлов изменений по порядку.
    """
    errors = []
    if base is None:
        return errors
    data = work if work is not None else copy.deepcopy(base)
    for i, op in enumerate(cs.get("Изменения", []), 1):
        probe = OrderedDict((k, v) for k, v in op.items() if k != "Было")
        try:
            ac.apply_op(data, cs, i - 1, probe, ac.Context(), False)
        except (ac.ChangeError, KeyError, ValueError, TypeError) as exc:
            errors.append("оп. %d: %s" % (i, exc))
    return errors


def load_base(path):
    return ac.load_json(path)


def resolve_editor(explicit):
    if explicit:
        return shlex.split(explicit)
    for var in ("STO_EDITOR", "VISUAL", "EDITOR"):
        if os.environ.get(var):
            return shlex.split(os.environ[var])
    if platform.system() == "Windows":
        if shutil.which("code"):
            return ["code", "--wait", "--new-window"]
        return ["notepad"]
    for cmd in ("nano", "vim", "vi"):
        if shutil.which(cmd):
            return [cmd]
    return ["vi"]


def summarize(cs, path, errors=None):
    n = len(cs.get("Изменения", []))
    counts = OrderedDict()
    for op in cs.get("Изменения", []):
        counts[op["Операция"]] = counts.get(op["Операция"], 0) + 1
    print("%s: %s v%s, операций %d (%s)" %
          (os.path.basename(path), cs["Идентификатор"], cs.get("Версия", 1), n,
           ", ".join("%s=%d" % kv for kv in counts.items()) or "—"))
    for e in errors or []:
        print("  ! " + e)
    return not errors


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------
def expand(patterns, ext=None):
    out = []
    for pattern in patterns:
        if os.path.isdir(pattern):
            hits = sorted(glob.glob(os.path.join(pattern, "*" + (ext or ""))))
        else:
            hits = sorted(glob.glob(pattern)) or [pattern]
        for h in hits:
            if os.path.abspath(h) not in out and os.path.isfile(h):
                out.append(os.path.abspath(h))
    return out


def cmd_init(args):
    base = load_base(args.base) if args.base else {}
    path = args.out or os.path.join("changes", args.id + TEXT_EXT)
    if os.path.exists(path) and not args.force:
        raise TextError("файл уже существует: %s (--force для перезаписи)" % path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    from datetime import date
    text = TEMPLATE.format(
        id=args.id, date=date.today().isoformat(), order=args.order,
        base=args.base or "", base_code=base.get("Шифр стандарта", ""),
        base_sha=ac.sha256_file(args.base) if args.base else "")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("Шаблон: %s" % os.path.abspath(path))
    print("Открыть: python changes_editor.py edit \"%s\" --base \"%s\" --preview" %
          (path, args.base or ""))


def cmd_edit(args):
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        raise TextError("нет файла: %s" % path)
    editor = resolve_editor(args.editor)
    print("Редактор: %s" % " ".join(editor))
    try:
        subprocess.run(editor + [path], check=True)
    except FileNotFoundError:
        raise TextError("редактор не найден: %s. Укажите --editor" % editor[0])
    except subprocess.CalledProcessError as exc:
        raise TextError("редактор завершился с кодом %d" % exc.returncode)
    files = [path]
    ok = cmd_check(argparse.Namespace(files=files, base=args.base))
    if not ok:
        return
    if args.build:
        cmd_build(argparse.Namespace(files=files, out=None, out_dir=None,
                                     base=args.base))
    if args.preview:
        if not args.base:
            raise TextError("для --preview нужно указать --base")
        cmd_preview(argparse.Namespace(base=args.base,
                                       changes=[os.path.dirname(path) or "."],
                                       strict=False, report=None,
                                       out=None, ignore_hash=False))


def sort_key(item):
    cs = item[1]
    return (int(cs.get("Порядок", 0)), str(cs.get("Дата", "")),
            str(cs.get("Идентификатор", "")))


def read_text_files(files):
    """Прочитать и скомпилировать текстовые изменения, отсортировать как сборка."""
    compiled = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        cs, warnings = compile_text(text)
        compiled.append((path, cs, warnings))
    compiled.sort(key=sort_key)
    return compiled


def cmd_check(args):
    base = load_base(args.base) if args.base else None
    ok = True
    files = expand(args.files, TEXT_EXT)
    if not files:
        raise TextError("не найдено ни одного *.изм.txt")
    work = copy.deepcopy(base) if base is not None else None
    compiled = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            cs, warnings = compile_text(text)
            compiled.append((path, cs, warnings))
        except TextError as exc:
            print("%s: ОШИБКА %s" % (os.path.basename(path), exc))
            ok = False
    compiled.sort(key=sort_key)
    for path, cs, warnings in compiled:
        errors = check_paths(cs, base, work)
        errors += ["ПРЕДУПРЕЖДЕНИЕ: " + w for w in warnings]
        ok &= summarize(cs, path, errors)
    return ok


def cmd_build(args):
    if args.out and len(args.files) != 1 and len(expand(args.files, TEXT_EXT)) != 1:
        raise TextError("--out допустим только для одного файла")
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
    base = load_base(args.base) if args.base else None
    files = expand(args.files, TEXT_EXT)
    if not files:
        raise TextError("не найдено ни одного *.изм.txt")
    work = copy.deepcopy(base) if base is not None else None
    for path, cs, _ in read_text_files(files):
        if base:
            errors = check_paths(cs, base, work)
            if errors:
                raise TextError("%s:\n  %s" % (path, "\n  ".join(errors)))
        if args.out:
            dst = os.path.abspath(args.out)
        elif args.out_dir:
            dst = os.path.join(os.path.abspath(args.out_dir),
                               os.path.basename(path)[:-len(TEXT_EXT)] + ".json")
        else:
            dst = os.path.join(os.path.dirname(path),
                               os.path.basename(path)[:-len(TEXT_EXT)] + ".json")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(cs, f, ensure_ascii=False, indent=2)
        summarize(cs, dst)
        print("  -> %s" % dst)


def cmd_from_json(args):
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
    for path in expand(args.files, ".json"):
        cs = ac.load_json(path)
        text = decompile(cs)
        if args.out_dir:
            dst = os.path.join(os.path.abspath(args.out_dir),
                               os.path.splitext(os.path.basename(path))[0] + TEXT_EXT)
        else:
            dst = os.path.splitext(path)[0] + TEXT_EXT
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
        print("%s -> %s" % (os.path.basename(path), dst))


def cmd_get(args):
    base = load_base(args.base)
    path = parse_path(args.path)
    parent, key, value, canon, _, _ = ac.resolve(base, path)
    print("Путь: %s" % ac.canon_str(canon))
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)


def cmd_preview(args):
    base = load_base(args.base)
    files = expand(args.changes, TEXT_EXT)
    if not files:
        raise TextError("не найдено ни одного *.изм.txt")
    work = copy.deepcopy(base)
    with tempfile.TemporaryDirectory(prefix="sto-changes-") as tmp:
        sources = {}
        used = set()
        for path, cs, _ in read_text_files(files):
            errors = check_paths(cs, base, work)
            if errors:
                raise TextError("%s:\n  %s" % (path, "\n  ".join(errors)))
            stem = os.path.basename(path)[:-len(TEXT_EXT)]
            name = stem + ".json"
            if name in used:
                name = "%02d_%s" % (len(used), name)
            used.add(name)
            tmp_path = os.path.join(tmp, name)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cs, f, ensure_ascii=False, indent=2)
            sources[os.path.abspath(tmp_path)] = path
        try:
            data, ctx, registry, skipped, base_sha, problems, warnings = ac.assemble(
                args.base, [tmp], strict=args.strict,
                ignore_hash=args.ignore_hash)
        except ac.ChangeError as exc:
            msg = str(exc)
            for tmp_path, src in sources.items():
                msg = msg.replace(tmp_path, src)
            raise TextError(msg)
    result_sha = None
    if args.out and not problems:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        result_sha = ac.sha256_file(args.out)
    report = ac.build_report(ctx, registry, skipped, base_sha, problems,
                             warnings, result_sha)
    print(report)
    if result_sha:
        print("Собрано: %s" % os.path.abspath(args.out))
    else:
        print("Редакция не записана (dry-run / ошибки).")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
    if problems:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(
        description="Текстовый редактор изменений стандарта (*.изм.txt -> JSON)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Формат описан в начале этого файла и в шаблоне команды init.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="создать шаблон текстового изменения")
    p.add_argument("--id", required=True)
    p.add_argument("--base")
    p.add_argument("--out")
    p.add_argument("--order", type=int, default=10)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("edit", help="открыть файл в текстовом редакторе и проверить")
    p.add_argument("file")
    p.add_argument("--editor")
    p.add_argument("--base")
    p.add_argument("--build", action="store_true")
    p.add_argument("--preview", action="store_true")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("check", help="проверить синтаксис и пути")
    p.add_argument("files", nargs="+")
    p.add_argument("--base")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("build", help="скомпилировать в JSON изменения")
    p.add_argument("files", nargs="+")
    p.add_argument("--out")
    p.add_argument("--out-dir")
    p.add_argument("--base")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("from-json", help="разобрать JSON обратно в текст")
    p.add_argument("files", nargs="+")
    p.add_argument("--out-dir")
    p.set_defaults(func=cmd_from_json)

    p = sub.add_parser("get", help="показать текущее значение по пути")
    p.add_argument("path")
    p.add_argument("--base", required=True)
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("preview", help="проверить/собрать редакцию из текстовых изменений")
    p.add_argument("--base", required=True)
    p.add_argument("--changes", nargs="+", required=True)
    p.add_argument("--out", help="записать собранный JSON редакции (иначе dry-run)")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--ignore-hash", action="store_true",
                   help="не проверять SHA-256 базы из шапки")
    p.add_argument("--report")
    p.set_defaults(func=cmd_preview)

    args = ap.parse_args()
    try:
        rc = args.func(args)
        if rc is False:
            sys.exit(1)
    except (TextError, ac.ChangeError, OSError, ValueError, KeyError) as exc:
        print("ОШИБКА: %s" % exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
