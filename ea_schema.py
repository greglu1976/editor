# -*- coding: utf-8 -*-
"""Схема стандарта СТО, соответствующая ``EA/structure2.xml``.

Модель EA описывает классы, их поля и вложенные коллекции. Этот модуль —
исполняемое описание той же модели без зависимости от Enterprise Architect:
он используется и мигратором JSON, и редактором стандарта.

Для каждого класса заданы:

* ``fields``  — скалярные поля в порядке модели: ``(ключ, тип, значение)``;
* ``children`` — вложенные коллекции: ``(ключ, класс элемента)``.

Типы: ``s`` — строка, ``i`` — целое, ``f`` — число, ``b`` — логическое,
``l`` — список, ``d`` — словарь. Значение по умолчанию — то, что получает
новый узел, созданный в редакторе.

Модуль не зависит от остальных модулей редактора и от GUI.
"""

from __future__ import annotations

import copy

#: Схема классов. Порядок полей совпадает с порядком атрибутов в structure2.
CLASSES = {
    "Standard": {
        "fields": [
            ("name", "s", ""),
            ("code", "s", ""),
            ("property", "s", ""),
            ("date", "s", ""),
        ],
        "children": [
            ("sections", "Section"),
            ("cabinets", "Cabinet"),
            ("containers", "Container"),
            # Плоский каталог функциональных блоков всех ИЭУ стандарта.
            # Элементы — FunctionalBlockEntry; собирается автоматически
            # из cabinets, но может редактироваться пользователем.
            ("functional_blocks", "FunctionalBlockEntry"),
        ],
    },
    "Section": {
        "fields": [
            ("header_style", "s", ""),
            ("number", "s", ""),
            ("content", "s", ""),
            ("header", "s", ""),
        ],
        "children": [
            ("subsections", "Subsection"),
            ("clauses", "Clause"),
            ("tables", "Table"),
            ("figures", "Figure"),
        ],
    },
    "Subsection": {
        "fields": [
            ("header_style", "s", ""),
            ("number", "s", ""),
            ("header", "s", ""),
        ],
        "children": [
            ("clauses", "Clause"),
            ("tables", "Table"),
            ("figures", "Figure"),
        ],
    },
    "Clause": {
        "fields": [("number", "s", ""), ("content", "s", "")],
        "children": [
            ("subclauses", "Subclause"),
            ("tables", "Table"),
            ("figures", "Figure"),
        ],
    },
    "Subclause": {
        "fields": [("number", "s", ""), ("content", "s", "")],
        "children": [("tables", "Table"), ("figures", "Figure")],
    },
    "Table": {
        # colums_width — именно так поле названо в structure2.xml.
        "fields": [
            ("name", "s", ""),
            ("reference", "s", ""),
            ("number", "s", ""),
            ("colums_width", "l", []),
            # Поле не описано в UML, но используется редактором как ссылка
            # на шкаф, из которого собираются строки таблицы.
            ("cabinet", "s", ""),
        ],
        "children": [("rows", "TableRow")],
    },
    "TableRow": {
        "fields": [
            ("content", "l", []),
            ("is_header_first_row", "b", False),
            ("is_header_second_row", "b", False),
        ],
        "children": [],
    },
    "Figure": {
        "fields": [
            ("name", "s", ""),
            ("reference", "s", ""),
            ("number", "s", ""),
            # Файл функционально-логической схемы редактора, связанный
            # с рисунком (дополнение редактора к модели EA).
            ("scheme", "s", ""),
            # Параметры страницы для рисунка: пустые значения означают
            # формат и ориентацию текущего раздела документа.
            ("format", "s", ""),
            ("orientation", "s", ""),
        ],
        "children": [],
    },
    "Cabinet": {
        "fields": [
            ("cypher", "s", ""),
            ("architecture", "s", ""),
            ("name", "s", ""),
            ("controllable_element", "s", ""),
            ("protected_element", "s", ""),
            ("scope", "s", ""),
            ("description", "s", ""),
            ("type", "s", ""),
            ("tag", "s", ""),
            ("group", "s", ""),
            # Обратные ссылки на КЭТ; дополнение редактора к модели EA.
            ("containers", "l", []),
        ],
        "children": [
            ("components", "Component"),
            ("power_supplies", "PowerSupply"),
            ("kits", "Kit"),
            ("terminal_blocks", "TerminalBlock"),
        ],
    },
    "Component": {
        "fields": [
            ("name", "s", ""),
            ("description", "s", ""),
            ("quantity", "s", ""),
        ],
        "children": [],
    },
    "PowerSupply": {"fields": [("purpose", "s", "")], "children": []},
    "Container": {
        "fields": [
            ("type", "s", ""),
            ("description", "s", ""),
            ("max_prot_cabs_slots", "i", 0),
        ],
        "children": [],
    },
    "Kit": {
        "fields": [
            ("number", "i", 0),
            ("description", "s", ""),
            ("type", "s", ""),
            ("tag", "s", ""),
            ("group", "s", ""),
        ],
        "children": [("ieds", "IED"), ("terminal_rows", "TerminalRow")],
    },
    "IED": {
        "fields": [
            ("number", "i", 0),
            ("description", "s", ""),
            # Файл функционально-логической схемы редактора, входящей
            # в состав ИЭУ (FunctionalLogicScheme в structure2.xml —
            # дополнение редактора к модели EA).
            ("scheme", "s", ""),
        ],
        "children": [
            ("function_blocks", "FunctionBlock"),
            ("analog_inputs", "AnalogInput"),
            ("control_commands", "ControlCommand"),
            ("datasets", "DataSet"),
            ("functional_buttons", "FunctionalButton"),
            ("incoming_goose_signals", "IncomingGooseSignal"),
            ("inner_discrete_circuits", "InnerDiscreteCircuit"),
            ("leds", "LED"),
            ("osc_analog_signals", "OscAnalogSignal"),
            ("ports", "Port"),
        ],
    },
    "FunctionBlock": {
        "fields": [
            ("name", "s", ""),
            ("isMainFunction", "b", False),
            ("isInITS", "b", False),
            ("iec_name", "s", ""),
            # МЭК 61850 по частям: LD / LN / DO / DA (для отчётов).
            ("LD", "s", ""),
            ("LN", "s", ""),
            ("DO", "s", ""),
            ("DA", "s", ""),
            ("russian_path", "s", ""),
            ("corp_prof_name", "s", ""),
        ],
        "children": [("functions", "Function")],
    },
    "Function": {
        "fields": [
            ("name", "s", ""),
            ("iec_name", "s", ""),
            ("LNclass", "s", ""),
            ("LD", "s", ""),
            ("LN", "s", ""),
            ("DO", "s", ""),
            ("DA", "s", ""),
        ],
        "children": [
            ("inputs", "Input"),
            ("outputs", "Output"),
            ("settings", "Setting"),
            ("parameters", "Parameter"),
        ],
    },
    "Input": {
        "fields": [
            ("name", "s", ""),
            ("description", "s", ""),
            ("iec_name", "s", ""),
            ("LD", "s", ""),
            ("LN", "s", ""),
            ("DO", "s", ""),
            ("DA", "s", ""),
            ("type", "s", ""),
            ("id", "s", ""),
        ],
        "children": [],
    },
    "Output": {
        "fields": [
            ("name", "s", ""),
            ("description", "s", ""),
            ("iec_name", "s", ""),
            ("LD", "s", ""),
            ("LN", "s", ""),
            ("DO", "s", ""),
            ("DA", "s", ""),
            ("type", "s", ""),
            ("id", "s", ""),
        ],
        "children": [],
    },
    "Setting": {
        # В UML значения double, но в стандартах встречаются интервалы и
        # текстовые формы («0,2 о.е.»), поэтому храним как строку.
        "fields": [
            ("name", "s", ""),
            ("min_value", "s", ""),
            ("max_value", "s", ""),
            ("step", "s", ""),
            ("unit", "s", ""),
            ("default_value", "s", ""),
            ("description", "s", ""),
        ],
        "children": [],
    },
    "Parameter": {
        "fields": [
            ("name", "s", ""),
            ("value", "s", ""),
            ("default_value", "s", ""),
            ("description", "s", ""),
        ],
        "children": [],
    },
    "AnalogInput": {
        "fields": [
            ("circuit_type", "s", ""),
            ("test_block", "s", ""),
            ("contacts_count", "s", ""),
            ("note", "s", ""),
        ],
        "children": [],
    },
    "ControlCommand": {
        "fields": [("name", "s", ""), ("info_model", "s", "")],
        "children": [],
    },
    "DataSet": {
        "fields": [
            ("mapping", "s", ""),
            ("name", "s", ""),
            ("class", "s", ""),
            ("sender", "s", ""),
            ("id", "s", ""),
            ("note", "s", ""),
        ],
        "children": [("signals", "Signal")],
    },
    "Signal": {
        "fields": [
            ("name", "s", ""),
            ("info_model", "s", ""),
            ("destination", "s", ""),
            ("note", "s", ""),
            ("status", "s", ""),
            ("KT", "s", ""),
            ("cus", "s", ""),
            ("rdu", "s", ""),
            ("RAS", "s", ""),
            ("LD", "s", ""),
            ("LN", "s", ""),
            ("DO", "s", ""),
            ("DA", "s", ""),
        ],
        "children": [],
    },
    "FunctionalButton": {
        "fields": [
            ("mapping", "s", ""),
            ("short_name", "s", ""),
            ("disable_condition", "s", ""),
            ("enable_condition", "s", ""),
        ],
        "children": [],
    },
    "IncomingGooseSignal": {
        "fields": [
            ("signal", "s", ""),
            ("info_model", "s", ""),
            ("source", "s", ""),
            ("max_number", "i", 0),
            ("RAS", "s", ""),
            ("note", "s", ""),
            ("source_number", "i", 0),
        ],
        "children": [],
    },
    "InnerDiscreteCircuit": {
        "fields": [
            ("discrete_signal", "s", ""),
            ("direction", "s", ""),
            ("note", "s", ""),
        ],
        "children": [],
    },
    "LED": {
        "fields": [
            ("mapping", "s", ""),
            ("name", "s", ""),
            ("mode", "s", ""),
            ("note", "s", ""),
        ],
        "children": [],
    },
    "OscAnalogSignal": {
        "fields": [
            ("description", "s", ""),
            ("canal", "i", 0),
            ("name", "s", ""),
            ("startRAS", "s", ""),
        ],
        "children": [],
    },
    "Port": {"fields": [("description", "s", "")], "children": []},
    "TerminalBlock": {
        "fields": [("text", "s", "")],
        "children": [("rows", "TerminalRow")],
    },
    "TerminalRow": {
        "fields": [("location", "s", ""), ("assembly_unit", "s", "")],
        "children": [("terminals", "Terminal")],
    },
    "Terminal": {
        "fields": [
            ("number", "s", ""),
            ("quantity", "i", 0),
            ("function_type", "s", ""),
            ("connection_type", "s", ""),
            ("purpose", "s", ""),
        ],
        "children": [],
    },
    # ---------------------------------------------------------------------------
    # Плоский каталог функциональных блоков стандарта (на уровне Standard).
    # Содержит ссылку на источник (шкаф / комплект / ИЭУ) и полную копию
    # данных FunctionBlock — для размещения на чертеже без открытия ИЭУ.
    # ---------------------------------------------------------------------------
    "FunctionalBlockEntry": {
        "fields": [
            # Принадлежность: шкаф, комплект, ИЭУ
            ("cabinet", "s", ""),    # шифр шкафа-источника
            ("kit", "s", ""),        # номер комплекта
            ("ied", "s", ""),        # номер ИЭУ
            # Данные блока функций (аналог FunctionBlock)
            ("name", "s", ""),
            ("isMainFunction", "b", False),
            ("isInITS", "b", False),
            ("iec_name", "s", ""),
            ("LD", "s", ""),
            ("LN", "s", ""),
            ("DO", "s", ""),
            ("DA", "s", ""),
            ("russian_path", "s", ""),
            ("corp_prof_name", "s", ""),
        ],
        "children": [("functions", "Function")],
    },
    "Bus": {
        "fields": [("id", "s", ""), ("description", "s", "")],
        "children": [("connections", "Connection")],
    },
    "Connection": {
        "fields": [
            ("name", "s", ""),
            ("description", "s", ""),
            ("id", "s", ""),
        ],
        "children": [],
    },
}

#: Вид узла редактора → класс схемы.
KIND_CLASS = {
    "meta": "Standard",
    "text": "Section",
    "table": "Table",
    "figure": "Figure",
    "cabinet": "Cabinet",
    "kit": "Kit",
    "ied": "IED",
    "block": "FunctionBlock",
    "function": "Function",
    "slot": "Input",
    "setting": "Setting",
    "parameter": "Parameter",
    "component": "Component",
    "power_supply": "PowerSupply",
    "terminal_block": "TerminalBlock",
    "terminal_row": "TerminalRow",
    "terminal": "Terminal",
    "analog_input": "AnalogInput",
    "control_command": "ControlCommand",
    "dataset": "DataSet",
    "signal": "Signal",
    "functional_button": "FunctionalButton",
    "goose_signal": "IncomingGooseSignal",
    "inner_circuit": "InnerDiscreteCircuit",
    "led": "LED",
    "osc_signal": "OscAnalogSignal",
    "port": "Port",
    "container": "Container",
    "fb_entry": "FunctionalBlockEntry",
}

#: Подписи полей в интерфейсе. Для отсутствующих используется сам ключ.
LABELS = {
    "name": "Наименование",
    "code": "Шифр",
    "property": "Принадлежность",
    "date": "Дата введения",
    "number": "Номер",
    "header": "Заголовок",
    "header_style": "Стиль заголовка",
    "content": "Содержание",
    "reference": "Ссылка",
    "scheme": "Файл схемы редактора",
    "format": "Формат",
    "orientation": "Ориентация",
    "colums_width": "Ширина колонок",
    "cabinet": "Шкаф",
    "rows": "Строки",
    "cypher": "Шифр шкафа",
    "architecture": "Архитектура",
    "controllable_element": "Управляемый элемент",
    "protected_element": "Защищаемый элемент",
    "scope": "Область применения",
    "description": "Описание",
    "type": "Тип",
    "tag": "Тег",
    "group": "Группа",
    "containers": "Контейнеры",
    "functional_blocks": "Функциональные блоки",
    "quantity": "Количество",
    "max_prot_cabs_slots": "Слотов защитных шкафов",
    "ieds": "ИЭУ",
    "ied": "ИЭУ",
    "kits": "Комплекты",
    "kit": "Комплект",
    "components": "Компоненты",
    "power_supplies": "Вводы питания",
    "purpose": "Назначение",
    "function_blocks": "Блоки функций",
    "analog_inputs": "Аналоговые входы",
    "control_commands": "Команды управления",
    "datasets": "Наборы данных",
    "functional_buttons": "Функциональные кнопки",
    "incoming_goose_signals": "Входящие GOOSE",
    "inner_discrete_circuits": "Внутренние дискретные цепи",
    "leds": "Светодиоды",
    "osc_analog_signals": "Аналоговые сигналы осциллограмм",
    "ports": "Порты",
    "signals": "Сигналы",
    "isMainFunction": "Основная функция",
    "isInITS": "В ИТС",
    "iec_name": "МЭК 61850",
    "LD": "LD",
    "LN": "LN",
    "DO": "DO",
    "DA": "DA",
    "russian_path": "Путь (рус.)",
    "corp_prof_name": "Корпоративный профиль",
    "LNclass": "Класс LN",
    "functions": "Функции",
    "inputs": "Входы",
    "outputs": "Выходы",
    "settings": "Уставки",
    "parameters": "Параметры",
    "id": "Идентификатор",
    "min_value": "Минимум",
    "max_value": "Максимум",
    "step": "Шаг",
    "unit": "Единица",
    "default_value": "По умолчанию",
    "value": "Значение",
    "circuit_type": "Тип цепи",
    "test_block": "Испытательный блок",
    "contacts_count": "Контакты",
    "note": "Примечание",
    "info_model": "Информационная модель",
    "class": "Класс",
    "sender": "Отправитель",
    "mapping": "Отображение",
    "short_name": "Краткое имя",
    "disable_condition": "Условие запрета",
    "enable_condition": "Условие разрешения",
    "signal": "Сигнал",
    "source": "Источник",
    "max_number": "Максимум",
    "source_number": "Номер источника",
    "discrete_signal": "Дискретный сигнал",
    "direction": "Направление",
    "mode": "Режим",
    "canal": "Канал",
    "startRAS": "Начало RAS",
    "RAS": "RAS",
    "DO": "DO",
    "DA": "DA",
    "destination": "Получатель",
    "status": "Статус",
    "KT": "КТ",
    "cus": "CUS",
    "rdu": "RDU",
    "location": "Расположение",
    "assembly_unit": "Сборочная единица",
    "terminals": "Клеммы",
    "terminal_blocks": "Клеммники",
    "terminal_rows": "Ряды клемм",
    "connection_type": "Тип подключения",
    "function_type": "Тип (функц.)",
    "connections": "Связи",
    "colums": "Колонки",
}

#: Поля редактора, которых нет в UML. Не добавляются при миграции, но
#: остаются доступны в редакторе и создаются у новых узлов.
EXTRA_FIELDS = {("Table", "cabinet"), ("Cabinet", "containers"),
                ("Standard", "functional_blocks")}
# LD/LN/DO/DA — дополнение редактора к UML: при миграции не добавляются,
# но создаются у новых узлов и доступны в редакторе и отчётах.
EXTRA_FIELDS.update(
    (cls, part)
    for cls in ("FunctionBlock", "Function", "Input", "Output",
                "FunctionalBlockEntry", "Signal")
    for part in ("LD", "LN", "DO", "DA")
)

#: Старые имена полей, встречавшиеся в предыдущих версиях JSON.
ALIASES = {
    ("TerminalRow", "Location"): "location",
    ("Parameter", "conditions"): "value",
    ("Input", "slot_type"): "type",
    ("Output", "slot_type"): "type",
    ("Port", "port"): "description",
}


def label(key):
    """Человекочитаемое название поля ``key``."""
    return LABELS.get(key, str(key))


def kind_of(cls, key):
    """Тип поля ``key`` класса ``cls`` или ``None`` для произвольного поля."""
    for field, kind, _default in CLASSES.get(cls, {}).get("fields", []):
        if field == key:
            return kind
    return None


def default_of(cls, key):
    """Значение поля по умолчанию (копия для списков и словарей)."""
    for field, _kind, default in CLASSES.get(cls, {}).get("fields", []):
        if field == key:
            return copy.deepcopy(default)
    return ""


def child_class(cls, key):
    """Класс элемента коллекции ``key`` или ``None``."""
    for field, child in CLASSES.get(cls, {}).get("children", []):
        if field == key:
            return child
    return None


def fields(cls):
    """Список ``(ключ, тип, default)`` класса ``cls``."""
    return list(CLASSES.get(cls, {}).get("fields", []))


def children(cls):
    """Список ``(ключ, класс)`` класса ``cls``."""
    return list(CLASSES.get(cls, {}).get("children", []))


def missing_fields(cls, item):
    """Имена полей модели, отсутствующих в ``item``."""
    if not isinstance(item, dict):
        return []
    return [key for key, _kind, _default in fields(cls)
            if key not in item and (cls, key) not in EXTRA_FIELDS]


def new_node(cls, **values):
    """Новый узел класса ``cls`` со всеми полями и коллекциями схемы."""
    node = {}
    for key, _kind, default in fields(cls):
        node[key] = copy.deepcopy(default)
    for key, _child in children(cls):
        node[key] = []
    node.update(values)
    return node


def _convert(value, kind):
    """Привести значение к типу схемы, если это можно сделать без потерь."""
    if kind == "s":
        return value if isinstance(value, str) else str(value)
    if kind == "i":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
        return value
    if kind == "f":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return value
        return value
    if kind == "b":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "да", "true", "yes")
        return bool(value)
    return value


def normalize(cls, item, add_children=False, recursive=True):
    """Привести узел к схеме ``cls``.

    Добавляет отсутствующие поля, переименовывает старые имена, приводит
    типы и (по желанию) создаёт пустые коллекции. Лишние поля не удаляет —
    в стандартах встречаются дополнительные данные, используемые редактором.

    Возвращает ``True``, если ``item`` изменился.
    """
    if not isinstance(item, dict):
        return False
    changed = False
    for old, new in ALIASES.items():
        if old[0] == cls and old[1] in item and new not in item:
            item[new] = item.pop(old[1])
            changed = True
    for key, kind, default in fields(cls):
        if (cls, key) in EXTRA_FIELDS and key not in item:
            continue
        if key not in item:
            item[key] = copy.deepcopy(default)
            changed = True
        elif kind in ("s", "i", "f", "b"):
            value = _convert(item[key], kind)
            if value != item[key]:
                item[key] = value
                changed = True
    if add_children:
        for key, _child in children(cls):
            if key not in item:
                item[key] = []
                changed = True
    if recursive:
        for key, child in children(cls):
            values = item.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                if normalize(child, value, add_children=add_children,
                             recursive=recursive):
                    changed = True
    return changed


def normalize_document(data, add_children=False):
    """Нормализовать весь стандарт ``Standard`` по схеме structure2."""
    return normalize("Standard", data, add_children=add_children)
