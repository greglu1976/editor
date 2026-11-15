# -*- coding: utf-8 -*-
"""Сборка новой редакции стандарта из базового JSON и набора изменений.

ФОРМАТ ФАЙЛА ИЗМЕНЕНИЯ («СТО-изменения/1.0»)
=====================================================================
Метки NEW / DEPRECATED / OVERRIDE хранятся НЕ в ключах данных, а как
значение поля «Операция» в отдельном списке операций. Итоговый стандарт
остаётся чистым (совместимым с example.json и json_to_docx.py), а вся
история изменений живёт в файлах-патчах и в блоке «Редакция».

    {
      "Формат": "СТО-изменения/1.0",
      "Идентификатор": "ИЗМ-1",          // стабильный номер изменения
      "Версия": 1,                       // версия САМОГО файла изменения
      "Дата": "2021-03-15",
      "Порядок": 10,                     // порядок применения (число)
      "Статус": "действует",             // прочие статусы пропускаются
      "Наименование": "...",
      "Основание": "Приказ № ...",
      "Применимо к": {
        "Шифр стандарта": "СТО 56947007-33.040.20.279-2019",
        "SHA-256 базы": "8a96e50f..."    // необязательно, но настоятельно рекомендуется
      },
      "Заменяет": ["ИЗМ-0"],             // разрешает конфликт с этими изменениями
      "Изменения": [ <операция>, ... ]
    }

АДРЕСАЦИЯ: «Путь» — массив сегментов, идущих от корня JSON.
    "Содержимое стандарта"                      ключ объекта (точное совпадение)
    {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}
                                                найти единственный дочерний
                                                объект по значениям полей
    {"№": "17"}                                короткая форма @where (удобно
                                                для строк таблиц)
    {"@index": 3}                              индекс массива (не рекомендуется:
                                                сдвигается при вставках)
    {"@where": {"Параметр": "..."}},          несколько полей = условие И
Селектор обязан найти РОВНО ОДИН объект, иначе сборка падает.

ОПЕРАЦИИ (поле «Операция»):
    OVERRIDE    заменить значение по пути. «Значение» — полная замена,
                «Поля» — частичное обновление полей объекта (для строк таблиц).
                «Было» — проверка ожидаемого старого значения (скаляр или
                подмножество полей). Настоятельно рекомендуется: это защита
                от «поплывшего» базового файла.
    NEW         добавить элемент. Для объекта: «Ключ» + «Значение»,
                необязательно «Перед» (вставить перед указанным ключом).
                Для массива: «Значение» и необязательно «Позиция».
    COPY        дублировать уже существующий узел (любой: шкаф, таблицу,
                строку, поле, скаляр). Копия — глубокое клонирование значения
                в момент применения.
                «Ключ» — имя копии в объекте-приёмнике (по умолчанию в том же,
                что и источник); копия встаёт сразу после источника (или по
                «Перед» / «После»). «Куда» — путь другого родителя,
                «Позиция» — вставка в массив (по умолчанию после источника). Копию можно сразу изменить: «Замены» массово
                заменяют подстроки в ИМЕНАХ ПОЛЕЙ и строковых значениях
                ({"Старое": "...", "Новое": "...", "Где": "все|ключи|значения"}),
                «Поля» / «Удалить» правят верхний уровень копии, «Правки» —
                вложенные узлы (относительные пути: «Значение», «Поля»,
                «Удалить», «Переименовать»), «Перенумеровать» — нумерация
                строк таблиц 1..N. «Было» проверяет источник.
    DEPRECATED  пометить, НО НЕ УДАЛЯТЬ: добавляются поля «Статус»,
                «Основание», «Действует до», «Изменение». Путь также
                попадает в «Редакция / Отменённые элементы».
    DELETE      физически удалить (для исправления ошибок разбора, а не для
                отмены пунктов стандарта). «Перенумеровать»: true —
                восстановить нумерацию 1..N в содержащей таблице.
    RENAME      переименовать ключ объекта, новое имя в «Ключ».

«Разрешить»: true в операции явно снимает проверку конфликта путей.

ПРАВИЛА СБОРКИ
    1. Несколько файлов с одним «Идентификатор» = версии одного изменения;
       применяется только старшая «Версия», остальные попадают в отчёт.
    2. Файлы со статусом не из {действует, утверждено} пропускаются.
    3. Порядок: («Порядок», «Дата», «Идентификатор»). Результат детерминирован.
    4. Конфликт: две операции из РАЗНЫХ изменений правят один и тот же путь
       (или путь-предок) -> ошибка, если позднее изменение не указало более
       раннее в «Заменяет» или в операции нет «Разрешить»: true. COPY читает
       копируемый узел в момент применения, поэтому изменение, правящее
       источник, тоже конфликтует с копированием (порядок влиял бы на копию).
    5. «Было» проверяется в момент применения, т.е. относительно состояния
       ПОСЛЕ предыдущих изменений, а не относительно исходной базы.
    6. После сборки пересчитывается «Количество строк» во всех таблицах,
       проверяются нумерация 1..N, имена комплектов, ссылки «Таблицы
       комплекта», отсутствие PUA-символов и пустых таблиц.
    7. Сверка с базой: все изменившиеся пути должны лежать внутри путей,
       затронутых операциями (или быть служебными). Любое «случайное»
       изменение данных считается ошибкой.

ПРИМЕРЫ
    python apply_changes.py --fingerprint "СТО ...279-2019.json"
    python apply_changes.py --base "СТО ...279-2019.json" \
        --changes changes --out "СТО ...279-2019 (с изм. 1-2).json" \
        --report "_parse/changes_report.txt"
    python apply_changes.py --base ... --changes changes --dry-run --strict
"""
from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import date

FORMAT = "СТО-изменения/1.0"
OPS = {"NEW", "OVERRIDE", "COPY", "DEPRECATED", "DELETE", "RENAME"}
ACTIVE = {"действует", "утверждено", "active", "approved"}
COMPLECT_RE = re.compile(r"^Комплект(?: [123])?$")
PUA_RE = re.compile(r"[\ue000-\uf8ff]")


class ChangeError(Exception):
    """Ошибка формата, адресации или конфликт изменений."""


# ---------------------------------------------------------------------------
# Служебные функции
# ---------------------------------------------------------------------------
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(v):
    """Приведение значения к строке для сравнения «Было»."""
    if isinstance(v, str):
        return v.strip()
    if v is None:
        return ""
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def seg_text(seg, resolved=None):
    if isinstance(seg, str):
        return seg
    if isinstance(seg, bool) or isinstance(seg, int):
        return "#%s" % seg
    if isinstance(seg, dict):
        where = seg.get("@where", seg)
        if "@index" in seg:
            return "#%s" % seg["@index"]
        return "@where(%s)" % ",".join(
            "%s=%s" % (k, v) for k, v in where.items())
    return str(seg)


def where_of(seg):
    if isinstance(seg, dict):
        w = seg.get("@where", {k: v for k, v in seg.items()
                               if not k.startswith("@")})
        return w or None
    return None


def matches(obj, where):
    return isinstance(obj, dict) and all(
        norm(obj.get(k, "")) == norm(v) for k, v in where.items())


def select(container, seg):
    """Вернуть (ключ/индекс, значение) для одного сегмента пути."""
    if isinstance(container, dict):
        if isinstance(seg, str):
            if seg not in container:
                raise ChangeError("нет ключа %r; есть: %s" %
                                  (seg, ", ".join(list(container.keys())[:8])))
            return seg, container[seg]
        where = where_of(seg)
        if where is not None:
            found = [k for k, v in container.items() if matches(v, where)]
            if len(found) != 1:
                raise ChangeError("селектор %s нашёл %d объектов (нужен ровно 1)" %
                                  (seg_text(seg), len(found)))
            return found[0], container[found[0]]
        raise ChangeError("недопустимый сегмент для объекта: %r" % (seg,))
    if isinstance(container, list):
        if isinstance(seg, dict) and "@index" in seg:
            i = int(seg["@index"])
        elif isinstance(seg, int) and not isinstance(seg, bool):
            i = seg
        elif isinstance(seg, dict):
            where = where_of(seg)
            found = [i for i, v in enumerate(container) if matches(v, where)]
            if len(found) != 1:
                raise ChangeError("селектор %s нашёл %d строк (нужна ровно 1)" %
                                  (seg_text(seg), len(found)))
            i = found[0]
        elif isinstance(seg, str):
            found = [i for i, v in enumerate(container) if norm(v) == norm(seg)]
            if len(found) != 1:
                raise ChangeError("значение %r найдено %d раз" % (seg, len(found)))
            i = found[0]
        else:
            raise ChangeError("недопустимый сегмент для массива: %r" % (seg,))
        if not 0 <= i < len(container):
            raise ChangeError("индекс %d вне массива (длина %d)" % (i, len(container)))
        return i, container[i]
    raise ChangeError("путь упирается в скаляр: %r" % (seg,))


def resolve(root, path, need_target=True):
    """Пройти путь.

    Возвращает (родитель, ключ, значение, канонический путь, список
    предков-контейнеров, физический путь). Канонический путь стабилен
    (селекторы остаются селекторами) и нужен для журнала/конфликтов;
    физический содержит реальные ключи и индексы и нужен для сверки с базой.
    """
    if not isinstance(path, list) or not path:
        raise ChangeError("«Путь» должен быть непустым массивом")
    cur = root
    canon, phys = [], []
    ancestors = [root]
    last = len(path) - 1 if need_target else len(path)
    for seg in path[:last]:
        prev = cur
        key, cur = select(prev, seg)
        canon.append(seg_text(seg, key))
        phys.append(("#%d" % key) if isinstance(prev, list) else str(key))
        ancestors.append(cur)
    if not need_target:
        return cur, None, cur, canon, ancestors, phys
    parent = cur
    key, value = select(parent, path[-1])
    canon.append(seg_text(path[-1], key))
    phys.append(("#%d" % key) if isinstance(parent, list) else str(key))
    return parent, key, value, canon, ancestors, phys


def esc(key):
    """Экранирование сегмента пути (JSON Pointer)."""
    return str(key).replace("~", "~0").replace("/", "~1")


def canon_str(canon):
    return "/" + "/".join(c.rstrip("/") for c in canon)


def phys_str(phys):
    return "/" + "/".join(esc(p) for p in phys)


def find_table(ancestors):
    for obj in reversed(ancestors):
        if isinstance(obj, dict) and "Строки" in obj and "Столбцы" in obj:
            return obj
    return None


def insert_before(dct, key, value, before):
    out = OrderedDict()
    placed = False
    for k, v in dct.items():
        if k == before and not placed:
            out[key] = value
            placed = True
        out[k] = v
    if not placed:
        out[key] = value
    dct.clear()
    dct.update(out)
    return placed


def rename_key(dct, old, new):
    out = OrderedDict()
    for k, v in dct.items():
        out[new if k == old else k] = v
    dct.clear()
    dct.update(out)


def insert_after(dct, after, key, value):
    out = OrderedDict()
    placed = False
    for k, v in dct.items():
        out[k] = v
        if k == after and not placed:
            out[key] = value
            placed = True
    if not placed:
        out[key] = value
    dct.clear()
    dct.update(out)
    return placed


# ---------------------------------------------------------------------------
# Дублирование узла (операция COPY)
# ---------------------------------------------------------------------------
REPLACE_SCOPES = {"все": "все", "all": "все", "ключи": "ключи",
                  "keys": "ключи", "значения": "значения", "values": "значения"}


def _as_text(v):
    return "" if v is None else str(v)


def parse_replacements(op, where="копия"):
    """«Замены» операции COPY -> [{"Старое", "Новое", "Где"}]."""
    raw = op.get("Замены") or []
    if not isinstance(raw, list):
        raise ChangeError("%s: «Замены» должно быть массивом" % where)
    out = []
    for i, item in enumerate(raw, 1):
        tag = "%s: замена %d" % (where, i)
        if isinstance(item, str):
            old, sep, new = item.partition("=>")
            if not sep:
                raise ChangeError("%s: ожидается «старое => новое»" % tag)
            old, new = old.strip(), new.strip()
            scope = "все"
        elif isinstance(item, dict):
            old = item.get("Старое", item.get("Было", ""))
            new = item.get("Новое", item.get("Стало", ""))
            scope = REPLACE_SCOPES.get(
                str(item.get("Где", item.get("Where", "все"))).strip().lower(), "")
            if not scope:
                raise ChangeError(
                    "%s: «Где» должно быть «все», «ключи» или «значения»" % tag)
        else:
            raise ChangeError("%s: ожидается объект или строка" % tag)
        old, new = _as_text(old), _as_text(new)
        if not old:
            raise ChangeError("%s: пустое «Старое» — нечего заменять" % tag)
        out.append({"Старое": old, "Новое": new, "Где": scope})
    return out


def replace_in_tree(value, old, new, scope, stats, path=""):
    """Заменить подстроки в ключах и/или строковых значениях поддерева.

    Возвращает новое значение: для скаляра в корне копии замена создаёт
    новую строку, поэтому результат нужно присвоить.
    """
    if isinstance(value, dict):
        out = OrderedDict()
        for k, v in value.items():
            nk = k
            if isinstance(k, str) and scope in ("все", "ключи") and old in k:
                nk = k.replace(old, new)
                stats["keys"] += 1
                if not nk:
                    raise ChangeError("замена %r -> %r: поле %r стало пустым (%s)"
                                      % (old, new, k, path or "/"))
            if nk in out:
                raise ChangeError(
                    "замена %r -> %r: в объекте %s два поля стали %r"
                    % (old, new, path or "/", nk))
            out[nk] = replace_in_tree(v, old, new, scope, stats,
                                      path + "/" + esc(nk))
        value.clear()
        value.update(out)
        return value
    if isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = replace_in_tree(v, old, new, scope, stats,
                                       path + "/#%d" % i)
        return value
    if isinstance(value, str) and scope in ("все", "значения") and old in value:
        stats["values"] += 1
        return value.replace(old, new)
    return value


def apply_copy_edit(root, edit, where):
    """Одна относительная правка внутри копии."""
    if not isinstance(edit, dict):
        raise ChangeError("%s: правка должна быть объектом" % where)
    if not isinstance(edit.get("Путь"), list) or not edit["Путь"]:
        raise ChangeError("%s: нужен непустой «Путь» относительно копии" % where)
    parent, key, value, canon, _, _ = resolve(root, edit["Путь"])
    if "Было" in edit:
        check_expected(edit, value, False, where)
    if edit.get("Удалить"):
        if isinstance(parent, dict):
            del parent[key]
        elif isinstance(parent, list):
            parent.pop(key)
        else:
            raise ChangeError("%s: нечего удалять" % where)
    elif "Переименовать" in edit:
        if not isinstance(parent, dict):
            raise ChangeError("%s: переименовать можно только поле объекта" % where)
        new = _as_text(edit["Переименовать"])
        if not new:
            raise ChangeError("%s: пустое новое имя поля" % where)
        if new in parent and new != key:
            raise ChangeError("%s: поле %r уже есть" % (where, new))
        rename_key(parent, key, new)
    elif "Поля" in edit:
        if not isinstance(value, dict) or not isinstance(edit["Поля"], dict):
            raise ChangeError("%s: «Поля» применимы только к объекту" % where)
        value.update(copy.deepcopy(edit["Поля"]))
    elif "Значение" in edit:
        parent[key] = copy.deepcopy(edit["Значение"])
    else:
        raise ChangeError("%s: нужен «Значение», «Поля», «Удалить» "
                          "или «Переименовать»" % where)


def build_copy(source, op, where="копия"):
    """Глубоко скопировать source и применить правки копии из операции.

    Возвращает (значение копии, статистика замен). Используется и сборкой,
    и GUI для предварительного показа копии до её вставки.
    """
    value = copy.deepcopy(source)
    stats = {"keys": 0, "values": 0}
    for rep in parse_replacements(op, where):
        value = replace_in_tree(value, rep["Старое"], rep["Новое"],
                                rep["Где"], stats)

    if "Поля" in op:
        if not isinstance(value, dict) or not isinstance(op["Поля"], dict):
            raise ChangeError("%s: «Поля» применимы только к объекту" % where)
        value.update(copy.deepcopy(op["Поля"]))

    if "Удалить" in op:
        if not isinstance(value, dict):
            raise ChangeError("%s: «Удалить» применимо только к объекту" % where)
        keys = op["Удалить"]
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, list):
            raise ChangeError("%s: «Удалить» — массив имён полей" % where)
        for key in keys:
            if key not in value:
                raise ChangeError("%s: в копии нет поля %r" % (where, key))
            del value[key]

    edits = op.get("Правки") or []
    if not isinstance(edits, list):
        raise ChangeError("%s: «Правки» должны быть массивом" % where)
    for j, edit in enumerate(edits, 1):
        apply_copy_edit(value, edit, "%s: правка %d" % (where, j))

    if op.get("Перенумеровать"):
        for table in all_tables(value):
            for i, row in enumerate(table.get("Строки") or [], 1):
                if isinstance(row, dict) and "№" in row:
                    row["№"] = str(i)
    return value, stats


# ---------------------------------------------------------------------------
# Загрузка и отбор файлов изменений
# ---------------------------------------------------------------------------
def collect_change_sets(patterns, skipped):
    files = []
    for pattern in patterns:
        if os.path.isdir(pattern):
            found = sorted(glob.glob(os.path.join(pattern, "*.json")))
        else:
            found = sorted(glob.glob(pattern)) or [pattern]
        for f in found:
            if os.path.abspath(f) not in files:
                files.append(os.path.abspath(f))
    if not files:
        raise ChangeError("не найдено ни одного файла изменений")

    parsed = []
    for path in files:
        cs = load_json(path)
        if cs.get("Формат") != FORMAT:
            raise ChangeError("%s: неверный «Формат» (ожидается %r)" % (path, FORMAT))
        for field in ("Идентификатор", "Изменения"):
            if field not in cs:
                raise ChangeError("%s: нет поля %r" % (path, field))
        if not isinstance(cs["Изменения"], list):
            raise ChangeError("%s: «Изменения» должно быть массивом" % path)
        parsed.append((path, cs))

    # Один Идентификатор = несколько версий одного изменения -> старшая версия.
    by_id = OrderedDict()
    for path, cs in parsed:
        key = cs["Идентификатор"]
        by_id.setdefault(key, []).append((path, cs))
    chosen = []
    for key, group in by_id.items():
        group.sort(key=lambda pc: (int(pc[1].get("Версия", 1)),
                                   str(pc[1].get("Дата", "")), pc[0]))
        winner = group[-1]
        chosen.append(winner)
        for path, cs in group[:-1]:
            skipped.append("%s: версия %s вытеснена версией %s изменения %s" %
                           (os.path.basename(path), cs.get("Версия", 1),
                            winner[1].get("Версия", 1), key))

    active = []
    for path, cs in chosen:
        status = str(cs.get("Статус", "действует")).strip().lower()
        if status not in ACTIVE:
            skipped.append("%s: статус %r -> пропущено" %
                           (os.path.basename(path), cs.get("Статус")))
            continue
        active.append((path, cs))
    active.sort(key=lambda pc: (int(pc[1].get("Порядок", 0)),
                                str(pc[1].get("Дата", "")),
                                str(pc[1]["Идентификатор"])))
    return active


# ---------------------------------------------------------------------------
# Применение операций
# ---------------------------------------------------------------------------
class Context:
    def __init__(self):
        self.touches = []          # (canon, id изменения, № операции, код)
        self.applied = []          # строки отчёта
        self.deprecated = []       # записи для блока «Редакция»
        self.renumber = []         # объекты таблиц для перенумерации
        self.warnings = []         # предупреждения операций (например, замена 0 раз)
        self.supersedes = set()    # id, которые текущее изменение заменяет


def overlap(a, b):
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def check_conflict(ctx, canon, cs, idx, op):
    path = canon_str(canon)
    supersedes = ctx.supersedes
    for prev_path, prev_id, prev_idx, prev_op in ctx.touches:
        if prev_id == cs["Идентификатор"] or not overlap(path, prev_path):
            continue
        if prev_id in supersedes or op.get("Разрешить"):
            continue
        raise ChangeError(
            "конфликт: %s (оп. %d, %s) и %s (оп. %d, %s) правят %s / %s. "
            "Укажите «Заменяет»: [%r] или «Разрешить»: true" %
            (cs["Идентификатор"], idx + 1, op["Операция"], prev_id,
             prev_idx + 1, prev_op, prev_path, path, prev_id))


def check_expected(op, value, strict, where):
    if "Было" not in op:
        if strict:
            raise ChangeError("%s: в строгом режиме обязательно поле «Было»" % where)
        return None
    expected = op["Было"]
    if isinstance(expected, dict):
        if not isinstance(value, dict):
            raise ChangeError("%s: ожидался объект, получено %r" % (where, value))
        for k, v in expected.items():
            if norm(value.get(k, "")) != norm(v):
                raise ChangeError(
                    "%s: поле %r ожидалось %r, фактически %r" %
                    (where, k, v, value.get(k, "")))
    elif norm(value) != norm(expected):
        raise ChangeError("%s: ожидалось %r, фактически %r" %
                          (where, expected, value))
    return norm(expected)


def apply_op(data, cs, idx, op, ctx, strict):
    code = str(op.get("Операция", "")).upper()
    if code not in OPS:
        raise ChangeError("изменение %s, оп. %d: неизвестная операция %r" %
                          (cs["Идентификатор"], idx + 1, op.get("Операция")))
    where = "%s / оп. %d / %s" % (cs["Идентификатор"], idx + 1, code)
    path = op.get("Путь")
    old = None
    read_canon = None
    replace_stats = None

    if code == "NEW":
        parent, _, _, canon, ancestors, phys = resolve(data, path, need_target=False)
        if "Ключ" in op:
            if not isinstance(parent, dict):
                raise ChangeError("%s: «Ключ» применим только к объекту" % where)
            key = op["Ключ"]
            if key in parent:
                raise ChangeError("%s: ключ %r уже существует; используйте OVERRIDE" %
                                  (where, key))
            value = copy.deepcopy(op.get("Значение"))
            if "Перед" in op:
                if not insert_before(parent, key, value, op["Перед"]):
                    ctx.applied.append("  ! %s: ключ «Перед» %r не найден, добавлено в конец" %
                                       (where, op["Перед"]))
            else:
                parent[key] = value
            canon, phys = canon + [str(key)], phys + [str(key)]
        elif isinstance(parent, list):
            value = copy.deepcopy(op.get("Значение"))
            pos = op.get("Позиция")
            index = len(parent) if pos is None else int(pos)
            if pos is None:
                parent.append(value)
            else:
                parent.insert(index, value)
            canon, phys = canon + ["+%d" % index], phys + ["#%d" % index]
        else:
            raise ChangeError("%s: для объекта нужен «Ключ», для массива — «Значение»" %
                              where)
        allowed = [phys_str(phys), phys_str(phys[:-1])]
        if op.get("Перенумеровать"):
            table = find_table(ancestors)
            if table is not None:
                ctx.renumber.append(table)
        target_canon = canon

    elif code == "COPY":
        (src_parent, src_key, src_value, src_canon, src_ancestors,
         src_phys) = resolve(data, path)
        if "Было" in op:
            check_expected(op, src_value, False, where)
        if "Куда" in op:
            parent, _, _, parent_canon, tgt_ancestors, parent_phys = \
                resolve(data, op["Куда"], need_target=False)
        else:
            parent = src_parent
            parent_canon, parent_phys = src_canon[:-1], src_phys[:-1]
            tgt_ancestors = src_ancestors

        value, replace_stats = build_copy(src_value, op, where)

        if isinstance(parent, dict):
            key = op.get("Ключ")
            if not isinstance(key, str) or not key:
                raise ChangeError(
                    "%s: для дублирования в объект нужен «Ключ» — имя копии" %
                    where)
            if key in parent:
                raise ChangeError("%s: ключ %r уже существует" % (where, key))
            if "Позиция" in op:
                raise ChangeError("%s: «Позиция» применима только к массиву" %
                                  where)
            if "Перед" in op:
                if not insert_before(parent, key, value, op["Перед"]):
                    ctx.applied.append(
                        "  ! %s: ключ «Перед» %r не найден, копия добавлена "
                        "в конец" % (where, op["Перед"]))
            elif "После" in op:
                if not insert_after(parent, op["После"], key, value):
                    ctx.applied.append(
                        "  ! %s: ключ «После» %r не найден, копия добавлена "
                        "в конец" % (where, op["После"]))
            elif parent is src_parent and isinstance(src_key, str):
                insert_after(parent, src_key, key, value)
            else:
                parent[key] = value
            canon = parent_canon + [str(key)]
            phys = parent_phys + [str(key)]
        elif isinstance(parent, list):
            if "Ключ" in op:
                raise ChangeError(
                    "%s: «Ключ» применим только к объекту; для массива "
                    "укажите «Позиция»" % where)
            if "Позиция" in op:
                try:
                    pos = int(op["Позиция"])
                except (TypeError, ValueError):
                    raise ChangeError("%s: «Позиция» должна быть числом" % where)
            elif parent is src_parent and isinstance(src_key, int):
                pos = src_key + 1
            else:
                pos = len(parent)
            if not 0 <= pos <= len(parent):
                raise ChangeError("%s: позиция %d вне массива (длина %d)" %
                                  (where, pos, len(parent)))
            parent.insert(pos, value)
            canon = parent_canon + ["+%d" % pos]
            phys = parent_phys + ["#%d" % pos]
        else:
            raise ChangeError("%s: копию можно вставить только в объект "
                              "или массив" % where)

        allowed = [phys_str(phys), phys_str(phys[:-1])]
        if op.get("Перенумеровать"):
            for table in all_tables(value):
                ctx.renumber.append(table)
            table = find_table(tgt_ancestors)
            if table is not None:
                ctx.renumber.append(table)
        target_canon = canon
        read_canon = src_canon

    else:
        parent, key, value, canon, ancestors, phys = resolve(data, path)
        allowed = [phys_str(phys)]
        old = check_expected(op, value, strict, where)
        target_canon = canon
        if code == "OVERRIDE":
            if "Поля" in op:
                if not isinstance(value, dict):
                    raise ChangeError("%s: «Поля» применимы только к объекту" % where)
                value.update(copy.deepcopy(op["Поля"]))
            else:
                if "Значение" not in op:
                    raise ChangeError("%s: нужно «Значение» или «Поля»" % where)
                parent[key] = copy.deepcopy(op["Значение"])
        elif code == "DEPRECATED":
            if not isinstance(value, dict):
                raise ChangeError("%s: пометить можно только объект" % where)
            reason = op.get("Причина") or op.get("Основание") or cs.get("Основание", "")
            value["Статус"] = op.get("Статус", "Утратило силу")
            value["Основание"] = reason
            value["Действует до"] = op.get("Действует до", cs.get("Дата", ""))
            value["Изменение"] = cs["Идентификатор"]
            ctx.deprecated.append(OrderedDict([
                ("Путь", canon_str(canon)),
                ("Изменение", cs["Идентификатор"]),
                ("Основание", reason),
                ("Действует до", value["Действует до"]),
            ]))
            allowed.extend(phys_str(phys + [k]) for k in
                           ("Статус", "Основание", "Действует до", "Изменение"))
        elif code == "DELETE":
            if isinstance(parent, dict):
                del parent[key]
            else:
                parent.pop(key)
            allowed.append(phys_str(phys[:-1]))
            if op.get("Перенумеровать"):
                table = find_table(ancestors)
                if table is not None:
                    ctx.renumber.append(table)
        elif code == "RENAME":
            if not isinstance(parent, dict) or "Ключ" not in op:
                raise ChangeError("%s: RENAME нужен объект и «Ключ»" % where)
            new_key = op["Ключ"]
            if new_key in parent and new_key != key:
                raise ChangeError("%s: ключ %r уже занят" % (where, new_key))
            rename_key(parent, key, new_key)
            allowed.append(phys_str(phys[:-1]))

    target_path = canon_str(target_canon)
    check_conflict(ctx, target_canon, cs, idx, op)
    ctx.touches.append((target_path, cs["Идентификатор"], idx, code))
    if code == "COPY":
        read_path = canon_str(read_canon)
        if read_path != target_path:
            check_conflict(ctx, read_canon, cs, idx, op)
            ctx.touches.append((read_path, cs["Идентификатор"], idx, "COPY-READ"))
        if op.get("Замены") and not (replace_stats["keys"]
                                     or replace_stats["values"]):
            ctx.warnings.append("%s: ни одна замена не сработала — проверьте "
                                "«Старое» и «Где»" % where)
        ctx.applied.append(
            "  %-11s %s  (замен: ключей %d, значений %d)" %
            (code, target_path, replace_stats["keys"], replace_stats["values"]))
    else:
        ctx.applied.append(
            "  %-11s %s%s%s" %
            (code, target_path,
             ("  было: %s" % _short(old)) if old is not None else "",
             ("  -> %s" % _short(op.get("Значение") if "Значение" in op
                                 else op.get("Поля") or op.get("Ключ") or ""))
             if code in ("OVERRIDE", "NEW", "RENAME", "DEPRECATED") else ""))
    return allowed


def _short(v):
    t = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return (t[:90] + "…") if len(t) > 90 else t


# ---------------------------------------------------------------------------
# Постобработка и проверки
# ---------------------------------------------------------------------------
def all_tables(node):
    if isinstance(node, dict):
        if isinstance(node.get("Строки"), list) and "Столбцы" in node:
            yield node
        for v in node.values():
            yield from all_tables(v)
    elif isinstance(node, list):
        for v in node:
            yield from all_tables(v)


def finalize(data, ctx):
    seen = set()
    for table in ctx.renumber:
        if id(table) in seen:
            continue
        seen.add(id(table))
        for i, row in enumerate(table["Строки"], 1):
            if isinstance(row, dict) and "№" in row:
                row["№"] = str(i)
    for table in all_tables(data):
        if "Количество строк" in table:
            table["Количество строк"] = len(table["Строки"])


def diff_paths(a, b, prefix=""):
    """Все листовые пути, где два JSON различаются."""
    if isinstance(a, dict) != isinstance(b, dict) or \
            isinstance(a, list) != isinstance(b, list):
        yield prefix or "/"
        return
    if isinstance(a, dict):
        for k in list(a.keys()) + [k for k in b if k not in a]:
            p = prefix + "/" + esc(k)
            if k not in a or k not in b:
                yield p
            else:
                yield from diff_paths(a[k], b[k], p)
    elif isinstance(a, list):
        if len(a) != len(b):
            yield prefix or "/"
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                yield from diff_paths(x, y, prefix + "/#%d" % i)
    elif norm(a) != norm(b):
        yield prefix or "/"


def validate(data, base, ctx, allowed_prefixes, strict):
    problems = []
    warnings = []
    content = data.get("Содержимое стандарта", {})

    # 1. Сверка с базой: ничего лишнего не изменилось.
    allowed = [p for p in allowed_prefixes if p]
    changed = [p for p in diff_paths(base, data) if not p.startswith("/Редакция")]
    unexpected = [p for p in changed
                  if not any(p == a or p.startswith(a.rstrip("/") + "/")
                             for a in allowed)
                  and not p.endswith("/Количество строк")]
    if unexpected:
        problems.append("незадекларированные изменения (%d): %s" %
                        (len(unexpected), "; ".join(unexpected[:5])))

    # 2. Имена комплектов.
    for key, cab in content.items():
        if not isinstance(cab, dict) or "Описание шкафа" not in cab:
            continue
        names = [k for k in cab["Описание шкафа"] if COMPLECT_RE.match(k)]
        if len(names) == 1 and names[0] != "Комплект":
            problems.append("%s: один комплект должен называться «Комплект», а не %r" %
                            (key, names[0]))
        if len(names) > 1:
            want = ["Комплект %d" % i for i in range(1, len(names) + 1)]
            if names != want:
                problems.append("%s: комплекты %s, ожидалось %s" % (key, names, want))

    # 3. Таблицы: нумерация, счётчики, ссылки из комплектов.
    for table in all_tables(data):
        cols = table.get("Столбцы") or []
        rows = table.get("Строки") or []
        if not rows:
            problems.append("пустая таблица: %s" % _short(table.get("Наименование", "")))
        if "Количество строк" in table and table["Количество строк"] != len(rows):
            problems.append("неверный «Количество строк»: %d != %d" %
                            (table["Количество строк"], len(rows)))
        if cols and cols[0] == "№":
            nums = [str(r.get("№", "")) for r in rows if isinstance(r, dict)]
            if nums != [str(i) for i in range(1, len(rows) + 1)]:
                warnings.append("нумерация не 1..N (%s): %s" %
                                (_short(table.get("Наименование", "")),
                                 ",".join(nums[:12])))
    for key, cab in content.items():
        if not isinstance(cab, dict) or "Описание шкафа" not in cab:
            continue
        own = set(cab.get("Таблицы", {}))
        for cname, obj in cab["Описание шкафа"].items():
            if not COMPLECT_RE.match(cname) or not isinstance(obj, dict):
                continue
            for _, ref in (obj.get("Таблицы комплекта") or {}).items():
                if ref and ref not in own:
                    warnings.append("%s/%s: ссылка на отсутствующую таблицу %s" %
                                    (key, cname, ref))

    # 4. Символы и переносы строк.
    def scan(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                scan(v, path + "/" + esc(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                scan(v, path + "/#%d" % i)
        elif isinstance(node, str):
            if PUA_RE.search(node):
                problems.append("PUA-символ: %s" % path)
            if "\n" in node:
                problems.append("перевод строки в значении: %s" % path)
    scan(content)

    if strict and warnings:
        problems.extend("предупреждение в строгом режиме: " + w for w in warnings)
    return problems, warnings


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------
def assemble(base_path, change_patterns, strict=False, ignore_hash=False):
    base = load_json(base_path)
    base_sha = sha256_file(base_path)
    data = copy.deepcopy(base)
    skipped = []
    sets = collect_change_sets(change_patterns, skipped)
    ctx = Context()
    allowed = ["/Редакция"]
    registry = []

    for path, cs in sets:
        applies = cs.get("Применимо к", {})
        if applies.get("Шифр стандарта") not in (None, base.get("Шифр стандарта")):
            raise ChangeError("%s: изменение относится к стандарту %r, а база — %r" %
                              (path, applies.get("Шифр стандарта"),
                               base.get("Шифр стандарта")))
        expected_sha = applies.get("SHA-256 базы")
        if expected_sha and expected_sha != base_sha and not ignore_hash:
            raise ChangeError(
                "%s: хэш базы не совпадает.\n  ожидался %s\n  фактический %s\n"
                "Проверьте, что изменение составлено для этой версии базы "
                "(или используйте --ignore-hash)." %
                (path, expected_sha, base_sha))
        ctx.supersedes = set(cs.get("Заменяет", []))
        ctx.applied.append("\n%s (версия %s, %s) — %s" %
                           (cs["Идентификатор"], cs.get("Версия", 1),
                            cs.get("Дата", ""), cs.get("Наименование", "")))
        for i, op in enumerate(cs["Изменения"]):
            try:
                allowed += apply_op(data, cs, i, op, ctx, strict)
            except ChangeError as exc:
                raise ChangeError("%s: %s" % (path, exc))
        registry.append(OrderedDict([
            ("Идентификатор", cs["Идентификатор"]),
            ("Версия", cs.get("Версия", 1)),
            ("Дата", cs.get("Дата", "")),
            ("Наименование", cs.get("Наименование", "")),
            ("Основание", cs.get("Основание", "")),
            ("SHA-256 файла", sha256_file(path)),
            ("Операций", len(cs["Изменения"])),
            ("Заменяет", list(cs.get("Заменяет", []))),
        ]))

    finalize(data, ctx)
    problems, warnings = validate(data, base, ctx, allowed, strict)
    warnings = list(ctx.warnings) + warnings
    if strict:
        problems.extend("предупреждение в строгом режиме: " + w
                        for w in ctx.warnings)

    data["Редакция"] = OrderedDict([
        ("Формат", FORMAT),
        ("Собрано", date.today().isoformat()),
        ("Базовый стандарт", base.get("Шифр стандарта", "")),
        ("SHA-256 базы", base_sha),
        ("Применённые изменения", registry),
        ("Исключённые изменения", skipped),
        ("Отменённые элементы", ctx.deprecated),
        ("Всего операций", len(sets) and sum(len(cs["Изменения"]) for _, cs in sets) or 0),
        ("Затронуто путей", len({t[0] for t in ctx.touches})),
    ])
    return data, ctx, registry, skipped, base_sha, problems, warnings


def build_report(ctx, registry, skipped, base_sha, problems, warnings, result_sha=None):
    lines = ["СБОРКА РЕДАКЦИИ СТАНДАРТА", "=" * 60,
             "SHA-256 базы: %s" % base_sha]
    if result_sha:
        lines.append("SHA-256 результата: %s" % result_sha)
    lines.append("")
    lines.append("ПРИМЕНЁННЫЕ ИЗМЕНЕНИЯ (%d)" % len(registry))
    for r in registry:
        lines.append("  %s v%s от %s — %s (%d оп.)" %
                     (r["Идентификатор"], r["Версия"], r["Дата"],
                      r["Наименование"], r["Операций"]))
    if skipped:
        lines.append("\nИСКЛЮЧЕНО")
        lines.extend("  - " + s for s in skipped)
    lines.append("\nЖУРНАЛ ОПЕРАЦИЙ")
    lines.extend(ctx.applied)
    if ctx.deprecated:
        lines.append("\nОТМЕНЁННЫЕ (НО СОХРАНЁННЫЕ) ЭЛЕМЕНТЫ")
        for rec in ctx.deprecated:
            lines.append("  %s | %s | %s" %
                         (rec["Путь"], rec["Изменение"], rec["Основание"]))
    lines.append("\nПРОВЕРКА")
    if warnings:
        lines.extend("  ПРЕДУПРЕЖДЕНИЕ: " + w for w in warnings)
    lines.append("  " + ("ОШИБКИ:" if problems else "OK"))
    lines.extend("    ! " + p for p in problems)
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(
        description="Сборка новой редакции стандарта из базового JSON и изменений")
    ap.add_argument("--base", help="базовый JSON стандарта")
    ap.add_argument("--changes", nargs="+", default=[],
                    help="файлы/каталоги/маски с JSON изменений")
    ap.add_argument("--out", help="путь к собранному JSON")
    ap.add_argument("--report", help="путь к текстовому отчёту")
    ap.add_argument("--dry-run", action="store_true",
                    help="только проверить и показать отчёт, не писать JSON")
    ap.add_argument("--strict", action="store_true",
                    help="требовать «Было» и считать предупреждения ошибками")
    ap.add_argument("--ignore-hash", action="store_true",
                    help="не проверять SHA-256 базы, указанный в изменении")
    ap.add_argument("--fingerprint", metavar="JSON",
                    help="напечатать SHA-256 файла (для поля «SHA-256 базы»)")
    args = ap.parse_args()

    if args.fingerprint:
        print(sha256_file(args.fingerprint))
        return
    if not args.base or not args.changes:
        ap.error("нужны --base и --changes (либо --fingerprint JSON)")
    if not args.out and not args.dry_run:
        ap.error("нужен --out или --dry-run")

    try:
        data, ctx, registry, skipped, base_sha, problems, warnings = assemble(
            args.base, args.changes, strict=args.strict,
            ignore_hash=args.ignore_hash)
    except (ChangeError, OSError, ValueError) as exc:
        print("ОШИБКА СБОРКИ: %s" % exc, file=sys.stderr)
        sys.exit(1)

    result_sha = None
    if args.out and not args.dry_run and not problems:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        result_sha = sha256_file(args.out)
    report = build_report(ctx, registry, skipped, base_sha, problems, warnings,
                          result_sha)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
    print(report)
    print("Собрано: %s" % (args.out if result_sha else "ничего (dry-run/ошибки)"))
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
