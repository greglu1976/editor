#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Каталог и слияние шкафов из всех стандартов EA.

Диалог «Новый стандарт…» и редактор должны предлагать шкафы не только
текущего тома, а всех JSON папки ``EA/``. Шифры шкафов уникальны, но номера
таблиц-форм и рисунков повторяются в каждом томе (``5.2``, ``5.3``…), поэтому
при слиянии каждый перенесённый том сначала перенумеровывается в свой
уникальный диапазон: так текстовые ссылки «Таблица 5.x» не схлопываются.
Финальная сквозная нумерация собирает всё в один ряд ``5.2…``.

Модуль не зависит от Tk и тестируется напрямую.
"""

from __future__ import annotations

import copy
import os
import re

import ea_new_standard as ns
import ea_standard as es
import ea_structure as st


class MergeError(st.StructureError):
    """Ошибка чтения или слияния стандартов."""


_VOLUME = re.compile(r"т\.\s*(\d+)", re.IGNORECASE)

#: Канонические начальные номера для финальной сквозной нумерации.
CANONICAL_STARTS = {"subs": 3, "tables": 2, "figures": 1}

#: Шаг уникального диапазона при предварительной перенумерации тома.
_BAND = 1000

_CACHE = {"key": None, "entries": None}


def norm_cypher(value):
    """Нормализованный шифр для сравнения (без «ШЭТ» и пробелов)."""
    return ns.norm_cypher(value)


def volume_label(path):
    """«т. 1» / «т. 5» из имени файла; fallback — имя без расширения."""
    name = os.path.basename(path or "")
    match = _VOLUME.search(name)
    if match:
        return "т. " + match.group(1)
    return os.path.splitext(name)[0] or "стандарт"


def _cache_key(paths):
    state = []
    for path in paths:
        try:
            info = os.stat(path)
            state.append((path, int(info.st_mtime), info.st_size))
        except OSError:
            state.append((path, -1, -1))
    return tuple(state)


def catalog(paths=None, use_cache=True):
    """Все шкафы всех стандартов: ``[{"cypher","name","path","volume","data"}]``.

    Один том загружается один раз. Повторные вызовы берут данные из кэша,
    пока файлы не изменились. При совпадении шифров побеждает первый файл
    по порядку ``es.files()``.
    """
    paths = list(paths) if paths is not None else es.files()
    key = _cache_key(paths)
    if use_cache and _CACHE["key"] == key and _CACHE["entries"] is not None:
        return list(_CACHE["entries"])

    entries = []
    seen = set()
    for path in paths:
        try:
            data = es.load(path)
        except (OSError, ValueError):
            continue
        volume = volume_label(path)
        for item in es.cabinets(data):
            cypher = str(item.get("cypher") or "").strip()
            code = norm_cypher(cypher)
            if not code or code in seen:
                continue
            seen.add(code)
            entries.append({
                "cypher": cypher,
                "name": str(item.get("name") or ""),
                "path": path,
                "volume": volume,
                "data": data,
            })
    if use_cache:
        _CACHE["key"] = key
        _CACHE["entries"] = list(entries)
    return entries


def load_catalog_cached():
    """Каталог с кэшированием (для диалогов)."""
    return catalog(use_cache=True)


def cabinet_subsections_of(data, cypher):
    """Подразлы, где лежат таблицы-формы шкафа ``cypher``."""
    result = []
    for sub in ns.cabinet_subsections(data):
        if any(str(table.get("cabinet") or "").strip() == cypher
               for table in sub.get("tables") or []):
            result.append(sub)
    return result


def _target_section(data):
    """Раздел, куда кладутся подразделы шкафов (обычно «5»)."""
    for section in es.sections(data):
        for sub in section.get("subsections") or []:
            if any(table.get("cabinet") for table in sub.get("tables") or []):
                return section
    for section in es.sections(data):
        if str(section.get("number") or "").strip() == "5":
            return section
    section = {
        "number": "5", "header": "Шкафы",
        "header_style": "ДОК Заголовок вкл в содержание",
        "content": "", "subsections": [], "tables": [], "figures": [],
    }
    data.setdefault("sections", []).append(section)
    return section


def _copy_common_rows(data, source, cypher):
    """Перенести из общих таблиц строки, где упомянут новый шкаф."""
    codes = [cypher]
    by_key = {}
    for table in es.iter_tables(data):
        if not table.get("cabinet"):
            key = (str(table.get("number") or ""),
                   str(table.get("name") or ""))
            by_key.setdefault(key, []).append(table)
    for table in es.iter_tables(source):
        if table.get("cabinet"):
            continue
        key = (str(table.get("number") or ""),
               str(table.get("name") or ""))
        for target in by_key.get(key, []):
            existing = {str(row.get("content") or "")
                        for row in target.get("rows") or []}
            for row in table.get("rows") or []:
                text = str(row.get("content") or "")
                if text in existing:
                    continue
                if not any(ns._mentions(text, codes)):
                    continue
                target.setdefault("rows", []).append(copy.deepcopy(row))
                existing.add(text)


def validate_merged(data):
    """Проверка результата слияния: структура + уникальность номеров.

    В отличие от :func:`ea_new_standard.validate`, не требует заполненных
    реквизитов (шифр, дата): слияние — структурная операция, реквизиты
    стандарта заполняются отдельно при creation.
    """
    problems = list(es.validate(data))
    cyphers = [str(item.get("cypher") or "")
               for item in es.cabinets(data)]
    repeated = sorted({code for code in cyphers if cyphers.count(code) > 1})
    if repeated:
        problems.append("повторяются шифры шкафов: %s" % ", ".join(repeated))
    numbers = [str(table.get("number") or "")
               for table in es.iter_tables(data) if table.get("cabinet")]
    repeated = sorted({number for number in numbers
                       if numbers.count(number) > 1})
    if repeated:
        problems.append("повторяются номера таблиц: %s"
                        % ", ".join(repeated[:10]))
    return problems


def merge_cabinets(target, additions, starts=None):
    """Вернуть копию ``target`` со шкафами и формами из ``additions``.

    ``additions`` — список записей каталога (или dict с ключами ``cypher``
    и ``data``). Шкафы, уже присутствующие в ``target``, пропускаются: их
    карточки и формы там уже есть. Для каждого нового шкафа исходный том
    перенумеровывается в уникальный диапазон, из него берутся карточка,
    подраздел с таблицами и рисунками, затем всё сводится в сквозной ряд.
    """
    if not isinstance(target, dict):
        raise MergeError("целевой стандарт должен быть объектом JSON")
    data = copy.deepcopy(target)
    final_starts = dict(starts or CANONICAL_STARTS)
    existing = {norm_cypher(item.get("cypher"))
                for item in es.cabinets(data)}
    section = _target_section(data)
    added = []

    for index, addition in enumerate(additions or []):
        cypher = str(addition.get("cypher") or "").strip()
        code = norm_cypher(cypher)
        if not code or code in existing:
            continue
        source = addition.get("data")
        if not isinstance(source, dict):
            raise MergeError("нет данных стандарта для шкафа %s" % cypher)
        if es.cabinet(source, cypher) is None:
            raise MergeError("шкаф %s не найден в источнике" % cypher)

        work = copy.deepcopy(source)
        band = _BAND * (index + 1)
        ns.renumber_standard(work, starts={"subs": band, "tables": band,
                                           "figures": band})

        cabinet = es.cabinet(work, cypher)
        st.add(data.setdefault("cabinets", []), cabinet)
        subs = cabinet_subsections_of(work, cypher)
        target_subs = section.setdefault("subsections", [])
        for sub in subs:
            st.add(target_subs, sub)
        if not subs:
            raise MergeError("у шкафа %s нет таблиц-форм" % cypher)

        _copy_common_rows(data, work, cypher)
        existing.add(code)
        added.append(cypher)

    if added:
        ns.renumber_standard(data, starts=final_starts)
        problems = validate_merged(data)
        if problems:
            raise MergeError("после слияния невалидная структура: %s"
                             % "; ".join(problems[:5]))
    return data
