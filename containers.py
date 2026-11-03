# -*- coding: utf-8 -*-
"""Каталог контейнеров электротехнических типовых (КЭТ) для редактора схем.

Контейнер — это «стойка» для шкафов: на схеме КЭТ рисуется вертикально, его
слоты идут сверху вниз (до 7 шкафов в 20-футовом исполнении, до 14 — в
40-футовом). Каждый слот **привязывается к шкафу линией** — шкаф остаётся
там, где его поставили на схеме. Привязка хранится в самом контейнере
(``cabinets[номер слота] = id шкафа``), поэтому она сохраняется в файле схемы
вместе с контейнером.

Данные каталога взяты из «Временных рекомендаций по применению контейнеров
типовых электротехнических (КЭТ)» (ПАО «Россети», архитектура II типа):

* КЭТ СЗАУ 6-1-II … 6-7-II — типовые составы шкафов защиты, автоматики и
  управления;
* КЭТ систем связи (КЭТ СС);
* КЭТ АБ и ЩПТ, КЭТ ЩСН (требования к составу в стандарте не детализированы);
* КЭТ РЗА по группам первичного оборудования — перечни шкафов по
  СТО 56947007-33.040.20.277/280/283/286-2019;
* КЭТ ПА и КЭТ УПАСК;
* КЭТ АСУ ТП.

Встроенные КЭТ перенесены в ``catalog.normalized.json`` (раздел
``builtin_kets``); модуль хранит нормализацию, стандарты и работу с
пользовательским каталогом.

Формат записи:
    {
        "key":       "уникальный ключ КЭТ",
        "code":      "маркировка по стандарту (КЭТ 6-1-II, КЭТ СС, …)",
        "name":      "назначение контейнера",
        "description": "полное описание",
        "group":     "СЗАУ | РЗА Т/АТ | … | СС",
        "standard_key": "ключ из STANDARDS",
        "size":      "20dc | 20hc | 40"  — типоразмер,
        "slots":     7                   — вместимость, шкафов,
        "functions": ["функции"],
        "cabinets":  ["ключи шкафов из cabs.py"],
        "composition": ["справочный состав по стандарту"],
        "source":    "раздел стандарта",
    }

Типоразмеры и климатическое исполнение — по разделу «Технические требования
к конструктивному исполнению КЭТ»: 20’DC 6058×2438×2591, 20’HC 6058×2438×2896,
40’ — 12192 мм; УХЛ1; IP-23 при открытых жалюзи и IP-55 при закрытых.
"""

import copy
import json
import os
import re
import uuid

try:  # единое нормализованное хранилище пользовательского каталога
    from rza_catalog import store as catalog_store
except Exception:  # pragma: no cover - приложение должно запускаться и без него
    catalog_store = None

#: Предельное число слотов для шкафов в одном контейнере.
MAX_SLOTS = 14

#: Типоразмеры КЭТ: габариты в мм и вместимость по шкафам 800 мм.
SIZES = {
    "20dc": {
        "code": "20’DC",
        "title": "20 футов, сухогрузный (20’DC)",
        "length_mm": 6058,
        "width_mm": 2438,
        "height_mm": 2591,
        "slots": 7,
    },
    "20hc": {
        "code": "20’HC",
        "title": "20 футов, High Cube (20’HC)",
        "length_mm": 6058,
        "width_mm": 2438,
        "height_mm": 2896,
        "slots": 7,
    },
    "40dc": {
        "code": "40’DC",
        "title": "40 футов, сухогрузный (40’DC)",
        "length_mm": 12192,
        "width_mm": 2438,
        "height_mm": 2591,
        "slots": 14,
    },
}

#: Общие требования к КЭТ (раздел 4 стандарта).
COMMON = {
    "organization": "ПАО «Россети»",
    "climate": "УХЛ1",
    "ip": "IP-23 при открытых жалюзи / IP-55 при закрытых",
    "ports": ["ввод/вывод СН 220 В (А, В, С, 0)",
              "цепи оперативного постоянного тока («+», «−»)"],
    "requirements": [
        "конструкция самонесущая, готова к работе после установки на фундамент",
        "внутри: панель СН, воздуховоды охлаждения и отопления, осушители, "
        "освещение, охранная сигнализация",
        "размещение шкафов — в один ряд с двухсторонним обслуживанием",
        "каркас: гофрированный лист снаружи, изоляционный композит внутри",
    ],
}


def _standard(code, title, group):
    return {
        "code": code,
        "title": title,
        "group": group,
        "organization": COMMON["organization"],
        "architecture": "II тип",
    }


#: Нормативные документы, по которым выполнены типовые КЭТ каталога.
STANDARDS = {
    "ket": _standard(
        "Временные рекомендации по применению КЭТ",
        "Временные рекомендации по применению контейнеров типовых "
        "электротехнических (КЭТ). Архитектура II типа",
        "КЭТ"),
    "tat": _standard(
        "СТО 56947007-33.040.20.277-2019",
        "Типовые шкафы ШЭТ РЗА (авто)трансформаторов 110-750 кВ. "
        "Архитектура II типа",
        "Т/АТ"),
    "skrm": _standard(
        "СТО 56947007-33.040.20.280-2019",
        "Типовые шкафы ШЭТ РЗА шунтирующих реакторов, компенсационных "
        "реакторов и батарей статических конденсаторов 110-750 кВ",
        "СКРМ"),
    "lep": _standard(
        "СТО 56947007-33.040.20.283-2019",
        "Типовые шкафы ШЭТ РЗА ЛЭП 110-750 кВ. Архитектура II типа",
        "ЛЭП"),
    "sch": _standard(
        "СТО 56947007-33.040.20.286-2019",
        "Типовые шкафы ШЭТ РЗА сборных шин, ошиновок и шинных аппаратов "
        "6-750 кВ. Архитектура II типа",
        "СШ"),
    "pa": _standard(
        "Временные рекомендации по применению КЭТ, разд. «ШЭТ ПА»",
        "Типовые шкафы противоаварийной автоматики для КЭТ",
        "ПА"),
    "upask": _standard(
        "Временные рекомендации по применению КЭТ, разд. «ШЭТ УПАСК»",
        "Типовые шкафы УПАСК для КЭТ",
        "УПАСК"),
    "ss": _standard(
        "Временные рекомендации по применению КЭТ, разд. «КЭТ систем связи»",
        "Типовые контейнеры систем связи",
        "СС"),
}

#: Группы контейнеров для списков и фильтров.
GROUPS = (
    "СЗАУ",
    "РЗА Т/АТ",
    "РЗА СШ",
    "РЗА СКРМ",
    "РЗА ЛЭП",
    "ПА",
    "УПАСК",
    "СС",
    "АБ и ЩПТ",
    "ЩСН",
    "АСУ ТП",
    "Прочие",
)


def size_slots(size_key):
    """Вместимость типоразмера по умолчанию (7 или 14 шкафов)."""
    return SIZES.get(size_key, SIZES["20dc"])["slots"]


def size_for_slots(slots):
    """Типоразмер, в который помещается указанное число шкафов."""
    slots = max(1, int(slots or 0))
    return "20dc" if slots <= SIZES["20dc"]["slots"] else "40dc"


#: Встроенные КЭТ загружаются из catalog.normalized.json (builtin_kets).
#: Статический список удалён при переносе данных в хранилище.
CONTAINERS = []

# Подстановка общих данных стандарта: тип, габариты, климат, IP, группа.
def _apply_standard_defaults(container):
    """Дополняет контейнер данными его стандарта и типоразмера."""
    standard = STANDARDS.get(container.get("standard_key"))
    if standard:
        container.setdefault("standard", standard["code"])
        container.setdefault("standard_title", standard["title"])
        container.setdefault("architecture", standard["architecture"])
        container.setdefault("group", standard["group"])
    else:
        container.setdefault("group", "Прочие")

    size_key = container.get("size")
    if size_key not in SIZES:
        size_key = size_for_slots(container.get("slots") or 0)
        container["size"] = size_key
    # Данные типоразмера зависят от size, поэтому пересчитываются, а не
    # подставляются через setdefault: иначе после правки типоразмера
    # остались бы старые габариты.
    size = SIZES[size_key]
    container["size_code"] = size["code"]
    container["size_title"] = size["title"]
    container["dimensions"] = "{}×{}×{} мм (Д×Ш×В)".format(
        size["length_mm"], size["width_mm"], size["height_mm"])
    container["climate"] = COMMON["climate"]
    container["ip"] = COMMON["ip"]
    container["ports"] = list(COMMON["ports"])
    if not container.get("slots"):
        container["slots"] = size["slots"]
    container["slots"] = max(1, min(MAX_SLOTS, int(container["slots"])))
    return container


def _stored_builtin_containers():
    """Встроенные КЭТ из catalog.normalized.json (основной источник)."""
    if catalog_store is None:
        return []
    try:
        catalog = catalog_store.read_store(
            catalog_store.CANONICAL_STORE_PATH, copy_data=False
        )
        return [
            catalog_store.container_to_ket_dict(container)
            for container in catalog_store.builtin_ket_entries(catalog)
        ]
    except Exception:
        return []


_stored_containers = _stored_builtin_containers()
if _stored_containers:
    CONTAINERS = _stored_containers


for container in CONTAINERS:
    _apply_standard_defaults(container)


def standard_for(container):
    """Стандарт, по которому выполнен контейнер; None — произвольный КЭТ."""
    key = container.get("standard_key")
    return STANDARDS.get(key) if key else None


def size_for(container):
    """Данные типоразмера контейнера."""
    return SIZES.get(container.get("size"), SIZES["20dc"])


# ---------------------------------------------------------------------------
# Пользовательский каталог: создание, изменение и удаление контейнеров
# ---------------------------------------------------------------------------
# Встроенные контейнеры из CONTAINERS не меняются. Пользовательские КЭТ
# хранятся в catalog.normalized.json (см. rza_catalog/store.py). Путь ниже —
# только резервный legacy-формат для первого bootstrap хранилища.

USER_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "containers.json")


def normalize_container(container):
    """Приводит контейнер к согласованному виду (слоты, состав, типоразмер)."""
    container["cabinets"] = [key for key in container.get("cabinets", [])
                             if isinstance(key, str) and key]
    container["composition"] = [str(item) for item in
                                container.get("composition", []) if str(item).strip()]
    container["functions"] = [str(item) for item in
                              container.get("functions", []) if str(item).strip()]
    try:
        slots = int(container.get("slots") or 0)
    except (TypeError, ValueError):
        slots = 0
    container["slots"] = max(1, min(MAX_SLOTS, slots or size_slots(
        container.get("size"))))
    if container.get("size") not in SIZES:
        container["size"] = size_for_slots(container["slots"])
    _apply_standard_defaults(container)
    return container


def _read_user_catalog():
    if catalog_store is not None:
        try:
            catalog = catalog_store.ensure_store()
            custom = []
            overrides = {}
            for container in catalog_store.ket_entries(catalog):
                definition = catalog_store.container_to_ket_dict(container)
                if container.origin == "override":
                    overrides[container.key] = definition
                else:
                    custom.append(definition)
            return {
                "custom": custom,
                "overrides": overrides,
                "deleted": sorted(catalog.deleted_containers),
            }
        except Exception:
            pass

    if not os.path.exists(USER_CATALOG_PATH):
        return {"custom": [], "overrides": {}, "deleted": []}
    try:
        with open(USER_CATALOG_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {"custom": [], "overrides": {}, "deleted": []}
    data.setdefault("custom", [])
    data.setdefault("overrides", {})
    data.setdefault("deleted", [])
    return data


def _write_user_catalog(data):
    if catalog_store is not None:
        try:
            def mutate(catalog):
                catalog_store.reset_ket_entries(catalog)
                for definition in data.get("custom") or []:
                    if not isinstance(definition, dict):
                        continue
                    container = catalog_store.ket_dict_to_container(
                        definition, "custom")
                    catalog.containers[container.key] = container
                for definition in (data.get("overrides") or {}).values():
                    if not isinstance(definition, dict):
                        continue
                    container = catalog_store.ket_dict_to_container(
                        definition, "override")
                    catalog.containers[container.key] = container
                catalog.deleted_containers = set(data.get("deleted") or [])

            catalog_store.update_store(mutate)
            return
        except Exception:
            pass

    if not data["custom"] and not data["overrides"] and not data["deleted"]:
        if os.path.exists(USER_CATALOG_PATH):
            os.remove(USER_CATALOG_PATH)
        return
    with open(USER_CATALOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def builtin_keys():
    return {container.get("key") for container in CONTAINERS}


def is_builtin(key):
    return key in builtin_keys()


def all_containers():
    """Встроенные контейнеры + пользовательские, с учётом правок и удалений."""
    user = _read_user_catalog()
    result = []
    for container in CONTAINERS:
        key = container.get("key")
        if key in user["deleted"]:
            continue
        entry = copy.deepcopy(user["overrides"].get(key) or container)
        normalize_container(entry)
        result.append(entry)
    for entry in user["custom"]:
        if entry.get("key") in user["deleted"]:
            continue
        entry = copy.deepcopy(entry)
        normalize_container(entry)
        result.append(entry)
    return result


def find_container(key):
    for container in all_containers():
        if container.get("key") == key:
            return container
    return None


def _make_key(code, name):
    base = code or name or "ket"
    slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", base).strip("-").lower()
    slug = slug or "ket"
    existing = {container.get("key") for container in all_containers()}
    key = slug
    while key in existing:
        key = "{}-{}".format(slug, uuid.uuid4().hex[:4])
    return key


def save_container(definition, original_key=None):
    """Создаёт или изменяет контейнер в пользовательском каталоге.

    original_key — ключ изменяемого контейнера (None при создании).
    Возвращает ключ сохранённого контейнера.
    """
    user = _read_user_catalog()
    entry = copy.deepcopy(definition)
    key = original_key or entry.get("key")
    if not key or (original_key is None and not entry.get("key")):
        key = _make_key(entry.get("code"), entry.get("name"))
    entry["key"] = key
    normalize_container(entry)

    if is_builtin(key):
        user["overrides"][key] = entry
    else:
        replaced = False
        for index, container in enumerate(user["custom"]):
            if container.get("key") == key:
                user["custom"][index] = entry
                replaced = True
                break
        if not replaced:
            user["custom"].append(entry)

    if key in user["deleted"]:
        user["deleted"].remove(key)
    _write_user_catalog(user)
    return key


def delete_container(key):
    """Удаляет контейнер из каталога (встроенный — скрывается навсегда)."""
    user = _read_user_catalog()
    if is_builtin(key):
        if key not in user["deleted"]:
            user["deleted"].append(key)
        user["overrides"].pop(key, None)
    else:
        user["custom"] = [container for container in user["custom"]
                          if container.get("key") != key]
    _write_user_catalog(user)


def duplicate_container(key):
    """Создаёт копию контейнера и возвращает ключ копии."""
    source = find_container(key)
    if source is None:
        return None
    entry = copy.deepcopy(source)
    entry["key"] = ""
    entry["name"] = "{} (копия)".format(entry.get("name", "КЭТ"))
    if entry.get("code"):
        entry["code"] = "{} (копия)".format(entry["code"])
    return save_container(entry, None)


def reset_user_catalog():
    """Удаляет пользовательские КЭТ, не трогая каталог шкафов."""
    if catalog_store is not None:
        try:
            catalog_store.update_store(catalog_store.reset_ket_entries)
            return
        except Exception:
            pass
    if os.path.exists(USER_CATALOG_PATH):
        os.remove(USER_CATALOG_PATH)
