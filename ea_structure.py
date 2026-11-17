#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Структурные операции над стандартом EA.

Фабрики новых узлов и операции добавления/удаления не зависят от Tk: окно
редактора (:mod:`ea_editor`) вызывает их, а тесты — напрямую. Данные шкафов
и таблиц остаются в том же формате, что и в ``EA/*.json``.
"""

from __future__ import annotations

import re

import ea_edit as ee
import ea_standard as es


class StructureError(Exception):
    """Невозможно добавить или удалить узел."""


_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")

#: Какой ключ контейнера соответствует каждому виду потомков.
_CHILD_KEY = {
    "subsection": "subsections",
    "clause": "clauses",
    "table": "tables",
    "figure": "figures",
    "kit": "kits",
    "ied": "ieds",
}

#: Ключи, в которых лежат потомки узла (для подсчёта при удалении).
_DESCENDANT_KEYS = ("subsections", "clauses", "subclauses", "tables",
                    "figures", "kits", "ieds")

_DEFAULT_SECTION_STYLE = "ДОК Заголовок вкл в содержание"
_DEFAULT_SUBSECTION_STYLE = "ДОК Текст 3уров 2-пункт"

_TERMINAL_HEADERS = ("Ряд", "Расположение", "Номера клемм", "Количество",
                     "Тип (функц.)", "Тип (подкл.)", "Назначение")
_FUNCTION_HEADERS = ("Функция", "Параметр", "Описание", "Состояния")

_IED_LISTS = ("analog_inputs", "osc_analog_signals", "incoming_goose_signals",
              "inner_discrete_circuits", "datasets", "ports",
              "functional_buttons", "leds", "control_commands", "functions")


# ---------------------------------------------------------------------------
# Номера и подписи
# ---------------------------------------------------------------------------
def next_number(items, base=""):
    """Следующий номер в контейнере: ``int`` для числовых, строка иначе.

    ``base`` — префикс строкового номера (``"4."``, ``"Б"``). Числовая часть
    берётся как максимум среди элементов, чей номер заканчивается цифрами.
    """
    numbers = [item.get("number") for item in items
               if isinstance(item, dict) and "number" in item]
    if numbers and all(isinstance(value, int) for value in numbers):
        return max(numbers) + 1
    highest = 0
    for value in numbers:
        match = _TRAILING_NUMBER.match(str(value or ""))
        if not match:
            continue
        prefix, digits = match.groups()
        if base and prefix != base:
            continue
        highest = max(highest, int(digits))
    return "%s%d" % (base, highest + 1)


def kind_name(kind):
    """Подпись вида таблицы — фрагмент из ``es.KINDS`` (гарантирует `table_kind`)."""
    for needle, value in es.KINDS:
        if value == kind:
            return needle
    return ""


def kind_headers(kind):
    """Подписи колонок формы для вида таблицы шкафа."""
    if kind in ee._FLAT:
        return list(ee._FLAT_HEADERS[kind])
    if kind == "goose_signals":
        return list(ee._GOOSE_HEADERS)
    if kind == "report_signals":
        return list(ee._REPORT_HEADERS)
    if kind == "functions":
        return list(_FUNCTION_HEADERS)
    if kind == "terminal_blocks":
        return list(_TERMINAL_HEADERS)
    if kind == "description":
        return ["Параметр", "Значение"]
    return []


def _style(items, default):
    for item in reversed(list(items)):
        style = item.get("header_style")
        if style:
            return style
    return default


def _form_rows(headers):
    """Форма таблицы: одна строка-шапка, совместимая с `es._form_headers`."""
    return [{"content": list(headers),
             "is_header_first_row": True,
             "is_header_second_row": False}]


def _as_number(value):
    """Номер ИЭУ/комплекта в данных — целое число."""
    text = str(value)
    return int(text) if text.isdigit() else value


# ---------------------------------------------------------------------------
# Контейнеры
# ---------------------------------------------------------------------------
def child_list(data, node, kind):
    """Список, в который добавляется потомок вида ``kind``."""
    if kind == "section":
        return data.setdefault("sections", [])
    if kind == "cabinet":
        return data.setdefault("cabinets", [])
    key = _CHILD_KEY.get(kind)
    if not key or not isinstance(node, dict):
        raise StructureError("неизвестный вид узла: %s" % kind)
    return node.setdefault(key, [])


def add(container, item, index=None):
    """Добавить узел в список; ``index`` — позиция или ``None`` в конец."""
    if index is None or index >= len(container):
        container.append(item)
    else:
        container.insert(max(0, index), item)


def remove(container, item):
    """Удалить узел из списка по идентичности."""
    for index, value in enumerate(container):
        if value is item:
            del container[index]
            return
    raise StructureError("узел не найден в контейнере")


def descendant_count(node):
    """Число непосредственных и вложенных потомков узла."""
    count = 0
    for key in _DESCENDANT_KEYS:
        children = node.get(key) or []
        count += len(children)
        for child in children:
            if isinstance(child, dict):
                count += descendant_count(child)
    return count


# ---------------------------------------------------------------------------
# Фабрики узлов
# ---------------------------------------------------------------------------
def new_section(data, number=None, header=None):
    return {
        "number": number or next_number(es.sections(data)),
        "header": header or "Новый раздел",
        "header_style": _style(es.sections(data), _DEFAULT_SECTION_STYLE),
        "content": "",
        "subsections": [],
        "tables": [],
        "figures": [],
    }


def new_subsection(data, section, number=None, header=None):
    existing = section.get("subsections") or []
    base = str(section.get("number") or "").strip()
    if base and not base.endswith("."):
        base += "."
    return {
        "number": number or next_number(existing, base),
        "header": header or "Новый подраздел",
        "header_style": _style(existing, _DEFAULT_SUBSECTION_STYLE),
        "clauses": [],
        "tables": [],
        "figures": [],
    }


def new_clause(data, container, number=None):
    existing = container.get("clauses") or []
    base = str(container.get("number") or "").strip()
    if base and not base.endswith("."):
        base += "."
    return {
        "number": number or next_number(existing, base),
        "content": "",
        "subclauses": [],
        "tables": [],
        "figures": [],
    }


def new_figure(data, container, number=None, name=None, base=None):
    existing = container.get("figures") or []
    if base is None:
        base = str(container.get("number") or "").strip()
        if base and not base.endswith("."):
            base += "."
    value = number or next_number(existing, base)
    return {
        "number": value,
        "name": name or "Новый рисунок",
        "reference": "Рисунок %s" % value,
    }


def new_cabinet(data, cypher=None, name=None):
    existing = {str(item.get("cypher") or "").strip()
                for item in es.cabinets(data)}
    code = (cypher or "").strip()
    if not code:
        index = 1
        while "Новый шкаф %d" % index in existing:
            index += 1
        code = "Новый шкаф %d" % index
    elif code in existing:
        raise StructureError("шкаф с таким шифром уже есть: %s" % code)
    return {
        "cypher": code,
        "architecture": "",
        "name": name or "",
        "controllable_element": "",
        "protected_element": "",
        "scope": "",
        "description": "",
        "type": "",
        "group": "",
        "tag": "",
        "power_supplies": [],
        "components": [],
        "terminal_blocks": [],
        "containers": [],
        "kits": [],
    }


def new_kit(data, cabinet, number=None):
    return {
        "number": _as_number(number if number is not None else next_number(
            cabinet.get("kits") or [])),
        "description": "",
        "type": "ИЭУ",
        "tag": "",
        "group": "",
        "ieds": [],
    }


def new_ied(data, kit, number=None):
    return {
        "number": _as_number(number if number is not None else next_number(
            kit.get("ieds") or [])),
        **{key: [] for key in _IED_LISTS},
    }


def new_table(data, spec, number=None):
    """Новая таблица по спецификации.

    ``spec`` — dict с полями ``name``, ``cabinet``, ``kind``, ``headers``,
    ``number``, ``reference``. Для таблицы шкафа ``name`` обязано содержать
    фрагмент из ``es.KINDS``; если имя пустое, оно берётся из ``kind``.
    """
    name = str(spec.get("name") or "").strip()
    code = str(spec.get("cabinet") or "").strip()
    kind = spec.get("kind") or None
    if code:
        if es.cabinet(data, code) is None:
            raise StructureError("шкаф не найден: %s" % code)
        if not name:
            name = kind_name(kind)
        if es.table_kind(name) != kind:
            raise StructureError("название таблицы должно содержать: %s"
                                 % (kind_name(kind) or "вид данных"))
        headers = list(spec.get("headers") or kind_headers(kind))
        if not headers:
            raise StructureError("нет подписей колонок для вида: %s" % kind)
    else:
        headers = list(spec.get("headers") or ["Колонка 1", "Колонка 2"])
        kind = None

    value = str(number if number is not None else spec.get("number") or "")
    if not value:
        value = next_number(es.iter_tables(data))
    reference = str(spec.get("reference") or "").strip() \
        or ("Таблица %s" % value)
    table = {
        "number": value,
        "name": name or "Новая таблица",
        "reference": reference,
        "rows": _form_rows(headers),
    }
    if code:
        table["cabinet"] = code
    return table


# ---------------------------------------------------------------------------
# Проверки перед удалением
# ---------------------------------------------------------------------------
def _owner_cabinet(data, node, kind):
    for cabinet in es.cabinets(data):
        if kind == "kit" and node in (cabinet.get("kits") or []):
            return cabinet
        if kind == "ied":
            for kit in cabinet.get("kits") or []:
                if node in (kit.get("ieds") or []):
                    return cabinet
    return None


def delete_issues(data, node, kind):
    """Причины, по которым узел удалять нельзя (пусто — можно)."""
    issues = []
    if kind == "cabinet":
        code = node.get("cypher")
        refs = [table.get("number") or "(без номера)"
                for table in es.iter_tables(data)
                if table.get("cabinet") == code]
        if refs:
            issues.append("на шкаф ссылаются таблицы: %s. "
                          "Сначала удалите или отвяжите их."
                          % ", ".join(refs[:8]))
    if kind in ("kit", "ied"):
        cabinet = _owner_cabinet(data, node, kind)
        if cabinet is not None:
            linked = [table.get("number") or "(без номера)"
                      for table in es.iter_tables(data)
                      if table.get("cabinet") == cabinet.get("cypher")]
            kits = cabinet.get("kits") or []
            first_ied = (kits[0].get("ieds") or [None])[0] if kits else None
            used = ((kind == "kit" and kits and node is kits[0])
                    or (kind == "ied" and node is first_ied))
            if linked and used:
                issues.append("этот %s — первый у шкафа, от него зависят "
                              "таблицы: %s. Сначала удалите таблицы."
                              % ("комплект" if kind == "kit" else "ИЭУ",
                                 ", ".join(linked[:8])))
    return issues
