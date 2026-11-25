# -*- coding: utf-8 -*-
"""Расширенная модель стандарта СТО по ``EA/structure2.xml``.

Модель EA описывает не только документ и шкаф, но и функциональную
декомпозицию ИЭУ:

    IED → FunctionBlock → Function → Input / Output
                                      Setting / Parameter

Старые JSON стандартов хранили плоский список ``functions``: каждая запись
была сразу и блоком, и функцией, а параметры лежали прямо в ней. Здесь
собран один слой доступа к обоим представлениям:

* :func:`function_blocks` читает новый ключ ``function_blocks``, а при его
  отсутствии собирает блоки из старого ``functions`` (группировка по
  ``russian_path``);
* :func:`iter_functions` обходит блоки и функции;
* :func:`normalize_function` / :func:`normalize_function_block` приводят
  запись к полям structure2 (``corp_prof_name``, ``LNclass``, ``inputs``,
  ``outputs``, ``settings``, ``parameters``);
* :func:`migrate_document` переписывает документ в новый вид.

Модуль не зависит от остальных модулей редактора: его используют и
стандарты (``ea_standard``), и графический редактор ФЛС
(``logic_library``).
"""

from __future__ import annotations

import copy

#: Перечисление SlotTypes из structure2.xml: тип входа/выхода функции.
SLOT_TYPES = {
    "analog_process_level": "Аналоговые цепи с уровня процесса",
    "discrete_process_level": "Дискретные цепи с уровня процесса",
    "control_operation": "Управляющие воздействия",
    "internal_info_exchange": "Информационный обмен внутри ИЭУ",
    "external_info_exchange": "Информационный обмен между ИЭУ",
}

SLOT_TYPE_ORDER = tuple(SLOT_TYPES)
DEFAULT_SLOT_TYPE = "discrete_process_level"

#: Вид связи ФЛС ↔ тип слота.
LINK_KIND_BY_SLOT = {
    "analog_process_level": "analog",
    "discrete_process_level": "discrete",
    "control_operation": "control",
    "internal_info_exchange": "internal",
    "external_info_exchange": "external",
}
SLOT_BY_LINK_KIND = {kind: slot for slot, kind in LINK_KIND_BY_SLOT.items()}


def _text(value):
    if value is None:
        return ""
    return str(value)


#: Составные части МЭК 61850-пути: LD / LN / DO / DA.
IEC_PARTS = ("LD", "LN", "DO", "DA")


def iec_parts(source):
    """Структурные поля LD/LN/DO/DA из словаря (или пустые строки)."""
    source = source if isinstance(source, dict) else {}
    return {key: _text(source.get(key)).strip() for key in IEC_PARTS}


def slot_type_title(slot_type):
    return SLOT_TYPES.get(slot_type, "")


def link_kind_for_slot(slot_type):
    return LINK_KIND_BY_SLOT.get(slot_type, "discrete")


def slot_type_for_link(kind):
    return SLOT_BY_LINK_KIND.get(kind, DEFAULT_SLOT_TYPE)


def new_slot(direction="in", name="", description="", iec_name="",
             slot_type="", slot_id="", **iec):
    """Новый вход/выход функции (классы Input и Output structure2).

    Дополнительные ``LD``/``LN``/``DO``/``DA`` сохраняются рядом с полной
    строкой ``iec_name`` — они нужны отчётам, которым нужны части пути.
    """
    if slot_type not in SLOT_TYPES:
        slot_type = DEFAULT_SLOT_TYPE
    result = {
        "id": _text(slot_id),
        "name": _text(name),
        "description": _text(description),
        "iec_name": _text(iec_name),
        "type": slot_type,
    }
    result.update(iec_parts(iec))
    return result


def normalize_slot(slot, direction="in"):
    """Вход/выход из JSON: понимает строку, число и старый ``input_count``."""
    if isinstance(slot, str):
        return new_slot(direction, name=slot)
    if not isinstance(slot, dict):
        return new_slot(direction)
    slot_type = _text(slot.get("type") or slot.get("slot_type")).strip()
    if slot_type not in SLOT_TYPES:
        slot_type = DEFAULT_SLOT_TYPE
    result = {
        "id": _text(slot.get("id")),
        "name": _text(slot.get("name")),
        "description": _text(slot.get("description")),
        "iec_name": _text(slot.get("iec_name")),
        "type": slot_type,
    }
    result.update(iec_parts(slot))
    return result


def normalize_slots(values, direction="in"):
    """Список входов/выходов; целое число превращается в N безымянных."""
    if isinstance(values, int) and not isinstance(values, bool):
        return [new_slot(direction) for _ in range(max(0, values))]
    if not isinstance(values, (list, tuple)):
        return []
    return [normalize_slot(item, direction) for item in values]


def normalize_parameter(parameter):
    """Параметр (программный переключатель) по полям structure2."""
    if not isinstance(parameter, dict):
        return {"name": _text(parameter), "value": "",
                "default_value": "", "description": ""}
    # Старое поле «Состояния» — это возможные значения переключателя.
    value = parameter.get("value")
    if value in (None, ""):
        value = parameter.get("conditions")
    return {
        "name": _text(parameter.get("name")),
        "value": _text(value),
        "default_value": _text(parameter.get("default_value")),
        "description": _text(parameter.get("description")),
    }


def normalize_setting(setting):
    """Уставка по полям structure2."""
    if not isinstance(setting, dict):
        return {"name": _text(setting), "min_value": "", "max_value": "",
                "step": "", "unit": "", "default_value": "",
                "description": ""}
    return {
        "name": _text(setting.get("name")),
        "min_value": _text(setting.get("min_value")),
        "max_value": _text(setting.get("max_value")),
        "step": _text(setting.get("step")),
        "unit": _text(setting.get("unit")),
        "default_value": _text(setting.get("default_value")),
        "description": _text(setting.get("description")),
    }


def normalize_function(function):
    """Функция по полям structure2: name, iec_name, LNclass и вложенные данные."""
    function = function if isinstance(function, dict) else {}
    result = {
        "name": _text(function.get("name")),
        "iec_name": _text(function.get("iec_name")),
        "LNclass": _text(function.get("LNclass")),
        "inputs": normalize_slots(function.get("inputs"), "in"),
        "outputs": normalize_slots(function.get("outputs"), "out"),
        "settings": [normalize_setting(item)
                     for item in function.get("settings") or []],
        "parameters": [normalize_parameter(item)
                       for item in function.get("parameters") or []],
    }
    result.update(iec_parts(function))
    return result


def normalize_function_block(block):
    """Функциональный блок по полям structure2."""
    block = block if isinstance(block, dict) else {}
    name = _text(block.get("name")).strip()
    path = _text(block.get("russian_path")).strip()
    result = {
        "name": name or path,
        "isMainFunction": bool(block.get("isMainFunction")),
        "isInITS": bool(block.get("isInITS")),
        "iec_name": _text(block.get("iec_name")),
        "russian_path": path or name,
        "corp_prof_name": _text(block.get("corp_prof_name")),
        "functions": [normalize_function(item)
                      for item in block.get("functions") or []
                      if isinstance(item, dict)],
    }
    result.update(iec_parts(block))
    return result


def _blocks_from_legacy(items):
    """Старый плоский список → блоки, сгруппированные по ``russian_path``."""
    blocks, index = [], {}
    for item in items:
        if not isinstance(item, dict):
            continue
        path = _text(item.get("russian_path")).strip()
        name = _text(item.get("name")).strip()
        key = path or name
        block = index.get(key)
        if block is None:
            block = {
                "name": key,
                "isMainFunction": bool(item.get("isMainFunction")),
                "isInITS": bool(item.get("isInITS")),
                "iec_name": _text(item.get("iec_name")),
                "russian_path": path or name,
                "corp_prof_name": _text(item.get("corp_prof_name")),
                "functions": [],
            }
            block.update(iec_parts(item))
            index[key] = block
            blocks.append(block)
        else:
            block["isMainFunction"] = (block["isMainFunction"]
                                       or bool(item.get("isMainFunction")))
            block["isInITS"] = (block["isInITS"]
                                or bool(item.get("isInITS")))
            if not block["iec_name"] and item.get("iec_name"):
                block["iec_name"] = _text(item.get("iec_name"))
            if not block["corp_prof_name"] and item.get("corp_prof_name"):
                block["corp_prof_name"] = _text(item.get("corp_prof_name"))
        function = {
            "name": name,
            "iec_name": _text(item.get("iec_name")),
            "LNclass": _text(item.get("LNclass")),
            "inputs": normalize_slots(item.get("inputs"), "in"),
            "outputs": normalize_slots(item.get("outputs"), "out"),
            "settings": [normalize_setting(value)
                         for value in item.get("settings") or []],
            "parameters": [normalize_parameter(value)
                           for value in item.get("parameters") or []],
        }
        function.update(iec_parts(item))
        block["functions"].append(function)
    return blocks


def function_blocks(ied):
    """Блоки функций ИЭУ: новый ``function_blocks`` или старый ``functions``."""
    if not isinstance(ied, dict):
        return []
    blocks = ied.get("function_blocks")
    if isinstance(blocks, list):
        return [normalize_function_block(item) for item in blocks
                if isinstance(item, dict)]
    legacy = ied.get("functions")
    if not isinstance(legacy, list):
        return []
    # Некоторые файлы уже хранят блоки под старым ключом.
    if any(isinstance(item, dict) and isinstance(item.get("functions"), list)
           for item in legacy):
        return [normalize_function_block(item) for item in legacy
                if isinstance(item, dict)]
    return _blocks_from_legacy(legacy)


def block_functions(block):
    """Функции блока (уже нормализованные)."""
    if not isinstance(block, dict):
        return []
    return [normalize_function(item) for item in block.get("functions") or []
            if isinstance(item, dict)]


def iter_functions(ied):
    """Обход ``(блок, функция)`` в порядке документа."""
    for block in function_blocks(ied):
        for function in block.get("functions") or []:
            yield block, function


def function_count(ied):
    return sum(1 for _block, _function in iter_functions(ied))


def block_label(block):
    return (_text(block.get("name")).strip()
            or _text(block.get("russian_path")).strip())


def function_label(block, function=None):
    """Подпись функции: «блок / функция», если имена различаются."""
    name = _text((function or {}).get("name")).strip()
    path = block_label(block)
    if path and name and path != name:
        return "%s / %s" % (path, name)
    return name or path


def migrate_document(data):
    """Перевести документ стандарта на ключ ``function_blocks``.

    Возвращает ``(документ, изменено)``. Документ правится на месте.
    """
    changed = False
    for cabinet in (data or {}).get("cabinets") or []:
        for kit in cabinet.get("kits") or []:
            for ied in kit.get("ieds") or []:
                if not isinstance(ied, dict):
                    continue
                if "function_blocks" in ied:
                    continue
                if "functions" not in ied:
                    continue
                ied["function_blocks"] = function_blocks(ied)
                del ied["functions"]
                changed = True
    return data, changed


def copy_ied(ied):
    """Глубокая копия ИЭУ с новым представлением функций."""
    result = copy.deepcopy(ied or {})
    if "functions" in result and "function_blocks" not in result:
        result["function_blocks"] = function_blocks(result)
        del result["functions"]
    return result
