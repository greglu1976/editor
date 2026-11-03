# -*- coding: utf-8 -*-
"""Доступ редактора схем к структуре шкафов и комплектов (structure.json).

Файл собирает ``tools/build_structure.py`` по образцу ``standards/structure.json``:
плоские записи шкафов и комплектов, связанные по ключам. Идентификаторы записей —
это ключи каталога редактора, поэтому структура стыкуется со схемой напрямую:

* шкаф на схеме:  ``element.cabinet_key``  →  ``structure.cabinet(key)``;
* комплект шкафа: ``komplekts.typical_key(cabinet_key, index)``
  (или ``element.komplekt_key`` без префикса ``typ:``/``kit:``)
  →  ``structure.kit(kit_key)``;
* контейнер (КЭТ): его шкафы перебираются ключами слотов — см. ``cabinets_of``.

Публичный интерфейс:

    available()            — есть ли читаемая структура;
    load(force=False)      — весь документ (кэшируется);
    reload()               — перечитать файл;
    cabinet(key)           — запись шкафа или None;
    kit(key)               — запись комплекта или None;
    kit_for(cabinet_key, index)  — запись комплекта № index (0-based);
    kits_of(cabinet_key)   — записи комплектов шкафа;
    path()                 — путь к файлу;
    summary()              — сводка по источникам и заполнению;
    format_record(rec)     — человекочитаемое представление записи;
    error()                — текст последней ошибки чтения.
"""

from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, "structure.json")

#: Ключ записи — идентификатор; служебные поля начинаются с «_».
ID_FIELD = "id"

_document = None
_document_path = None
_error = None

CABINET_SECTION = "Шкаф"
KIT_SECTION = "комплекты"

#: Таблицы, которые показываются как таблицы (а не как список).
TABLE_FIELDS = (
    "Входные аналоговые измерения",
    "Внутренние дискретные цепи",
    "Входные GOOSE сообщения",
    "Выходные GOOSE сообщения",
    "Функциональные клавиши со светодиодной индикацией",
    "Светодиодная сигнализация",
    "Команды управления от АСУ ТП",
    "Аналоговые значения, формируемые ИЭУ",
    "Отчеты в АСУ ТП",
    "Основные компоненты шкафа",
    "Испытательные блоки шкафа",
    "Входные GOOSE сообщения (шкаф)",
    "Выходные GOOSE сообщения (шкаф)",
)


def path():
    return _document_path or DEFAULT_PATH


def load(force=False, path=None):
    """Читает и кэширует structure.json; None, если файла нет/он испорчен."""
    global _document, _document_path, _error
    target = path or DEFAULT_PATH
    if _document is not None and not force and target == (_document_path or target):
        return _document
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        _document, _document_path, _error = None, None, (
            "structure.json не найден — соберите его скриптом "
            "tools/build_structure.py")
        return None
    except Exception as exc:
        _document, _document_path, _error = None, None, "structure.json: %s" % exc
        return None
    if not isinstance(data, dict) or not data.get(CABINET_SECTION):
        _document, _document_path, _error = None, None, (
            "structure.json не содержит раздела «%s»" % CABINET_SECTION)
        return None
    _build_indexes(data)
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
# Индексы
# ---------------------------------------------------------------------------

def _build_indexes(document):
    cabinets = document.get(CABINET_SECTION) or []
    kits = document.get(KIT_SECTION) or []
    document["_cabinets_by_id"] = {c.get(ID_FIELD): c for c in cabinets
                                   if c.get(ID_FIELD)}
    document["_kits_by_id"] = {k.get(ID_FIELD): k for k in kits
                               if k.get(ID_FIELD)}
    kits_by_cabinet = {}
    for kit in kits:
        kits_by_cabinet.setdefault(kit.get(CABINET_SECTION), []).append(kit)
    for entry in kits_by_cabinet.values():
        entry.sort(key=lambda k: k.get("Номер комплекта") or 0)
    document["_kits_by_cabinet"] = kits_by_cabinet
    codes = {}
    for cabinet in cabinets:
        code = re.sub(r"\s+", " ", (cabinet.get("Шифр шкафа") or "")).strip().upper()
        if code:
            codes.setdefault(code, []).append(cabinet)
    document["_cabinets_by_code"] = codes


def _by_code(document, code):
    key = re.sub(r"\s+", " ", (code or "")).strip().upper()
    entries = (document.get("_cabinets_by_code") or {}).get(key) or []
    return entries[0] if entries else None


def cabinet(cabinet_key):
    """Запись шкафа по ключу каталога (или по шифру, если ключ не найден)."""
    document = load()
    if not document:
        return None
    entry = (document.get("_cabinets_by_id") or {}).get(cabinet_key)
    return entry or _by_code(document, cabinet_key)


def kit(kit_key):
    document = load()
    if not document:
        return None
    return (document.get("_kits_by_id") or {}).get(kit_key)


def normalize_kit_key(kit_key, cabinet_key=None, index=None):
    """Ключ комплекта структуры из ключа элемента схемы.

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
    entry = (document.get("_kits_by_id") or {}).get(
        normalize_kit_key(None, cabinet_key, index))
    if entry:
        return entry
    kits = (document.get("_kits_by_cabinet") or {}).get(cabinet_key) or []
    if 0 <= int(index) < len(kits):
        return kits[int(index)]
    return None


def kits_of(cabinet_key):
    document = load()
    if not document:
        return []
    return list((document.get("_kits_by_cabinet") or {}).get(cabinet_key) or [])


def cabinets_of(keys):
    """Записи шкафов по списку ключей (слоты контейнера КЭТ)."""
    return [entry for entry in (cabinet(key) for key in (keys or [])) if entry]


# ---------------------------------------------------------------------------
# Текстовое представление
# ---------------------------------------------------------------------------

def _is_table(value):
    return isinstance(value, dict) and all(
        str(k).isdigit() for k in value) and bool(value)


def _render_row(row, indent):
    if not isinstance(row, dict):
        return "%s%s" % (indent, row)
    parts = []
    for name, value in row.items():
        if value in (None, "", [], {}):
            continue
        parts.append("%s: %s" % (name, value))
    return "%s%s" % (indent, " | ".join(parts) if parts else indent.strip())


def format_record(record, indent="", show_tables=True):
    """Человекочитаемое представление записи структуры (шкафа или комплекта)."""
    if not record:
        return ""
    lines = []
    for name, value in record.items():
        if name.startswith("_") or name == ID_FIELD:
            continue
        if name.startswith("Комплект ") or name == "Шкаф":
            continue
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list) and value and all(
                isinstance(item, str) for item in value):
            lines.append("%s%s (%d):" % (indent, name, len(value)))
            lines.extend("%s  • %s" % (indent, item) for item in value)
            continue
        if isinstance(value, list) and value and all(
                isinstance(item, dict) for item in value):
            lines.append("%s%s (%d):" % (indent, name, len(value)))
            lines.extend(_render_row(item, indent + "  ") for item in value)
            continue
        if _is_table(value):
            lines.append("%s%s (%d):" % (indent, name, len(value)))
            if show_tables:
                for number in sorted(value, key=lambda x: int(x)):
                    lines.append(_render_row(value[number],
                                             "%s  %s. " % (indent, number)))
            continue
        if isinstance(value, str) and "\n" in value:
            lines.append("%s%s:" % (indent, name))
            lines.extend("%s  %s" % (indent, line) for line in value.split("\n"))
            continue
        lines.append("%s%s: %s" % (indent, name, value))
    return "\n".join(lines)


def format_cabinet_full(cabinet_key):
    """Шкаф + все его комплекты одним текстом (для окна просмотра)."""
    entry = cabinet(cabinet_key)
    if not entry:
        return ""
    text = [entry.get("Полное имя шкафа") or entry.get("Наименование шкафа")
            or entry.get(ID_FIELD)]
    text.append("")
    text.append(format_record(entry))
    for kit_entry in kits_of(entry.get(ID_FIELD)):
        text.append("")
        text.append("—" * 60)
        head = "КОМПЛЕКТ %s · %s" % (kit_entry.get("Номер комплекта"),
                                     kit_entry.get("Полное имя комплекта") or "")
        text.append(head)
        text.append(format_record(kit_entry))
    return "\n".join(text)


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def summary():
    """Текст: сколько записей, чем заполнено, из каких источников собрано."""
    document = load()
    if not document:
        return error() or "структура недоступна"
    cabinets = document.get(CABINET_SECTION) or []
    kits = document.get(KIT_SECTION) or []
    lines = ["Файл: %s" % path(),
             "Шкафов: %d, комплектов: %d" % (len(cabinets), len(kits)),
             "Источники:"]
    for name, value in (document.get("источники") or {}).items():
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        lines.append("  • %s: %s" % (name, value or "—"))
    lines.append("")
    lines.append("Заполнение:")

    def counted(entries, field):
        return sum(1 for entry in entries
                   if entry.get(field) not in (None, "", [], {}, "нет данных"))

    for field in ("Назначение шкафа", "Шифр шкафа", "Защищаемый элемент",
                  "Управляемый элемент",
                  "Вводы питания оперативного постоянного тока",
                  "Основные компоненты шкафа"):
        lines.append("  шкаф · %s: %d / %d" % (field, counted(cabinets, field),
                                               len(cabinets)))
    for field in TABLE_FIELDS[:9]:
        lines.append("  комплект · %s: %d / %d" % (field, counted(kits, field),
                                                   len(kits)))
    return "\n".join(lines)


if __name__ == "__main__":  # быстрая проверка: python3 structure.py [ключ]
    import sys

    key = sys.argv[1] if len(sys.argv) > 1 else None
    if key:
        print(format_cabinet_full(key))
    else:
        print(summary())
