# -*- coding: utf-8 -*-
"""Каталог комплектов РЗА.

Комплект — подключаемая единица шкафа РЗА. Раньше комплекты хранились
только внутри шкафов (поле ``komplets`` в каталоге шкафов). Теперь у них
есть собственный каталог, чтобы комплекты можно было вести отдельно:

* **типовые** — берутся из типовых шкафов каталога (``cabs.py``): у каждого
  типового шкафа свой комплект (или несколько). Такой комплект ссылается на
  шкаф-источник и в каталоге не дублируется, а вычисляется на лету;
* **нетиповые** — комплекты нетиповых шкафов каталога (вычисляются так же)
  и комплекты, созданные пользователем (хранятся в ``komplekts.json``);
* **прочие** — пользовательские комплекты без привязки к шкафу
  (запас, нестандартное оборудование, временные решения).

Формат записи комплекта::

    {
        "key": "уникальный ключ (у типовых: typ:<ключ шкафа>:<номер>)",
        "kind": "typical | custom | other",
        "name": "Комплект 1",
        "type": "МП РЗА",
        "functions": ["ДЗТ", "..."],
        "desc": "примечание",
        "has_ied": True,                 # есть ли в комплекте ИЭУ
        "ieds": [{"name": "ИЭУ1", "type": "МП РЗА", "desc": "..."}],
        "test_blocks": {
            "voltage": {"count": 2, "circuits": ["Ua", "Ub", "Uc"]},
            "current": {"count": 1, "circuits": ["Ia", "Ib", "Ic"]},
        },
        "cabinet_key": "ключ типового шкафа (только для типовых)",
        "cabinet_index": 0,             # номер комплекта в шкафу-источнике
    }

Пользовательский каталог хранится в ``komplekts.json`` рядом с этим файлом::

    {"custom": [...], "overrides": {"ключ": {...}}, "deleted": ["ключ"]}

Типовые комплекты в ``custom`` не попадают: их правки лежат в ``overrides``
(меняются только поля комплекта, ссылка на шкаф остаётся каталога шкафов).
"""

import copy
import json
import os
import re
import uuid

#: Виды комплектов: ключ → подпись в интерфейсе.
KINDS = {
    "typical": "Типовой",
    "custom": "Нетиповой",
    "other": "Прочий",
}

KIND_ORDER = ("typical", "custom", "other")

#: Пресеты цепей испытательных блоков — те же, что в свойствах аналоговых связей.
VOLTAGE_PRESETS = ("Ua", "Ub", "Uc", "Uab", "Ubc", "Uca", "3U0",
                   "Uшон", "Uн", "Uи", "Uф", "Uк")
CURRENT_PRESETS = ("Ia", "Ib", "Ic", "3I0")

MAX_TEST_BLOCKS = 99

USER_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "komplekts.json")

#: Поля, которые можно править у типового комплекта (остальное — из шкафа).
_OVERRIDABLE = ("name", "type", "functions", "desc", "has_ied", "ieds",
                "test_blocks")


# ---------------------------------------------------------------------------
# Нормализация
# ---------------------------------------------------------------------------
def split_list(value):
    """«Ua, Ub; Uc» или список → список строк без пустых элементов."""
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[,;\n]+", value)
    else:
        items = []
        for item in value:
            items.extend(split_list(item))
    return [str(item).strip() for item in items if str(item).strip()]


def normalize_test_blocks(blocks):
    """Приводит испытательные блоки к {'voltage': {...}, 'current': {...}}."""
    source = blocks if isinstance(blocks, dict) else {}
    result = {}
    for side in ("voltage", "current"):
        entry = source.get(side)
        if not isinstance(entry, dict):
            entry = {}
        try:
            count = int(entry.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        count = max(0, min(MAX_TEST_BLOCKS, count))
        result[side] = {"count": count,
                        "circuits": split_list(entry.get("circuits"))}
    return result


def normalize_komplekt(definition, default_kind=None):
    """Возвращает комплект с полным набором полей (не меняет исходный).

    default_kind используется каталогом шкафов: у комплектов типового шкафа
    вид по умолчанию «типовой», у остальных — «нетиповой».
    """
    entry = copy.deepcopy(dict(definition or {}))

    kind = entry.get("kind")
    if kind not in KINDS:
        if default_kind in KINDS:
            kind = default_kind
        else:
            kind = "typical" if entry.get("cabinet_key") else "custom"
    entry["kind"] = kind

    entry["key"] = entry.get("key") or ""
    entry["name"] = str(entry.get("name") or "").strip() or "Комплект"
    entry["type"] = str(entry.get("type") or "").strip() or "МП РЗА"
    entry["functions"] = split_list(entry.get("functions"))
    entry["desc"] = str(entry.get("desc") or "").strip()

    ieds = []
    for ied in entry.get("ieds") or []:
        if not isinstance(ied, dict):
            continue
        ieds.append({
            "name": str(ied.get("name") or "ИЭУ").strip() or "ИЭУ",
            "type": str(ied.get("type") or "МП РЗА").strip() or "МП РЗА",
            "desc": str(ied.get("desc") or "").strip(),
        })
    entry["ieds"] = ieds
    entry["has_ied"] = bool(entry.get("has_ied")) if "has_ied" in entry \
        else bool(ieds)

    entry["test_blocks"] = normalize_test_blocks(entry.get("test_blocks"))
    entry["cabinet_key"] = str(entry.get("cabinet_key") or "")
    try:
        entry["cabinet_index"] = max(0, int(entry.get("cabinet_index") or 0))
    except (TypeError, ValueError):
        entry["cabinet_index"] = 0
    entry["cabinet_code"] = str(entry.get("cabinet_code") or "")
    entry["cabinet_name"] = str(entry.get("cabinet_name") or "")
    entry["cabinet_group"] = str(entry.get("cabinet_group") or "")
    entry["source"] = entry.get("source") or (
        "cabinet" if entry["kind"] == "typical" and entry["key"].startswith("typ:")
        else "user")
    return entry


def effective_ieds(entry):
    """Список ИЭУ с учётом галочки «Есть ИЭУ»."""
    if not entry.get("has_ied"):
        return []
    return list(entry.get("ieds") or [])


def has_test_blocks(entry):
    blocks = normalize_test_blocks(entry.get("test_blocks"))
    return any(blocks[side]["count"] for side in ("voltage", "current"))


def test_blocks_text(entry, compact=False):
    """Подпись испытательных блоков: «U: 2 (Ua, Ub); I: 1 (Ia)» или «—»."""
    blocks = normalize_test_blocks(entry.get("test_blocks"))
    parts = []
    for side, prefix in (("voltage", "U"), ("current", "I")):
        item = blocks[side]
        if not item["count"]:
            continue
        circuits = ", ".join(item["circuits"])
        if compact:
            parts.append("{}{}".format(prefix, item["count"]))
        else:
            parts.append("{}: {}{}".format(prefix, item["count"],
                                           " ({})".format(circuits)
                                           if circuits else ""))
    if compact:
        return "/".join(parts) or "—"
    return "; ".join(parts) or "—"


def kind_title(entry):
    return KINDS.get(entry.get("kind"), "Нетиповой")


def cabinet_label(cabinet):
    """Подпись шкафа для списков выбора: «шифр — название [группа]»."""
    code = str(cabinet.get("code") or "").strip()
    name = str(cabinet.get("name") or cabinet.get("title") or "Шкаф").strip()
    group = str(cabinet.get("group") or "").strip()
    text = "{} — {}".format(code, name) if code else name
    return "{} [{}]".format(text, group) if group else text


def cabinet_ref_text(entry):
    """Подпись ссылки на типовой шкаф (или «—»)."""
    if entry.get("kind") != "typical":
        return "—"
    code = entry.get("cabinet_code") or entry.get("cabinet_name")
    if not code:
        return "—"
    index = int(entry.get("cabinet_index") or 0) + 1
    return "{} · комплект {}".format(code, index)


def kit_label(entry):
    """Подпись комплекта для списков каталога."""
    parts = ["[{}] {}".format(kind_title(entry),
                              entry.get("name") or "Комплект")]
    if entry.get("kind") == "typical":
        code = entry.get("cabinet_code") or entry.get("cabinet_name")
        if code:
            parts.append(code)
    count = len(effective_ieds(entry))
    parts.append("{} ИЭУ".format(count) if count else "без ИЭУ")
    if has_test_blocks(entry):
        parts.append("БИ " + test_blocks_text(entry, compact=True))
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Типовые комплекты из каталога шкафов
# ---------------------------------------------------------------------------
def typical_key(cabinet_key, index):
    return "typ:{}:{}".format(cabinet_key or "", int(index))


def is_typical_key(key):
    return str(key or "").startswith("typ:")


def _cabinet_kits(cabinet):
    """Комплекты шкафа (с учётом старого формата ieds)."""
    komplets = cabinet.get("komplets")
    if isinstance(komplets, list):
        return komplets
    return []


def cabinet_kit_kind(cabinet):
    """Вид комплекта по шкафу-источнику: типовой шкаф → типовой комплект."""
    return "typical" if cabinet.get("standard_key") else "custom"


def link_komplets_to_cabinet(komplets, cabinet):
    """Проставляет комплектам шкафа ссылку на него, если ссылки ещё нет.

    Для типового комплекта ссылка на типовой шкаф обязательна; у комплектов,
    уже скопированных из другого шкафа каталога, ссылка сохраняется.
    """
    cabinet_key = cabinet.get("key") or ""
    if not cabinet_key:
        return komplets
    for index, kit in enumerate(komplets):
        if kit.get("kind") != "typical" or kit.get("cabinet_key"):
            continue
        kit["cabinet_key"] = cabinet_key
        kit["cabinet_index"] = index
        kit["cabinet_code"] = cabinet.get("code") or ""
        kit["cabinet_name"] = cabinet.get("name") or cabinet.get("title") or ""
        kit["cabinet_group"] = cabinet.get("group") or ""
    return komplets


def kit_from_cabinet(cabinet, index, kind=None):
    """Комплект по шкафу каталога и номеру комплекта в нём."""
    komplets = _cabinet_kits(cabinet)
    if not komplets:
        return None
    index = max(0, min(int(index), len(komplets) - 1))
    komplekt = normalize_komplekt(komplets[index])
    cabinet_key = cabinet.get("key") or ""
    kind = kind or cabinet_kit_kind(cabinet)
    prefix = "typ" if kind == "typical" else "cab"
    return normalize_komplekt({
        "key": "{}:{}:{}".format(prefix, cabinet_key, index),
        "kind": kind,
        "source": "cabinet",
        "name": komplekt["name"],
        "type": komplekt["type"],
        "functions": komplekt["functions"],
        "desc": komplekt["desc"],
        "has_ied": komplekt["has_ied"],
        "ieds": komplekt["ieds"],
        "test_blocks": komplekt["test_blocks"],
        "cabinet_key": cabinet_key,
        "cabinet_index": index,
        "cabinet_code": cabinet.get("code") or "",
        "cabinet_name": cabinet.get("name") or cabinet.get("title") or "",
        "cabinet_group": cabinet.get("group") or "",
    })


def cabinet_komplekts(cabinets=None):
    """Комплекты всех шкафов каталога — основа каталога комплектов."""
    if cabinets is None:
        import cabs as cabinet_catalog
        cabinets = cabinet_catalog.all_cabinets()
    result = []
    for cabinet in cabinets:
        for index in range(len(_cabinet_kits(cabinet))):
            kit = kit_from_cabinet(cabinet, index)
            if kit is not None:
                result.append(kit)
    return result


def typical_komplekts(cabinets=None):
    """Только типовые комплекты — из типовых шкафов каталога."""
    return [kit for kit in cabinet_komplekts(cabinets)
            if kit.get("kind") == "typical"]


def typical_cabinets(cabinets=None):
    """Типовые шкафы каталога — источники типовых комплектов."""
    if cabinets is None:
        import cabs as cabinet_catalog
        cabinets = cabinet_catalog.all_cabinets()
    return [cabinet for cabinet in cabinets
            if cabinet.get("standard_key") and _cabinet_kits(cabinet)]


# ---------------------------------------------------------------------------
# Пользовательский каталог
# ---------------------------------------------------------------------------
def _read_catalog():
    empty = {"custom": [], "overrides": {}, "deleted": []}
    if not os.path.exists(USER_CATALOG_PATH):
        return empty
    try:
        with open(USER_CATALOG_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return empty
    if not isinstance(data, dict):
        return empty
    data.setdefault("custom", [])
    data.setdefault("overrides", {})
    data.setdefault("deleted", [])
    return data


def _write_catalog(data):
    if not data["custom"] and not data["overrides"] and not data["deleted"]:
        if os.path.exists(USER_CATALOG_PATH):
            os.remove(USER_CATALOG_PATH)
        return
    with open(USER_CATALOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _merge_override(base, override):
    """Правка типового комплекта: меняются только поля комплекта."""
    entry = copy.deepcopy(base)
    for field in _OVERRIDABLE:
        if field in override:
            entry[field] = copy.deepcopy(override[field])
    return normalize_komplekt(entry)


def all_komplekts(cabinets=None):
    """Комплекты шкафов каталога + пользовательские (custom/other)."""
    user = _read_catalog()
    result = []
    for kit in cabinet_komplekts(cabinets):
        if kit["key"] in user["deleted"]:
            continue
        override = user["overrides"].get(kit["key"])
        if isinstance(override, dict):
            kit = _merge_override(kit, override)
        result.append(kit)
    for entry in user["custom"]:
        if not isinstance(entry, dict):
            continue
        if entry.get("key") in user["deleted"]:
            continue
        kit = normalize_komplekt(entry)
        kit["source"] = "user"
        result.append(kit)
    result.sort(key=lambda kit: (
        KIND_ORDER.index(kit["kind"]) if kit["kind"] in KIND_ORDER else 9,
        kit.get("cabinet_code") or kit.get("cabinet_name") or "",
        kit.get("name") or "",
    ))
    return result


def find_komplekt(key, cabinets=None):
    if not key:
        return None
    for kit in all_komplekts(cabinets):
        if kit.get("key") == key:
            return kit
    return None


def _make_key(entry):
    base = " ".join(str(entry.get(field) or "") for field in
                    ("cabinet_code", "name")).strip() or "komplekt"
    slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", base).strip("-").lower()
    slug = slug or "komplekt"
    existing = {kit.get("key") for kit in all_komplekts()}
    key = slug
    while key in existing:
        key = "{}-{}".format(slug, uuid.uuid4().hex[:4])
    return key


def save_komplekt(definition, original_key=None):
    """Создаёт или изменяет комплект. Возвращает ключ сохранённого комплекта."""
    user = _read_catalog()
    entry = normalize_komplekt(definition)
    key = original_key or entry.get("key") or ""

    # Новый типовой комплект не дублируем: он уже есть у шкафа-источника,
    # поэтому сохраняем правку этого комплекта (наложение).
    if (not key and entry["kind"] == "typical" and entry["cabinet_key"]):
        linked = typical_key(entry["cabinet_key"], entry.get("cabinet_index") or 0)
        if find_komplekt(linked) is not None:
            key = linked

    current = find_komplekt(key) if key else None

    if current is not None and current.get("source") == "cabinet":
        # Типовой комплект из шкафа: правим только поля комплекта.
        user["overrides"][key] = {field: copy.deepcopy(entry[field])
                                  for field in _OVERRIDABLE}
        user["deleted"] = [item for item in user["deleted"] if item != key]
        _write_catalog(user)
        return key

    if not key or (current is None and not is_typical_key(key)):
        key = _make_key(entry)
    entry["key"] = key
    if entry["kind"] == "typical" and not entry["cabinet_key"]:
        entry["kind"] = "custom"
    entry["source"] = "user"

    replaced = False
    for index, kit in enumerate(user["custom"]):
        if kit.get("key") == key:
            user["custom"][index] = entry
            replaced = True
            break
    if not replaced:
        user["custom"].append(entry)
    user["deleted"] = [item for item in user["deleted"] if item != key]
    _write_catalog(user)
    return key


def delete_komplekt(key):
    """Удаляет комплект. Типовые комплекты удалить нельзя — вернёт False."""
    entry = find_komplekt(key)
    if entry is None:
        return False
    if entry.get("source") == "cabinet":
        return False
    user = _read_catalog()
    user["custom"] = [kit for kit in user["custom"]
                      if kit.get("key") != key]
    user["overrides"].pop(key, None)
    _write_catalog(user)
    return True


def duplicate_komplekt(key):
    """Копия комплекта как нетиповой. Возвращает ключ копии."""
    source = find_komplekt(key)
    if source is None:
        return None
    entry = copy.deepcopy(source)
    entry["key"] = ""
    entry["source"] = "user"
    entry["kind"] = "custom"
    entry["cabinet_key"] = ""
    entry["cabinet_index"] = 0
    entry["cabinet_code"] = ""
    entry["cabinet_name"] = ""
    entry["cabinet_group"] = ""
    entry["name"] = "{} (копия)".format(entry.get("name") or "Комплект")
    return save_komplekt(entry, None)


def reset_user_catalog():
    """Удаляет пользовательские комплекты и правки типовых."""
    if os.path.exists(USER_CATALOG_PATH):
        os.remove(USER_CATALOG_PATH)


# ---------------------------------------------------------------------------
# Комплект внутри шкафа схемы
# ---------------------------------------------------------------------------
def for_cabinet(definition):
    """Копия комплекта для хранения в шкафу схемы.

    Ключ сохраняется для связи с каталогом, но вид и поля комплекта в шкафу
    можно менять свободно: это уже не каталожная запись, а копия.
    """
    entry = normalize_komplekt(definition)
    entry["source"] = "cabinet_entry"
    return copy.deepcopy(entry)


def normalize_komplets(komplets, default_kind=None, cabinet=None):
    """Нормализует комплекты шкафа; при известном шкафе — проставляет ссылки."""
    result = [normalize_komplekt(komplekt, default_kind)
              for komplekt in (komplets or [])]
    if cabinet:
        link_komplets_to_cabinet(result, cabinet)
    return result


def test_blocks_summary(entry):
    """Краткая подпись блоков для шкафа на схеме: «U2/I1» или «»."""
    blocks = normalize_test_blocks(entry.get("test_blocks"))
    parts = []
    for side, prefix in (("voltage", "U"), ("current", "I")):
        if blocks[side]["count"]:
            parts.append("{}{}".format(prefix, blocks[side]["count"]))
    return "/".join(parts)
