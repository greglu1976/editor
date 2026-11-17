# -*- coding: utf-8 -*-
"""Сборка итогового JSON по стандарту СТО 56947007-33.040.20.279-2019.

Структура полностью повторяет результаты для 280-2019 и 281-2019:
метаданные стандарта -> "Содержимое стандарта" -> общий перечень шкафов,
по одному объекту на шкаф (назначение, описание из таблицы 5.x.1 и все
таблицы раздела), прочие таблицы и приложение А.

Отличия 279-2019: архитектура I типа, шесть шкафов (разделы 5.2-5.7),
шифры 430.01-0 / 431.02-0 / 430.03-0 / 430.04-0 / 430.05-0 / 431.06-0,
101 таблица, у шкафа 5.3 два ИЭУ (23 таблицы и три столбца в 5.3.1).
"""
import difflib
import json
import os
import re
from collections import OrderedDict

import pymupdf

# Пути можно переопределить извне (см. standard_to_docx.py).
PDF = os.environ.get("STO_PDF", r"G:/e_standards/СТО 56947007-33.040.20.279-2019.pdf")
RAW = os.environ.get("STO_RAW", r"G:/e_standards/_parse/raw_tables_279.json")
OUT = os.environ.get("STO_OUT", r"G:/e_standards/СТО 56947007-33.040.20.279-2019.json")

CABINETS = OrderedDict([
    ("5.2", {
        "Ключ": "Шкаф защит батареи статических конденсаторов типа ШЭТ 430.01-0 для архитектуры I типа",
        "Шифр": "ШЭТ 430.01-0",
        "Назначение": "Шкаф комплекта защит БСК 110-330 кВ, включающий в себя дифференциальную токовую защиту, дифференциальную токовую защиту нулевой последовательности, небалансную токовую защиту, защиту от перегрузки токами высших гармоник, защиту минимального и максимального напряжения, а также резервные токовые защиты.",
    }),
    ("5.3", {
        "Ключ": "Шкаф защит и автоматики батареи статических конденсаторов типа ШЭТ 431.02-0 для архитектуры I типа",
        "Шифр": "ШЭТ 431.02-0",
        "Назначение": "Шкаф комплекта защит БСК 110-330 кВ, включающий в себя дифференциальную токовую защиту, дифференциальную токовую защиту нулевой последовательности, небалансную токовую защиту, защиту от перегрузки токами высших гармоник, защиту минимального и максимального напряжения, а также резервные токовые защиты; в составе шкафа реализуется УРОВ и АУВ выключателя БСК.",
    }),
    ("5.4", {
        "Ключ": "Шкаф защит шунтирующего реактора типа ШЭТ 430.03-0 для архитектуры I типа",
        "Шифр": "ШЭТ 430.03-0",
        "Назначение": "Шкаф комплекта защит шунтирующего реактора 220-750 кВ, включающий в себя дифференциальную токовую защиту реактора (продольную и поперечную), газовые, технологические и резервные токовые защиты реактора, а также функцию контроля изоляции высоковольтных вводов реактора.",
    }),
    ("5.5", {
        "Ключ": "Шкаф защит шунтирующего реактора типа ШЭТ 430.04-0 для архитектуры I типа",
        "Шифр": "ШЭТ 430.04-0",
        "Назначение": "Шкаф комплекта защит шунтирующего реактора 110-330 кВ, включающий в себя дифференциальную токовую защиту реактора (продольную и поперечную), газовые, технологические и резервные токовые защиты реактора.",
    }),
    ("5.6", {
        "Ключ": "Шкаф защит компенсационной обмотки и ее ошиновки, обмотки управления управляемого шунтирующего реактора с подмагничиванием типа ШЭТ 430.05-0 для архитектуры I типа",
        "Шифр": "ШЭТ 430.05-0",
        "Назначение": "Шкаф комплекта защит компенсационной обмотки, ошиновки НН и обмотки управления УШРП, включающий в себя дифференциальную токовую защиту обмотки КОР и/или ошиновки НН КОР, а также токовые защиты КОР, ОУР.",
    }),
    ("5.7", {
        "Ключ": "Шкаф защит и автоматики компенсационного реактора типа ШЭТ 431.06-0 для архитектуры I типа",
        "Шифр": "ШЭТ 431.06-0",
        "Назначение": "Шкаф комплекта защит компенсационного реактора, включающий в себя дифференциальную токовую защиту, газовые, технологические и резервные защиты, УРОВ и АУВ компенсационного реактора.",
    }),
])

# Сноски 1-3 таблицы 5.1.1 относятся к строкам 3, 4 и 5.
# Ключ - номер строки таблицы, как в сборщиках 280/281-2019.
FOOTNOTES = {
    "3": "Шкаф может также применяться для защиты сетевой обмотки управляемого шунтирующего реактора",
    "4": "Шкаф может также применяться для защиты сетевой обмотки управляемого шунтирующего реактора",
    "5": "Здесь и далее обозначение (НН, КОР) после наименования ДЗО показывает, что данная функция может применяться для защиты ошиновки НН КОР, включая компенсационную обмотку или только для защиты компенсационной обмотки шунтирующего реактора, что определяется конфигурацией аналоговых сигналов тока, подключенных к данной функции.",
}

# Подпись приложения А в PDF обрывается на «I архитектуры»;
# восстанавливаем по заголовку приложения (аналогично 280/281-2019).
TITLE_FIX = {
    "А.1": "Применимость шкафов ШЭТ РЗА оборудования СКРМ 110-750 кВ для I архитектуры построения ПС",
}

VERTICAL_FIX = {
    "Класс": "Класс сообщения",
    "сообщения": "Класс сообщения",
    "Класссообщения": "Класс сообщения",
    "Класс сообщения": "Класс сообщения",
    "Группа сигнал.": "Группа сигнализации",
    "Группа сигнализации": "Группа сигнализации",
    "Пуск": "Пуск",
}

# 5.3.1 - единственная таблица описания с тремя столбцами (ИЭУ1 / ИЭУ2).
DESC_EXTRA_COLUMNS = {"5.3.1": ["Значение (ИЭУ1)", "Значение (ИЭУ2)"]}


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def header_count(num):
    # 5.x.1 - таблица «параметр - значение» без шапки
    if re.match(r"^5\.[2-7]\.1$", num):
        return 0
    # многоуровневые шапки общих таблиц
    if num in ("4.2.2", "4.4.3"):
        return 2
    # шкафы 5.2, 5.4-5.7: сигналы ИЭУ, внешние сигналы,
    # аналоговые значения и ряды зажимов имеют двухуровневую шапку
    if re.match(r"^5\.[24-7]\.(7|8|9|12)$", num):
        return 2
    # шкаф 5.3 (два ИЭУ): 12-17 - сигналы/аналоговые значения, 21 - ряды зажимов
    if re.match(r"^5\.3\.(12|13|14|15|16|17|21)$", num):
        return 2
    return 1


def apply_vertical(frag):
    rows = [list(r) for r in frag["rows"]]
    for key, value in frag.get("vertical", {}).items():
        ri, ci = (int(x) for x in key.split(","))
        if ri < len(rows) and ci < len(rows[ri]):
            rows[ri][ci] = VERTICAL_FIX.get(norm(value), norm(value))
    return rows


def build_columns(header_rows):
    if not header_rows:
        return ["Параметр", "Значение"]
    n = max(len(r) for r in header_rows)
    matrix = [[norm(r[i]) if i < len(r) else "" for i in range(n)] for r in header_rows]
    for ri in range(len(matrix)):
        last = ""
        for ci in range(n):
            if matrix[ri][ci]:
                last = matrix[ri][ci]
            elif last and ri == 0:
                matrix[ri][ci] = last
    names = []
    for ci in range(n):
        parts = [matrix[ri][ci] for ri in range(len(matrix)) if matrix[ri][ci]]
        uniq = []
        for p in parts:
            if p not in uniq:
                uniq.append(p)
        names.append(" / ".join(uniq) if uniq else "Столбец %d" % (ci + 1))
    seen, result = {}, []
    for name in names:
        if name in seen:
            seen[name] += 1
            result.append("%s (%d)" % (name, seen[name]))
        else:
            seen[name] = 1
            result.append(name)
    return result


def row_signature(row):
    return norm(" ".join(row)).lower()


def looks_like_header(row, sigs):
    first = norm(row[0]) if row else ""
    if re.match(r"^\d+(\.\d+)?$", first):
        return False
    if first == "№":
        return True
    s = row_signature(row)
    return any(difflib.SequenceMatcher(None, s, h).ratio() > 0.72 for h in sigs)


def merge_continuations(rows):
    """Строки с пустым номером - продолжение предыдущей строки."""
    out = []
    for row in rows:
        row = list(row)
        if not any(norm(x) for x in row):
            continue
        if out and not norm(row[0]) and any(norm(x) for x in row[1:]):
            for ci, val in enumerate(row):
                val = norm(val)
                if val and ci < len(out[-1]):
                    out[-1][ci] = (out[-1][ci] + " " + val).strip()
            continue
        out.append([norm(x) for x in row])
    return out


def make_table(num, frags):
    title = TITLE_FIX.get(num, norm(frags[0]["caption"]["title"]))
    pages = sorted({f["page"] for f in frags})
    hc = header_count(num)
    all_rows = [apply_vertical(f) for f in frags]
    header_rows = all_rows[0][:hc]
    sigs = [row_signature(r) for r in header_rows]
    data = list(all_rows[0][hc:])
    for rows in all_rows[1:]:
        i = 0
        while i < min(hc, len(rows)) and looks_like_header(rows[i], sigs):
            i += 1
        data.extend(rows[i:])
    # объединять строки-продолжения можно только в нумерованных таблицах
    numbered = bool(header_rows) and norm(header_rows[0][0]) == "№"
    if numbered:
        data = merge_continuations(data)
    if hc == 0 and num in DESC_EXTRA_COLUMNS:
        columns = ["Параметр"] + DESC_EXTRA_COLUMNS[num]
    else:
        columns = build_columns(header_rows)
    ncols = max([len(columns)] + [len(r) for r in data]) if data else len(columns)
    columns = columns + ["Столбец %d" % (i + 1) for i in range(len(columns), ncols)]
    records = []
    for row in data:
        row = (row + [""] * ncols)[:ncols]
        records.append(OrderedDict((columns[i], row[i]) for i in range(ncols)))
    return OrderedDict([
        ("Наименование", title),
        ("Страницы", pages),
        ("Заголовки", [[norm(c) for c in r] for r in header_rows]),
        ("Столбцы", columns),
        ("Количество строк", len(records)),
        ("Строки", records),
    ])


def description_from_table(table):
    """Таблица 5.x.1 вида «параметр - значение».

    Значение может быть многострочным или занимать несколько столбцов
    (5.3.1: ИЭУ1 / ИЭУ2) - в этом случае сохраняется список значений.
    """
    desc = OrderedDict()
    last = None
    for rec in table["Строки"]:
        vals = [norm(v) for v in rec.values()]
        key = vals[0]
        extra = [v for v in vals[1:] if v]
        if not key and last:
            cur = desc[last]
            if not isinstance(cur, list):
                cur = [cur]
            desc[last] = cur + extra
            continue
        if not key:
            continue
        desc[key] = extra[0] if len(extra) == 1 else (extra if extra else "")
        last = key
    return desc


def scope_text(doc):
    text = norm(doc[3].get_text())
    m = re.search(r"1\s+Область применения\s+(.+?)\s+2\s+Нормативные ссылки", text)
    if not m:
        return ""
    return re.sub(r"([А-Яа-яЁё])- ([А-Яа-яЁё])", r"\1-\2", norm(m.group(1)))


def main():
    raw = json.load(open(RAW, encoding="utf-8"))
    groups = OrderedDict()
    current = None
    for frag in raw:
        cap = frag["caption"]
        if cap:
            current = cap["num"]
            groups[current] = [frag]
        else:
            groups[current].append(frag)

    tables = OrderedDict((("Таблица " + num), make_table(num, frags))
                         for num, frags in groups.items())
    doc = pymupdf.open(PDF)

    content = OrderedDict()
    listing = []
    for rec in tables["Таблица 5.1.1"]["Строки"]:
        v = list(rec.values())
        no = norm(v[0])
        listing.append(OrderedDict([
            ("Наименование шкафа", norm(v[1])),
            ("Код ШЭТ", norm(v[2])),
            ("Функции РЗА", norm(v[3])),
            ("Примечание", FOOTNOTES.get(no, norm(v[4]) if len(v) > 4 else "")),
        ]))
    content["Общий перечень шкафов стандарта"] = listing

    cabinet_nums = set()
    for section, info in CABINETS.items():
        own = OrderedDict()
        for num, table in tables.items():
            if num.startswith("Таблица " + section + "."):
                own[num] = table
                cabinet_nums.add(num)
        desc = description_from_table(own["Таблица " + section + ".1"])
        content[info["Ключ"]] = OrderedDict([
            ("Раздел стандарта", section),
            ("Шифр шкафа", info["Шифр"]),
            ("Назначение шкафа", info["Назначение"]),
            ("Описание шкафа", desc),
            ("Таблицы", own),
        ])

    common = OrderedDict((n, t) for n, t in tables.items()
                         if n not in cabinet_nums and not n.startswith("Таблица А."))
    appendix = OrderedDict((n, t) for n, t in tables.items() if n.startswith("Таблица А."))
    content["Прочие таблицы стандарта (разделы 4 и 5.1)"] = common
    content["Приложение А"] = appendix

    result = OrderedDict([
        ("Обозначение стандарта", "Типовые шкафы ШЭТ РЗА шунтирующих реакторов, компенсационных реакторов и батарей статических конденсаторов 110-750 кВ. Архитектура I типа"),
        ("Шифр стандарта", "СТО 56947007-33.040.20.279-2019"),
        ("Дата введения", "26.12.2019"),
        ("Принадлежность стандарта", "ПАО «ФСК ЕЭС»"),
        ("Область применения стандарта", scope_text(doc)),
        ("Содержимое стандарта", content),
    ])

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("tables:", len(tables), "cabinet tables:", len(cabinet_nums),
          "common:", len(common), "appendix:", len(appendix))
    for section in CABINETS:
        t = content[CABINETS[section]["Ключ"]]["Таблицы"]
        print(section, "tables:", len(t), "rows total:", sum(x["Количество строк"] for x in t.values()))
    print("scope:", result["Область применения стандарта"][:100])


if __name__ == "__main__":
    main()
