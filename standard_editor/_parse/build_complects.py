# -*- coding: utf-8 -*-
"""Разбиение описания каждого шкафа на КОМПЛЕКТЫ по образцу example.json.

Правила (по замечанию пользователя):

* в шкафу может быть один, два или три комплекта;
* комплект может быть без ИЭУ;
* описание каждого комплекта берётся из example.json:

      "Комплект": {
          "Имя ИЭУ": "ИЭУ",
          "Входные аналоговые измерения": {
              "Аналоговая цепь": "Ia, Ib, Ic",
              "Испытательный блок в шкафу": "SG1",
              "Количество контактов испытательного блока с учетом регистрации его состояния": "6+1",
              "Примечание": "Фазные токи В БСК (В1)",
              "Функция": []
          }
      }

  В example.json показана ПЕРВАЯ СТРОКА таблицы «Входные аналоговые
  измерения» шкафа ШЭТ 431.01-1. Поскольку строк в таблице несколько,
  «Входные аналоговые измерения» в итоговом JSON - это список таких
  объектов (по одной записи на строку таблицы).

* один ИЭУ  -> ключ "Комплект";
* два ИЭУ   -> "Комплект 1", "Комплект 2";
* три ИЭУ   -> "Комплект 1", "Комплект 2", "Комплект 3";
* комплект без ИЭУ -> "Имя ИЭУ": "" и пояснение в "Примечание".

Имя ИЭУ: "ИЭУ" при одном ИЭУ, "ИЭУ1"/"ИЭУ2"/"ИЭУ3" при нескольких.

Источник данных - уже собранный JSON стандарта (никакого повторного
парсинга PDF): таблица 5.x.1 даёт описание, таблицы «Входные аналоговые
измерения» / «SV потоки» дают состав комплекта, таблица «Основные
компоненты» и общий перечень шкафов дают количество ИЭУ.

Использование:
    python _parse/build_complects.py --json "СТО ....json" \
        [--out "СТО ....json"] [--report _parse/complects_279.txt]

По умолчанию исходный файл перезаписывается, копия сохраняется в
_parse/<имя>.bak.json.

Явная конфигурация комплектов (COMPLECTS) нужна для шкафов, где PDF не
указывает число ИЭУ напрямую, и для шкафов с комплектом БЕЗ ИЭУ:
    COMPLECTS["<шифр стандарта>"]["5.3"] = ["ИЭУ1", "ИЭУ2", ""]
где "" означает комплект без ИЭУ. Если секции в конфигурации нет,
число комплектов определяется автоматически.
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys
from collections import OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Явно заданные комплекты. Пустая строка / None = комплект без ИЭУ.
# Остальные шкафы определяются автоматически (см. detect_complects).
COMPLECTS = {
    "СТО 56947007-33.040.20.279-2019": {
        "5.3": ["ИЭУ1", "ИЭУ2"],          # два ИЭУ, раздельные таблицы 5.3.2/5.3.3
    },
    "СТО 56947007-33.040.20.281-2019": {
        "5.3": ["ИЭУ1", "ИЭУ2"],          # «(два комплекта)», таблицы общие для ИЭУ1 (ИЭУ2)
    },
}

ANALOG_RE = re.compile(
    r"^(Входные аналоговые измерения|Входные SV потоки|SV потоки)\b", re.I)
CANON = {
    "Аналоговая цепь": "Аналоговая цепь",
    "Аналоговые измерения": "Аналоговая цепь",
    "SV поток": "Аналоговая цепь",
    "Испытательный блок в шкафу": "Испытательный блок в шкафу",
    "Количество контактов испытательного блока с учетом регистрации его состояния":
        "Количество контактов испытательного блока с учетом регистрации его состояния",
    "Примечание": "Примечание",
}
# Ключи 5.x.1, которые относятся к ИЭУ/комплекту (для шкафов с общими
# таблицами, где в 5.x.1 только одна колонка значений).
IEU_KEYS = re.compile(
    r"^(Основные функции МП ИЭУ|Цифровые порты ИЭУ|Входные |Выходные |"
    r"Функциональные клавиши|Светодиодная сигнализация|Дискретные сигналы|"
    r"Аналоговые значения|Команды управления|Отчеты в АСУ ТП|"
    r"Основные параметры функций|Внутренние дискретные цепи)", re.I)
TABLE_REF = re.compile(r"^Таблица\s+[\d.А]+", re.I)


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip() if isinstance(s, str) else s


def collapse(lines):
    """Одна строка -> скаляр, несколько строк -> список (как в example.json)."""
    lines = [norm(x) for x in lines if norm(x)]
    if not lines:
        return ""
    return lines[0] if len(lines) == 1 else lines


def signal_from_listing(listing_row):
    """Число ИЭУ/комплектов по строке «Общего перечня шкафов стандарта»."""
    if not listing_row:
        return 0
    text = " ".join(str(v) for v in listing_row.values() if isinstance(v, str))
    if re.search(r"\(\s*три\s+комплекта", text, re.I):
        return 3
    if re.search(r"\(\s*два\s+комплекта", text, re.I):
        return 2
    nums = {int(x) for x in re.findall(r"ИЭУ\s*([123])", text)}
    return max(nums) if nums else 0


def signal_from_components(cab):
    """Количество ИЭУ из таблицы «Основные компоненты»."""
    for t in cab["Таблицы"].values():
        if not t["Наименование"].startswith("Основные компоненты"):
            continue
        for rec in t["Строки"]:
            vals = [norm(v) for v in rec.values()]
            if len(vals) >= 4 and "ИЭУ" in vals[1] and "электронное устройство" in vals[1].lower():
                m = re.match(r"^(\d+)", vals[3])
                if m:
                    return int(m.group(1))
    return 0


def detect_complects(cab, listing_row):
    """Определить (число комплектов, словарь сигналов) по независимым признакам."""
    tables = cab["Таблицы"]
    sec = cab["Раздел стандарта"]
    desc = tables["Таблица " + sec + ".1"]
    analog = [n for n, t in tables.items() if ANALOG_RE.match(t["Наименование"])]
    ncols = max(len(r) for r in desc["Строки"]) if desc["Строки"] else 2
    signals = OrderedDict([
        ("компоненты: ИЭУ, шт.", signal_from_components(cab)),
        ("таблицы аналоговых измерений", len(analog)),
        ("колонки значений в 5.x.1", ncols - 1),
        ("общий перечень шкафов", signal_from_listing(listing_row)),
    ])
    keys = " ".join(norm(list(r.values())[0]) for r in desc["Строки"])
    m = re.search(r"Основные функции МП ИЭУ\s*([123])\s*\(\s*ИЭУ\s*([123])", keys)
    signals["заголовок 5.x.1 «ИЭУ1 (ИЭУ2)»"] = int(m.group(2)) if m else 0
    n = max([v for v in signals.values() if v] or [1])
    return min(max(n, 1), 3), signals


def split_description(desc, n):
    """Разложить таблицу 5.x.1 на общие и посекционные (по ИЭУ) параметры.

    Возвращает (common, per_complect, shared_only), где shared_only=True,
    если в таблице одна колонка значений (общие таблицы на несколько ИЭУ).
    """
    rows = [list(r.values()) for r in desc["Строки"]]
    ncol = max([len(r) for r in rows] + [2])
    grouped = []                       # [(ключ, [[значения колонки 1], ...])]
    for row in rows:
        row = (row + [""] * ncol)[:ncol]
        key = norm(row[0])
        vals = [norm(x) for x in row[1:]]
        if not key and grouped and any(vals):
            prev = grouped[-1][1]
            while len(prev) < len(vals):
                prev.append([])
            for i, v in enumerate(vals):
                if v:
                    prev[i].append(v)
            continue
        if not key:
            continue
        grouped.append((key, [[v] if v else [] for v in vals]))

    shared_only = n > 1 and not any(
        any(lines for lines in cols[1:]) for _, cols in grouped)
    common, per = OrderedDict(), [OrderedDict() for _ in range(n)]
    for key, cols in grouped:
        multi = any(lines for lines in cols[1:])
        if not multi:
            common[key] = collapse(cols[0])
            if shared_only and IEU_KEYS.match(key) and n > 1:
                for i in range(n):
                    per[i][key] = common[key]
            continue
        for i in range(n):
            lines = cols[i] if i < len(cols) else []
            # «ИЭУ1» / «ИЭУ2» в строке функций - это подпись колонки,
            # а не функция; имя устройства уже лежит в «Имя ИЭУ».
            lines = [x for x in lines if not re.fullmatch(r"ИЭУ\s*[123]", x, re.I)]
            per[i][key] = collapse(lines)
    return common, per, shared_only


def analog_rows(table):
    """Строки таблицы аналоговых измерений в формате example.json."""
    out = []
    for rec in table["Строки"]:
        obj = OrderedDict()
        for col, value in rec.items():
            col = norm(col)
            if col == "№" or col.startswith("Столбец ") or not col:
                continue
            name = CANON.get(col, col)
            if name in obj and norm(value):
                obj[name] = (obj[name] + "; " + norm(value)).strip("; ")
            else:
                obj[name] = norm(value)
        obj["Функция"] = []
        out.append(obj)
    return out


def analog_tables(cab):
    return OrderedDict(
        (num, t) for num, t in cab["Таблицы"].items()
        if ANALOG_RE.match(t["Наименование"]))


def cabinet_listing(content, cipher):
    """Строка общего перечня, соответствующая шифру шкафа."""
    for row in content.get("Общий перечень шкафов стандарта", []):
        if norm(row.get("Код ШЭТ", "")).replace(" ", "") in cipher:
            return row
    return None


def transform(data, report):
    code = data["Шифр стандарта"]
    content = data["Содержимое стандарта"]
    conf = COMPLECTS.get(code, {})
    changed = 0
    for key, cab in content.items():
        if not isinstance(cab, dict) or "Описание шкафа" not in cab:
            continue
        sec = cab["Раздел стандарта"]
        cipher = cab["Шифр шкафа"]
        listing = cabinet_listing(content, cipher)
        auto, signals = detect_complects(cab, listing)
        names = conf.get(sec)
        if names is None:
            n = auto
            names = ["ИЭУ"] if n == 1 else ["ИЭУ%d" % (i + 1) for i in range(n)]
        else:
            n = len(names)
        names = ["" if x is None else x for x in names]

        desc_table = cab["Таблицы"]["Таблица " + sec + ".1"]
        common, per, shared_only = split_description(desc_table, n)
        # Таблицы аналоговых измерений относятся только к комплектам С ИЭУ.
        # У комплекта без ИЭУ таких измерений нет.
        ieu_idx = [i for i, name in enumerate(names) if name]
        atabs = list(analog_tables(cab).items())
        mapped = [(None, None)] * n
        if ieu_idx and len(atabs) == len(ieu_idx):
            for k, i in enumerate(ieu_idx):
                mapped[i] = atabs[k]
        elif ieu_idx and len(atabs) == 1:
            for i in ieu_idx:
                mapped[i] = atabs[0]         # общие таблицы ИЭУ1 (ИЭУ2)
        elif ieu_idx and len(atabs) > len(ieu_idx):
            for k, i in enumerate(ieu_idx):
                mapped[i] = atabs[k]

        new_desc = OrderedDict(common)
        if n == 1:
            # Строго по example.json: плоское описание шкафа + один «Комплект».
            # Сохраняем ВСЕ прежние ключи описания (ничего не теряем).
            new_desc = OrderedDict(cab["Описание шкафа"])
        for i in range(n):
            ckey = "Комплект" if n == 1 else "Комплект %d" % (i + 1)
            obj = OrderedDict()
            obj["Имя ИЭУ"] = names[i]
            if not names[i]:
                obj["Примечание"] = "Комплект без ИЭУ"
            num, table = mapped[i]
            obj["Входные аналоговые измерения"] = analog_rows(table) if table else []
            refs = OrderedDict()
            for pk, pv in per[i].items():
                if TABLE_REF.match(pv) if isinstance(pv, str) else False:
                    refs[pk] = pv
                elif pv not in ("", [], None):
                    obj[pk] = pv
            if num:
                refs["Входные аналоговые измерения"] = num
            if refs and n > 1:
                obj["Таблицы комплекта"] = refs
            new_desc[ckey] = obj
            report.append(
                "  %-6s %-16s ИЭУ=%-5s аналог. таблица=%-16s строк=%-3s "
                "ключ=%s" % (sec, cipher, names[i] or "(без ИЭУ)",
                             num or "-", table["Количество строк"] if table else 0,
                             ckey))
        report.append("  %-6s сигналы: %s -> комплектов: %d%s" % (
            sec, ", ".join("%s=%s" % kv for kv in signals.items()), n,
            " (явная конфигурация)" if sec in conf else ""))
        cab["Описание шкафа"] = new_desc
        changed += 1
    return changed


def scalars(obj):
    """Все непустые строковые значения описания (для проверки потерь)."""
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(scalars(v))
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            out.extend(scalars(v))
        return out
    return [obj] if isinstance(obj, str) and obj.strip() else []


def validate(before, after):
    problems = []
    bc, ac = before["Содержимое стандарта"], after["Содержимое стандарта"]

    def all_tables(content):
        out = []
        for v in content.values():
            if isinstance(v, dict) and "Таблицы" in v:
                out.extend(v["Таблицы"].items())
            elif isinstance(v, dict):
                out.extend(v.items())
        return out

    bt, at = all_tables(bc), all_tables(ac)
    if len(bt) != len(at):
        problems.append("число таблиц изменилось: %d -> %d" % (len(bt), len(at)))
    brows = sum(t["Количество строк"] for _, t in bt if isinstance(t, dict) and "Строки" in t)
    arows = sum(t["Количество строк"] for _, t in at if isinstance(t, dict) and "Строки" in t)
    if brows != arows:
        problems.append("число строк изменилось: %d -> %d" % (brows, arows))

    for key, cab in ac.items():
        if not isinstance(cab, dict) or "Описание шкафа" not in cab:
            continue
        desc = cab["Описание шкафа"]
        comps = [k for k in desc if re.fullmatch(r"Комплект(?: [123])?", k)]
        if not comps:
            problems.append("%s: нет ни одного комплекта" % key)
            continue
        numbered = sorted(k for k in comps if k != "Комплект")
        if "Комплект" in comps and len(comps) > 1:
            problems.append("%s: смешаны «Комплект» и «Комплект N»" % key)
        if len(numbered) > 1 and numbered != ["Комплект %d" % i for i in range(1, len(numbered) + 1)]:
            problems.append("%s: нарушена нумерация комплектов: %s" % (key, numbered))
        for k in comps:
            obj = desc[k]
            if "Имя ИЭУ" not in obj:
                problems.append("%s / %s: нет «Имя ИЭУ»" % (key, k))
            if "Входные аналоговые измерения" not in obj:
                problems.append("%s / %s: нет «Входные аналоговые измерения»" % (key, k))
            elif not isinstance(obj["Входные аналоговые измерения"], list):
                problems.append("%s / %s: аналоговые измерения не список" % (key, k))
        # проверка потери текстов описания
        old = scalars(bc[key]["Описание шкафа"])
        new = set(scalars(desc))
        missing = [v for v in old if v not in new]
        if missing:
            problems.append("%s: потеряно значений описания: %s" % (key, missing[:4]))
    return problems, len(bt), brows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out")
    ap.add_argument("--report")
    args = ap.parse_args()
    src = os.path.abspath(args.json)
    dst = os.path.abspath(args.out or src)
    with open(src, encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=OrderedDict)
    before = copy.deepcopy(data)

    report = ["Стандарт: %s" % data["Шифр стандарта"], "Исходный файл: %s" % src]
    changed = transform(data, report)
    problems, ntables, nrows = validate(before, data)
    report.append("Шкафов: %d, таблиц: %d, строк данных: %d" % (changed, ntables, nrows))
    if problems:
        report.append("ПРОБЛЕМЫ:")
        report.extend("  ! " + p for p in problems)
        print("\n".join(report), file=sys.stderr)
        sys.exit(1)
    report.append("Проверка: OK (таблицы/строки без изменений, значения описания сохранены)")

    if dst == src:
        bak = os.path.join(BASE, "_parse", os.path.basename(src) + ".bak.json")
        shutil.copy2(src, bak)
        report.append("Резервная копия: %s" % bak)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    report.append("Результат: %s" % dst)
    if args.report:
        with open(os.path.abspath(args.report), "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
