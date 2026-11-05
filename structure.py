# -*- coding: utf-8 -*-
"""Доступ редактора схем к структуре РЗА (structure.json, формат v3).

Формат — иерархия «контейнеры (КЭТ) → шкафы → комплекты → ИЭУ» (спецификация —
STRUCTURE.md, собирает ``tools/build_structure.py``). Правила модели:

* **шкаф состоит из комплектов** — поле «комплекты» есть у каждого шкафа,
  минимум одна запись; ИЭУ на уровне шкафа не хранится;
* **комплект бывает с ИЭУ или без** — обязательное поле «есть ИЭУ»;
  вложенное «иэу» — только у комплекта с ИЭУ;
* **единственное ИЭУ в описании шкафа входит в комплект** — сборщик
  переносит его и все сводные таблицы шкафа в запись этого комплекта/ИЭУ.

Файлы версии 2 читаются в режиме совместимости (признак «есть ИЭУ»
выводится из наличия вложенных ИЭУ). Идентификаторы записей —
ключи каталога редактора, поэтому структура стыкуется со схемой напрямую:

* шкаф на схеме:      ``element.cabinet_key``    →  ``structure.cabinet(key)``;
* комплект шкафа:     ``komplekts.typical_key(cabinet_key, index)``
                      (или ``element.komplekt_key`` без префикса ``typ:``/``cab:``)
                      →  ``structure.kit(kit_key)``;
* контейнер на схеме: ``element.container_key``  →  ``structure.container(key)``,
  шкафы контейнера — по списку id «шкафы» его записи (см. ``cabinets_of``).

Публичный интерфейс:

    available()            — есть ли читаемая структура;
    load(force=False)      — весь документ (кэшируется);
    reload()               — перечитать файл;
    container(key)         — запись контейнера или None;
    containers_of(key)     — контейнеры, в которые входит шкаф;
    cabinet(key)           — запись шкафа или None (по ключу или шифру);
    kit(key)               — запись комплекта или None;
    kit_for(cabinet_key, index)  — запись комплекта № index (0-based);
    kits_of(cabinet_key)   — вложенные записи комплектов шкафа;
    cabinets_of(keys)      — записи шкафов по списку ключей;
    ieds_of(kit)           — вложенные ИЭУ комплекта;
    has_ied(kit)           — есть ли у комплекта ИЭУ;
    cabinets()/containers()/kits()/ieds() — плоские списки для деревьев UI;
    labels(...)            — подписи узлов для окон приложения;
    path()                 — путь к файлу;
    summary()              — сводка по источникам и заполнению;
    format_record(rec)     — человекочитаемое представление записи;
    format_cabinet_full(k) — шкаф + комплекты + ИЭУ одним текстом;
    format_kit_full(k)     — комплект + ИЭУ в контексте шкафа;
    format_container(k)    — контейнер + шкафы + комплекты + ИЭУ;
    error()                — текст последней ошибки чтения.
"""

from __future__ import annotations

import json
import os
import re

import apppaths

HERE = apppaths.app_dir()
DEFAULT_PATH = os.path.join(HERE, "structure.json")

#: Разделы и служебные ключи формата v3.
ID_FIELD = "id"
NUMBER_FIELD = "номер"
SOURCE_FIELD = "источник"
HAS_IED_FIELD = "есть ИЭУ"      # обязательный признак комплекта
CONTAINER_SECTION = "контейнеры"
CABINET_SECTION = "шкафы"
KITS_FIELD = "комплекты"        # вложенные комплекты в записи шкафа
IEDS_FIELD = "иэу"              # вложенные ИЭУ в записи комплекта
CONTAINERS_FIELD = "контейнеры"  # обратная ссылка в записи шкафа
CABINETS_FIELD = "шкафы"        # ссылка в записи контейнера
SUPPORTED_VERSIONS = (2, 3)

#: Служебные ключи: скрываются в текстовом представлении (id — контекст
#: записи; вложения «комплекты»/«шкафы» рендерит вызывающий код).
_SERVICE_FIELDS = frozenset((ID_FIELD, NUMBER_FIELD, KITS_FIELD,
                             CABINETS_FIELD))

_document = None
_document_path = None
_error = None
_index = None


def path():
    return _document_path or DEFAULT_PATH


def load(force=False, path=None):
    """Читает и кэширует structure.json; None, если файла нет/он испорчен."""
    global _document, _document_path, _error, _index
    target = path or DEFAULT_PATH
    if _document is not None and not force and target == (_document_path or target):
        return _document
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        _document, _document_path, _error, _index = None, None, (
            "structure.json не найден — соберите его скриптом "
            "tools/build_structure.py"), None
        return None
    except Exception as exc:
        _document, _document_path, _error, _index = None, None, (
            "structure.json: %s" % exc), None
        return None
    if not isinstance(data, dict) or not data.get(CABINET_SECTION):
        _document, _document_path, _error, _index = None, None, (
            "structure.json не содержит раздела «%s»" % CABINET_SECTION), None
        return None
    version = data.get("версия")
    if version is not None and version not in SUPPORTED_VERSIONS:
        _document, _document_path, _error, _index = None, None, (
            "structure.json устаревшего формата (версия %s, нужна 3) — "
            "пересоберите скриптом tools/build_structure.py" % version), None
        return None
    _index = _build_indexes(data)
    _document, _document_path, _error = data, target, None
    return data


def reload():
    return load(force=True)


def error():
    load()
    return _error


def available():
    return load() is not None


# ---------------------------------------------------------------------------
# Индексы (в модуле, не внутри документа)
# ---------------------------------------------------------------------------

def _build_indexes(document):
    """Индексы записей: по id, комплекты по шкафу, шкафы по шифру."""
    cabinets = document.get(CABINET_SECTION) or []
    containers_list = document.get(CONTAINER_SECTION) or []
    kits_by_id = {}
    kits_by_cabinet = {}
    for cabinet in cabinets:
        key = cabinet.get(ID_FIELD)
        kits = [kit for kit in (cabinet.get(KITS_FIELD) or [])
                if isinstance(kit, dict) and kit.get(ID_FIELD)]
        kits.sort(key=lambda k: k.get(NUMBER_FIELD) or 0)
        kits_by_cabinet[key] = kits
        for kit in kits:
            kits_by_id[kit[ID_FIELD]] = kit
    return {
        "cabinets_by_id": {c.get(ID_FIELD): c for c in cabinets
                           if c.get(ID_FIELD)},
        "containers_by_id": {c.get(ID_FIELD): c for c in containers_list
                             if c.get(ID_FIELD)},
        "kits_by_id": kits_by_id,
        "kits_by_cabinet": kits_by_cabinet,
        "cabinets_by_code": _codes_index(cabinets),
    }


def _codes_index(cabinets):
    codes = {}
    for cabinet in cabinets:
        code = re.sub(r"\s+", " ", (cabinet.get("шифр") or "")).strip().upper()
        if code:
            codes.setdefault(code, []).append(cabinet)
    return codes


def _by_code(document, code):
    key = re.sub(r"\s+", " ", (code or "")).strip().upper()
    entries = _index["cabinets_by_code"].get(key) or [] \
        if _index and document is _document else []
    return entries[0] if entries else None


def cabinet(cabinet_key):
    """Запись шкафа по ключу каталога (или по шифру, если ключ не найден)."""
    document = load()
    if not document:
        return None
    entry = _index["cabinets_by_id"].get(cabinet_key)
    return entry or _by_code(document, cabinet_key)


def kit(kit_key):
    document = load()
    if not document:
        return None
    return _index["kits_by_id"].get(kit_key)


def container(container_key):
    """Запись контейнера КЭТ по ключу каталога."""
    load()
    return (_index or {}).get("containers_by_id", {}).get(container_key)


def normalize_kit_key(kit_key, cabinet_key=None, index=None):
    """Ключ комплекта из ключа элемента схемы.

    Элемент схемы хранит «typ:шкаф:номер» / «cab:шкаф:номер» или просто
    «шкаф#номер»; всё это сводится к id записи комплекта.
    """
    text = str(kit_key or "")
    if text.startswith("typ:") or text.startswith("cab:"):
        return text
    if "#" in text and cabinet_key and text.startswith(cabinet_key):
        try:
            return "typ:%s:%d" % (cabinet_key, int(text.split("#", 1)[1]))
        except ValueError:
            return text
    if cabinet_key is not None and index is not None:
        return "typ:%s:%d" % (cabinet_key, int(index))
    return text


def kit_for(cabinet_key, index):
    document = load()
    if not document:
        return None
    entry = _index["kits_by_id"].get(
        normalize_kit_key(None, cabinet_key, index))
    if entry:
        return entry
    kits = _index["kits_by_cabinet"].get(cabinet_key) or []
    if 0 <= int(index) < len(kits):
        return kits[int(index)]
    return None


def kits_of(cabinet_key):
    document = load()
    if not document:
        return []
    return list(_index["kits_by_cabinet"].get(cabinet_key) or [])


def containers_of(cabinet_key):
    """Записи контейнеров, в которые входит шкаф (по обратной ссылке)."""
    entry = cabinet(cabinet_key)
    result = []
    for key in (entry or {}).get(CONTAINERS_FIELD) or []:
        record = container(key)
        if record:
            result.append(record)
    return result


def cabinets_of(keys):
    """Записи шкафов по списку ключей (слоты контейнера КЭТ)."""
    return [entry for entry in (cabinet(key) for key in (keys or [])) if entry]


# ---------------------------------------------------------------------------
# Модель «шкаф → комплекты → ИЭУ»: доступ из окон приложения
# ---------------------------------------------------------------------------

def ieds_of(kit_record):
    """Вложенные ИЭУ комплекта; у комплекта без ИЭУ — пустой список."""
    return [ied for ied in (kit_record or {}).get(IEDS_FIELD) or []
            if isinstance(ied, dict)]


def has_ied(kit_record):
    """Есть ли у комплекта ИЭУ (v3 — по флагу, v2 — по вложению)."""
    if not kit_record:
        return False
    flag = kit_record.get(HAS_IED_FIELD)
    return bool(ieds_of(kit_record)) if flag is None else bool(flag)


def cabinets():
    """Все записи шкафов документа."""
    return list((load() or {}).get(CABINET_SECTION) or [])


def containers():
    """Все записи контейнеров КЭТ."""
    return list((load() or {}).get(CONTAINER_SECTION) or [])


def kits():
    """Все комплекты всех шкафов (плоский список)."""
    return [kit for cabinet in cabinets()
            for kit in cabinet.get(KITS_FIELD) or []
            if isinstance(kit, dict)]


def ieds():
    """Все ИЭУ всех комплектов (плоский список)."""
    return [ied for kit in kits() for ied in ieds_of(kit)]


def cabinet_of_kit(kit_key):
    """Запись шкафа, которому принадлежит комплект, или None."""
    target = kit(kit_key)
    if not target:
        return None
    return next((cabinet for cabinet in cabinets()
                 if any(item.get(ID_FIELD) == target.get(ID_FIELD)
                        for item in cabinet.get(KITS_FIELD) or [])), None)


def cabinet_label(record):
    """Подпись шкафа для дерева: «ШЭТ 211.01-1 — название»."""
    record = record or {}
    code = (record.get("шифр") or "").strip()
    name = (record.get("наименование") or record.get("полное имя")
            or record.get(ID_FIELD) or "Шкаф").strip()
    return "%s — %s" % (code, name) if code else name


def kit_label(record):
    """Подпись комплекта: номер, имя, «с ИЭУ / без ИЭУ»."""
    record = record or {}
    number = record.get(NUMBER_FIELD)
    name = (record.get("полное имя") or "Комплект").strip()
    head = "Комплект %s · %s" % (number, name) if number else name
    ieds = ieds_of(record)
    if ieds:
        return "%s · с ИЭУ (%s)" % (
            head, ", ".join(str(ied.get("обозначение") or "ИЭУ")
                            for ied in ieds))
    return "%s · без ИЭУ" % head


def ied_label(record):
    """Подпись ИЭУ: «ИЭУ1 (МП РЗА)»."""
    record = record or {}
    name = (record.get("обозначение") or "ИЭУ").strip()
    kind = (record.get("тип") or "").strip()
    return "%s (%s)" % (name, kind) if kind else name


def container_label(record):
    """Подпись контейнера КЭТ."""
    record = record or {}
    code = (record.get("код") or "").strip()
    name = (record.get("название") or record.get(ID_FIELD) or "КЭТ").strip()
    return "%s — %s" % (code, name) if code else name


# ---------------------------------------------------------------------------
# Текстовое представление
# ---------------------------------------------------------------------------

def _clean_row(row):
    """Строка таблицы без пустых ячеек."""
    return {name: value for name, value in row.items()
            if value not in (None, "", [], {})}


def _render_row(row, indent):
    """Строка таблицы в одну строку текста: «поле: значение | …»."""
    parts = ["%s: %s" % (name, value)
             for name, value in _clean_row(row).items()]
    return "%s%s" % (indent, " | ".join(parts) if parts else indent.strip())


def _render_list(items, indent):
    return ["%s  • %s" % (indent, item) for item in items]


def _render_ied(record, indent, lines):
    """ИЭУ внутри комплекта: обозначение, таблицы, источник."""
    head = record.get("обозначение") or "ИЭУ"
    if record.get("тип"):
        head += " (%s)" % record["тип"]
    lines.append("%s  • ИЭУ: %s" % (indent, head))
    body = format_record(record, indent + "    ")
    if body:
        lines.append(body)


def format_record(record, indent="", show_tables=True):
    """Человекочитаемое представление записи (шкафа, комплекта, ИЭУ, КЭТ).

    Вложенные «комплекты»/«шкафы» не выводятся (их показывает вызывающий
    код); вложенные «иэу» выводятся как подпункты.
    """
    if not record:
        return ""
    lines = []
    for name, value in record.items():
        if name in _SERVICE_FIELDS:
            continue
        if name == CONTAINERS_FIELD:            # обратная ссылка шкафа
            if value:
                lines.append("%sвходит в КЭТ: %s" % (indent, ", ".join(value)))
            continue
        if name == IEDS_FIELD:                  # вложенные ИЭУ комплекта
            if show_tables:
                for ied in value or []:
                    _render_ied(ied, indent, lines)
            continue
        if name == SOURCE_FIELD:
            lines.append("%s%s: %s" % (indent, name, value))
            continue
        if isinstance(value, bool):
            lines.append("%s%s: %s" % (indent, name, "да" if value else "нет"))
            continue
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list) and value and all(
                isinstance(item, str) for item in value):
            lines.append("%s%s (%d):" % (indent, name, len(value)))
            lines.extend(_render_list(value, indent))
            continue
        if isinstance(value, list) and value and all(
                isinstance(item, dict) for item in value):
            lines.append("%s%s (%d):" % (indent, name, len(value)))
            if show_tables:
                for number, row in enumerate(value, start=1):
                    lines.append(_render_row(row, "%s  %s. " % (indent, number)))
            continue
        if isinstance(value, str) and "\n" in value:
            lines.append("%s%s:" % (indent, name))
            lines.extend("%s  %s" % (indent, line)
                         for line in value.split("\n"))
            continue
        lines.append("%s%s: %s" % (indent, name, value))
    return "\n".join(lines)


def kit_head(kit_entry, indent=""):
    """Заголовок комплекта с явным признаком «с ИЭУ / без ИЭУ»."""
    number = kit_entry.get(NUMBER_FIELD) or "?"
    name = kit_entry.get("полное имя") or "Комплект"
    count = len(ieds_of(kit_entry))
    composition = ("с ИЭУ (%s)" % ", ".join(
        str(ied.get("обозначение") or "ИЭУ")
        for ied in ieds_of(kit_entry))) if has_ied(kit_entry) else "без ИЭУ"
    return "%sКОМПЛЕКТ %s · %s · %s" % (indent, number, name, composition)


def format_cabinet_full(cabinet_key):
    """Шкаф + все его комплекты (в т. ч. без ИЭУ) одним текстом."""
    entry = cabinet(cabinet_key)
    if not entry:
        return ""
    text = [entry.get("полное имя") or entry.get("наименование")
            or entry.get(ID_FIELD)]
    text.append("Шкаф состоит из %d комплект(ов)" % len(kits_of(cabinet_key)))
    text.append("")
    text.append(format_record(entry))
    for kit_entry in entry.get(KITS_FIELD) or []:
        text.append("")
        text.append("—" * 60)
        text.append(kit_head(kit_entry))
        body = format_record(kit_entry)
        if body:
            text.append(body)
        if not has_ied(kit_entry):
            text.append("  (ИЭУ в составе комплекта нет)")
    return "\n".join(text)


def format_kit_full(kit_key):
    """Комплект + его ИЭУ в контексте шкафа (для окна просмотра)."""
    entry = kit(kit_key)
    if not entry:
        return ""
    parent = cabinet_of_kit(kit_key)
    text = []
    if parent:
        text.append("Шкаф: %s" % (parent.get("полное имя")
                                  or cabinet_label(parent)))
        text.append("Состав шкафа: %d комплект(ов)"
                    % len(parent.get(KITS_FIELD) or []))
        text.append("")
    text.append(kit_head(entry))
    text.append("")
    body = format_record(entry)
    if body:
        text.append(body)
    if not has_ied(entry):
        text.append("Комплект без ИЭУ: вложенных устройств нет.")
    return "\n".join(text)


def format_container(container_key):
    """Контейнер + его шкафы + комплекты + ИЭУ одним текстом."""
    entry = container(container_key)
    if not entry:
        return ""
    text = [container_label(entry), ""]
    text.append(format_record(entry))
    for cabinet_entry in cabinets_of(entry.get(CABINETS_FIELD)):
        text.append("")
        text.append("=" * 60)
        text.append("ШКАФ · %s" % cabinet_label(cabinet_entry))
        body = format_record(cabinet_entry)
        if body:
            text.append(body)
        for kit_entry in cabinet_entry.get(KITS_FIELD) or []:
            text.append("")
            text.append(kit_head(kit_entry, indent="  "))
            body = format_record(kit_entry, indent="  ")
            if body:
                text.append(body)
    return "\n".join(text)


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def _counted(entries, field):
    return sum(1 for entry in entries
               if entry.get(field) not in (None, "", [], {}))


def summary():
    """Текст: сколько записей, чем заполнено, из каких источников собрано."""
    document = load()
    if not document:
        return error() or "структура недоступна"
    containers_list = containers()
    cabinets_list = cabinets()
    kits_list = kits()
    ieds_list = ieds()
    with_ied = sum(1 for kit in kits_list if has_ied(kit))
    no_kits = [entry.get(ID_FIELD) for entry in cabinets_list
               if not entry.get(KITS_FIELD)]
    lines = ["Файл: %s (версия %s)" % (path(), document.get("версия") or "?"),
             "Модель: КЭТ → шкафы → комплекты → ИЭУ",
             "Контейнеров: %d, шкафов: %d, комплектов: %d, ИЭУ: %d"
             % (len(containers_list), len(cabinets_list), len(kits_list),
                len(ieds_list)),
             "Комплектов с ИЭУ: %d, без ИЭУ: %d"
             % (with_ied, len(kits_list) - with_ied),
             "Шкафов без комплектов: %d%s"
             % (len(no_kits), " — %s" % ", ".join(no_kits[:5])
                if no_kits else ""),
             "Источники:"]
    for name, value in (document.get("источники") or {}).items():
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        lines.append("  • %s: %s" % (name, value or "—"))
    lines.append("")
    lines.append("Заполнение:")

    for field in ("назначение", "шифр", "защищаемый элемент",
                  "управляемый элемент", "вводы питания",
                  "основные компоненты"):
        lines.append("  шкаф · %s: %d / %d"
                     % (field, _counted(cabinets_list, field),
                        len(cabinets_list)))
    for field in ("входные аналоговые измерения", "внутренние дискретные цепи",
                  HAS_IED_FIELD):
        lines.append("  комплект · %s: %d / %d"
                     % (field,
                        sum(1 for kit in kits_list
                            if has_ied(kit)) if field == HAS_IED_FIELD
                        else _counted(kits_list, field),
                        len(kits_list)))
    for field in ("входные GOOSE", "выходные GOOSE",
                  "функциональные клавиши", "светодиодная сигнализация",
                  "команды управления от АСУ ТП", "отчеты в АСУ ТП"):
        lines.append("  ИЭУ · %s: %d / %d"
                     % (field, _counted(ieds_list, field), len(ieds_list)))
    return "\n".join(lines)


if __name__ == "__main__":  # быстрая проверка: python3 structure.py [ключ]
    import sys

    key = sys.argv[1] if len(sys.argv) > 1 else None
    if key and key.startswith("ket"):
        print(format_container(key))
    elif key and kit(key):
        print(format_kit_full(key))
    elif key:
        print(format_cabinet_full(key))
    else:
        print(summary())
