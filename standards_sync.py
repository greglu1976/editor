# -*- coding: utf-8 -*-
"""Сверка каталога шкафов со стандартами ``standards_base/`` и перенос данных.

Сравниваются три уровня:

* **состав** — комплекты шкафа: каталог против карточки стандарта (не хватает
  комплекта с ИЭУ2 → строка «+ комплект 2: ИЭУ2»);
* **поля каталога** — те же поля, что правит пользователь в каталоге
  (функции МП ИЭУ, функции ИТС, применимость, защищаемый элемент и т. д.);
* **структура** — то, чего в каталоге нет вообще (назначение, ряды зажимов,
  таблицы ИЭУ): такие строки попадают в ``structure.json`` только пересборкой.

Каталог главнее стандарта: поле перезаписывается, только если в каталоге пусто
или лежит ссылка на таблицу («Таблица 5.2.14»). Таблицы ИЭУ в каталог не
переносятся никогда — их всегда берёт сборка структуры.

    python standards_sync.py                  # план: что отличается
    python standards_sync.py --apply          # перенести состав и поля
    python standards_sync.py --apply --parts состав
    python standards_sync.py --add            # шкафы стандартов, которых нет в каталоге
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys

import cabs
import komplekts
import standards_base
import structure

#: Пары «поле записи структуры» → «поле каталога» и «это список».
#: ``None`` — поля в каталоге нет, оно живёт только в структуре.
FIELD_MAP = (
    ("функции МП ИЭУ", "mp_functions", False),
    ("описание функций ИТС", "its_functions_desc", False),
    ("функции ИТС", "its_functions", True),
    ("применимость", "applicability", False),
    ("защищаемый элемент", "protected", False),
    ("управляемый элемент", "controlled", True),
    ("архитектура ПС", "architecture", False),
    ("вводы питания", "power_supply", True),
    ("порты", "ports", True),
    ("назначение", None, False),
)

#: Поля-таблицы: в каталоге их нет, они появляются в структуре.
TABLE_FIELDS = ("ряды зажимов", "основные компоненты",
                "параметры функций ИЭУ")

#: Поля записи ИЭУ, которые не являются таблицами.
IED_SKIP = ("обозначение", "тип", "описание", "источник")

#: Группы строк различия.
KIND_CATALOG = "поля"           # правится в каталоге
KIND_STRUCTURE = "в структуру"  # появится только после пересборки


# ---------------------------------------------------------------------------
# Значения и их сравнение
# ---------------------------------------------------------------------------
def is_table(value):
    """Значение — таблица (список строк-словарей)."""
    return isinstance(value, (list, tuple)) and bool(value) and all(
        isinstance(item, dict) for item in value)


def rows_count(value):
    return len(value) if isinstance(value, (list, tuple)) else 0


def value_text(value, limit=120):
    """Значение в одну строку: таблица — «таблица, N строк»."""
    if value is None:
        return "—"
    if is_table(value):
        return "таблица, %d строк" % rows_count(value)
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = ", ".join("%s: %s" % (key, item) for key, item in value.items())
    else:
        text = " ".join(str(value).split())
    if len(text) > limit:
        text = text[:limit - 3].rstrip() + "…"
    return text or "—"


def normalize(value):
    """Значение для сравнения: без разницы «–/-», регистра и пробелов.

    Строка «а; б» и список ``["а", "б"]`` считаются одним и тем же: каталог
    хранит часть полей строкой, стандарт — списком.
    """
    if is_table(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (list, tuple)):
        return "\n".join(normalize(item) for item in value)
    text = " ".join(str(value or "").split())
    text = text.replace("–", "-").replace("—", "-")
    parts = text.split(";") if ";" in text else [text]
    return "\n".join(part.strip().lower() for part in parts if part.strip())


def informative(value):
    """В значении есть данные (а не пусто и не ссылка на таблицу)."""
    return komplekts.is_informative(value)


# ---------------------------------------------------------------------------
# Индексы
# ---------------------------------------------------------------------------
def catalog_index():
    """Шифр стандарта → запись каталога."""
    index = {}
    for cabinet in cabs.all_cabinets():
        index[standards_base.norm_code(cabinet.get("code") or "")] = cabinet
    return index


def structure_records():
    """Записи structure.json по ключу шкафа."""
    document = structure.load() or {}
    index = {}
    for record in document.get(structure.CABINET_SECTION) or []:
        key = record.get(structure.ID_FIELD)
        if key:
            index[key] = record
    return index


# ---------------------------------------------------------------------------
# Различия
# ---------------------------------------------------------------------------
def composition(std_record, cabinet):
    """Недостающие комплекты: «+ комплект 2: ИЭУ2»."""
    rows = []
    std_kits = std_record.get("комплекты") or []
    cat_kits = cabinet.get("komplets") or []
    for index, kit in enumerate(std_kits):
        names = [str(ied.get("обозначение") or "ИЭУ")
                 for ied in kit.get("иэу") or []]
        if index >= len(cat_kits):
            rows.append({"вид": "+", "поле": "комплект %d" % (index + 1),
                         "было": "—", "стало": ", ".join(names) or "без ИЭУ",
                         "значение_каталог": None, "значение_стандарт": kit})
            continue
        cat_ieds = [str(ied.get("name") or "") for ied
                    in (cat_kits[index].get("ieds") or [])]
        if len(names) != len(cat_ieds):
            rows.append({"вид": "~", "поле": "комплект %d" % (index + 1),
                         "было": "%d ИЭУ" % len(cat_ieds),
                         "стало": ", ".join(names) or "без ИЭУ",
                         "значение_каталог": cat_kits[index],
                         "значение_стандарт": kit})
    return rows


def field_rows(std_record, cabinet, record=None):
    """Различия по полям: каталог (или структура) против стандарта."""
    rows = []
    for field, catalog_key, _as_list in FIELD_MAP:
        std_value = std_record.get(field)
        if not informative(std_value):
            continue
        # Поле есть в каталоге только если у записи каталога есть такой ключ
        # и значение в нём — настоящие данные, а не ссылка на таблицу.
        catalog_has_field = bool(catalog_key) and catalog_key in (cabinet or {})
        now_value = (cabinet or {}).get(catalog_key) if catalog_has_field else None
        catalog = catalog_has_field and informative(now_value)
        if catalog:
            if normalize(now_value) != normalize(std_value):
                rows.append({"вид": "~", "поле": field,
                             "было": value_text(now_value),
                             "стало": value_text(std_value),
                             "каталог": True, "группа": KIND_CATALOG,
                             "значение_каталог": now_value,
                             "значение_стандарт": std_value})
            continue
        # В каталоге поля нет или оно пустое/ссылочное: сравнить со структурой.
        struct_value = (record or {}).get(field)
        if informative(struct_value) and normalize(struct_value) \
                == normalize(std_value):
            continue
        rows.append({"вид": "+", "поле": field,
                     "было": value_text(struct_value),
                     "стало": value_text(std_value),
                     "каталог": False, "группа": KIND_STRUCTURE,
                     "значение_структура": struct_value,
                     "значение_стандарт": std_value})
    return rows


def table_changes(std_record, record=None):
    """Таблицы ИЭУ, которые в структуре отличаются от стандарта."""
    rows = []
    std_kits = std_record.get("комплекты") or []
    struct_kits = (record or {}).get("комплекты") or []
    for index, kit in enumerate(std_kits):
        struct_kit = struct_kits[index] if index < len(struct_kits) else {}
        struct_ieds = struct_kit.get("иэу") or []
        for ied_index, ied in enumerate(kit.get("иэу") or []):
            struct_ied = struct_ieds[ied_index] \
                if ied_index < len(struct_ieds) else {}
            name = ied.get("обозначение") or ("ИЭУ%d" % (ied_index + 1))
            for field, value in ied.items():
                if field in IED_SKIP or not value:
                    continue
                now = struct_ied.get(field)
                if normalize(now) == normalize(value):
                    continue
                rows.append({
                    "поле": "%s · %s" % (name, field),
                    "было": value_text(now),
                    "стало": value_text(value),
                    "значение_структура": now,
                    "значение_стандарт": value,
                })
    return rows


def cabinet_diff(card, cabinet, records=None):
    """Одна карточка стандарта против каталога и структуры."""
    key = (cabinet or {}).get("key") or standards_base.key_of_code(card["шифр"])
    std_record = standards_base.record(card, key)
    record = (records if records is not None else structure_records()).get(key)
    std_kits = std_record.get("комплекты") or []
    cat_kits = (cabinet or {}).get("komplets") or []
    rows = field_rows(std_record, cabinet, record)
    tables = table_changes(std_record, record)
    item = {
        "шифр": card["шифр"],
        "ключ": key,
        "стандарт": card["стандарт"],
        "раздел": card.get("раздел") or "",
        "запись": std_record,
        "каталог": cabinet,
        "комплектов_каталог": len(cat_kits),
        "комплектов_стандарт": len(std_kits),
        "состав": composition(std_record, cabinet or {}),
        "поля": rows,
        "каталог_поля": [row for row in rows if row["каталог"]],
        "структура": [row for row in rows if not row["каталог"]],
        "таблицы": len(tables),
        "таблицы_строки": tables,
    }
    item["всего"] = (len(item["состав"]) + len(item["каталог_поля"])
                     + len(item["структура"]) + len(tables))
    return item


def diff():
    """Различия по всем шкафам стандартов, которые есть в каталоге."""
    index = catalog_index()
    records = structure_records()
    items = []
    for card in standards_base.cabinets():
        cabinet = index.get(card["шифр"])
        if cabinet is None:
            continue
        items.append(cabinet_diff(card, cabinet, records))
    return items


def summary(items=None):
    """Сводка: сколько шкафов и различий по видам."""
    items = diff() if items is None else items
    result = {"шкафов": len(items), "с_различиями": 0, "состав": 0,
              "поля": 0, "в_структуру": 0, "таблицы": 0, "всего": 0}
    for item in items:
        if item["всего"]:
            result["с_различиями"] += 1
        result["состав"] += len(item["состав"])
        result["поля"] += len(item["каталог_поля"])
        result["в_структуру"] += len(item["структура"])
        result["таблицы"] += item["таблицы"]
        result["всего"] += item["всего"]
    return result


# ---------------------------------------------------------------------------
# Перенос в каталог
# ---------------------------------------------------------------------------
def kits_from_standard(item):
    """Комплекты, которых нет в каталоге (с ИЭУ из стандарта)."""
    cabinet = item.get("каталог") or {}
    std_record = item.get("запись") or {}
    existing = len(cabinet.get("komplets") or [])
    result = []
    for index, kit in enumerate(std_record.get("комплекты") or []):
        if index < existing:
            continue
        ieds = kit.get("иэу") or []
        names = [str(ied.get("обозначение") or "ИЭУ") for ied in ieds]
        functions = [str(name) for name in kit.get("функции РЗА") or []]
        result.append({
            "key": "",
            "name": "Комплект %d" % (index + 1),
            "kind": "typical",
            "type": "МП РЗА",
            "functions": functions,
            "desc": ("%s: %s" % (", ".join(names), ", ".join(functions))
                     if names and functions else ""),
            "has_ied": bool(ieds),
            "ieds": [{"name": name, "type": "МП РЗА", "desc": ""}
                     for name in names],
        })
    return result


def apply(item, parts=("состав", "поля")):
    """Переносит состав и поля одного шкафа в cabinets.json."""
    cabinet = item.get("каталог")
    if not cabinet:
        return {"изменено": 0, "шкаф": item.get("шифр")}
    definition = copy.deepcopy(cabinet)
    changed = 0
    if "состав" in parts:
        kits = list(definition.get("komplets") or [])
        for kit in kits_from_standard(item):
            kits.append(kit)
            changed += 1
        if kits:
            definition["komplets"] = kits
    if "поля" in parts:
        std_record = item.get("запись") or {}
        for field, catalog_key, _as_list in FIELD_MAP:
            if not catalog_key:
                continue
            matches = [row for row in item["поля"]
                       if row["поле"] == field and row["каталог"]]
            if not matches:
                continue
            value = std_record.get(field)
            if not informative(value):
                continue
            if normalize(definition.get(catalog_key)) == normalize(value):
                continue
            definition[catalog_key] = value
            changed += 1
    if changed:
        cabs.save_cabinet(definition, cabinet.get("key"))
    return {"изменено": changed, "шкаф": item.get("шифр")}


def apply_all(parts=("состав", "поля"), items=None):
    """Переносит различия по всем шкафам; возвращает список результатов."""
    items = diff() if items is None else items
    return [apply(item, parts) for item in items if item["всего"]]


# ---------------------------------------------------------------------------
# Шкафы стандартов, которых нет в каталоге
# ---------------------------------------------------------------------------
#: Хвост шифра СТО, который не входит в номер: год («-2019») или «-XXXX».
_STANDARD_TAIL = re.compile(r"^(?:X{2,}|Х{2,}|\d{4})$")


def _standard_number(code):
    """Номер СТО без года: «СТО …20.280-XXXX» → «СТО …20.280»."""
    text = standards_base.norm_code(code)
    head, sep, tail = text.rpartition("-")
    if sep and _STANDARD_TAIL.match(tail.strip()):
        return head.strip()
    return ""


def standard_info(code):
    """Ключ и группа стандарта по его шифру.

    Ключ ищется в ``cabs.STANDARDS`` по номеру СТО: у 280-XXXX и 280-2019
    номер общий, поэтому обе редакции попадают в группу «СКРМ». Для
    незнакомого стандарта ключ строится из шифра, группа остаётся пустой.
    """
    number = _standard_number(code)
    if number:
        for key, standard in cabs.STANDARDS.items():
            if _standard_number(standard.get("code")) == number:
                return key, standard.get("group") or ""
    return standards_base.key_of_code(code), ""


def standard_title(code):
    """Полное название стандарта из шапки файла standards_base."""
    wanted = standards_base.norm_code(code)
    for header in standards_base.standards():
        if standards_base.norm_code(header["шифр"]) == wanted:
            return header.get("обозначение") or ""
    return ""


def missing_cabinets():
    """Карточки стандартов, шифров которых нет в каталоге шкафов."""
    index = catalog_index()
    return [card for card in standards_base.cabinets()
            if card["шифр"] not in index]


def _join(value):
    """Список → строка через «; » (каталог хранит питания и порты строкой)."""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value if str(item).strip())
    return value


def _has_goose(record):
    for kit in record.get("комплекты") or []:
        for ied in kit.get("иэу") or []:
            if "входные GOOSE" in ied or "выходные GOOSE" in ied:
                return True
    return False


def catalog_entry(card):
    """Карточка стандарта → запись каталога для ``cabs.save_cabinet``."""
    key = standards_base.key_of_code(card["шифр"])
    record = standards_base.record(card, key)
    standard_key, group = standard_info(card["стандарт"])
    entry = {
        "key": key,
        "code": card["шифр"],
        "name": (record.get("наименование") or card.get("заголовок")
                 or card["шифр"]),
        "title": card.get("заголовок") or "",
        "description": record.get("назначение") or "",
        "group": group,
        "standard_key": standard_key,
        "standard": card["стандарт"],
        "standard_title": standard_title(card["стандарт"]),
        "architecture": record.get("архитектура ПС") or "",
        "protected": record.get("защищаемый элемент") or "",
        "controlled": record.get("управляемый элемент") or [],
        "its_functions": record.get("функции ИТС") or [],
        "applicability": record.get("применимость") or "",
        "source": ("разд. %s" % card["раздел"]) if card.get("раздел") else "",
        "goose": _has_goose(record),
        "komplets": kits_from_standard({"каталог": {}, "запись": record}),
        "mp_functions": record.get("функции МП ИЭУ") or "",
        "its_functions_desc": record.get("описание функций ИТС") or "",
        "power_supply": _join(record.get("вводы питания")),
        "ports": _join(record.get("порты")),
        "connection_scheme": record.get("поясняющая схема подключения") or "",
        "general_view": record.get("эскиз общего вида") or "",
        "structural_scheme": record.get("структурно-функциональная схема") or "",
    }
    return {name: value for name, value in entry.items()
            if value not in (None, "", [], {})}


def import_missing(cards=None):
    """Добавляет в каталог шкафы стандартов, которых в нём нет.

    Возвращает ``{"добавлено": [{"шифр", "ключ"}], "ошибки": [текст]}``.
    Таблицы ИЭУ в каталог не пишутся — их переносит пересборка структуры.
    """
    cards = missing_cabinets() if cards is None else list(cards)
    taken = {cabinet.get("key") for cabinet in cabs.all_cabinets()}
    added, errors = [], []
    for card in cards:
        try:
            entry = catalog_entry(card)
            if not entry.get("key"):
                errors.append("%s: не удалось построить ключ" % card["шифр"])
                continue
            if entry["key"] in taken:
                errors.append("%s: ключ %s уже занят"
                              % (card["шифр"], entry["key"]))
                continue
            key = cabs.save_cabinet(entry)
        except Exception as exc:                   # noqa: BLE001
            errors.append("%s: %s" % (card["шифр"], exc))
            continue
        taken.add(key)
        added.append({"шифр": card["шифр"], "ключ": key})
    return {"добавлено": added, "ошибки": errors}


# ---------------------------------------------------------------------------
# Построчный перенос различий
# ---------------------------------------------------------------------------
def _catalog_key(field):
    """Поле каталога для поля записи (None — поле живёт только в структуре)."""
    for name, key, _as_list in FIELD_MAP:
        if name == field:
            return key
    return None


def row_changes(item):
    """Различия шкафа построчно, со значениями обеих сторон.

    ``можно_в_структуру`` / ``можно_в_стандарт`` показывают, поддерживается
    ли направление, ``причина`` объясняет отказ.
    """
    changes = []
    for row in item.get("состав") or []:
        changes.append({
            "группа": "Состав",
            "поле": row["поле"],
            "вид": row["вид"],
            "значение_структура": row.get("было"),
            "значение_стандарт": row.get("стало"),
            "можно_в_структуру": True,
            "можно_в_стандарт": False,
            "причина": "обратный перенос удалил бы комплект из стандарта",
        })
    for row in item.get("поля") or []:
        catalog = bool(row.get("каталог"))
        structure_value = row.get("значение_каталог") if catalog \
            else row.get("значение_структура")
        key = _catalog_key(row["поле"])
        changes.append({
            "группа": "Поле",
            "поле": row["поле"],
            "вид": row["вид"],
            "значение_структура": structure_value,
            "значение_стандарт": row.get("значение_стандарт"),
            "можно_в_структуру": bool(key),
            "можно_в_стандарт": structure_value not in (None, "", [], {}),
            "причина": "" if key else "поле живёт только в структуре",
        })
    for row in item.get("таблицы_строки") or []:
        changes.append({
            "группа": "Таблица",
            "поле": row["поле"],
            "вид": "~",
            "значение_структура": row.get("значение_структура"),
            "значение_стандарт": row.get("значение_стандарт"),
            "можно_в_структуру": True,
            "можно_в_стандарт": False,
            "причина": "таблицы ИЭУ переносятся только из стандарта",
        })
    return changes


def _field_to_structure(item, change):
    """Значение стандарта → поле каталога."""
    field = change["поле"]
    key = _catalog_key(field)
    if not key:
        return {"ok": False, "текст": "поле «%s» живёт только в структуре"
                                      % field}
    cabinet = item.get("каталог") or {}
    definition = copy.deepcopy(cabinet)
    definition[key] = change.get("значение_стандарт")
    cabs.save_cabinet(definition, cabinet.get("key"))
    return {"ok": True, "текст": "«%s» → каталог" % field,
            "пересобрать": True}


def _kit_to_structure(item, change):
    """Комплект стандарта → каталог (вместе с недостающими до него)."""
    match = re.search(r"(\d+)", change.get("поле") or "")
    if not match:
        return {"ok": False, "текст": "не удалось определить номер комплекта"}
    number = int(match.group(1))
    cabinet = item.get("каталог") or {}
    record = copy.deepcopy(item.get("запись") or {})
    record["комплекты"] = (record.get("комплекты") or [])[:number]
    new = kits_from_standard({"каталог": cabinet, "запись": record})
    if not new:
        return {"ok": False, "текст": "комплект %d уже есть в каталоге"
                                      % number}
    definition = copy.deepcopy(cabinet)
    definition["komplets"] = list(cabinet.get("komplets") or []) + new
    cabs.save_cabinet(definition, cabinet.get("key"))
    return {"ok": True, "текст": "комплект %d → каталог" % number,
            "пересобрать": True}


def apply_change(item, change, direction="в структуру"):
    """Переносит одну строку различия в структуру или в стандарт.

    Возвращает ``ok``, ``текст`` и ``пересобрать`` — нужно ли обновить
    ``structure.json`` после записи.
    """
    group = change.get("группа")
    field = change.get("поле")
    if direction == "в структуру":
        if group == "Поле":
            return _field_to_structure(item, change)
        if group == "Состав":
            return _kit_to_structure(item, change)
        if group == "Таблица":
            return {"ok": True, "текст": "таблицы ИЭУ берутся из стандарта — "
                                         "нужна пересборка",
                    "пересобрать": True}
        return {"ok": False, "текст": "неизвестная группа «%s»" % group}
    if group != "Поле":
        return {"ok": False, "текст": change.get("причина")
                or "обратный перенос для этой строки не поддерживается"}
    value = change.get("значение_структура")
    if value in (None, "", [], {}):
        return {"ok": False, "текст": "в структуре нет значения для «%s»"
                                      % field}
    result = standards_base.update_card(item["шифр"], {field: value})
    if result["ошибка"]:
        return {"ok": False, "текст": result["ошибка"]}
    if not result["поля"]:
        return {"ok": False, "текст": "в стандарте нет поля «%s»" % field}
    return {"ok": True, "текст": "«%s» записано в %s"
                                 % (field, result["файл"]),
            "пересобрать": False}


# ---------------------------------------------------------------------------
# Текст для консоли и окна
# ---------------------------------------------------------------------------
def plan_text(items=None):
    """Построчный план: что и где отличается."""
    items = diff() if items is None else items
    stats = summary(items)
    lines = ["Шкафов в стандартах: %d, с различиями: %d"
             % (stats["шкафов"], stats["с_различиями"]),
             "различий: %d — состав: %d, поля: %d, в структуру: %d, "
             "таблицы: %d" % (stats["всего"], stats["состав"],
                              stats["поля"], stats["в_структуру"],
                              stats["таблицы"])]
    for item in items:
        if not item["всего"]:
            continue
        heads = []
        if item["состав"]:
            heads.append("состав: %d" % len(item["состав"]))
        catalog_rows = [row for row in item["поля"] if row["каталог"]]
        if catalog_rows:
            heads.append("поля: %d" % len(catalog_rows))
        if item["структура"]:
            heads.append("в структуру: %d" % len(item["структура"]))
        if item["таблицы"]:
            heads.append("таблицы: %d" % item["таблицы"])
        lines.append("  %-16s %s" % (item["шифр"], "; ".join(heads)))
    return "\n".join(lines)


def detail_text(item):
    """Подробности одного шкафа для окна сверки."""
    if not item:
        return ""
    std = item.get("запись") or {}
    header = "%s · %s" % (item["шифр"], item.get("стандарт") or "")
    if item.get("раздел"):
        header += " · раздел %s" % item["раздел"]
    lines = [header,
             "Комплектов: каталог %d → стандарт %d"
             % (item["комплектов_каталог"], item["комплектов_стандарт"]),
             ""]

    def block(title, rows, empty="нет различий"):
        lines.append(title.upper())
        if not rows:
            lines.append("  " + empty)
        for row in rows:
            lines.append("  %s %s" % (row["вид"], row["поле"]))
            if row["вид"] == "~":
                lines.append("      было:   %s" % row["было"])
                lines.append("      станет: %s" % row["стало"])
            else:
                lines.append("      %s" % row["стало"])
        lines.append("")

    block("Состав", item["состав"])
    block("Поля каталога", [row for row in item["поля"] if row["каталог"]])
    block("Только в структуре (после пересборки)", item["структура"])
    lines.append("ТАБЛИЦЫ ИЭУ")
    if item["таблицы"]:
        lines.append("  %d таблиц(ы) отсутствуют в структуре или отличаются — "
                     "обновятся пересборкой" % item["таблицы"])
    else:
        lines.append("  структура совпадает со стандартом")
    if std.get("наименование"):
        lines.append("")
        lines.append("Наименование: %s" % std["наименование"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Сверка каталога шкафов со standards_base и перенос данных")
    parser.add_argument("--apply", action="store_true",
                        help="перенести состав и поля в cabinets.json")
    parser.add_argument("--parts", default="состав,поля",
                        help="что переносить (состав, поля)")
    parser.add_argument("--json", action="store_true",
                        help="вывести различия в JSON")
    parser.add_argument("--add", action="store_true",
                        help="добавить в каталог шкафы, которых в нём нет")
    args = parser.parse_args(argv)

    error = standards_base.error()
    if error:
        print("standards_base: %s" % error, file=sys.stderr)
        return 2
    if args.add:
        result = import_missing()
        added = result["добавлено"]
        print("Добавлено шкафов: %d" % len(added))
        for item in added:
            print("  + %s (%s)" % (item["шифр"], item["ключ"]))
        for message in result["ошибки"]:
            print("  ! %s" % message)
        if added:
            print("Дальше: python tools/build_structure.py")
        return 0 if not result["ошибки"] else 1
    items = diff()
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    print(plan_text(items))
    if args.apply:
        parts = tuple(part.strip() for part in args.parts.split(",")
                      if part.strip())
        results = apply_all(parts, items)
        changed = sum(result["изменено"] for result in results)
        print("\nПеренесено изменений: %d в %d шкафах."
              % (changed, len([result for result in results
                               if result["изменено"]])))
        print("Дальше: python tools/build_structure.py — таблицы ИЭУ и "
              "остальные поля появятся в structure.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
