#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мост «стандарт EA ↔ каталог шкафов редактора».

Стандарт в структуре EA (``EA/*.json``, см. :mod:`ea_standard`) хранит шкафы
сам, а редактор схем размещает шкафы из каталога :mod:`cabs`. Здесь шкаф
стандарта превращается в запись каталога — один раз, при первом размещении
на схеме.

Правила:

* если в каталоге уже есть шкаф с тем же шифром (и тем же стандартом), он и
  используется: запись не перезаписывается, чтобы не потерять правки
  пользователя и данные, которых в новой структуре нет (испытательные блоки);
* иначе запись собирается из полей шкафа EA и сохраняется через
  :func:`cabs.save_cabinet`;
* комплект для схемы (:func:`kit_entry`) собирается из комплекта EA, но
  запись каталога при этом не создаётся — её создаёт размещение шкафа;
* обратное направление — :func:`cabinet_from_catalog` и
  :func:`kit_from_catalog`: типовой шкаф или комплект каталога переносится
  в стандарт вместе с карточкой, комплектами, ИЭУ, измерениями и сигналами.

    python ea_catalog.py --check
    python ea_catalog.py --cabinet 431.11-1
"""

from __future__ import annotations

import argparse
import copy
import re
import sys

import cabs
import ea_standard as es
import ea_structure as st
import komplekts

#: Диапазон напряжения в области применения: «РУ 110–330 кВ» → «110–330 кВ».
_VOLTAGE_RE = re.compile(r"(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*кВ", re.IGNORECASE)


def _norm(value):
    """Текст для сравнения: без регистра, с едиными тире и без лишних пробелов."""
    text = str(value or "").lower().replace("ё", "е")
    for dash in ("\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Стандарт
# ---------------------------------------------------------------------------
def _words(text):
    return [word for word in re.split(r"[^0-9a-zа-я]+", _norm(text)) if word]


def _code_subset(ea_code, standard_code):
    """Слова кода стандарта входят в код стандарта EA.

    «СТО (проект, ред. 2)» — да, «СТО 56947007-33.040.20.280-2019» — нет.
    Нужно, чтобы отличить выпущенный СТО от проектного с тем же названием.
    """
    words = _words(standard_code)
    if not words:
        return False
    ea_words = set(_words(ea_code))
    return all(word in ea_words for word in words)


def standard_key(data):
    """Ключ стандарта каталога (``cabs.STANDARDS``) для стандарта EA.

    Сначала сравнивается код: он однозначен, если встречается у одного
    стандарта. У проектных СТО код общий («СТО (проект, ред. 2)»), поэтому
    дальше сравнивается полное наименование, а при нескольких совпадениях —
    код по значимым словам. Пустая строка — стандарт не найден; шкаф тогда
    попадает в группу «Прочие».
    """
    code = _norm((data or {}).get("code"))
    name = _norm((data or {}).get("name"))
    by_code = [key for key, standard in cabs.STANDARDS.items()
               if code and _norm(standard.get("code")) == code]
    if len(by_code) == 1:
        return by_code[0]
    by_name = [key for key, standard in cabs.STANDARDS.items()
               if name and _norm(standard.get("title")) == name]
    for key in by_name:
        if _code_subset(code, cabs.STANDARDS[key].get("code")):
            return key
    return by_name[0] if by_name else ""


def _table_refs(data, cypher):
    """Ссылка на первую таблицу документа, которая берёт данные из шкафа."""
    for table in es.iter_tables(data):
        if table.get("cabinet") != cypher:
            continue
        number = table.get("number") or ""
        if number:
            return "табл. %s" % number
    return ""


def _voltage(scope):
    match = _VOLTAGE_RE.search(str(scope or ""))
    if not match:
        return ""
    return "%s\u2013%s кВ" % (match.group(1), match.group(2))


def _function_names(ieds, flag="isMainFunction"):
    """Названия блоков функций ИЭУ без повторов (порядок — как в модели)."""
    names = []
    for ied in ieds:
        for block in es.function_blocks(ied):
            if not block.get(flag):
                continue
            name = (block.get("name")
                    or block.get("russian_path") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def function_names(kit, flag="isMainFunction"):
    """Названия функций комплекта без повторов (порядок — как в стандарте)."""
    ieds = [ied for ied in kit.get("ieds") or [] if isinstance(ied, dict)]
    return _function_names(ieds, flag)


def _analog(ieds):
    """Аналоговые измерения ИЭУ в формате комплекта каталога."""
    rows = []
    for ied in ieds:
        for item in ied.get("analog_inputs") or []:
            rows.append({
                "block": item.get("test_block") or "",
                "signals": item.get("circuit_type") or "",
                "contacts": item.get("contacts_count") or "",
                "note": item.get("note") or "",
            })
    return rows


# ---------------------------------------------------------------------------
# Записи каталога
# ---------------------------------------------------------------------------
def _kit_record(data, cabinet_item, kit):
    """Комплект шкафа EA в формате записи каталога (komplekts.py)."""
    standard = standard_key(data)
    ieds = [ied for ied in kit.get("ieds") or [] if isinstance(ied, dict)]
    functions = function_names(kit)
    if not functions:
        functions = function_names(kit, "isInITS")
    return {
        "key": "",
        "kind": "typical" if standard else "custom",
        "name": "Комплект %s" % (kit.get("number") or 1),
        "type": kit.get("type") or "МП РЗА",
        "functions": functions,
        "desc": (kit.get("description")
                 or cabinet_item.get("description") or ""),
        "has_ied": bool(ieds),
        "ieds": [{
            "name": "ИЭУ%s" % (ied.get("number") or index + 1),
            "type": "МП РЗА",
            "desc": "",
        } for index, ied in enumerate(ieds)],
        "analog_inputs": _analog(ieds),
    }


def catalog_record(data, cabinet_item):
    """Запись каталога шкафов по шкафу стандарта EA.

    Поля, которых в новой структуре нет (испытательные блоки, напряжение
    отдельным полем), не выдумываются: напряжение берётся из области
    применения, если она его содержит.
    """
    standard = standard_key(data)
    cypher = str(cabinet_item.get("cypher") or "").strip()
    name = str(cabinet_item.get("name") or "").strip()
    controlled = str(cabinet_item.get("controllable_element") or "").strip()
    record = {
        # Пустая строка, а не None: cabs._apply_standard_defaults иначе
        # привязывает шкаф к первому СТО («tat»).
        "standard_key": standard,
        "code": cypher,
        "name": name,
        "title": name,
        "description": cabinet_item.get("description") or "",
        "protected": cabinet_item.get("protected_element") or "",
        "controlled": [item.strip() for item in controlled.split(",")
                       if item.strip()],
        "its_functions": _function_names([
            ied for kit in cabinet_item.get("kits") or []
            for ied in kit.get("ieds") or [] if isinstance(ied, dict)]),
        "applicability": cabinet_item.get("scope") or "",
        "architecture": cabinet_item.get("architecture") or "",
        "source": _table_refs(data, cypher),
        "komplets": [_kit_record(data, cabinet_item, kit)
                     for kit in cabinet_item.get("kits") or []],
    }
    voltage = _voltage(cabinet_item.get("scope"))
    if voltage:
        record["voltage"] = voltage
    code = _norm((data or {}).get("code"))
    if "проект" in code:
        record["tags"] = [komplekts.TAG_UNRELEASED]
    return record


def find_catalog_cabinet(data, cabinet_item):
    """Шкаф каталога с тем же шифром или None (запись не создаётся)."""
    cypher = _norm(cabinet_item.get("cypher"))
    if not cypher:
        return None
    standard = standard_key(data)
    matches = []
    for cabinet in cabs.all_cabinets():
        if _norm(cabinet.get("code")) != cypher:
            continue
        if standard and cabinet.get("standard_key") not in ("", standard):
            continue
        matches.append(cabinet)
    if not matches:
        return None
    for cabinet in matches:
        if cabinet.get("standard_key") == standard:
            return cabinet
    return matches[0]


def ensure_catalog(data, cabinet_item):
    """Запись каталога для шкафа стандарта: существующая или новая.

    Существующая запись не меняется: в каталоге могут быть поля, которых в
    новой структуре нет. Возвращает запись каталога (с комплектами).
    """
    found = find_catalog_cabinet(data, cabinet_item)
    if found is not None:
        return found
    record = catalog_record(data, cabinet_item)
    key = cabs.save_cabinet(record)
    return cabs.find_cabinet(key) or record


def update_cabinet(data, cabinet_item):
    """Обновляет шкаф и его комплекты в каталоге по стандарту EA.

    Если шкаф с таким шифром уже есть в каталоге, обновляет его атрибуты
    и комплекты из стандарта, сбрасывая устаревшие переопределения
    типовых комплектов. Если шкафа нет — создаёт новую запись.
    Возвращает (key, created: bool).
    """
    found = find_catalog_cabinet(data, cabinet_item)
    rec = catalog_record(data, cabinet_item)
    if found is None:
        key = cabs.save_cabinet(rec)
        return key, True

    key = found["key"]
    merged = copy.deepcopy(found)
    for field in ("code", "name", "title", "description", "protected",
                  "controlled", "its_functions", "applicability",
                  "architecture", "source", "komplets", "standard_key"):
        if field in rec and rec[field]:
            merged[field] = copy.deepcopy(rec[field])
    if "voltage" in rec and rec["voltage"]:
        merged["voltage"] = rec["voltage"]
    if "tags" in rec:
        existing_tags = merged.get("tags") or []
        for tag in rec["tags"]:
            if tag not in existing_tags:
                existing_tags.append(tag)
        merged["tags"] = existing_tags

    saved_key = cabs.save_cabinet(merged, original_key=key)

    # В каталоге комплектов сбрасываем переопределения типовых комплектов этого шкафа
    try:
        user_k = komplekts._read_catalog()
        changed_k = False
        max_kits = max(len(merged.get("komplets") or []),
                       len(found.get("komplets") or [])) + 5
        for idx in range(max_kits):
            tkey = komplekts.typical_key(key, idx)
            if tkey in user_k.get("overrides", {}):
                del user_k["overrides"][tkey]
                changed_k = True
        if changed_k:
            komplekts._write_catalog(user_k)
    except Exception:
        pass

    return saved_key, False


def update_standard_cabinets(data):
    """Обновляет все шкафы и комплекты данного стандарта в каталоге редактора.

    Возвращает словарь со статистикой:
    {
        "updated": int,        # число обновлённых шкафов
        "created": int,        # число созданных шкафов
        "kits": int,           # суммарное число комплектов
        "cabinets": list[str], # шифры шкафов
    }
    """
    cabinets = es.cabinets(data)
    created_count = 0
    updated_count = 0
    total_kits = 0
    cyphers = []

    for item in cabinets:
        cypher = item.get("cypher") or ""
        key, is_new = update_cabinet(data, item)
        if is_new:
            created_count += 1
        else:
            updated_count += 1
        total_kits += len(item.get("kits") or [])
        if cypher:
            cyphers.append(cypher)

    return {
        "updated": updated_count,
        "created": created_count,
        "kits": total_kits,
        "cabinets": cyphers,
    }


# ---------------------------------------------------------------------------
# Комплекты: каталог → стандарт → схема
# ---------------------------------------------------------------------------
def _split_text(value):
    """«а; б; в» или список → список непустых строк."""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[;\n]+", str(value or ""))
            if part.strip()]


def test_block_components(cabinet, kit=None):
    """Строки «Основные компоненты» по испытательным блокам каталога.

    Испытательные блоки лежат отдельно от карточки (``cabs_signals.json``);
    если для шкафа их нет, берётся список блоков самого комплекта.
    """
    rows = []
    blocks = (cabs.signals_for(cabinet) or {}).get("test_blocks") or []
    for item in blocks:
        rows.append({
            "name": item.get("name") or "Испытательный блок",
            "description": item.get("spec") or "",
            "quantity": str(item.get("count") or ""),
        })
    if not rows:
        for item in (kit or {}).get("test_block_list") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "name": item.get("name") or "Испытательный блок",
                "description": item.get("circuits") or "",
                "quantity": str(item.get("count") or ""),
            })
    return rows


def add_test_blocks(cabinet, kit):
    """Дополнить компоненты шкафа испытательными блоками комплекта.

    Если в шкафу уже есть испытательные блоки, новые не добавляются: иначе
    повторное добавление комплекта удвоит строки таблицы компонентов.
    Возвращает список добавленных строк.
    """
    components = cabinet.get("components")
    if not isinstance(components, list):
        components = []
        cabinet["components"] = components
    if any("испытательн" in str(item.get("name") or "").lower()
           for item in components):
        return []
    added = []
    for row in test_block_components({"key": kit.get("cabinet_key")}, kit):
        components.append(row)
        added.append(row)
    return added


def _discrete_rows(signals):
    """Входные и выходные дискретные цепи из сигналов каталога."""
    rows = []
    for kind, direction in (("io_in", "Вход"), ("io_out", "Выход")):
        for item in signals.get(kind) or []:
            rows.append({
                "discrete_signal": item.get("name") or "",
                "direction": direction,
                "note": item.get("details") or "",
            })
    return rows


def _incoming_rows(signals):
    """Входящие GOOSE-сообщения из сигналов каталога."""
    return [{
        "signal": item.get("name") or "",
        "info_model": item.get("code") or "",
        "source": item.get("details") or "",
        "max_number": "",
        "source_number": None,
        "RAS": "-",
        "note": "",
    } for item in signals.get("goose_in") or []]


def _outgoing_dataset(signals):
    """Исходящие GOOSE-сообщения одним набором данных ИЭУ."""
    items = signals.get("goose_out") or []
    if not items:
        return []
    return [{
        "name": "Исходящие сообщения",
        "id": "",
        "sender": "",
        "class": "",
        "mapping": "",
        "note": "",
        "signals": [{
            "name": item.get("name") or "",
            "info_model": item.get("code") or "",
            "destination": item.get("details") or "",
            "note": "",
            "status": "",
            "KT": "",
            "cus": "",
            "rdu": "",
            "RAS": "",
            "DO": "",
            "DA": "",
        } for item in items],
    }]


def kit_from_catalog(kit, number=None, cabinet=None):
    """Типовой комплект каталога в формате комплекта стандарта EA.

    Обратная сторона :func:`_kit_record`: функции, аналоговые измерения и
    состав ИЭУ переносятся в комплект. Если передан шкаф каталога, в первое
    ИЭУ попадают ещё и сигналы из ``cabs_signals.json``: дискретные цепи,
    входящие GOOSE и исходящие сообщения. Происхождение сохраняется в
    описании, если у комплекта нет своего описания.
    """
    entry = komplekts.normalize_komplekt(kit)
    description = entry.get("desc") or ""
    if not description:
        description = "Типовой комплект «{}» шкафа {}".format(
            entry.get("name") or "Комплект",
            entry.get("cabinet_code") or entry.get("cabinet_name") or "—")
    result = {
        "number": number if number is not None else 1,
        "description": description,
        "type": entry.get("type") or "ИЭУ",
        "tag": ", ".join(komplekts.tags_of(entry)),
        "group": entry.get("cabinet_group") or "",
        "ieds": [],
    }
    functions = [{
        "name": name,
        "russian_path": name,
        "isMainFunction": True,
        "isInITS": False,
        "iec_name": "",
        "corp_prof_name": "",
        "functions": [{
            "name": name,
            "iec_name": "",
            "LNclass": "",
            "inputs": [],
            "outputs": [],
            "settings": [],
            "parameters": [],
        }],
    } for name in entry.get("functions") or []]
    analog = [{
        "circuit_type": row.get("signals") or "",
        "test_block": row.get("block") or "",
        "contacts_count": row.get("contacts") or "",
        "note": row.get("note") or "",
    } for row in entry.get("analog_inputs") or [] if isinstance(row, dict)]
    signals = cabs.signals_for(cabinet) if cabinet else {}
    ports = [{"description": text}
             for text in _split_text((cabinet or {}).get("ports"))]
    for index, ied in enumerate(komplekts.effective_ieds(entry)):
        record = st.new_ied(None, result, number=index + 1)
        if index == 0:
            record["function_blocks"] = copy.deepcopy(functions)
            record["analog_inputs"] = copy.deepcopy(analog)
            if ports:
                record["ports"] = copy.deepcopy(ports)
            if signals:
                record["inner_discrete_circuits"] = _discrete_rows(signals)
                record["incoming_goose_signals"] = _incoming_rows(signals)
                record["datasets"] = _outgoing_dataset(signals)
        result["ieds"].append(record)
    return result


def cabinet_from_catalog(cabinet):
    """Типовой шкаф каталога → карточка шкафа стандарта EA.

    Переносятся реквизиты карточки, вводы питания, испытательные блоки и
    комплекты со своими ИЭУ, функциями, аналоговыми измерениями и сигналами.
    Такой карточке хватает данных, чтобы таблицы-формы стандарта показали
    содержимое шкафа без ручного заполнения.
    """
    if not isinstance(cabinet, dict):
        raise ValueError("ожидалась запись каталога шкафов")
    cypher = str(cabinet.get("code") or "").strip()
    if not cypher:
        raise ValueError("у шкафа каталога нет шифра")
    controlled = cabinet.get("controlled") or []
    components = []
    seen = set()
    for kit in cabinet.get("komplets") or []:
        for row in test_block_components(cabinet, kit):
            key = (row["name"], row["description"], row["quantity"])
            if key in seen:
                continue
            seen.add(key)
            components.append(row)
    card = {
        "cypher": cypher,
        "architecture": cabinet.get("architecture") or "",
        "name": cabinet.get("name") or cabinet.get("title") or "",
        "controllable_element": ", ".join(_split_text(controlled)),
        "protected_element": cabinet.get("protected") or "",
        "scope": cabinet.get("applicability") or cabinet.get("voltage") or "",
        "description": cabinet.get("description") or "",
        "type": "ШЭТ" if cabinet.get("standard_key") else "",
        "group": cabinet.get("group") or "",
        "tag": ", ".join(komplekts.tags_of(cabinet)),
        "power_supplies": [{"purpose": text} for text in
                           _split_text(cabinet.get("power_supply"))],
        "components": components,
        "terminal_blocks": [],
        "containers": list(cabinet.get("containers") or []),
        "kits": [],
    }
    for index, kit in enumerate(cabinet.get("komplets") or []):
        card["kits"].append(kit_from_catalog(kit, number=index + 1,
                                             cabinet=cabinet))
    if not card["kits"]:
        card["kits"].append(st.new_kit(None, card, number=1))
    return card


def kit_entry(data, cabinet_item, kit):
    """Комплект стандарта в виде, который принимает шкаф на схеме.

    Запись каталога не создаётся: если шкаф ещё не размещался, ссылки на
    каталог остаются пустыми, а сам комплект — типовой.
    """
    record = find_catalog_cabinet(data, cabinet_item) or {}
    entry = _kit_record(data, cabinet_item, kit)
    entry["key"] = ""
    entry["cabinet_key"] = record.get("key", "")
    entry["cabinet_code"] = record.get("code") or cabinet_item.get("cypher", "")
    entry["cabinet_name"] = record.get("name") or cabinet_item.get("name", "")
    entry["cabinet_group"] = record.get("group", "")
    entry["cabinet_index"] = int(kit.get("number") or 0)
    entry["source"] = "ea_standard"
    return komplekts.for_cabinet(entry)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_check(data):
    problems = 0
    for item in es.cabinets(data):
        cypher = item.get("cypher", "")
        found = find_catalog_cabinet(data, item)
        if found is not None:
            print("  есть  %-16s %s" % (cypher, found.get("key")))
            continue
        record = catalog_record(data, item)
        print("  новый %-16s стандарт «%s», комплектов %d"
              % (cypher, record.get("standard_key") or "—",
                 len(record.get("komplets") or [])))
        if not record.get("komplets"):
            problems += 1
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Шкафы стандарта EA в каталоге редактора")
    parser.add_argument("--file", help="JSON стандарта (по умолчанию первый)")
    parser.add_argument("--check", action="store_true",
                        help="сверить шкафы стандарта с каталогом")
    parser.add_argument("--sync", action="store_true",
                        help="обновить шкафы и комплекты каталога по стандарту")
    parser.add_argument("--cabinet", help="показать запись каталога по шифру")
    args = parser.parse_args(argv)

    path = args.file or es.default_base()
    if not path:
        print("Нет стандартов в папке %s" % es.folder())
        return 1
    data = es.load(path)
    print("Стандарт: %s" % path)
    print("Ключ каталога: %s" % (standard_key(data) or "—"))

    if args.sync:
        stats = update_standard_cabinets(data)
        print("Обновление каталога по стандарту:")
        print("  обновлено шкафов: %d" % stats["updated"])
        print("  создано шкафов:   %d" % stats["created"])
        print("  комплектов:       %d" % stats["kits"])
        print("  шкафы:            %s" % ", ".join(stats["cabinets"]))
        return 0

    if args.cabinet:
        item = es.cabinet(data, args.cabinet)
        if item is None:
            print("Шкаф не найден: %s" % args.cabinet)
            return 1
        record = find_catalog_cabinet(data, item) or catalog_record(data, item)
        for key in ("key", "standard_key", "code", "name", "group",
                    "architecture", "voltage", "protected", "controlled",
                    "its_functions", "source"):
            value = record.get(key)
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            print("  %-14s %s" % (key, value if value else "—"))
        print("  комплектов     %d" % len(record.get("komplets") or []))
        return 0

    problems = _print_check(data)
    print("Проблем: %d" % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
