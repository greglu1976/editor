# -*- coding: utf-8 -*-
"""Сборка structure.json — структуры РЗА в формате v3:

    контейнеры (КЭТ) → шкафы → комплекты → ИЭУ

Формат v3 (полная спецификация — STRUCTURE.md):

* верхний уровень — разделы «контейнеры» и «шкафы», массивы записей;
* запись контейнера: «шкафы» — id включённых шкафов (ссылка, а не вложение:
  шкаф может входить в несколько КЭТ или существовать вне КЭТ);
* запись шкафа: **всегда** «комплекты» — вложенные записи комплектов
  (минимум одна; комплект принадлежит ровно одному шкафу), и «контейнеры» —
  id КЭТ, в которые входит шкаф (обратная ссылка, вычисляется при сборке).
  ИЭУ на уровне шкафа не хранится: **шкаф состоит из комплектов**;
* запись комплекта: обязательное поле «есть ИЭУ» (true/false) и, только для
  комплекта с ИЭУ, «иэу» — вложенные записи ИЭУ. Комплект без ИЭУ —
  равноправная запись структуры, а не пропуск;
* если в описании шкафа одно ИЭУ, оно входит в комплект: старое поле
  ``cabinet["ieds"]`` переносится в первый комплект (``komplekts``), а
  сводные таблицы шкафа (GOOSE, испытательные блоки) привязываются к этому
  ИЭУ/комплекту, а не остаются на уровне шкафа;
* запись ИЭУ: таблицы стандарта по конкретному ИЭУ (GOOSE, функциональные
  клавиши, светодиодная сигнализация, команды АСУ ТП, аналоговые значения,
  отчёты).

Правила форм значений:

* таблицы — массивы строк-объектов, списки — массивы строк;
* отсутствующие данные — поле не пишется (никаких «нет данных» и пустышек);
* служебные ключи — фиксированный набор: «id», «номер», «контейнеры»,
  «шкафы», «комплекты», «иэу», «есть ИЭУ», «источник»; остальные ключи —
  содержательные поля. «есть ИЭУ» — структурный признак, пишется всегда
  (true или false), в отличие от необязательных данных.

id — ключи каталога редактора, поэтому запись стыкуется с элементом схемы
без дополнительного маппинга:

    шкаф:     id = key шкафа каталога       (например shet-211-01-1)
    комплект: id = key комплекта каталога   (например typ:shet-211-01-1:0)

Источники данных (по убыванию приоритета для одного поля):

1. ``standards/src/*.json`` — исходные таблицы по ИЭУ (восстанавливаются из
   базы знаний «Исходные» скриптом tools/recover_kb_docs.py): входные/выходные
   GOOSE, функциональные клавиши, светодиодная сигнализация, команды АСУ ТП,
   аналоговые значения, отчёты. Таблицы привязываются по индексу: IEDn
   исходника → «иэу[n-1]» комплекта № n; один блок исходника на несколько
   ИЭУ/комплектов помечается «источник: общая таблица (без разделения)»;
2. каталог редактора — cabs.all_cabinets() (cabs_data.py, cabs_sto.py,
   cabinets.json): шифр, наименования, архитектура, защищаемый/управляемый
   элемент, питания, порты, компоненты, функции, применимость, состав ИЭУ;
3. ``cabs_analog.json`` — «Входные аналоговые измерения» (БИ, цепи, контакты);
4. ``cabs_signals.json`` — внутренние дискретные цепи и сводный GOOSE шкафа;
5. ``standards/extracted.json`` (если есть) — дополнения из PDF стандартов:
   «Назначение», «Основные компоненты».

Внешние дискретные сигналы («Дискретные сигналы, формируемые ИЭУ», входные
дискретные) в структуру не переносятся — по требованию образца данных.

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
import containers          # noqa: E402  каталог КЭТ

SRC_DIR = os.path.join(ROOT, "standards", "src")
EXTRACTED = os.path.join(ROOT, "standards", "extracted.json")
SIGNALS = os.path.join(ROOT, "cabs_signals.json")
ANALOG = os.path.join(ROOT, "cabs_analog.json")
OUT_DEFAULT = os.path.join(ROOT, "structure.json")

# --- служебные ключи формата v3 -------------------------------------------
K_ID = "id"
K_NUMBER = "номер"
K_CONTAINERS = "контейнеры"      # раздел и обратная ссылка в шкафе
K_CABINETS = "шкафы"             # раздел и ссылка в контейнере
K_KITS = "комплекты"             # вложенные комплекты в шкафе
K_IEDS = "иэу"                   # вложенные ИЭУ в комплекте
K_HAS_IED = "есть ИЭУ"           # обязательный признак комплекта
K_SOURCE = "источник"

#: Поля таблицы «Входные аналоговые измерения».
ANALOG_ROW = ("Испытательный блок", "Аналоговые измерения",
              "Контакты испытательного блока", "Примечание")

#: Признак внутренней дискретной цепи в cabs_signals.json.
INTERNAL_RE = re.compile(r"^(Положение SG\d|Дверь шкафа|Общешкафная лампа"
                         r"|Наличие напряжения|Цепи питания ИЭУ)")
SG_RE = re.compile(r"^Положение SG(\d+)")


# ---------------------------------------------------------------------------
# Формы значений: непустое → значение, пустое → поле не пишется
# ---------------------------------------------------------------------------

def set_if(record, name, value):
    """Пишет поле, только если значение непустое (правило «пустое не пишем»)."""
    if value is None:
        return
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return
    if isinstance(value, (list, tuple, dict)) and not value:
        return
    record[name] = value


def str_list(value):
    """Массив непустых строк или None.

    Строка дробится по «;» и переводам строки (как раньше dash_list),
    готовый список берётся поэлементно.
    """
    if value is None:
        return None
    if isinstance(value, str):
        items = [p.strip() for p in re.split(r"[;\n]", value) if p.strip()]
    else:
        items = [str(v).strip() for v in value if str(v).strip()]
    return items or None


def table_rows(rows):
    """Массив строк-таблиц (только непустые) или None."""
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cleaned = {k: (v.strip() if isinstance(v, str) else v)
                   for k, v in row.items()}
        cleaned = {k: v for k, v in cleaned.items()
                   if v not in (None, "", [], {})}
        if cleaned:
            result.append(cleaned)
    return result or None


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


# ---------------------------------------------------------------------------
# Исходные таблицы по ИЭУ (standards/src)
# ---------------------------------------------------------------------------

def load_kb_sources():
    """{нормализованный шифр шкафа: [записи исходника]} из standards/src."""
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
    """[блок ИЭУ1, ИЭУ2, …] по порядку ИЭУ исходника."""
    keys = [k for k in record if re.match(r"^IED\d+$", k)]
    keys.sort(key=lambda k: int(k[3:]))
    return [record[k] for k in keys if isinstance(record.get(k), dict)]


def kb_for_kit(kb_ied_list, kit_index):
    """Блок исходника для комплекта № kit_index.

    По индексу комплекта; если у шкафа в исходнике один блок — он общий.
    Возвращает (блок | None, общий: bool).
    """
    if not kb_ied_list:
        return None, False
    if kit_index < len(kb_ied_list):
        return kb_ied_list[kit_index], False
    if len(kb_ied_list) == 1:
        return kb_ied_list[0], True
    return None, False


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


def analog_row(row):
    """Строка таблицы «Входные аналоговые измерения»."""
    return {
        "Испытательный блок": row.get("block") or "",
        "Аналоговые измерения": row.get("signals") or "",
        "Контакты испытательного блока": row.get("contacts") or "",
        "Примечание": row.get("note") or "",
    }


def analog_by_ied(analog_entry):
    """{имя ИЭУ: [строки «Входные аналоговые измерения»]}."""
    out = {}
    for name, rows in (analog_entry or {}).items():
        out[name.strip()] = [analog_row(row) for row in rows or []]
    return out


# ---------------------------------------------------------------------------
# Записи: контейнер, шкаф, комплект, ИЭУ
# ---------------------------------------------------------------------------

def build_container(container):
    """Запись контейнера КЭТ из каталога containers.py."""
    record = {
        K_ID: container.get("key"),
        "код": (container.get("code") or "").strip(),
        "название": (container.get("name") or "").strip(),
        "группа": (container.get("group") or "").strip(),
        "типоразмер": (container.get("size_code") or "").strip(),
        "слотов": container.get("slots"),
        K_CABINETS: [key for key in (container.get("cabinets") or []) if key],
    }
    set_if(record, "описание", (container.get("description") or "").strip())
    set_if(record, "стандарт", (container.get("standard") or "").strip())
    set_if(record, "архитектура", (container.get("architecture") or "").strip())
    set_if(record, "функции", str_list(container.get("functions")))
    set_if(record, "состав", str_list(container.get("composition")))
    set_if(record, "габариты", (container.get("dimensions") or "").strip())
    set_if(record, "климатическое исполнение",
           (container.get("climate") or "").strip())
    set_if(record, "степень защиты", (container.get("ip") or "").strip())
    set_if(record, "примечание", (container.get("note") or "").strip())
    set_if(record, K_SOURCE, (container.get("source") or "").strip())
    return record


def build_ied(ied, kb_ied, shared):
    """Запись ИЭУ: состав из каталога + таблицы стандарта по индексу."""
    record = {
        "обозначение": (ied.get("name") or "").strip(),
        "тип": (ied.get("type") or "").strip(),
    }
    set_if(record, "описание", (ied.get("desc") or "").strip())
    if kb_ied:
        ins = kb_ied.get("input_goose") or []
        outs = kb_ied.get("output_goose") or []
        if not ins and not outs:                    # архитектура I: всё в куче
            d_in, g_in = split_signals(kb_ied.get("input_signals"), "in")
            d_out, g_out = split_signals(kb_ied.get("output_signals"), "out")
            ins, outs = g_in, g_out
        set_if(record, "входные GOOSE", table_rows(goose_in_rows(ins)))
        set_if(record, "выходные GOOSE", table_rows(goose_out_rows(outs)))
        set_if(record, "функциональные клавиши",
               str_list(kb_ied.get("functional_keys")))
        set_if(record, "светодиодная сигнализация",
               str_list(kb_ied.get("led_signals")))
        set_if(record, "команды управления от АСУ ТП",
               str_list(kb_ied.get("control_commands")))
        set_if(record, "аналоговые значения",
               str_list(kb_ied.get("analog_values")))
        set_if(record, "отчеты в АСУ ТП", str_list(kb_ied.get("reports")))
        source = "СТО, таблицы по ИЭУ"
        if shared:
            source += " (общая таблица, без разделения по ИЭУ)"
        record[K_SOURCE] = source
    return record


def build_kit(cabinet, index, kit, kb_block, kb_shared, by_block,
              common_chains, ied_analog_rows):
    """Запись комплекта: поля каталога + таблицы + вложенные ИЭУ.

    Комплект без ИЭУ — полноценная запись с «есть ИЭУ: false» и без поля
    «иэу»; неактивный список ``ieds`` (галочка снята) в состав не входит.
    """
    ieds = [i for i in komplekts.effective_ieds(kit) if isinstance(i, dict)]

    kit_name = kit.get("name") or ("Комплект %d" % (index + 1))
    cab_label = cabinet.get("code") or cabinet.get("name") or ""
    full_name = kit_name if not cab_label else "%s шкафа %s" % (kit_name, cab_label)
    if len(ieds) == 1 and ieds[0].get("name"):
        full_name = "%s (%s)" % (full_name, ieds[0]["name"])

    single_kit = len(cabinet.get("komplets") or []) <= 1
    record = {
        K_ID: kit.get("key"),
        K_NUMBER: index + 1,
        "вид": komplekts.KINDS.get(kit.get("kind") or "typical", ""),
        "полное имя": full_name,
        K_HAS_IED: bool(ieds),
    }
    set_if(record, "назначение", (kit.get("desc") or "").strip())
    if single_kit:
        set_if(record, "шифр", (cabinet.get("code") or "").strip())
    set_if(record, "функции РЗА", str_list(kit.get("functions")))
    set_if(record, "теги", komplekts.tags_of(kit) or None)

    # --- аналоговые измерения: комплект (из каталога) → справочник по ИЭУ --
    analog = [analog_row(row) for row in kit.get("analog_inputs") or []]
    if not analog and ied_analog_rows:
        ied_names = [i.get("name") or "" for i in ieds]
        for name in ied_names:
            if ied_analog_rows.get(name):
                analog = ied_analog_rows[name]
                break
        else:
            if len(ied_analog_rows) == 1:
                analog = next(iter(ied_analog_rows.values()))
    set_if(record, "входные аналоговые измерения", table_rows(analog))

    # --- внутренние дискретные цепи ---------------------------------------
    # Общешкафные цепи достаются каждому комплекту, цепи «Положение SGn» —
    # тому комплекту, у которого этот испытательный блок в аналоговых измерениях.
    chains = list(common_chains)
    for row in analog:
        match = re.search(r"SG(\d+)", row.get("Испытательный блок") or "")
        if match:
            chains.extend(by_block.get(int(match.group(1)), []))
    if not analog:
        for number in sorted(by_block):
            chains.extend(by_block[number])
    set_if(record, "внутренние дискретные цепи", table_rows(chains))

    # --- вложенные ИЭУ ------------------------------------------------------
    ied_records = []
    for ied_index, ied in enumerate(ieds):
        block = None
        shared = False
        if kb_block is not None and ied_index == 0:
            # Таблицы исходника привязываются к первому ИЭУ комплекта;
            # если ИЭУ несколько, блок общий — это помечено в «источник».
            block, shared = kb_block, kb_shared or len(ieds) > 1
        ied_records.append(build_ied(ied, block, shared))
    if ied_records:
        record[K_IEDS] = ied_records
    return record


def build_cabinet(cabinet, kit_records, kb_record, extracted, container_ids):
    """Запись шкафа: поля каталога и стандартов + вложенные комплекты."""
    key = cabinet.get("key")
    record = {K_ID: key}
    set_if(record, "полное имя", cabinet_full_name(cabinet))
    set_if(record, "шифр", (cabinet.get("code") or "").strip())
    set_if(record, "наименование",
           (cabinet.get("title") or cabinet.get("name") or "").strip())
    set_if(record, "назначение", (extracted or {}).get("Назначение шкафа"))
    set_if(record, "архитектура ПС",
           (cabinet.get("architecture")
            or (kb_record or {}).get("Architecture") or "").strip())
    set_if(record, "защищаемый элемент",
           (cabinet.get("protected")
            or (kb_record or {}).get("ProtectedElement") or "").strip())
    set_if(record, "управляемый элемент", str_list(cabinet.get("controlled")))
    set_if(record, "вводы питания", str_list(cabinet.get("power_supply")))
    set_if(record, "порты", str_list(cabinet.get("ports")))

    components = (extracted or {}).get("Основные компоненты шкафа")
    if not components:
        raw = cabinet.get("components")
        if isinstance(raw, list):
            components = raw
        elif isinstance(raw, dict):
            components = list(raw.values())
        elif raw and not str(raw).strip().lower().startswith("таблица"):
            components = [str(raw)]
    if components:
        if all(isinstance(item, dict) for item in components):
            set_if(record, "основные компоненты", table_rows(components))
        else:
            set_if(record, "основные компоненты",
                   str_list([str(item) for item in components]))

    set_if(record, "класс напряжения", (cabinet.get("voltage") or "").strip())
    set_if(record, "группа", (cabinet.get("group") or "").strip())
    set_if(record, "стандарт", (cabinet.get("standard") or "").strip())
    set_if(record, "функции ИТС", str_list(cabinet.get("its_functions")))
    set_if(record, "функции МП ИЭУ", (cabinet.get("mp_functions") or "").strip())
    set_if(record, "описание функций ИТС",
           (cabinet.get("its_functions_desc") or "").strip())
    set_if(record, "применимость", (cabinet.get("applicability") or "").strip())
    set_if(record, K_SOURCE, (cabinet.get("source") or "").strip())
    set_if(record, "поясняющая схема подключения",
           (cabinet.get("connection_scheme") or "").strip())
    set_if(record, "эскиз общего вида", (cabinet.get("general_view") or "").strip())
    set_if(record, "структурно-функциональная схема",
           (cabinet.get("structural_scheme") or "").strip())
    set_if(record, "схема электрическая принципиальная",
           (cabinet.get("schematic") or "").strip())
    set_if(record, "параметры функций ИЭУ",
           (cabinet.get("parameters") or "").strip())
    set_if(record, "дополнительная аппаратура",
           (cabinet.get("additional_equipment") or "").strip())
    set_if(record, "аппаратура связи",
           (cabinet.get("communication")
            or (kb_record or {}).get("CommunicationEquipment") or "").strip())
    set_if(record, "климатическое исполнение",
           (cabinet.get("climate") or "").strip())
    set_if(record, "степень защиты оболочки",
           (cabinet.get("enclosure") or "").strip())
    set_if(record, "охлаждение", (cabinet.get("cooling") or "").strip())
    set_if(record, "примечания", (cabinet.get("notes") or "").strip())
    set_if(record, "теги", str_list(cabinet.get("tags")))
    if container_ids:
        record[K_CONTAINERS] = container_ids
    if kit_records:
        record[K_KITS] = kit_records
    return record


# ---------------------------------------------------------------------------
# Сборка документа
# ---------------------------------------------------------------------------

def coverage_of(record, prefix, fields):
    """Счётчики заполнения полей записи."""
    result = {}
    for field in fields:
        value = record.get(field)
        filled = value not in (None, "", [], {})
        result["%s: %s" % (prefix, field)] = filled
    return result


def single_ied_owner(kit_records):
    """(номер комплекта, номер ИЭУ), если во всём шкафу ровно одно ИЭУ.

    Именно к этому ИЭУ (и его комплекту) относятся сводные таблицы шкафа:
    одно ИЭУ в описании шкафа всегда входит в комплект.
    """
    found = [(kit_index, ied_index)
             for kit_index, kit in enumerate(kit_records)
             for ied_index in range(len(kit.get(K_IEDS) or []))]
    return found[0] if len(found) == 1 else None


def block_rows_of(blocks):
    """Таблица «Испытательные блоки» из cabs_signals.json."""
    return table_rows([
        {"Наименование": block.get("name") or "",
         "Количество": block.get("count") or "",
         "Характеристика": block.get("spec") or ""}
        for block in blocks or [] if isinstance(block, dict)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=OUT_DEFAULT)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args(argv)

    cabinets = cabs.all_cabinets()
    ket_list = containers.all_containers()
    kb = load_kb_sources()
    signals = load_json(SIGNALS)
    analog = load_json(ANALOG)
    extracted = load_json(EXTRACTED)
    #: дополнения из PDF по ключу шифра
    overlay = {code_key(code): entry for code, entry in extracted.items()
               if isinstance(entry, dict)}

    # контейнер → шкафы; обратный индекс шкаф → [контейнеры]
    cabinet_containers = {}
    for ket in ket_list:
        for cab_key in ket.get("cabinets") or []:
            cabinet_containers.setdefault(cab_key, []).append(ket.get("key"))

    coverage = Counter()
    warnings = []
    cabinet_records = []

    for cabinet in sorted(cabinets, key=lambda c: (c.get("group") or "",
                                                   c.get("code") or "",
                                                   c.get("key") or "")):
        key = cabinet.get("key")
        kb_entries = kb.get(norm_code(cabinet.get("code"))) or []
        kb_record = kb_entries[0] if kb_entries else None
        if kb_record:
            coverage["шкафов: исходные таблицы ИЭУ"] += 1

        kb_ied_list = kb_ieds(kb_record) if kb_record else []
        by_block, common_chains = internal_chains(signals.get(key))
        ied_analog_rows = analog_by_ied(analog.get(key))

        # Шкаф состоит из комплектов: минимум один; единственное ИЭУ из
        # описания шкафа переносится в первый комплект (komplekts).
        komplekts.ensure_cabinet_kits(cabinet)

        kit_records = []
        for index in range(len(cabinet.get("komplets") or [])):
            kit = komplekts.kit_from_cabinet(cabinet, index)
            if not kit:
                continue
            kb_block, kb_shared = kb_for_kit(kb_ied_list, index)
            if kb_block is None and kb_ied_list:
                warnings.append("%s: комплект %d — блоков исходника %d, "
                                "не хватает" % (key, index + 1, len(kb_ied_list)))
            kit_record = build_kit(cabinet, index, kit, kb_block, kb_shared,
                                   by_block, common_chains, ied_analog_rows)
            kit_records.append(kit_record)
            coverage["комплектов"] += 1
            for field in ("входные аналоговые измерения",
                          "внутренние дискретные цепи"):
                if kit_record.get(field):
                    coverage["комплект: " + field] += 1
            for ied in kit_record.get(K_IEDS) or []:
                coverage["иэу"] += 1
                if ied.get("входные GOOSE") or ied.get("выходные GOOSE"):
                    coverage["иэу: GOOSE"] += 1
                if ied.get("функциональные клавиши"):
                    coverage["иэу: функциональные клавиши"] += 1
                if ied.get("светодиодная сигнализация"):
                    coverage["иэу: светодиодная сигнализация"] += 1
                if ied.get("команды управления от АСУ ТП"):
                    coverage["иэу: команды АСУ ТП"] += 1
                if ied.get("отчеты в АСУ ТП"):
                    coverage["иэу: отчеты"] += 1
            if kit_record[K_HAS_IED]:
                coverage["комплектов с ИЭУ"] += 1
            else:
                coverage["комплектов без ИЭУ"] += 1

        # Данные шкафа, которые на самом деле относятся к его единственному
        # ИЭУ/комплекту, переносим внутрь комплекта. На уровне шкафа
        # остаются только по-настоящему общешкафные сведения.
        ied_owner = single_ied_owner(kit_records)
        if ied_owner:
            coverage["шкафов с одним ИЭУ"] += 1
        kit_owner = (ied_owner[0] if ied_owner else
                     0 if len(kit_records) == 1 else None)

        entry = signals.get(key) or {}
        gin = table_rows(cab_goose_rows(entry.get("goose_in"), "in"))
        gout = table_rows(cab_goose_rows(entry.get("goose_out"), "out"))
        if not kb_ied_list and ied_owner and (gin or gout):
            owner_kit, owner_ied = ied_owner
            target = kit_records[owner_kit][K_IEDS][owner_ied]
            if gin:
                target["входные GOOSE"] = gin
            if gout:
                target["выходные GOOSE"] = gout
            target[K_SOURCE] = "СТО, сводный список шкафа (одно ИЭУ)"
            coverage["иэу: GOOSE"] += 1
            coverage["сводный GOOSE перенесён в ИЭУ"] += 1
            gin = gout = None

        blocks = block_rows_of(entry.get("test_blocks"))
        if blocks and not any(k.get("входные аналоговые измерения")
                              for k in kit_records):
            if kit_owner is not None:
                set_if(kit_records[kit_owner], "испытательные блоки", blocks)
                set_if(kit_records[kit_owner], K_SOURCE,
                       "сводные данные шкафа")
                coverage["испытательные блоки перенесены в комплект"] += 1
            # без единственного владельца таблица остаётся на уровне шкафа
            # (добавляется ниже, после build_cabinet)

        entry_overlay = overlay.get(code_key(cabinet.get("code")))
        cabinet_record = build_cabinet(cabinet, kit_records, kb_record,
                                       entry_overlay,
                                       sorted(cabinet_containers.get(key, [])))

        # На уровне шкафа остаётся только то, что нельзя отнести к одному
        # комплекту (несколько комплектов с несколькими ИЭУ).
        if not kb_ied_list and (gin or gout):
            set_if(cabinet_record, "входные GOOSE", gin)
            set_if(cabinet_record, "выходные GOOSE", gout)
            set_if(cabinet_record, "источник GOOSE",
                   "сводный список шкафа, без разделения по комплектам")
            coverage["шкаф: сводный GOOSE"] += 1
        if blocks and kit_owner is None and not any(
                k.get("входные аналоговые измерения")
                for k in kit_records):
            set_if(cabinet_record, "испытательные блоки", blocks)
            set_if(cabinet_record, "источник испытательных блоков",
                   "общие данные шкафа (без разделения по комплектам)")

        cabinet_records.append(cabinet_record)
        coverage["шкафов"] += 1
        for field in ("назначение", "шифр", "защищаемый элемент",
                      "управляемый элемент", "вводы питания",
                      "основные компоненты"):
            if cabinet_record.get(field):
                coverage["шкаф: " + field] += 1
        if cabinet_record.get(K_CONTAINERS):
            coverage["шкафов в контейнерах"] += 1

    container_records = [build_container(ket) for ket in ket_list]

    result = {
        "версия": 3,
        "описание": "Структура РЗА: контейнеры (КЭТ) → шкафы → комплекты → ИЭУ. "
                    "Шкаф всегда состоит минимум из одного комплекта; комплект "
                    "бывает с ИЭУ («есть ИЭУ: true», вложенные «иэу») и без ИЭУ "
                    "(«есть ИЭУ: false»); единственное ИЭУ в описании шкафа "
                    "входит в комплект. id — ключи каталога редактора схем "
                    "(cabs.py, komplekts.py, containers.py). Связи: "
                    "«контейнеры.шкафы» ↔ «шкаф.контейнеры». "
                    "Спецификация — STRUCTURE.md.",
        "сущности": {
            "контейнер": "КЭТ; «шкафы» — id включённых шкафов",
            "шкаф": "шкаф РЗА; состоит из «комплектов» (вложены, минимум "
                    "один); «контейнеры» — id КЭТ, в которые входит шкаф; "
                    "ИЭУ на уровне шкафа не хранится",
            "комплект": "подключаемая единица шкафа; «есть ИЭУ» — "
                        "обязательный признак; «иэу» — вложенные ИЭУ только "
                        "у комплекта с ИЭУ",
            "иэу": "интеллектуальное электронное устройство; таблицы СТО "
                   "по этому ИЭУ",
        },
        "источники": {
            "каталог шкафов": "cabs.py (cabs_data.py, cabs_sto.py, cabinets.json)",
            "каталог контейнеров": "containers.py (containers.json)",
            "аналоговые измерения": "cabs_analog.json",
            "сигналы шкафа": "cabs_signals.json",
            "исходные таблицы по ИЭУ": sorted(
                os.path.basename(p) for p in glob.glob(os.path.join(SRC_DIR, "*.json"))),
            "дополнения из PDF": os.path.relpath(EXTRACTED, ROOT)
            if os.path.exists(EXTRACTED) else None,
            "нормативы": sorted(os.path.basename(p) for p in
                                glob.glob(os.path.join(ROOT, "standards", "*.pdf"))),
        },
        "контейнеры": container_records,
        "шкафы": cabinet_records,
    }
    # «дополнения из PDF»: пустые значения не пишем
    if result["источники"]["дополнения из PDF"] is None:
        del result["источники"]["дополнения из PDF"]
    if not result["источники"]["исходные таблицы по ИЭУ"]:
        del result["источники"]["исходные таблицы по ИЭУ"]
    if not result["источники"]["нормативы"]:
        del result["источники"]["нормативы"]

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
        handle.write("\n")

    size = os.path.getsize(args.out)
    print("structure.json v3: %d контейнеров, %d шкафов, %d комплектов "
          "(%d с ИЭУ, %d без ИЭУ), %d ИЭУ, %.1f МБ → %s"
          % (len(container_records), len(cabinet_records),
             coverage["комплектов"], coverage["комплектов с ИЭУ"],
             coverage["комплектов без ИЭУ"], coverage["иэу"],
             size / 1048576.0, args.out))
    orphan = sorted(set(kb) - {norm_code(c.get("code")) for c in cabinets})
    if orphan:
        print("исходники без пары в каталоге: %s" % orphan)
    unused = sorted(set(overlay) - {code_key(c.get("code")) for c in cabinets})
    if unused:
        print("шифры из PDF без пары в каталоге: %d — %s"
              % (len(unused), ", ".join(unused[:12])))
    for warning in warnings[:10]:
        print("! %s" % warning, file=sys.stderr)
    if args.stats:
        print("\nЗаполнение:")
        for name, count in sorted(coverage.items()):
            if name in ("шкафов", "комплектов", "иэу"):
                print("  %-42s %5d" % (name, count))
            else:
                total = (coverage["иэу"] if name.startswith("иэу:")
                         else coverage["комплектов"]
                         if name.startswith("комплект") else coverage["шкафов"])
                print("  %-42s %5d / %d" % (name, count, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
