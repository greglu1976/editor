#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Стандарты СТО в структуре EA (JSON по модели ``EA/structure.eapx``).

Новый формат стандарта: дерево документа (``sections``) хранит только форму
таблиц, а данные — в ``cabinets``. Таблица шкафа ссылается на шкаф полем
``cabinet``, поэтому строки для показа собираются здесь, в
:func:`table_view`, а не дублируются в JSON.

Модуль ничего не импортирует из старой интеграции стандартов
(``standards_base``, ``standards_editor``, ``standards_ui``,
``standard_editor``) — это новая ветка, которую можно развивать и позже
оставить единственной.

    python ea_standard.py --list
    python ea_standard.py --stats
    python ea_standard.py --check
    python ea_standard.py --table 5.7
    python ea_standard.py --cabinet 431.11-1
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import apppaths

#: Папка со стандартами: ``db/EA`` в сборке, ``EA`` рядом с исходниками.
FOLDER = apppaths.data_dir("EA")

#: Фрагменты названий таблиц шкафа -> вид данных в Cabinet (порядок важен).
KINDS = (
    ("описание шэт", "description"),
    ("входные аналоговые измерения", "analog_inputs"),
    ("внутренние дискретные цепи", "inner_discrete_circuits"),
    ("входящих сообщений", "incoming_goose_signals"),
    ("функциональные клавиши", "functional_buttons"),
    ("светодиодная сигнализация", "leds"),
    ("сообщения и отчеты", "datasets"),
    ("исходящих сообщений", "goose_signals"),
    ("исходящих отчетов", "report_signals"),
    ("осциллографируемые", "osc_analog_signals"),
    ("команды управления", "control_commands"),
    ("основные параметры функций", "functions"),
    ("ряды зажимов", "terminal_blocks"),
    ("основные компоненты", "components"),
)

#: Таблицы с двухъярусной шапкой.
TWO_ROW_HEADERS = ("ряды зажимов", "исходящих отчетов")

_DESCRIPTION_FIELDS = (
    ("шифр шкафа", "cypher"),
    ("архитектура", "architecture"),
    ("наименование шкафа", "name"),
    ("управляемый элемент", "controllable_element"),
    ("защищаемый элемент", "protected_element"),
    ("область применения", "scope"),
)


# ---------------------------------------------------------------------------
# Файлы и загрузка
# ---------------------------------------------------------------------------
def folder():
    """Папка со стандартами EA."""
    return FOLDER


def files():
    """Список JSON стандартов в папке (по имени файла)."""
    return sorted(glob.glob(os.path.join(FOLDER, "*.json")))


def available():
    """Стандарты EA на месте."""
    return bool(files())


def default_base():
    """Первый стандарт папки или None."""
    found = files()
    return found[0] if found else None


def load(path=None):
    """Прочитать стандарт (dict)."""
    path = path or default_base()
    if not path:
        raise FileNotFoundError("в папке нет JSON стандартов: %s" % FOLDER)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save(data, path):
    """Записать стандарт, вернуть размер файла."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return os.path.getsize(path)


# ---------------------------------------------------------------------------
# Обход дерева
# ---------------------------------------------------------------------------
def sections(data):
    return data.get("sections") or []


def cabinets(data):
    return data.get("cabinets") or []


def cabinet(data, code):
    """Шкаф по шифру (``cypher``) или None."""
    for item in cabinets(data):
        if item.get("cypher") == code:
            return item
    return None


def iter_clauses(data):
    """Все пункты документа (в разделах и подразделах)."""
    for section in sections(data):
        for clause in section.get("clauses") or []:
            yield clause
        for sub in section.get("subsections") or []:
            for clause in sub.get("clauses") or []:
                yield clause


def iter_tables(data):
    """Все таблицы документа в порядке следования."""
    for section in sections(data):
        for table in section.get("tables") or []:
            yield table
        for clause in section.get("clauses") or []:
            for table in clause.get("tables") or []:
                yield table
        for sub in section.get("subsections") or []:
            for table in sub.get("tables") or []:
                yield table
            for clause in sub.get("clauses") or []:
                for table in clause.get("tables") or []:
                    yield table


def iter_figures(data):
    for section in sections(data):
        for figure in section.get("figures") or []:
            yield figure
        for sub in section.get("subsections") or []:
            for figure in sub.get("figures") or []:
                yield figure


def table_kind(name):
    """Вид данных таблицы шкафа или None для таблиц документа."""
    low = (name or "").lower()
    for needle, kind in KINDS:
        if needle in low:
            return kind
    return None


# ---------------------------------------------------------------------------
# Карточки и статистика
# ---------------------------------------------------------------------------
def info(path):
    """Короткая карточка стандарта для списка."""
    data = load(path)
    return {
        "имя": os.path.basename(path),
        "путь": path,
        "шифр": data.get("code", ""),
        "разделы": len(sections(data)),
        "таблицы": len(list(iter_tables(data))),
        "шкафы": len(cabinets(data)),
        "размер": os.path.getsize(path),
    }


def standards():
    """Карточки всех стандартов папки."""
    return [info(path) for path in files()]


def stats(data):
    """Счётчики по стандарту."""
    tables = list(iter_tables(data))
    forms = [t for t in tables if t.get("cabinet")]
    return {
        "разделы": len(sections(data)),
        "таблицы": len(tables),
        "формы": len(forms),
        "таблицы_документа": len(tables) - len(forms),
        "шкафы": len(cabinets(data)),
        "строк_в_шкафах": sum(_cabinet_row_count(c) for c in cabinets(data)),
    }


def _ied(cabinet_item):
    kits = cabinet_item.get("kits") or []
    if not kits:
        return {}
    ieds = kits[0].get("ieds") or []
    return ieds[0] if ieds else {}


def _text(value):
    if value is None:
        return ""
    return str(value)


def _function_names(functions, flag):
    names = []
    for item in functions:
        if not item.get(flag):
            continue
        name = item.get("russian_path") or item.get("name") or ""
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def _cabinet_row_count(cabinet_item):
    """Сколько строк данных в шкафе (для статистики)."""
    ied = _ied(cabinet_item)
    total = len(cabinet_item.get("components") or [])
    total += len(cabinet_item.get("power_supplies") or [])
    total += len(ied.get("ports") or [])
    for key in ("analog_inputs", "inner_discrete_circuits",
                "incoming_goose_signals", "functional_buttons", "leds",
                "osc_analog_signals", "control_commands", "functions"):
        total += len(ied.get(key) or [])
    for dataset in ied.get("datasets") or []:
        total += 1 + len(dataset.get("signals") or [])
    for block in cabinet_item.get("terminal_blocks") or []:
        total += len(block.get("rows") or [])
        for row in block.get("rows") or []:
            total += len(row.get("terminals") or [])
    return total


def cabinet_card(cabinet_item):
    """Параметры шкафа для карточки (список [подпись, значение])."""
    ied = _ied(cabinet_item)
    functions = ied.get("functions") or []
    terminals = sum(len(row.get("terminals") or [])
                    for block in cabinet_item.get("terminal_blocks") or []
                    for row in block.get("rows") or [])
    return [
        ["Шифр шкафа", cabinet_item.get("cypher", "")],
        ["Архитектура", cabinet_item.get("architecture", "")],
        ["Наименование", cabinet_item.get("name", "")],
        ["Управляемый элемент", cabinet_item.get("controllable_element", "")],
        ["Защищаемый элемент", cabinet_item.get("protected_element", "")],
        ["Область применения", cabinet_item.get("scope", "")],
        ["Тип", cabinet_item.get("type", "")],
        ["Комплектов", str(len(cabinet_item.get("kits") or []))],
        ["Питание", "; ".join(p.get("purpose", "")
                              for p in cabinet_item.get("power_supplies") or [])],
        ["Цифровые порты", "; ".join(p.get("description", "")
                                     for p in ied.get("ports") or [])],
        ["Компонентов", str(len(cabinet_item.get("components") or []))],
        ["Клемм", str(terminals)],
        ["Наборов данных", str(len(ied.get("datasets") or []))],
        ["Сигналов в наборах", str(sum(len(d.get("signals") or [])
                                       for d in ied.get("datasets") or []))],
        ["Функций", str(len(functions))],
        ["Описание", (cabinet_item.get("description") or "").strip()],
    ]


# ---------------------------------------------------------------------------
# Таблицы: форма из документа, строки из шкафа
# ---------------------------------------------------------------------------
def _stored_view(table):
    """Таблица документа: шапка и строки как есть в JSON."""
    rows = [row.get("content") or [] for row in table.get("rows") or []]
    if not rows:
        return [], []
    if len(rows) >= 2 and (table["rows"][1].get("is_header_second_row")):
        headers = _merge_headers(rows[:2])
        return headers, rows[2:]
    return rows[0], rows[1:]


def _merge_headers(rows):
    """Склеить одно- и двухъярусную шапку в список подписей колонок."""
    width = max(len(row) for row in rows)
    headers = []
    for index in range(width):
        parts = []
        for row in rows:
            cell = (row[index] if index < len(row) else "").strip()
            if cell and cell not in parts:
                parts.append(cell)
        headers.append(" / ".join(parts))
    return headers


def _form_headers(table):
    """Подписи колонок по форме таблицы."""
    if "описание шэт" in (table.get("name") or "").lower():
        return ["Параметр", "Значение"]
    form = table.get("rows") or []
    if not form:
        return []
    return _merge_headers([row.get("content") or [] for row in form])


def _local_figures(data, cabinet_item):
    """Рисунки подраздела, в котором лежит описание шкафа."""
    code = cabinet_item.get("cypher")
    for section in sections(data):
        for sub in section.get("subsections") or []:
            for table in sub.get("tables") or []:
                if table.get("cabinet") == code and table_kind(table.get("name")) == "description":
                    return sub.get("figures") or []
    return []


def _table_refs(data, cabinet_item):
    """Ссылки на таблицы этого шкафа: название -> «Таблица N»."""
    refs = {}
    for table in iter_tables(data):
        if table.get("cabinet") != cabinet_item.get("cypher"):
            continue
        name = (table.get("name") or "").lower()
        if name:
            refs[name] = table.get("reference") or ""
    return refs


def _figure_refs(data, cabinet_item):
    refs = {}
    for figure in _local_figures(data, cabinet_item):
        name = (figure.get("name") or "").lower()
        if name.startswith("поясняющ"):
            refs.setdefault("поясняющ", figure.get("reference") or "")
        elif name.startswith("эскиз"):
            refs.setdefault("эскиз", figure.get("reference") or "")
    return refs


def _description_value(key, cabinet_item, refs, figures):
    low = (key or "").lower()
    for needle, field in _DESCRIPTION_FIELDS:
        if low.startswith(needle):
            return _text(cabinet_item.get(field))
    ied = _ied(cabinet_item)
    if low.startswith("основные функции"):
        return _function_names(ied.get("functions") or [], "isMainFunction")
    if low.startswith("функции итс"):
        return _function_names(ied.get("functions") or [], "isInITS")
    if low.startswith("вводы питания"):
        return "; ".join(p.get("purpose", "")
                         for p in cabinet_item.get("power_supplies") or [])
    if low.startswith("цифровые порты"):
        return "; ".join(p.get("description", "") for p in ied.get("ports") or [])
    for needle, reference in figures.items():
        if low.startswith(needle):
            return reference
    best, reference = 0, ""
    for name, ref in refs.items():
        if low and (name.startswith(low) or low.startswith(name)):
            size = min(len(name), len(low))
            if size > best:
                best, reference = size, ref
    return reference


def _rows_description(data, cabinet_item, table):
    refs = _table_refs(data, cabinet_item)
    figures = _figure_refs(data, cabinet_item)
    rows = []
    for row in table.get("rows") or []:
        cells = row.get("content") or []
        key = cells[0] if cells else ""
        rows.append([key, _description_value(key, cabinet_item, refs, figures)])
    return rows


def _rows_analog(ied):
    return [[_text(a.get("circuit_type")), _text(a.get("test_block")),
             _text(a.get("contacts_count")), _text(a.get("note"))]
            for a in ied.get("analog_inputs") or []]


def _rows_discrete(ied):
    return [[_text(d.get("discrete_signal")), _text(d.get("direction")),
             _text(d.get("note"))]
            for d in ied.get("inner_discrete_circuits") or []]


def _rows_incoming(ied):
    return [[_text(s.get("signal")), _text(s.get("info_model")),
             _text(s.get("source")), _text(s.get("max_number")),
             _text(s.get("RAS"))]
            for s in ied.get("incoming_goose_signals") or []]


def _rows_buttons(ied):
    return [[_text(b.get("mapping")), _text(b.get("short_name")),
             _text(b.get("disable_condition")), _text(b.get("enable_condition"))]
            for b in ied.get("functional_buttons") or []]


def _rows_leds(ied):
    return [[_text(led.get("mapping")), _text(led.get("name")),
             _text(led.get("mode"))]
            for led in ied.get("leds") or []]


def _rows_datasets(ied):
    return [[_text(d.get("mapping")), _text(d.get("sender")), _text(d.get("id")),
             _text(d.get("name")), _text(d.get("class")), _text(d.get("note"))]
            for d in ied.get("datasets") or []]


def _rows_goose(ied):
    rows = []
    for dataset in ied.get("datasets") or []:
        if dataset.get("class") == "-":
            continue
        for signal in dataset.get("signals") or []:
            rows.append([_text(signal.get("name")), _text(signal.get("info_model")),
                         _text(signal.get("destination"))])
    return rows


def _rows_reports(ied):
    rows = []
    for dataset in ied.get("datasets") or []:
        if dataset.get("class") != "-":
            continue
        for signal in dataset.get("signals") or []:
            rows.append([_text(signal.get("name")), _text(signal.get("status")),
                         _text(signal.get("KT")), _text(signal.get("cus")),
                         _text(signal.get("rdu")), _text(signal.get("RAS")),
                         _text(signal.get("DO")), _text(signal.get("DA"))])
    return rows


def _rows_osc(ied):
    return [[_text(s.get("description")), _text(s.get("canal")),
             _text(s.get("name")), _text(s.get("startRAS"))]
            for s in ied.get("osc_analog_signals") or []]


def _rows_commands(ied):
    return [[_text(c.get("name")), _text(c.get("info_model"))]
            for c in ied.get("control_commands") or []]


def _rows_functions(ied):
    rows, group = [], None
    for function in ied.get("functions") or []:
        path = _text(function.get("russian_path"))
        name = _text(function.get("name"))
        current = (path, name)
        if current != group:
            group = current
            label = name if not path or path == name else "%s / %s" % (path, name)
            rows.append([label, "", ""])
        for parameter in function.get("parameters") or []:
            rows.append([_text(parameter.get("name")),
                         _text(parameter.get("description")),
                         _text(parameter.get("conditions"))])
    return rows


def _rows_terminals(cabinet_item):
    rows = []
    for block in cabinet_item.get("terminal_blocks") or []:
        for row in block.get("rows") or []:
            location = _text(row.get("location"))
            if location:
                rows.append([location, "", "", "", ""])
            for terminal in row.get("terminals") or []:
                rows.append([_text(terminal.get("number")),
                             _text(terminal.get("quantity")),
                             _text(terminal.get("function_type")),
                             _text(terminal.get("connection_type")),
                             _text(terminal.get("purpose"))])
    return rows


def _rows_components(cabinet_item):
    return [[_text(c.get("name")), _text(c.get("description")),
             _text(c.get("quantity"))]
            for c in cabinet_item.get("components") or []]


def _cabinet_rows_for(kind, cabinet_item):
    ied = _ied(cabinet_item)
    builders = {
        "analog_inputs": lambda: _rows_analog(ied),
        "inner_discrete_circuits": lambda: _rows_discrete(ied),
        "incoming_goose_signals": lambda: _rows_incoming(ied),
        "functional_buttons": lambda: _rows_buttons(ied),
        "leds": lambda: _rows_leds(ied),
        "datasets": lambda: _rows_datasets(ied),
        "goose_signals": lambda: _rows_goose(ied),
        "report_signals": lambda: _rows_reports(ied),
        "osc_analog_signals": lambda: _rows_osc(ied),
        "control_commands": lambda: _rows_commands(ied),
        "functions": lambda: _rows_functions(ied),
        "terminal_blocks": lambda: _rows_terminals(cabinet_item),
        "components": lambda: _rows_components(cabinet_item),
    }
    builder = builders.get(kind)
    return builder() if builder else []


def table_view(data, table):
    """``(шапка, строки)`` таблицы: форма из документа, данные из шкафа."""
    code = table.get("cabinet")
    cabinet_item = cabinet(data, code) if code else None
    kind = table_kind(table.get("name"))
    if not code:
        return _stored_view(table)
    headers = _form_headers(table)
    if cabinet_item is None:
        return headers, []
    if kind == "description":
        return headers, _rows_description(data, cabinet_item, table)
    return headers, _cabinet_rows_for(kind, cabinet_item)


def table_by_number(data, number):
    """Таблица по номеру (``5.7``) или None."""
    for table in iter_tables(data):
        if table.get("number") == number:
            return table
    return None


# ---------------------------------------------------------------------------
# Проверка
# ---------------------------------------------------------------------------
def validate(data):
    """Список проблем структуры (пусто — всё сходится)."""
    problems = []
    known = {c.get("cypher") for c in cabinets(data)}
    for table in iter_tables(data):
        code = table.get("cabinet")
        number = table.get("number") or "(без номера)"
        if not code:
            continue
        if code not in known:
            problems.append("таблица %s: шкаф %s не найден" % (number, code))
            continue
        kind = table_kind(table.get("name"))
        if kind is None:
            problems.append("таблица %s: неизвестный вид данных" % number)
        if not table.get("rows"):
            problems.append("таблица %s: нет формы" % number)
    for cabinet_item in cabinets(data):
        code = cabinet_item.get("cypher") or "(без шифра)"
        ied = _ied(cabinet_item)
        for dataset in ied.get("datasets") or []:
            for signal in dataset.get("signals") or []:
                missing = {"name", "info_model", "destination", "status",
                           "KT", "cus", "rdu", "RAS", "DO", "DA", "note"} - set(signal)
                if missing:
                    problems.append("шкаф %s, набор %s: у сигнала нет %s"
                                    % (code, dataset.get("name"),
                                       ", ".join(sorted(missing))))
                    break
    return problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_table(headers, rows, limit=0):
    if not headers:
        print("(пустая таблица)")
        return
    shown = rows[:limit] if limit else rows
    data = [headers] + [list(map(_text, row)) for row in shown]
    widths = [max(len(str(row[i])) if i < len(row) else 0 for row in data)
              for i in range(len(headers))]
    for index, row in enumerate(data):
        cells = [(str(row[i]) if i < len(row) else "").ljust(widths[i])
                 for i in range(len(headers))]
        print(" | ".join(cells).rstrip())
        if index == 0:
            print("-+-".join("-" * width for width in widths))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Стандарты СТО в структуре EA")
    parser.add_argument("file", nargs="?", help="JSON стандарта (по умолчанию первый)")
    parser.add_argument("--list", action="store_true", help="список стандартов")
    parser.add_argument("--stats", action="store_true", help="счётчики стандарта")
    parser.add_argument("--check", action="store_true", help="проверить структуру")
    parser.add_argument("--table", help="показать таблицу по номеру")
    parser.add_argument("--cabinet", help="показать карточку шкафа")
    parser.add_argument("--limit", type=int, default=0, help="строк в таблице (0 — все)")
    args = parser.parse_args(argv)

    if args.list:
        for item in standards():
            print("%-46s %-28s шкафов %d, таблиц %d"
                  % (item["имя"], item["шифр"], item["шкафы"], item["таблицы"]))
        return 0

    path = args.file or default_base()
    if not path:
        print("в папке нет JSON стандартов: %s" % FOLDER, file=sys.stderr)
        return 2
    data = load(path)

    if args.stats:
        for key, value in stats(data).items():
            print("%-20s %s" % (key, value))
        return 0

    if args.check:
        problems = validate(data)
        for problem in problems:
            print("! %s" % problem)
        print("проблем: %d" % len(problems))
        return 1 if problems else 0

    if args.cabinet:
        item = cabinet(data, args.cabinet)
        if item is None:
            print("шкаф не найден: %s" % args.cabinet, file=sys.stderr)
            return 2
        _print_table(["Параметр", "Значение"], cabinet_card(item))
        return 0

    if args.table:
        table = table_by_number(data, args.table)
        if table is None:
            print("таблица не найдена: %s" % args.table, file=sys.stderr)
            return 2
        print("%s %s" % (table.get("reference", ""), table.get("name", "")))
        headers, rows = table_view(data, table)
        _print_table(headers, rows, args.limit)
        print("строк: %d" % len(rows))
        return 0

    print("%s\nшкафов: %d, таблиц: %d"
          % (data.get("name", ""), len(cabinets(data)), len(list(iter_tables(data)))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
