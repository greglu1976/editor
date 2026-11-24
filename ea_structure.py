#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Структурные операции над стандартом EA.

Фабрики новых узлов и операции добавления/удаления не зависят от Tk: окно
редактора (:mod:`ea_editor`) вызывает их, а тесты — напрямую. Данные шкафов
и таблиц остаются в том же формате, что и в ``EA/*.json``.
"""

from __future__ import annotations

import copy
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
                    "figures", "kits", "ieds", "function_blocks",
                    "functions", "inputs", "outputs", "settings",
                    "parameters")

_DEFAULT_SECTION_STYLE = "ДОК Заголовок вкл в содержание"
_DEFAULT_SUBSECTION_STYLE = "ДОК Текст 3уров 2-пункт"

_TERMINAL_HEADERS = ("Ряд", "Расположение", "Номера клемм", "Количество",
                     "Тип (функц.)", "Тип (подкл.)", "Назначение")
_FUNCTION_HEADERS = ("Функция", "Параметр", "Описание", "Состояния")

_IED_LISTS = ("analog_inputs", "osc_analog_signals", "incoming_goose_signals",
              "inner_discrete_circuits", "datasets", "ports",
              "functional_buttons", "leds", "control_commands",
              "function_blocks")


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
    if kind in ("description", "description_kit"):
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


def _description_rows(labels):
    """Строки формы описания: по одной строке на поле «Параметр — Значение»."""
    return [{"content": [label, ""],
             "is_header_first_row": index == 0,
             "is_header_second_row": False}
            for index, label in enumerate(labels)]


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
    if kind == "fb_entry":
        return data.setdefault("functional_blocks", [])
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
        "scheme": "",
        "format": "",
        "orientation": "",
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
        "identical": "",
        "ieds": [],
    }


def new_ied(data, kit, number=None):
    return {
        "number": _as_number(number if number is not None else next_number(
            kit.get("ieds") or [])),
        "description": "",
        # Файл ФЛС редактора, входящей в состав ИЭУ (structure2.xml).
        "scheme": "",
        **{key: [] for key in _IED_LISTS},
    }


def new_functional_block_entry(data, block=None, cabinet="", kit="", ied=""):
    """Новая запись плоского каталога ФБ стандарта.

    ``block`` — исходный FunctionBlock (копируется и нормализуется по
    структуре2); если ``None`` — создаётся пустой блок. Поля ``cabinet``,
    ``kit``, ``ied`` указывают источник (шкаф / комплект / ИЭУ).
    """
    import ea_model
    entry = ea_model.normalize_function_block(block)
    entry["cabinet"] = str(cabinet or "")
    entry["kit"] = str(kit or "")
    entry["ied"] = str(ied or "")
    return entry


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


def _containers_with_tables(data, container=None):
    """Контейнеры документа, где могут лежать таблицы (в порядке дерева)."""
    if container is None:
        for section in es.sections(data):
            yield from _containers_with_tables(data, section)
        return
    yield container
    # ordered_items не включает подразделы — обходим их отдельно.
    for sub in container.get("subsections") or []:
        if isinstance(sub, dict):
            yield from _containers_with_tables(data, sub)
    for kind, item in ordered_items(container):
        if kind in ("clause", "subclause"):
            yield from _containers_with_tables(data, item)


def _table_container(data, table):
    """Раздел/подраздел/пункт, в котором лежит ``table``."""
    for container in _containers_with_tables(data):
        if table in (container.get("tables") or []):
            return container
    return None


def _kit_description_name(code, numbers):
    """«Описание ИЭУ1(2) в составе ШЭТ …» по списку номеров группы."""
    label = "ИЭУ%s" % numbers[0]
    if len(numbers) > 1:
        label += "(%s)" % ",".join(str(number) for number in numbers[1:])
    return "Описание %s в составе %s" % (label, code)


def split_description_tables(data):
    """Разделить описание шкафа на таблицу шкафа и таблицы ИЭУ.

    Работает только для стандартов с ``description_split``; повторный вызов
    пересобирает таблицы ИЭУ заново, не оставляя дублей. Возвращает число
    созданных таблиц описания ИЭУ.
    """
    if not isinstance(data, dict) or not data.get("description_split"):
        return 0
    created = 0
    for cabinet_item in es.cabinets(data):
        code = str(cabinet_item.get("cypher") or "")
        description = next((
            table for table in es.iter_tables(data)
            if table.get("cabinet") == code
            and es.table_kind(table.get("name")) == "description"), None)
        if description is None:
            continue
        container = _table_container(data, description)
        if container is None:
            continue
        # Прежние таблицы ИЭУ удаляются: «Обновить стандарт» пересобирает
        # форму заново, а не копирует её всё больше.
        for owner in _containers_with_tables(data):
            tables = owner.get("tables") or []
            for table in list(tables):
                if (table is not description
                        and table.get("cabinet") == code
                        and (table.get("description_part") == "kit"
                             or es.table_kind(table.get("name"))
                             == "description_kit")):
                    tables.remove(table)
        description["description_part"] = "cabinet"
        description.pop("kit", None)
        description["rows"] = _description_rows(es.CABINET_DESCRIPTION_ROWS)

        kits = cabinet_item.get("kits") or []
        groups, seen = [], set()
        for index, kit in enumerate(kits, 1):
            if not isinstance(kit, dict):
                continue
            identical = str(kit.get("identical") or "").strip()
            if identical and identical in seen:
                continue
            members = [position for position, other in enumerate(kits, 1)
                       if isinstance(other, dict) and identical
                       and str(other.get("identical") or "").strip()
                       == identical]
            if not members:
                members = [index]
            if identical:
                seen.add(identical)
            groups.append((members, kit))

        for members, kit in groups:
            number = kit.get("number") or members[0]
            table = new_table(data, {
                "name": _kit_description_name(code, members),
                "cabinet": code,
                "kind": "description_kit",
                "headers": ["Параметр", "Значение"],
            })
            table["rows"] = _description_rows(es.KIT_DESCRIPTION_ROWS)
            table["description_part"] = "kit"
            table["kit"] = str(number)
            add(container.setdefault("tables", []), table)
            created += 1
    return created


# ---------------------------------------------------------------------------
# Перенос и копирование таблиц
# ---------------------------------------------------------------------------
def next_table_number(data, section_number=""):
    """Следующий номер таблицы в разделе: «5.58», «В.2» и т. п.

    Для раздела с номером номер продолжает его ряд (``5.2…5.57`` → ``5.58``);
    для раздела без номера — сквозной номер по документу.
    """
    prefix = str(section_number or "").strip()
    numbers = [str(table.get("number") or "")
               for table in es.iter_tables(data)]
    if prefix:
        pattern = re.compile(r"^%s\.(\d+)$" % re.escape(prefix))
        used = [int(match.group(1)) for number in numbers
                if (match := pattern.match(number))]
        minor = max(used, default=0) + 1
        candidate = "%s.%d" % (prefix, minor)
        while candidate in numbers:
            minor += 1
            candidate = "%s.%d" % (prefix, minor)
        return candidate
    return str(next_number(es.iter_tables(data)))


def copy_table(data, table, container, number=None, section_number=""):
    """Скопировать таблицу в другой контейнер с новым номером.

    Копия получает собственные строки (``deepcopy``) и новую ссылку
    «Таблица N»; имя при совпадении с исходным дополняется «(копия)».
    Возвращает новую таблицу.
    """
    clone = copy.deepcopy(table)
    clone.pop("order", None)
    value = str(number or next_table_number(data, section_number)).strip()
    if not value:
        raise StructureError("не задан номер новой таблицы")
    used = {str(item.get("number") or "") for item in es.iter_tables(data)}
    if value in used:
        raise StructureError("номер таблицы уже занят: %s" % value)
    clone["number"] = value
    clone["reference"] = "Таблица %s" % value
    clone["name"] = _unique_table_name(data, clone.get("name"))
    add(container.setdefault("tables", []), clone)
    return clone


def _unique_table_name(data, name):
    """Имя копии, не совпадающее с именами таблиц документа."""
    existing = {str(item.get("name") or "") for item in es.iter_tables(data)}
    base = str(name or "Таблица").strip() or "Таблица"
    candidate = base + " (копия)"
    index = 2
    while candidate in existing:
        candidate = "%s (копия %d)" % (base, index)
        index += 1
    return candidate


def move_node(node, source, target):
    """Перенести узел (таблицу, рисунок) в другой список без смены номера.

    Номер и ссылка сохраняются: на «Таблица N» могут ссылаться текст и
    описание шкафа. Возвращает узел.
    """
    if source is target:
        raise StructureError("узел уже находится в этом разделе")
    remove(source, node)
    node.pop("order", None)
    add(target, node)
    return node


def place_node(node, source, target, anchor=None, after=False):
    """Поставить узел в список ``target`` перед/после ``anchor``.

    В отличие от :func:`move_node`, работает и внутри одного списка, поэтому
    используется для перетаскивания мышью. Номер и ссылка не меняются.
    ``anchor=None`` означает конец списка. Если якорь находился в том же
    списке после узла, позиция ищется уже после удаления — индекс
    пересчитывается автоматически.
    """
    if node not in source:
        raise StructureError("узел не найден в контейнере")
    remove(source, node)
    index = None
    if anchor is not None:
        try:
            index = target.index(anchor)
        except ValueError:
            index = None
        if index is not None and after:
            index += 1
    add(target, node, index)
    return node


# ---------------------------------------------------------------------------
# Общий порядок пунктов, подпунктов, таблиц и рисунков
# ---------------------------------------------------------------------------
#: Вид элемента документа → ключ его списка в контейнере.
_ORDER_KEYS = {"clause": "clauses", "subclause": "subclauses",
               "table": "tables", "figure": "figures"}
#: Порядок, пока поле ``order`` не задано: как выводили раньше — таблицы,
#: рисунки, затем пункты и подпункты.
_LEGACY_KINDS = ("table", "figure", "clause", "subclause")
_BLOCK_KEYS = {"table": "tables", "figure": "figures"}


def _has_order(item):
    """Задано ли у элемента числовое поле общего порядка."""
    value = item.get("order") if isinstance(item, dict) else None
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def ordered_items(container):
    """Пункты, подпункты, таблицы и рисунки контейнера в порядке документа.

    Пока ни у одного элемента нет поля ``order``, порядок прежний: сначала
    таблицы и рисунки, затем пункты и подпункты. После первого переноса
    поле ``order`` задано у всех элементов контейнера и определяет их общий
    порядок. Элементы без поля (добавленные после переноса) идут в конце —
    так же, как они дописаны в свои списки.
    """
    items = []
    for kind in _LEGACY_KINDS:
        for item in container.get(_ORDER_KEYS[kind]) or []:
            if isinstance(item, dict):
                items.append((kind, item))
    if not any(_has_order(item) for _kind, item in items):
        return items
    ordered = [(kind, item) for kind, item in items if _has_order(item)]
    unordered = [(kind, item) for kind, item in items
                 if not _has_order(item)]
    ordered.sort(key=lambda pair: float(pair[1].get("order")))
    return ordered + unordered


def ordered_blocks(container):
    """Таблицы и рисунки контейнера в порядке документа."""
    return [(kind, item) for kind, item in ordered_items(container)
            if kind in _BLOCK_KEYS]


def move_item(kind, item, source, target, anchor=None, after=False):
    """Перенести пункт, подпункт, таблицу или рисунок в общий порядок.

    ``source`` — список, из которого берётся узел, ``target`` — словарь
    раздела, подраздела, пункта или подпункта. После переноса все элементы
    целевого контейнера получают поле ``order``, а списки переписываются в
    общем порядке. Возвращает узел.
    """
    if kind not in _ORDER_KEYS or not isinstance(item, dict):
        raise StructureError("неизвестный вид элемента: %s" % kind)
    if kind == "clause" and "subclauses" in target:
        raise StructureError("пункт нельзя вложить в пункт")
    if kind == "subclause" and "subclauses" not in target:
        raise StructureError("подпункт можно вложить только в пункт")
    items = ordered_items(target)
    if any(value is item for _kind, value in items):
        items = [(item_kind, value) for item_kind, value in items
                 if value is not item]
    else:
        remove(source, item)
    item.pop("order", None)
    if anchor is not None:
        index = next((position for position, (_kind, value)
                      in enumerate(items) if value is anchor), None)
        if index is None:
            index = len(items)
        elif after:
            index += 1
    else:
        index = len(items)
    items.insert(index, (kind, item))
    for position, (_kind, value) in enumerate(items):
        value["order"] = position
    for item_kind, key in _ORDER_KEYS.items():
        if key in target or item_kind == kind:
            target[key] = [value for value_kind, value in items
                           if value_kind == item_kind]
    return item


def move_block(kind, item, source, target, anchor=None, after=False):
    """Перенести таблицу/рисунок в контейнер с общим порядком блоков."""
    return move_item(kind, item, source, target, anchor=anchor, after=after)


def copy_figure(figure, container, number=None, base=""):
    """Скопировать рисунок в другой контейнер с новым номером."""
    clone = copy.deepcopy(figure)
    clone.pop("order", None)
    value = str(number or next_number(container.get("figures") or [],
                                      base)).strip()
    if not value:
        raise StructureError("не задан номер нового рисунка")
    clone["number"] = value
    clone["reference"] = "Рисунок %s" % value
    add(container.setdefault("figures", []), clone)
    return clone


def _unique_copy_name(container, name, key="name"):
    """Имя копии узла: «(копия)», при повторе — «(копия 2)» и далее."""
    existing = {str(item.get(key) or "") for item in container
                if isinstance(item, dict)}
    base = str(name or "").strip() or "Копия"
    candidate = base + " (копия)"
    index = 2
    while candidate in existing:
        candidate = "%s (копия %d)" % (base, index)
        index += 1
    return candidate


def _unique_slot_id(container, value):
    """Свободный ``id`` слота внутри той же коллекции входов/выходов."""
    used = {str(item.get("id") or "") for item in container
            if isinstance(item, dict)}
    value = str(value or "")
    if not value or value not in used:
        return value
    match = _TRAILING_NUMBER.match(value)
    if match:
        prefix, digits = match.groups()
        number = int(digits) + 1
        candidate = "%s%d" % (prefix, number)
        while candidate in used:
            number += 1
            candidate = "%s%d" % (prefix, number)
        return candidate
    candidate = value + "_copy"
    index = 2
    while candidate in used:
        candidate = "%s_copy%d" % (value, index)
        index += 1
    return candidate


def duplicate_node(item, container):
    """Вставить копию узла в тот же контейнер сразу после оригинала.

    Копия получает собственное имя с пометкой «(копия)»; у входа/выхода
    также обновляется ``id``, чтобы он не совпал с исходным слотом.
    Возвращает новую запись.
    """
    if not isinstance(item, dict):
        raise StructureError("узел нельзя скопировать")
    index = next((position for position, value in enumerate(container)
                  if value is item), None)
    if index is None:
        raise StructureError("узел не найден в контейнере")
    clone = copy.deepcopy(item)
    if "name" in clone:
        clone["name"] = _unique_copy_name(container, clone.get("name"))
    if "id" in clone:
        clone["id"] = _unique_slot_id(container, clone.get("id"))
    add(container, clone, index=index + 1)
    return clone


def copy_kit(kit, cabinet, number=None):
    """Скопировать комплект в шкаф, сохранив группу «Идентичны»."""
    clone = copy.deepcopy(kit)
    kits = cabinet.setdefault("kits", [])
    clone["number"] = _as_number(
        number if number is not None else next_number(kits))
    clone["description"] = _unique_copy_name(
        kits, clone.get("description"), key="description")
    add(kits, clone)
    return clone


# ---------------------------------------------------------------------------
# Привязка таблиц к шкафу
# ---------------------------------------------------------------------------
def rebind_table(table, code):
    """Привязать таблицу к шкафу ``code``.

    Форма (шапка) и номер сохраняются, строки при сборке берутся из нового
    шкафа. Шифр старого шкафа в наименовании заменяется на новый.
    """
    old = str(table.get("cabinet") or "")
    table["cabinet"] = code
    name = str(table.get("name") or "")
    if old and old != code and old in name:
        table["name"] = name.replace(old, code)
    return table


def rebind_tables(data, old, new):
    """Перепривязать все таблицы шкафа ``old`` к шкафу ``new``."""
    count = 0
    for table in es.iter_tables(data):
        if table.get("cabinet") == old:
            rebind_table(table, new)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Идентичные комплекты и перенос между шкафами
# ---------------------------------------------------------------------------
def kit_feeds_tables(data, kit, cabinet):
    """Первый комплект шкафа, из которого собираются его таблицы."""
    kits = cabinet.get("kits") or []
    if not kits or kits[0] is not kit:
        return False
    code = cabinet.get("cypher")
    return any(table.get("cabinet") == code for table in es.iter_tables(data))


def identical_replacement(data, kit, cabinet=None):
    """Другой комплект той же непустой группы «Идентичны».

    Сначала ищется в том же шкафу, затем в остальных. Возвращает
    ``(шкаф, комплект)`` или ``(None, None)``.
    """
    group = str(kit.get("identical") or "").strip()
    if not group:
        return None, None
    if cabinet is not None:
        for other in cabinet.get("kits") or []:
            if other is not kit and \
                    str(other.get("identical") or "").strip() == group:
                return cabinet, other
    for other_cabinet in es.cabinets(data):
        if other_cabinet is cabinet:
            continue
        for other in other_cabinet.get("kits") or []:
            if other is not kit and \
                    str(other.get("identical") or "").strip() == group:
                return other_cabinet, other
    return None, None


def promote_kit(cabinet, kit):
    """Сделать комплект первым: таблицы шкафа собираются из первого."""
    kits = cabinet.setdefault("kits", [])
    if not any(value is kit for value in kits):
        raise StructureError("комплект не найден в шкафу")
    if kits[0] is not kit:
        remove(kits, kit)
        kits.insert(0, kit)
    return kit


def move_kit(kit, source, target, number=None):
    """Перенести комплект в другой шкаф, сохранив группу «Идентичны»."""
    kits = source.get("kits") or []
    if not any(value is kit for value in kits):
        raise StructureError("комплект не найден в шкафу")
    remove(kits, kit)
    target_kits = target.setdefault("kits", [])
    kit["number"] = _as_number(
        number if number is not None else next_number(target_kits))
    add(target_kits, kit)
    return kit


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
            issues.append("на шкаф ссылаются таблицы: %s. Удалите их или "
                          "привяжите к другому шкафу (правый клик по таблице "
                          "→ «Привязать к другому шкафу…»)."
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
                issues.append(
                    "этот %s — первый у шкафа, от него зависят таблицы: %s. "
                    "Укажите у другого комплекта ту же группу «Идентичны» "
                    "или сначала удалите/перепривяжите таблицы."
                    % ("комплект" if kind == "kit" else "ИЭУ",
                       ", ".join(linked[:8])))
    return issues
