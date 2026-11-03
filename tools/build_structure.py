# -*- coding: utf-8 -*-
"""Сборка structure.json — единой структуры шкафов и комплектов РЗА.

Формат — образец standards/structure.json: плоские записи с «id» и ссылками
по ключам; шкафы и комплекты лежат в разных списках и связаны по идентификаторам
(шкаф → «Комплект N», комплект → «Шкаф»). Идентификаторы совпадают с ключами
каталога редактора схем (cabs.py / komplekts.py), поэтому запись структуры
стыкуется с элементом схемы без дополнительного маппинга:

    шкаф:     id = key шкафа каталога            (например shet-211-01-1)
    комплект: id = key комплекта каталога         (например typ:shet-211-01-1:0)

Источники данных (по убыванию приоритета для одного поля):

1. ``standards/src/*.json`` — исходные таблицы по ИЭУ (восстановлены из базы
   знаний «Исходные» скриптом tools/recover_kb_docs.py): входные/выходные
   GOOSE, функциональные клавиши, светодиодная сигнализация, команды АСУ ТП,
   аналоговые значения, отчёты;
2. каталог редактора — cabs.all_cabinets() (cabs_data.py, cabs_sto.py,
   cabinets.json): шифр, наименования, архитектура, защищаемый/управляемый
   элемент, питания, порты, компоненты, функции, применимость;
3. ``cabs_analog.json`` — «Входные аналоговые измерения» по ИЭУ (БИ, цепи,
   число контактов, примечание);
4. ``cabs_signals.json`` — внутренние дискретные цепи и GOOSE шкафа;
5. ``standards/extracted.json`` (если есть) — дополнения, выгруженные из PDF
   стандартов: «Назначение шкафа», «Основные компоненты шкафа».

Внешние дискретные сигналы («Дискретные сигналы, формируемые ИЭУ», входные
дискретные) в структуру не переносятся — этого требует образец.

Запуск:
    python3 tools/build_structure.py                 # собрать structure.json
    python3 tools/build_structure.py --stats         # и печатную сводку
    python3 tools/build_structure.py --out f.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cabs                # noqa: E402  каталог шкафов редактора
import komplekts           # noqa: E402  каталог комплектов редактора

SRC_DIR = os.path.join(ROOT, "standards", "src")
EXTRACTED = os.path.join(ROOT, "standards", "extracted.json")
SIGNALS = os.path.join(ROOT, "cabs_signals.json")
ANALOG = os.path.join(ROOT, "cabs_analog.json")
OUT_DEFAULT = os.path.join(ROOT, "structure.json")

#: Русские имена полей — ровно как в образце standards/structure.json.
F_CABINET = "Шкаф"
F_FULL_NAME = "Полное имя шкафа"
F_PURPOSE = "Назначение шкафа"
F_CODE = "Шифр шкафа"
F_ARCH = "Архитектура построения ПС"
F_TITLE = "Наименование шкафа"
F_PROTECTED = "Защищаемый элемент"
F_CONTROLLED = "Управляемый элемент"
F_POWER = "Вводы питания оперативного постоянного тока"
F_COMPONENTS = "Основные компоненты шкафа"

F_KIT_IEDE = "Обозначение ИЭУ"
F_KIT_FULL = "Полное имя комплекта"
F_KIT_PURPOSE = "Назначение комплекта"
F_KIT_CODE = "Шифр комплекта"
F_ANALOG = "Входные аналоговые измерения"
F_INTERNAL = "Внутренние дискретные цепи"
F_GOOSE_IN = "Входные GOOSE сообщения"
F_GOOSE_OUT = "Выходные GOOSE сообщения"
F_KEYS = "Функциональные клавиши со светодиодной индикацией"
F_LED = "Светодиодная сигнализация"
F_COMMANDS = "Команды управления от АСУ ТП"
F_ANALOG_OUT = "Аналоговые значения, формируемые ИЭУ"
F_REPORTS = "Отчеты в АСУ ТП"

NO_DATA = "нет данных"

#: Признак внутренней дискретной цепи в cabs_signals.json.
INTERNAL_RE = re.compile(r"^(Положение SG\d|Дверь шкафа|Общешкафная лампа"
                         r"|Наличие напряжения|Цепи питания ИЭУ)")
SG_RE = re.compile(r"^Положение SG(\d+)")


def norm_code(value):
    """Нормализация шифра для сопоставления источников."""
    if not value:
        return ""
    text = str(value).replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00a0", " ").replace('"', "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper()


def code_key(value):
    """Ключ шифра без пробелов — как в standards/extracted.json."""
    return re.sub(r"\s+", "", norm_code(value))


def dash_list(value):
    """Развернуть «а; б; в» / список в марк-список как в образце."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
    else:
        items = [p.strip() for p in re.split(r"[;\n]", str(value)) if p.strip()]
    if not items:
        return ""
    return "".join("- %s\n" % item for item in items).rstrip("\n")


def numbered(items, key="Наименование", extra=None):
    """Таблица вида {№: {...}} как в образце («Основные компоненты шкафа»)."""
    table = {}
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            row = dict(item)
        else:
            row = {key: item}
        if extra:
            row.update(extra)
        table[str(index)] = row
    return table


# ---------------------------------------------------------------------------
# Исходные таблицы по ИЭУ (standards/src)
# ---------------------------------------------------------------------------

def load_kb_sources():
    """{нормализованный шифр шкафа: запись исходника} из standards/src."""
    result = {}
    for path in sorted(glob.glob(os.path.join(SRC_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            print("не прочитан %s: %s" % (path, exc), file=sys.stderr)
            continue
        if isinstance(data, dict):
            data = [data]
        for record in data:
            code = norm_code(record.get("Cabinet"))
            if code:
                entry = dict(record)
                entry["_source"] = os.path.basename(path)
                result.setdefault(code, []).append(entry)
    return result


def kb_ieds(record):
    """[{"name":…, "input_goose":[…], …}] по порядку ИЭУ исходника."""
    keys = [k for k in record if re.match(r"^IED\d+$", k)]
    keys.sort(key=lambda k: int(k[3:]))
    return [record[k] for k in keys if isinstance(record.get(k), dict)]


def split_signals(rows, direction):
    """Разделить смешанную таблицу сигналов на дискретные и GOOSE."""
    discrete, goose = [], []
    for row in rows or []:
        logical = (row.get("source_logical") or row.get("logical") or "").strip()
        if logical in ("", "-"):
            discrete.append(row)
        else:
            goose.append(row)
    return discrete, goose


def goose_in_rows(rows):
    out = []
    for row in rows or []:
        out.append({
            "Наименование сигнала": row.get("signal") or "",
            "Источник (физический)": row.get("source_physical") or "",
            "Источник (логический, по МЭК 61850)":
                row.get("source_logical") or "",
            "Класс сообщения": row.get("class") or "",
        })
    return out


def goose_out_rows(rows):
    out = []
    for row in rows or []:
        out.append({
            "Наименование сигнала": row.get("signal") or "",
            "Обозначение по МЭК 61850": row.get("logical") or "",
            "Приемник": row.get("receiver") or "",
            "Класс сообщения": row.get("class") or "",
        })
    return out


def cab_goose_rows(rows, direction):
    """GOOSE шкафа из cabs_signals.json (колонки стандарта там слились)."""
    out = []
    for row in rows or []:
        item = {"Наименование сигнала": row.get("name") or ""}
        code = (row.get("code") or "").strip()
        if direction == "in":
            item["Источник (логический, по МЭК 61850)"] = code
        else:
            item["Обозначение по МЭК 61850"] = code
        details = re.sub(r"\s+", " ", row.get("details") or "").strip()
        if details:
            item["Сведения из стандарта"] = details
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# cabs_signals.json / cabs_analog.json
# ---------------------------------------------------------------------------

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def clean_internal_row(row, section):
    """Строка таблицы «Внутренние дискретные цепи» из io_* справочника."""
    name = (row.get("name") or "").strip()
    details = (row.get("details") or "").strip()
    direction = "Вход" if section == "io_in" else "Выход"
    note = details
    for marker in ("Внутренний 1", "Внутренний 2", "Внутренний"):
        if note.startswith(marker):
            note = note[len(marker):].strip()
            break
    for marker in ("Вход", "Выход"):
        if note.startswith(marker):
            direction = marker
            note = note[len(marker):].strip()
            break
    out = {"Дискретный сигнал": name, "Направление": direction}
    if note:
        out["Примечание"] = note
    return out


def internal_chains(signals_entry):
    """Внутренние дискретные цепи шкафа: (цепи ИЭУ по БИ, прочие цепи)."""
    by_block, common = {}, []
    for section in ("io_in", "io_out"):
        for row in (signals_entry or {}).get(section) or []:
            name = (row.get("name") or "").strip()
            if not INTERNAL_RE.match(name) or (row.get("code") or "").strip():
                continue
            cleaned = clean_internal_row(row, section)
            match = SG_RE.match(name)
            if match:
                by_block.setdefault(int(match.group(1)), []).append(cleaned)
            else:
                common.append(cleaned)
    return by_block, common


def analog_by_ied(analog_entry):
    """{имя ИЭУ: [строки «Входные аналоговые измерения»]}."""
    out = {}
    for name, rows in (analog_entry or {}).items():
        out[name.strip()] = [{
            "Испытательный блок в шкафу": row.get("block") or "",
            "Аналоговые измерения": row.get("signals") or "",
            "Количество контактов испытательного блока с учетом "
            "регистрации его состояния": row.get("contacts") or "",
            "Примечание": row.get("note") or "",
        } for row in rows or []]
    return out


def kit_analog_rows(kit):
    rows = []
    for row in kit.get("analog_inputs") or []:
        rows.append({
            "Испытательный блок в шкафу": row.get("block") or "",
            "Аналоговые измерения": row.get("signals") or "",
            "Количество контактов испытательного блока с учетом "
            "регистрации его состояния": row.get("contacts") or "",
            "Примечание": row.get("note") or "",
        })
    return rows


# ---------------------------------------------------------------------------
# Сборка записей
# ---------------------------------------------------------------------------

def cabinet_full_name(cabinet):
    """«Шкаф … типа ШЭТ 211.01-1 для архитектуры II типа» — как в СТО."""
    base = (cabinet.get("description") or cabinet.get("title")
            or cabinet.get("name") or "").strip()
    code = (cabinet.get("code") or "").strip()
    arch = (cabinet.get("architecture") or "").strip()
    if not base:
        return code
    tail = ""
    if code and code.lower() not in base.lower():
        tail += " типа %s" % code
    if arch and "архитектур" not in base.lower():
        word = re.sub(r"\s*(тип|типа)\s*$", "", arch).strip()
        tail += " для архитектуры %s типа" % word
    return (base + tail).strip()


def build_kit(cabinet, index, kit, kb_ied, by_block, common_chains,
              ied_analog_rows):
    ieds = kit.get("ieds") or []
    ied_names = [i.get("name") or "" for i in ieds if isinstance(i, dict)]
    ied_names = [n for n in ied_names if n]
    ied_label = ", ".join(ied_names) or NO_DATA

    kit_name = kit.get("name") or ("Комплект %d" % (index + 1))
    cab_label = cabinet.get("code") or cabinet.get("name") or ""
    full_name = kit_name if not cab_label else "%s шкафа %s" % (kit_name, cab_label)
    if ied_names:
        full_name = "%s (%s)" % (full_name, ied_label)

    single_kit = len(cabinet.get("komplets") or []) <= 1
    record = {
        "id": kit.get("key"),
        F_CABINET: cabinet.get("key"),
        "Номер комплекта": index + 1,
        F_KIT_IEDE: ied_label,
        F_KIT_FULL: full_name,
        F_KIT_PURPOSE: (kit.get("desc") or "").strip(),
        F_KIT_CODE: (cabinet.get("code") or "").strip() if single_kit else "",
        "Вид комплекта": komplekts.KINDS.get(kit.get("kind") or "typical", ""),
        "Функции РЗА комплекта": list(kit.get("functions") or []),
        "Состав ИЭУ": [{"Обозначение": ied.get("name") or "",
                        "Тип": ied.get("type") or "",
                        "Описание": ied.get("desc") or ""}
                       for ied in ieds if isinstance(ied, dict)],
    }
    if komplekts.tags_of(kit):
        record["Теги"] = komplekts.tags_of(kit)

    # --- аналоговые измерения: комплект (из каталога) → справочник по ИЭУ --
    analog = kit_analog_rows(kit)
    if not analog and ied_analog_rows:
        for name in ied_names:
            if ied_analog_rows.get(name):
                analog = ied_analog_rows[name]
                break
        else:
            if len(ied_analog_rows) == 1:
                analog = next(iter(ied_analog_rows.values()))

    # --- внутренние дискретные цепи ---------------------------------------
    # Общешкафные цепи достаются каждому комплекту, цепи «Положение SGn» —
    # тому комплекту, у которого этот испытательный блок в аналоговых измерениях.
    chains = list(common_chains)
    for row in analog:
        match = re.search(r"SG(\d+)", row["Испытательный блок в шкафу"])
        if match:
            chains.extend(by_block.get(int(match.group(1)), []))
    if not analog:
        for number in sorted(by_block):
            chains.extend(by_block[number])

    record[F_ANALOG] = numbered(analog)
    record[F_INTERNAL] = numbered(chains)

    # --- данные по ИЭУ из исходных таблиц ---------------------------------
    if kb_ied:
        ins = kb_ied.get("input_goose") or []
        outs = kb_ied.get("output_goose") or []
        if not ins and not outs:                    # архитектура I: всё в куче
            d_in, g_in = split_signals(kb_ied.get("input_signals"), "in")
            d_out, g_out = split_signals(kb_ied.get("output_signals"), "out")
            ins, outs = g_in, g_out
        record[F_GOOSE_IN] = numbered(goose_in_rows(ins))
        record[F_GOOSE_OUT] = numbered(goose_out_rows(outs))
        record[F_KEYS] = list(kb_ied.get("functional_keys") or [])
        record[F_LED] = list(kb_ied.get("led_signals") or [])
        record[F_COMMANDS] = list(kb_ied.get("control_commands") or [])
        record[F_ANALOG_OUT] = list(kb_ied.get("analog_values") or [])
        record[F_REPORTS] = list(kb_ied.get("reports") or [])
        record["Источник данных"] = "СТО, таблицы по %s" % (ied_label or "ИЭУ")
    else:
        record[F_GOOSE_IN] = []
        record[F_GOOSE_OUT] = []
        record[F_KEYS] = []
        record[F_LED] = []
        record[F_COMMANDS] = []
        record[F_ANALOG_OUT] = []
        record[F_REPORTS] = []
        record["Источник данных"] = "каталог редактора"
    return record


def build_cabinet(cabinet, kit_records, kb_record, extracted):
    key = cabinet.get("key")
    record = {
        "id": key,
        F_FULL_NAME: cabinet_full_name(cabinet),
        F_PURPOSE: (extracted or {}).get("Назначение шкафа") or NO_DATA,
        F_CODE: (cabinet.get("code") or "").strip(),
        F_ARCH: (cabinet.get("architecture")
                 or (kb_record or {}).get("Architecture") or "").strip(),
        F_TITLE: (cabinet.get("title") or cabinet.get("name") or "").strip(),
        F_PROTECTED: (cabinet.get("protected")
                      or (kb_record or {}).get("ProtectedElement") or "").strip(),
        F_CONTROLLED: "; ".join(cabinet.get("controlled") or []) or NO_DATA,
    }
    for offset, kit in enumerate(kit_records, start=1):
        record["Комплект %d" % offset] = kit["id"]

    record[F_POWER] = dash_list(cabinet.get("power_supply"))
    record["Цифровые порты ИЭУ"] = dash_list(cabinet.get("ports"))

    components = (extracted or {}).get(F_COMPONENTS)
    if not components:
        raw = cabinet.get("components")
        components = []
        if isinstance(raw, list):
            components = raw
        elif isinstance(raw, dict):
            components = list(raw.values())
        elif raw and not str(raw).strip().lower().startswith("таблица"):
            components = [str(raw)]
    record[F_COMPONENTS] = numbered(components) if components else NO_DATA

    record["Класс напряжения"] = (cabinet.get("voltage") or "").strip()
    record["Группа"] = (cabinet.get("group") or "").strip()
    record["Стандарт"] = (cabinet.get("standard") or "").strip()
    record["Функции ИТС"] = list(cabinet.get("its_functions") or [])
    record["Основные функции МП ИЭУ"] = (cabinet.get("mp_functions") or "").strip()
    record["Описание функций ИТС"] = (cabinet.get("its_functions_desc") or "").strip()
    record["Применимость"] = (cabinet.get("applicability") or "").strip()
    record["Источник (СТО)"] = (cabinet.get("source") or "").strip()
    record["Поясняющие схемы подключения"] = (cabinet.get("connection_scheme") or "").strip()
    record["Эскиз общего вида"] = (cabinet.get("general_view") or "").strip()
    record["Структурно-функциональная схема"] = (cabinet.get("structural_scheme") or "").strip()
    record["Схема электрическая принципиальная"] = (cabinet.get("schematic") or "").strip()
    record["Основные параметры функций ИЭУ"] = (cabinet.get("parameters") or "").strip()
    record["Дополнительная аппаратура"] = (cabinet.get("additional_equipment") or "").strip()
    record["Аппаратура связи"] = (cabinet.get("communication")
                                  or (kb_record or {}).get("CommunicationEquipment")
                                  or "").strip()
    record["Климатическое исполнение"] = (cabinet.get("climate") or "").strip()
    record["Степень защиты оболочки"] = (cabinet.get("enclosure") or "").strip()
    record["Охлаждение шкафа"] = (cabinet.get("cooling") or "").strip()
    record["Примечания"] = (cabinet.get("notes") or "").strip()
    tags = cabinet.get("tags") or []
    if tags:
        record["Теги"] = list(tags)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=OUT_DEFAULT)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args(argv)

    cabinets = cabs.all_cabinets()
    kb = load_kb_sources()
    signals = load_json(SIGNALS)
    analog = load_json(ANALOG)
    extracted = load_json(EXTRACTED)
    #: дополнения из PDF по ключу шифра
    overlay = {code_key(code): entry for code, entry in extracted.items()
               if isinstance(entry, dict)}

    kit_records = []
    cabinet_records = []
    matched_codes = set()
    used_overlay = set()
    coverage = Counter()

    for cabinet in sorted(cabinets, key=lambda c: (c.get("group") or "",
                                                   c.get("code") or "",
                                                   c.get("key") or "")):
        key = cabinet.get("key")
        kb_entries = kb.get(norm_code(cabinet.get("code"))) or []
        kb_record = kb_entries[0] if kb_entries else None
        if kb_record:
            matched_codes.add(norm_code(cabinet.get("code")))

        kb_ied_list = kb_ieds(kb_record) if kb_record else []
        by_block, common_chains = internal_chains(signals.get(key))
        ied_analog_rows = analog_by_ied(analog.get(key))

        kits_here = []
        for index in range(len(cabinet.get("komplets") or [])):
            kit = komplekts.kit_from_cabinet(cabinet, index)
            if not kit:
                continue
            if index < len(kb_ied_list):
                kb_ied = kb_ied_list[index]
            elif len(kb_ied_list) == 1:
                # один источник на несколько комплектов — данные общие
                kb_ied = kb_ied_list[0]
            else:
                kb_ied = None
            kit_record = build_kit(cabinet, index, kit, kb_ied, by_block,
                                   common_chains, ied_analog_rows)
            kits_here.append(kit_record)
            kit_records.append(kit_record)

        entry_overlay = overlay.get(code_key(cabinet.get("code")))
        if entry_overlay:
            used_overlay.add(code_key(cabinet.get("code")))
        cabinet_record = build_cabinet(cabinet, kits_here, kb_record,
                                       entry_overlay)

        # GOOSE шкафа (cabs_signals.json), если нет покомплектных исходников
        if not kb_ied_list:
            entry = signals.get(key) or {}
            gin = cab_goose_rows(entry.get("goose_in"), "in")
            gout = cab_goose_rows(entry.get("goose_out"), "out")
            if len(kits_here) == 1:
                if gin:
                    kits_here[0][F_GOOSE_IN] = numbered(gin)
                if gout:
                    kits_here[0][F_GOOSE_OUT] = numbered(gout)
                if gin or gout:
                    kits_here[0]["Источник данных"] = (
                            kits_here[0].get("Источник данных", "") +
                            "; GOOSE — сводный список шкафа").lstrip("; ")
            elif gin or gout:
                cabinet_record["Входные GOOSE сообщения (шкаф)"] = numbered(gin)
                cabinet_record["Выходные GOOSE сообщения (шкаф)"] = numbered(gout)

        # испытательные блоки шкафа — если по комплектам они не собраны
        entry = signals.get(key) or {}
        blocks = entry.get("test_blocks") or []
        if blocks and not any(k.get(F_ANALOG) for k in kits_here):
            cabinet_record["Испытательные блоки шкафа"] = [
                {"Наименование": b.get("name") or "",
                 "Количество": b.get("count") or "",
                 "Характеристика": b.get("spec") or ""} for b in blocks]

        cabinet_records.append(cabinet_record)

        # сводка заполнения
        coverage["шкафов"] += 1
        coverage["комплектов"] += len(kits_here)
        for name in (F_COMPONENTS, F_POWER, F_PROTECTED, F_CONTROLLED):
            if cabinet_record.get(name) not in (NO_DATA, "", [], {}):
                coverage["шкаф: " + name] += 1
        if kb_record:
            coverage["шкаф: исходные таблицы ИЭУ"] += 1
        for kit in kits_here:
            for name in (F_ANALOG, F_INTERNAL, F_GOOSE_IN, F_GOOSE_OUT, F_KEYS,
                         F_LED, F_COMMANDS):
                if kit.get(name):
                    coverage["комплект: " + name] += 1

    result = {
        "структура": "Шкафы и комплекты РЗА — структура по образцу standards/structure.json",
        "версия": 1,
        "формат": {
            "шкафы": "запись шкафа; «Комплект N» — id комплекта",
            "комплекты": "запись комплекта; «Шкаф» — id шкафа",
            "id": "совпадают с ключами каталога редактора схем (cabs.py, komplekts.py)",
        },
        "источники": {
            "каталог шкафов": "cabs.py (cabs_data.py, cabs_sto.py, cabinets.json)",
            "аналоговые измерения": "cabs_analog.json",
            "сигналы шкафа": "cabs_signals.json",
            "исходные таблицы по ИЭУ": sorted(
                os.path.basename(p) for p in glob.glob(os.path.join(SRC_DIR, "*.json"))),
            "дополнения из PDF": os.path.relpath(EXTRACTED, ROOT)
            if os.path.exists(EXTRACTED) else None,
            "нормативы": sorted(os.path.basename(p) for p in
                                glob.glob(os.path.join(ROOT, "standards", "*.pdf"))),
        },
        F_CABINET: cabinet_records,
        "комплекты": kit_records,
    }

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
        handle.write("\n")

    size = os.path.getsize(args.out)
    print("structure.json: %d шкафов, %d комплектов, %.1f МБ → %s" % (
        len(cabinet_records), len(kit_records), size / 1048576.0, args.out))
    orphan = sorted(set(kb) - matched_codes)
    if orphan:
        print("исходники без пары в каталоге: %s" % orphan)
    unused = sorted(set(overlay) - used_overlay)
    if unused:
        print("шифры из PDF без пары в каталоге: %d — %s"
              % (len(unused), ", ".join(unused[:12])))
    if args.stats:
        print("\nЗаполнение полей:")
        for name, count in sorted(coverage.items()):
            total = coverage["шкафов"] if name.startswith("шкаф") else \
                coverage["комплектов"]
            print("  %-42s %5d / %d" % (name, count, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
