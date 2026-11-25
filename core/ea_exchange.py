#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Выгрузка и загрузка шкафов, комплектов, блоков и функций в отдельный JSON.

Файл обмена — небольшой автономный документ::

    {
      "format": "ea-objects",
      "version": 1,
      "source": "СТО ...json",
      "objects": [
        {"kind": "cabinet", "label": "Шкаф ...", "data": {...}},
        {"kind": "kit", "label": "Комплект 1", "data": {...}},
        {"kind": "functional_block", "label": "...",
         "origin": "catalog", "data": {...}}
      ]
    }

В ``data`` лется обычный объект стандарта: exported-копия узла дерева.
При загрузке объекты помещаются в текущий стандарт:

* ``cabinet`` — в ``Standard.cabinets``;
* ``kit`` — в ``Cabinet.kits`` выбранного шкафа;
* ``functional_block`` — в каталог ``Standard.functional_blocks`` либо в
  ``IED.function_blocks`` (если указан владелец ИЭУ);
* ``function`` — в ``functions`` выбранного блока / функционального блока.

Модуль не зависит от Tk: редактор только подставляет диалоги и владельцев.
"""

from __future__ import annotations

import copy
import json
import os

import ea_merge as em
import ea_model as eem
import ea_structure as st

#: Имя формата в файле — защищает от случайной загрузки стандарта целиком.
FORMAT = "ea-objects"
VERSION = 1

#: Виды узлов дерева редактора, которые можно выгружать.
NODE_KINDS = {
    "cabinet": "cabinet",
    "kit": "kit",
    "fb_entry": "functional_block",
    "block": "functional_block",
    "function": "function",
}

KIND_LABELS = {
    "cabinet": "шкаф",
    "kit": "комплект",
    "functional_block": "функциональный блок",
    "function": "функция",
}

_CONTEXT_KEYS = ("cabinet", "kit", "ied")


class ExchangeError(st.StructureError):
    """Неверный файл обмена или невозможность загрузить объекты."""


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _contains(container, target, seen=None):
    """Есть ли ``target`` внутри ``container`` по идентичности объектов."""
    if container is target:
        return True
    if not isinstance(container, (dict, list, tuple)):
        return False
    seen = set() if seen is None else seen
    marker = id(container)
    if marker in seen:
        return False
    seen.add(marker)
    values = container.values() if isinstance(container, dict) else container
    for value in values:
        if isinstance(value, (dict, list, tuple)) and _contains(
                value, target, seen):
            return True
    return False


def label_of(kind, item):
    """Читаемая подпись объекта для файла и сообщений."""
    item = item if isinstance(item, dict) else {}
    if kind == "cabinet":
        return "Шкаф %s" % (item.get("cypher") or "без шифра")
    if kind == "kit":
        return "Комплект %s" % (item.get("number") or "без номера")
    if kind == "functional_block":
        return "Функциональный блок %s" % (
            eem.block_label(item) or "без имени")
    if kind == "function":
        return "Функция %s" % (item.get("name") or "без имени")
    return str(KIND_LABELS.get(kind, kind))


def _record(kind, item, origin=None, context=None):
    data = copy.deepcopy(item)
    record = {
        "kind": kind,
        "label": label_of(kind, item),
        "data": data,
    }
    if kind == "functional_block":
        record["origin"] = origin or "catalog"
        if origin == "catalog":
            # Плоский каталог хранит принадлежность рядом с блоком.
            for key in _CONTEXT_KEYS:
                if key in data:
                    record[key] = data[key]
    return record


def collect(nodes):
    """Собрать записи для выгрузки из узлов дерева редактора.

    ``nodes`` — список кортежей ``("cabinet", item, …)``, как в
    ``StandardEditorWindow._nodes``. Если выделены одновременно шкаф и его
    комплект (или блок и функция), вложенный объект выгружается один раз
    вместе с родителем.
    """
    candidates = []
    for node in nodes:
        if not node:
            continue
        kind = NODE_KINDS.get(node[0])
        item = node[1] if len(node) > 1 else None
        if not kind or not isinstance(item, dict):
            continue
        origin = ("catalog" if node[0] == "fb_entry" else "ied"
                  if node[0] == "block" else None)
        candidates.append((kind, item, origin))
    records = []
    for index, (kind, item, origin) in enumerate(candidates):
        if any(other_item is not item
               and _contains(other_item, item)
               for other_kind, other_item, _origin in candidates):
            continue
        records.append(_record(kind, item, origin))
    return records


def save(path, records, source=None):
    """Записать объекты в отдельный JSON-файл."""
    if not records:
        raise ExchangeError("нечего выгружать: выберите шкаф, комплект, "
                            "функциональный блок или функцию")
    payload = {
        "format": FORMAT,
        "version": VERSION,
        "objects": list(records),
    }
    if source:
        payload["source"] = os.path.basename(str(source))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def normalize(payload):
    """Проверить загруженный JSON и привести записи к рабочему виду."""
    if not isinstance(payload, dict):
        raise ExchangeError("файл обмена должен содержать объект JSON")
    if payload.get("format") != FORMAT:
        raise ExchangeError("это не файл обмена объектами стандарта "
                            "(format = %r)" % payload.get("format"))
    if payload.get("version") != VERSION:
        raise ExchangeError("неподдерживаемая версия файла обмена: %r"
                            % payload.get("version"))
    objects = payload.get("objects")
    if not isinstance(objects, list) or not objects:
        raise ExchangeError("в файле обмена нет объектов")
    records = []
    for index, raw in enumerate(objects, 1):
        if not isinstance(raw, dict):
            raise ExchangeError("объект %d: ожидается объект JSON" % index)
        kind = raw.get("kind")
        if kind not in KIND_LABELS:
            raise ExchangeError("объект %d: неизвестный вид %r"
                                % (index, kind))
        data = raw.get("data")
        if not isinstance(data, dict):
            raise ExchangeError("объект %d (%s): нет данных"
                                % (index, KIND_LABELS[kind]))
        if kind == "cabinet" and not str(data.get("cypher") or "").strip():
            raise ExchangeError("объект %d: у шкафа нет шифра" % index)
        record = {
            "kind": kind,
            "label": str(raw.get("label") or label_of(kind, data)),
            "data": copy.deepcopy(data),
        }
        if kind == "functional_block":
            record["origin"] = raw.get("origin") or "catalog"
            for key in _CONTEXT_KEYS:
                if key in raw:
                    record[key] = raw[key]
            record["data"] = eem.normalize_function_block(record["data"])
        elif kind == "function":
            record["data"] = eem.normalize_function(record["data"])
        records.append(record)
    return records


def load(path):
    """Прочитать и проверить файл обмена."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError) as exc:
        raise ExchangeError("не удалось прочитать файл: %s" % exc)
    except ValueError as exc:
        raise ExchangeError("файл не является корректным JSON: %s" % exc)
    return normalize(payload)


# ---------------------------------------------------------------------------
# Загрузка в стандарт
# ---------------------------------------------------------------------------
def _place_cabinet(data, record):
    item = record["data"]
    cypher = str(item.get("cypher") or "").strip()
    code = em.norm_cypher(cypher)
    cabinets = data.setdefault("cabinets", [])
    if any(em.norm_cypher(value.get("cypher")) == code
           for value in cabinets if isinstance(value, dict)):
        raise ExchangeError("шкаф %s уже есть в стандарте" % cypher)
    st.add(cabinets, item)
    return item


def _place_kit(data, record, cabinet):
    if not isinstance(cabinet, dict):
        raise ExchangeError("для загрузки комплекта нужен шкаф")
    item = record["data"]
    kits = cabinet.setdefault("kits", [])
    number = str(item.get("number") or "")
    if number and any(str(value.get("number") or "") == number
                      for value in kits if isinstance(value, dict)):
        item["number"] = st.next_number(kits)
    st.add(kits, item)
    return item


def _place_functional_block(data, record, owner):
    block = eem.normalize_function_block(record["data"])
    if isinstance(owner, dict):
        # Владелец уже живёт в стандарте: просто добавляем блок к нему.
        if "function_blocks" not in owner and "functions" in owner:
            owner["function_blocks"] = eem.function_blocks(owner)
            owner.pop("functions", None)
        blocks = owner.setdefault("function_blocks", [])
        st.add(blocks, block)
        return block
    entry = st.new_functional_block_entry(
        data, block,
        cabinet=record.get("cabinet") or "",
        kit=record.get("kit") or "",
        ied=record.get("ied") or "")
    st.add(data.setdefault("functional_blocks", []), entry)
    return entry


def _place_function(data, record, owner):
    if not isinstance(owner, dict):
        raise ExchangeError("для загрузки функции нужен блок или "
                            "функциональный блок")
    function = eem.normalize_function(record["data"])
    st.add(owner.setdefault("functions", []), function)
    return function


def apply(data, records, cabinet=None, fb_owner=None, function_owner=None):
    """Добавить загруженные объекты в ``data`` (на месте).

    ``cabinet`` — владелец комплектов, ``fb_owner`` — ИЭУ для блоков функций
    (без него блоки идут в плоский каталог), ``function_owner`` — блок для
    отдельных функций. При ошибке стандарт остаётся без изменений.

    Возвращает ``{"data", "created", "counts"}``.
    """
    if not isinstance(data, dict):
        raise ExchangeError("стандарт должен быть объектом JSON")
    if isinstance(records, dict):
        records = normalize(records)
    if not isinstance(records, list) or not records:
        raise ExchangeError("в файле обмена нет объектов")
    backup = copy.deepcopy(data)
    created = []
    counts = {}
    try:
        for record in records:
            kind = record["kind"]
            if kind == "cabinet":
                item = _place_cabinet(data, record)
            elif kind == "kit":
                item = _place_kit(data, record, cabinet)
            elif kind == "functional_block":
                item = _place_functional_block(data, record, fb_owner)
            else:
                item = _place_function(data, record, function_owner)
            created.append(item)
            counts[kind] = counts.get(kind, 0) + 1
    except Exception:
        data.clear()
        data.update(backup)
        raise
    return {"data": data, "created": created, "counts": counts}


def count_by_kind(records):
    """Сколько объектов каждого вида лежит в файле."""
    result = {}
    for record in records:
        kind = record["kind"]
        result[kind] = result.get(kind, 0) + 1
    return result
