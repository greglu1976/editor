#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Редактирование таблиц стандарта EA.

Таблица в документе — только форма: строки шкафа собираются из ``cabinets``
(см. :func:`ea_standard.table_view`). Этот модуль даёт обратимое
представление: ``load()`` отдаёт шапку и строки для редактора, ``save()``
раскладывает изменённые строки обратно в JSON стандарта.

Для таблиц шкафов в редактор добавляются служебные колонки контекста:

* «Набор данных» — к какому набору относится сигнал (GOOSE/отчёты);
* «Функция» — группа параметров функции;
* «Ряд», «Расположение» — место клемм в ряду зажимов.

Таблица «Описание ШЭТ» не редактируется: её значения собираются из карточки
шкафа и ссылок на таблицы/рисунки.
"""

from __future__ import annotations

import ea_standard as es


class TableEditError(Exception):
    """Ошибка разбора или записи таблицы."""


#: Плоские списки: вид → (где лежит, поля, числовые поля, значения по умолчанию).
_FLAT = {
    "analog_inputs": (
        "ied",
        ("circuit_type", "test_block", "contacts_count", "note"),
        (),
        {},
    ),
    "inner_discrete_circuits": (
        "ied",
        ("discrete_signal", "direction", "note"),
        (),
        {},
    ),
    "incoming_goose_signals": (
        "ied",
        ("signal", "info_model", "source", "max_number", "RAS"),
        ("max_number",),
        {"source_number": None, "note": ""},
    ),
    "functional_buttons": (
        "ied",
        ("mapping", "short_name", "disable_condition", "enable_condition"),
        (),
        {},
    ),
    "leds": (
        "ied",
        ("mapping", "name", "mode"),
        (),
        {"note": ""},
    ),
    "datasets": (
        "ied",
        ("mapping", "sender", "id", "name", "class", "note"),
        (),
        {"signals": []},
    ),
    "osc_analog_signals": (
        "ied",
        ("description", "canal", "name", "startRAS"),
        ("canal",),
        {},
    ),
    "control_commands": (
        "ied",
        ("name", "info_model"),
        (),
        {},
    ),
    "components": (
        "cabinet",
        ("name", "description", "quantity"),
        (),
        {},
    ),
}

_GOOSE_FIELDS = ("name", "info_model", "destination")
_REPORT_FIELDS = ("name", "status", "KT", "cus", "rdu", "RAS", "DO", "DA")

#: Подписи колонок совпадают с полями строк, а не с формой таблицы:
#: в форме может быть лишняя колонка «Примечание», которой нет в данных.
_FLAT_HEADERS = {
    "analog_inputs": ("Аналоговая цепь", "Испытательный блок",
                      "Количество контактов", "Примечание"),
    "inner_discrete_circuits": ("Дискретный сигнал", "Направление",
                                "Примечание"),
    "incoming_goose_signals": ("Наименование сигнала", "Отображение в ИМ",
                               "Источник", "Макс. количество", "РАС"),
    "functional_buttons": ("Назначение ФК", "Краткое наименование",
                           "Состояние «0»", "Состояние «1»"),
    "leds": ("Назначение", "Обозначение", "Режим"),
    "datasets": ("Назначение", "Отправитель", "Идентификатор",
                 "Набор данных", "Класс", "Примечание"),
    "osc_analog_signals": ("Описание", "Канал", "Наименование", "Пуск РАС"),
    "control_commands": ("Наименование", "Отображение в ИМ"),
    "components": ("Наименование", "Характеристика", "Количество"),
}

_GOOSE_HEADERS = ("Набор данных", "Наименование сигнала",
                  "Отображение в ИМ", "Приемник")
_REPORT_HEADERS = ("Набор данных", "Наименование", "Статус", "КТ", "ЦУС",
                   "РДУ", "РАС", "DO", "DA")

_SIGNAL_DEFAULTS = {
    "name": "",
    "info_model": "",
    "destination": "",
    "note": "",
    "status": "",
    "KT": "",
    "cus": "",
    "rdu": "",
    "RAS": "",
    "DO": "",
    "DA": "",
}


def _ied(cabinet):
    kits = cabinet.get("kits") or []
    ieds = (kits[0].get("ieds") or []) if kits else []
    return ieds[0] if ieds else {}


def _cabinet(data, table):
    code = table.get("cabinet")
    cabinet = es.cabinet(data, code) if code else None
    if cabinet is None:
        raise TableEditError("шкаф %s не найден" % (code or "—"))
    return cabinet


def _convert(value, numeric):
    text = str(value or "").strip()
    if numeric:
        return int(text) if text.isdigit() else None
    return text


def _blank(row):
    """Строка целиком пустая — её не записываем."""
    return not any(str(value or "").strip() for value in row)


def _document_headers(table):
    rows = table.get("rows") or []
    count = 0
    if rows and rows[0].get("is_header_first_row"):
        count = 1
    if len(rows) > 1 and rows[1].get("is_header_second_row"):
        count = 2
    return count


def _load_document(table):
    headers, rows = es.table_view(None, table)
    return headers, rows, ""


def _save_document(table, rows):
    count = _document_headers(table)
    form = list((table.get("rows") or [])[:count])
    form.extend({
        "content": list(row),
        "is_header_first_row": False,
        "is_header_second_row": False,
    } for row in rows)
    table["rows"] = form


def _load_flat(data, table, kind):
    _cabinet(data, table)
    headers = list(_FLAT_HEADERS[kind])
    source = es.table_view(data, table)[1]
    rows = [[row[index] if index < len(row) else ""
             for index in range(len(headers))] for row in source]
    return headers, rows, ""


def _save_flat(data, table, kind, rows):
    cabinet = _cabinet(data, table)
    scope, fields, numeric, defaults = _FLAT[kind]
    items = _ied(cabinet) if scope == "ied" else cabinet
    key = "components" if scope == "cabinet" else None
    current = list(items.get(key) or []) if key else list(
        items.get(kind) or [])
    result = []
    source = 0
    for row in rows:
        if _blank(row):
            continue
        item = dict(current[source]) if source < len(current) else dict(defaults)
        source += 1
        for field, value in zip(fields, row):
            item[field] = _convert(value, field in numeric)
        for field, value in defaults.items():
            item.setdefault(field, value)
        result.append(item)
    if key:
        cabinet[key] = result
    else:
        items[kind] = result


def _load_signals(data, table, kind):
    cabinet = _cabinet(data, table)
    ied = _ied(cabinet)
    fields = _GOOSE_FIELDS if kind == "goose_signals" else _REPORT_FIELDS
    headers = list(_GOOSE_HEADERS if kind == "goose_signals"
                   else _REPORT_HEADERS)
    rows = []
    for dataset in ied.get("datasets") or []:
        if kind == "goose_signals" and dataset.get("class") == "-":
            continue
        if kind == "report_signals" and dataset.get("class") != "-":
            continue
        for signal in dataset.get("signals") or []:
            rows.append([dataset.get("name", "")]
                        + [signal.get(field, "") for field in fields])
    return headers, rows, ""


def _save_signals(data, table, kind, rows):
    cabinet = _cabinet(data, table)
    ied = _ied(cabinet)
    fields = _GOOSE_FIELDS if kind == "goose_signals" else _REPORT_FIELDS
    grouped = {}
    for row in rows:
        if _blank(row):
            continue
        name = str(row[0] if row else "").strip()
        grouped.setdefault(name, []).append(row[1:])
    known = {dataset.get("name") for dataset in ied.get("datasets") or []}
    unknown = sorted(name for name in grouped if name not in known)
    if unknown:
        raise TableEditError("неизвестный набор данных: %s"
                             % ", ".join(name or "(не указан)"
                                         for name in unknown))
    for dataset in ied.get("datasets") or []:
        if kind == "goose_signals" and dataset.get("class") == "-":
            continue
        if kind == "report_signals" and dataset.get("class") != "-":
            continue
        old = list(dataset.get("signals") or [])
        new = []
        for index, cells in enumerate(grouped.get(dataset.get("name"), [])):
            signal = dict(old[index]) if index < len(old) else dict(_SIGNAL_DEFAULTS)
            for field, value in zip(fields, cells):
                signal[field] = str(value or "").strip()
            new.append(signal)
        dataset["signals"] = new


def _function_label(function):
    path = str(function.get("russian_path") or "")
    name = str(function.get("name") or "")
    if path and path != name:
        return "%s / %s" % (path, name)
    return name


def _load_functions(data, table):
    cabinet = _cabinet(data, table)
    ied = _ied(cabinet)
    headers = ["Функция", "Параметр", "Описание", "Состояния"]
    rows = []
    for function in ied.get("functions") or []:
        rows.append([_function_label(function), "", "", ""])
        for parameter in function.get("parameters") or []:
            rows.append(["", parameter.get("name", ""),
                         parameter.get("description", ""),
                         parameter.get("conditions", "")])
    return headers, rows, ""


def _save_functions(data, table, rows):
    cabinet = _cabinet(data, table)
    ied = _ied(cabinet)
    # подпись функции не всегда однозначна («НВЧЗ» — и путь, и имя),
    # поэтому исходные функции раздаём по подписям по очереди
    pending = {}
    for function in ied.get("functions") or []:
        pending.setdefault(_function_label(function), []).append(function)
    result = []
    current = None
    while rows and _blank(rows[-1]):
        rows = rows[:-1]
    for row in rows:
        cells = [str(value or "").strip() for value in row[:4]]
        cells += [""] * (4 - len(cells))
        label, name, description, conditions = cells
        if not label and not name and not description and not conditions:
            # пустая строка внутри функции — пустой параметр: в исходных
            # данных такие строки встречаются, терять их нельзя
            if current is None:
                continue
            current["parameters"].append(
                {"name": "", "description": "", "conditions": ""})
            continue
        if not name and not description and not conditions:
            queue = pending.get(label)
            previous = queue.pop(0) if queue else {}
            if previous:
                path = str(previous.get("russian_path") or "")
                func = str(previous.get("name") or "")
            elif " / " in label:
                path, func = label.split(" / ", 1)
            else:
                path, func = "", label
            current = {
                "name": func,
                "russian_path": path,
                "isMainFunction": bool(previous.get("isMainFunction")),
                "isInITS": bool(previous.get("isInITS")),
                "iec_name": previous.get("iec_name", ""),
                "parameters": [],
            }
            result.append(current)
            continue
        if current is None:
            raise TableEditError("параметр «%s» без функции" % name)
        current["parameters"].append({
            "name": name,
            "description": description,
            "conditions": conditions,
        })
    ied["functions"] = result


def _load_terminals(data, table):
    cabinet = _cabinet(data, table)
    headers = ["Ряд", "Расположение", "Номера клемм", "Количество",
               "Тип (функц.)", "Тип (подкл.)", "Назначение"]
    rows = []
    for block in cabinet.get("terminal_blocks") or []:
        text = str(block.get("text") or "")
        for row in block.get("rows") or []:
            location = str(row.get("location") or "")
            if location:
                rows.append([text, location, "", "", "", "", ""])
            for terminal in row.get("terminals") or []:
                rows.append([
                    text, location,
                    terminal.get("number", ""),
                    terminal.get("quantity", ""),
                    terminal.get("function_type", ""),
                    terminal.get("connection_type", ""),
                    terminal.get("purpose", ""),
                ])
    return headers, rows, ""


def _save_terminals(data, table, rows):
    cabinet = _cabinet(data, table)
    blocks, index = [], {}
    for row in rows:
        cells = [str(value or "").strip() for value in row[:7]]
        cells += [""] * (7 - len(cells))
        text, location, number, quantity, ftype, ctype, purpose = cells
        if not text and not location and not number:
            continue
        entry = index.get(text)
        if entry is None:
            entry = {"text": text, "rows": []}
            index[text] = entry
            blocks.append(entry)
        # место в ряду — отдельная группа; одинаковые подписи не склеиваем,
        # иначе порядок клемм в документе меняется
        groups = entry["rows"]
        if not groups or groups[-1]["location"] != location:
            groups.append({"location": location, "terminals": []})
        if number or quantity or ftype or ctype or purpose:
            groups[-1]["terminals"].append({
                "number": number,
                "quantity": int(quantity) if quantity.isdigit() else None,
                "function_type": ftype,
                "connection_type": ctype,
                "purpose": purpose,
            })
    cabinet["terminal_blocks"] = blocks


def load(data, table):
    """``(шапка, строки, примечание)`` для редактора таблицы."""
    code = table.get("cabinet")
    kind = es.table_kind(table.get("name"))
    if not code:
        return _load_document(table)
    if kind == "description":
        headers, rows = es.table_view(data, table)
        return headers, rows, ("Описание шкафа собирается из карточки шкафа; "
                               "здесь не редактируется.")
    if kind in _FLAT:
        return _load_flat(data, table, kind)
    if kind in ("goose_signals", "report_signals"):
        return _load_signals(data, table, kind)
    if kind == "functions":
        return _load_functions(data, table)
    if kind == "terminal_blocks":
        return _load_terminals(data, table)
    raise TableEditError("вид таблицы не редактируется: %s"
                         % (table.get("name") or "—"))


def save(data, table, rows):
    """Записать строки редактора обратно в стандарт."""
    code = table.get("cabinet")
    kind = es.table_kind(table.get("name"))
    if not code:
        _save_document(table, rows)
        return
    if kind == "description":
        raise TableEditError("описание шкафа здесь не редактируется")
    if kind in _FLAT:
        _save_flat(data, table, kind, rows)
        return
    if kind in ("goose_signals", "report_signals"):
        _save_signals(data, table, kind, rows)
        return
    if kind == "functions":
        _save_functions(data, table, rows)
        return
    if kind == "terminal_blocks":
        _save_terminals(data, table, rows)
        return
    raise TableEditError("вид таблицы не редактируется: %s"
                         % (table.get("name") or "—"))
