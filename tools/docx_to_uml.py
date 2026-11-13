# -*- coding: utf-8 -*-
"""Экспорт шкафов из DOCX стандарта по UML-модели EA/structure.xml.

Модель (XMI, экспорт Enterprise Architect) задаёт классы ``Cabinet`` →
``Kit`` → ``IED`` и все таблицы ИЭУ: ``AnalogInput``, ``Function``/``Parameter``,
``DataSet``/``Signal``, ``Terminal`` и т.д. Скрипт берёт DOCX раздела 4.16,
том 5, редакция 2 (СКРМ), разбирает его уже существующим парсером
[``docx_to_standards_json.py``](docx_to_standards_json.py) — с восстановлением
автоматической нумерации таблиц — и раскладывает строки таблиц по классам и
атрибутам UML. Имена полей в выходном JSON — **в точности как в XMI**.

Вложенность повторяет ассоциации модели; каждый объект проверяется: ключ
должен быть либо атрибутом класса, либо именем связанного дочернего класса.
Лишних/пустых полей не создаётся (исключение — булевы флаги ``Function``).

Запуск::

    python3 tools/docx_to_uml.py                       # всё по умолчанию
    python3 tools/docx_to_uml.py --docx "EA/другой.docx" --out output/x.json
    python3 tools/docx_to_uml.py --std-json "standards_base/....json"  # без DOCX

По умолчанию пишет ``EA/cabinets_uml.json`` и ``EA/cabinets_uml_report.md``.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import glob
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict, defaultdict

XMI = "{http://schema.omg.org/spec/XMI/2.1}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import docx_to_standards_json as dsj  # noqa: E402  (парсер DOCX проекта)

DEFAULT_UML = os.path.join(ROOT, "EA", "structure.xml")
DEFAULT_OUT = os.path.join(ROOT, "EA", "cabinets_uml.json")
DEFAULT_REPORT = os.path.join(ROOT, "EA", "cabinets_uml_report.md")

#: В XMI два класса с именем TerminalRow и композитные концы расставлены так,
#: что Kit ↔ TerminalRow ↔ TerminalBlock ↔ Terminal образуют кольцо. Для рядов
#: зажимов используется естественная иерархия таблицы: блок → ряд → клеммы.
EXTRA_CHILDREN = {
    # В XMI ассоциация IED → Kit проведена от ИЭУ к комплекту (0..1); по данным
    # стандарта ИЭУ входит в комплект, поэтому в JSON это Kit.IED.
    "Kit": {"IED", "TerminalBlock"},
    "TerminalBlock": {"TerminalRow"},
    "TerminalRow": {"Terminal"},
}

#: Префиксы подписей таблиц标准а → класс/блок UML (для трассировки).
TABLE_PREFIX = OrderedDict([
    ("Входные аналоговые измерения", "AnalogInput"),
    ("Внутренние дискретные цепи", "InnerDiscreteCircuit"),
    ("Информационные сигналы в составе входящих сообщений", "IncomingGooseSignal"),
    ("Функциональные клавиши", "FunctionalButton"),
    ("Светодиодная сигнализация", "LED"),
    ("Сообщения и отчеты, исходящие от ИЭУ", "DataSet/OutcomingMessage/OutcomingReport"),
    ("Информационные сигналы в составе исходящих сообщений", "Signal (GOOSE)"),
    ("Информационные сигналы в составе исходящих отчетов", "Signal (отчёты)"),
    ("Осциллографируемые аналоговые сигналы", "OscAnalogSignal"),
    ("Команды управления от АСУ ТП", "ControlCommand"),
    ("Основные параметры функций РЗА", "Function/Parameter"),
    ("Ряды зажимов", "TerminalBlock/TerminalRow/Terminal"),
    ("Основные компоненты шкафа", "Component"),
    ("Описание ШЭТ", "Cabinet/PowerSupply/port/Kit"),
])

DITTO = re.compile(r"^[»“\"']{1,3}$")


# ---------------------------------------------------------------------------
# UML-модель
# ---------------------------------------------------------------------------
class UmlModel:
    """Классы, атрибуты с типами и направления ассоциаций из XMI."""

    def __init__(self, path):
        self.path = path
        root = ET.parse(path).getroot()
        self.classes = {}                      # name -> {attr: type}
        self.by_id = {}                        # xmi:id -> class name
        for el in root.iter("packagedElement"):
            if el.get(XMI + "type") != "uml:Class":
                continue
            name = el.get("name")
            attrs = OrderedDict()
            for a in el:
                if a.tag != "ownedAttribute" or not a.get("name"):
                    continue
                t = a.find("type")
                type_id = t.get(XMI + "idref") if t is not None else "EAC__string"
                attrs[a.get("name")] = type_id.replace("EAC__", "").strip("_")
            self.classes.setdefault(name, OrderedDict()).update(attrs)
            self.by_id[el.get(XMI + "id")] = name

        # ownedAttribute без имени — второй конец ассоциации, живёт в классе
        self.member_ends = {}
        for el in root.iter("packagedElement"):
            if el.get(XMI + "type") != "uml:Class":
                continue
            for a in el:
                if a.tag == "ownedAttribute" and a.get(XMI + "id"):
                    t = a.find("type")
                    self.member_ends[a.get(XMI + "id")] = (
                        el.get("name"),
                        self.by_id.get(t.get(XMI + "idref")) if t is not None else None,
                    )

        self.links = []                        # (parent, child, aggregation)
        self.children = defaultdict(set)
        for el in root.iter("packagedElement"):
            if el.get(XMI + "type") != "uml:Association":
                continue
            oe = el.find("ownedEnd")
            if oe is None or oe.find("type") is None:
                continue
            parent = self.by_id.get(oe.find("type").get(XMI + "idref"))
            child = None
            for m in el:
                if m.tag == "memberEnd" and m.get(XMI + "idref") in self.member_ends:
                    child = self.member_ends[m.get(XMI + "idref")][1]
            if parent and child and parent != child:
                self.links.append((parent, child, oe.get("aggregation")))
                self.children[parent].add(child)
        for cls, extra in EXTRA_CHILDREN.items():
            self.children[cls] |= extra

        self.counts = Counter()
        self.filled = defaultdict(Counter)
        self.skipped = Counter()
        self.notes = []

    # -- фабрика объектов UML -------------------------------------------
    def make(self, cls, **values):
        """Создать объект класса, отбросив пустые значения и приведя типы."""
        if cls not in self.classes:
            raise KeyError("нет класса %s в UML" % cls)
        attrs = self.classes[cls]
        obj = OrderedDict()
        for key, value in values.items():
            if key not in attrs:
                raise KeyError("нет атрибута %s.%s в UML" % (cls, key))
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value or DITTO.match(value):
                    continue
            if isinstance(value, (list, dict)) and not value:
                continue
            typ = attrs[key]
            if typ.startswith("List_"):        # components: List<Component>
                obj[key] = value
                self.filled[cls][key] += len(value)
                continue
            if typ == "int":
                try:
                    value = int(str(value).strip())
                except (TypeError, ValueError):
                    self.skipped["%s.%s (не число: %r)" % (cls, key, value)] += 1
                    continue
            elif typ == "bool":
                value = bool(value)
            elif not isinstance(value, str):
                value = str(value)
            obj[key] = value
        self.counts[cls] += 1
        for key in obj:
            self.filled[cls][key] += 1
        return obj

    def attach(self, obj, cls, child, items):
        """Вложить список объектов дочернего класса по ассоциации."""
        if not items:
            return
        allowed = self.children[cls]
        if child not in allowed:
            raise KeyError("нет связи %s → %s в UML" % (cls, child))
        obj[child] = items

    # -- проверка результата ---------------------------------------------
    def validate(self, node, cls, errors, path=""):
        if isinstance(node, list):
            for index, item in enumerate(node):
                self.validate(item, cls, errors, "%s[%d]" % (path, index))
            return
        if not isinstance(node, dict):
            errors.append("%s: ожидался объект %s" % (path, cls))
            return
        attrs = self.classes.get(cls, {})
        for key, value in node.items():
            where = "%s.%s" % (path, key)
            if key in attrs:
                typ = attrs[key]
                if typ.startswith("List_"):
                    target = typ[5:]
                    if target in self.classes:
                        self.validate(value, target, errors, where)
                continue
            if key in self.children[cls]:
                self.validate(value, key, errors, where)
                continue
            errors.append("%s: ключ вне UML-модели" % where)


# ---------------------------------------------------------------------------
# Чтение стандарта
# ---------------------------------------------------------------------------
def read_standard(docx_path=None, std_json=None):
    if std_json:
        with open(std_json, encoding="utf-8") as fh:
            data = json.load(fh)
        return data, ["использован готовый JSON: %s" % std_json], std_json
    if not docx_path:
        found = sorted(glob.glob(os.path.join(ROOT, "EA", "*.docx")))
        if not found:
            raise SystemExit("в EA/ нет DOCX; укажите --docx или --std-json")
        docx_path = found[0]
    with contextlib.redirect_stdout(io.StringIO()):
        data, problems = dsj.convert(
            docx_path, cipher=dsj.cipher_of(docx_path), dry_run=True)
    return data, problems, docx_path


def rows_of(table):
    """Строки таблицы как списки значений; «» (то же, что выше) развёрнуто."""
    result = []
    previous = None
    for row in table.get("Строки") or []:
        values = [str(v).strip() if v is not None else "" for v in row.values()]
        if previous is None:
            previous = list(values)
        for i, value in enumerate(values):
            if DITTO.match(value or "-"):
                values[i] = previous[i] if i < len(previous) else ""
        previous = list(values)
        result.append(values)
    return result


def find_table(tables, prefix):
    for key, table in tables.items():
        if table.get("Наименование", "").startswith(prefix):
            return key, table
    raise LookupError("нет таблицы «%s…»" % prefix)


def split_list(value):
    """Значение карточки вида '- питание ИЭУ; - освещение' → список пунктов."""
    parts = re.split(r"\s*[-–]\s+", str(value).strip())
    return [p.strip(" ;.") for p in parts if p.strip(" ;.")]


def codes(value):
    return [c.strip() for c in re.split(r"[,;]", str(value or "")) if c.strip()]


def code_aliases(values):
    """Коды функций с раскрытием скобок: «ДТЗ СО (ДЗР ШР)» → ДТЗ СО, ДЗР.

    В карточке шкафа «Основные функции» и «Функции ИТС» перечисляют одни и те
    же защиты разными обозначениями; без алиасов флаги isMainFunction/isInITS
    расходятся там, где стандарт просто дал синоним.
    """
    aliases = set()
    for value in values:
        aliases.add(value)
        match = re.search(r"\(([^)]*)\)", value)
        if match:
            aliases.add(re.sub(r"\s*\([^)]*\)", "", value).strip())
            inner = match.group(1).strip()
            aliases.add(inner)
            aliases.add(inner.split()[0])
    return {a for a in aliases if a}


# ---------------------------------------------------------------------------
# Сборка одного шкафа
# ---------------------------------------------------------------------------
def build_cabinet(section_name, block, model, standard=""):
    desc = block["Описание шкафа"]
    tables = block["Таблицы"]
    source = {"раздел": block.get("Раздел стандарта", ""),
              "название раздела": section_name, "таблицы": OrderedDict()}
    used = source["таблицы"]

    def table(prefix, target):
        key, tbl = find_table(tables, prefix)
        used[target] = key
        return rows_of(tbl)

    # --- Cabinet и CabinetReport ---------------------------------------
    scope = next((v for k, v in desc.items() if k.startswith("Область применения")), "")
    cabinet = model.make(
        "Cabinet",
        standard=standard,
        cypher=desc.get("Шифр шкафа"),
        architecture=desc.get("Архитектура построения ПС"),
        name=desc.get("Наименование шкафа"),
        controllable_element=desc.get("Управляемый элемент"),
        protected_element=desc.get("Защищаемый элемент"),
        scope=scope,
        description=block.get("Назначение шкафа"),
    )

    component_rows = table("Основные компоненты шкафа", "Component")
    components = [model.make("Component", name=r[0], description=r[1], quantity=r[2])
                  for r in component_rows if len(r) >= 3 and any(r)]
    report = model.make(
        "CabinetReport",
        cab_cypher=desc.get("Шифр шкафа"),
        architecture=desc.get("Архитектура построения ПС"),
        cab_name=desc.get("Наименование шкафа"),
        controllable_element=desc.get("Управляемый элемент"),
        protected_element=desc.get("Защищаемый элемент"),
        components=components,
    )

    supplies = [model.make("PowerSupply", purpose=item)
                for item in split_list(desc.get(
                    "Вводы питания оперативного постоянного тока шкафа", ""))]
    model.attach(cabinet, "Cabinet", "PowerSupply", supplies)
    model.attach(cabinet, "Cabinet", "Component", components)

    # --- Kit / IED -------------------------------------------------------
    kit_desc = desc.get("Комплект") or {}
    ied_names = ([kit_desc["Имя ИЭУ"]] if isinstance(kit_desc, dict) else
                 [k.get("Имя ИЭУ", "ИЭУ") for k in kit_desc if isinstance(k, dict)])
    if not ied_names:
        ied_names = ["ИЭУ"]
    kit = model.make(
        "Kit", number=1,
        description="Комплект %s" % ", ".join(ied_names),
    )

    ports = [model.make("port", description=item)
             for item in split_list(desc.get("Цифровые порты", ""))]

    # --- таблицы ИЭУ: простые соответствия 1 строка = 1 объект ----------
    simple = [
        ("AnalogInput", "Входные аналоговые измерения",
         lambda r: dict(circuit_type=r[0], test_block=r[1],
                        contacts_count=r[2], note=r[3])),
        ("InnerDiscreteCircuit", "Внутренние дискретные цепи",
         lambda r: dict(discrete_signal=r[0], direction=r[1], note=r[2])),
        ("IncomingGooseSignal", "Информационные сигналы в составе входящих сообщений",
         lambda r: dict(signal=r[0], info_model=r[1], source=r[2],
                        max_number=r[3], RAS=r[4])),
        ("FunctionalButton", "Функциональные клавиши",
         lambda r: dict(mapping=r[0], short_name=r[1],
                        disable_condition=r[2], enable_condition=r[3])),
        ("LED", "Светодиодная сигнализация",
         lambda r: dict(mapping=r[0], name=r[1], mode=r[2])),
        ("OscAnalogSignal", "Осциллографируемые аналоговые сигналы",
         lambda r: dict(description=r[0], canal=r[1], name=r[2], startRAS=r[3])),
        ("ControlCommand", "Команды управления от АСУ ТП",
         lambda r: dict(name=r[0], info_model=r[1])),
    ]
    ied_children = defaultdict(list)
    for cls, prefix, mapper in simple:
        for row in table(prefix, cls):
            if not any(row):
                continue
            padded = list(row) + [""] * 8
            ied_children[cls].append(model.make(cls, **mapper(padded)))

    # --- Function / Parameter -------------------------------------------
    main_codes = codes(desc.get("Основные функции"))
    its_key = next((k for k in desc if k.startswith("Функции ИТС")), "")
    its_codes = codes(desc.get(its_key))
    main_aliases = code_aliases(main_codes)
    its_aliases = code_aliases(its_codes)
    all_codes = sorted(main_aliases | its_aliases, key=len, reverse=True)

    def flags(name):
        head = name.split("/")[0].strip()
        match = next((c for c in all_codes if head.upper().startswith(c.upper())), None)
        return (bool(match and match in main_aliases),
                bool(match and match in its_aliases))

    groups, current = [], None
    for row in table("Основные параметры функций РЗА", "Function/Parameter"):
        row = list(row) + [""] * 3
        if row[0] and not row[1] and not row[2]:       # строка-заголовок функции
            current = {"name": row[0], "params": []}
            groups.append(current)
        elif current is not None and row[0]:
            current["params"].append(
                model.make("Parameter", name=row[0], description=row[1],
                           conditions=row[2]))
        elif row[0]:
            model.skipped["Parameter без функции"] += 1
    seen_heads = {g["name"].split("/")[0].strip().upper() for g in groups}
    for code in dict.fromkeys(main_codes + its_codes):
        if code.upper() not in seen_heads:
            groups.append({"name": code, "params": []})
    functions = []
    for group in groups:
        is_main, is_its = flags(group["name"])
        fn = model.make("Function", name=group["name"],
                        isMainFunction=is_main, isInITS=is_its)
        model.attach(fn, "Function", "Parameter", group["params"])
        functions.append(fn)
    ied_children["Function"] = functions

    # --- DataSet / Signal / исходящие сообщения --------------------------
    meta, mode = {}, {}
    for row in table("Сообщения и отчеты, исходящие от ИЭУ",
                     "DataSet/OutcomingMessage/OutcomingReport"):
        row = list(row) + [""] * 6
        if row[0].startswith("Сообщения") and row[2] == "goID":
            continue
        if row[0].startswith("Отчеты") and row[2] == "rptID":
            continue
        if row[0].startswith("Примечание") or not row[3]:
            continue
        meta[row[3]] = dict(mapping=row[0], sender=row[1], id=row[2],
                            **{"class": row[4]}, note=row[5])
        mode[row[3]] = "goose" if row[3].startswith("dsgo") else "report"

    def signal_groups(prefix, target, kind):
        result, current = OrderedDict(), None
        for row in table(prefix, target):
            row = list(row) + [""] * 8
            if "набора данных" in row[0].lower():
                current = row[1].strip()
                result.setdefault(current, [])
                continue
            if not row[0]:
                continue
            if kind == "goose":
                sig = model.make("Signal", name=row[0], info_model=row[1],
                                 destination=row[2])
            else:
                do, da = row[6], row[7]
                info = ".".join(x for x in (do, da) if x)
                sig = model.make("Signal", name=row[0], info_model=info,
                                 status=row[1], KT=row[2], cus=row[3],
                                 rdu=row[4], RAS=row[5], DO=do, DA=da)
            if current is None:
                current = ""
                result.setdefault(current, [])
            result[current].append(sig)
        return result

    goose = signal_groups("Информационные сигналы в составе исходящих сообщений",
                          "Signal (GOOSE)", "goose")
    reports = signal_groups("Информационные сигналы в составе исходящих отчетов",
                            "Signal (отчёты)", "report")
    signals = OrderedDict()
    for name, items in goose.items():
        signals.setdefault(name, []).extend(items)
    for name, items in reports.items():
        signals.setdefault(name, []).extend(items)
    for name in meta:
        signals.setdefault(name, [])

    outcoming_messages, outcoming_reports, ied_datasets = [], [], []
    for name, sigs in signals.items():
        kind = mode.get(name, "goose" if name.startswith("dsgo") else "report")
        data = dict(meta.get(name, {}))
        data["name"] = name
        if not name:
            data.setdefault("mapping", "Сигналы без набора данных")
            model.notes.append("сигналы без маркера «Имя набора данных»")
        ds = model.make("DataSet", **data)
        model.attach(ds, "DataSet", "Signal", sigs)
        if kind == "goose":
            msg = model.make("OutcomingMessage")
            model.attach(msg, "OutcomingMessage", "DataSet", [ds])
            outcoming_messages.append(msg)
        else:
            outcoming_reports.append(model.make(
                "OutcomingReport", mapping=meta.get(name, {}).get("mapping"),
                sender=meta.get(name, {}).get("sender"),
                id=meta.get(name, {}).get("id"),
                message_class=meta.get(name, {}).get("class"),
                note=meta.get(name, {}).get("note")))
            ied_datasets.append(ds)
    ied_children["OutcomingMessage"] = outcoming_messages
    ied_children["OutcomingReport"] = outcoming_reports
    ied_children["DataSet"] = ied_datasets

    # --- TerminalBlock / TerminalRow / Terminal --------------------------
    raw_blocks, current = [], None
    for row in table("Ряды зажимов", "TerminalBlock/TerminalRow/Terminal"):
        row = list(row) + [""] * 5
        if "разделитель" in row[4].lower() and not row[1]:
            model.skipped["строки-разделители цепей (не клеммы)"] += 1
            continue
        if row[0] and not row[1] and not row[2] and not row[3]:
            current = {"text": row[0], "location": row[4], "items": []}
            raw_blocks.append(current)
        elif row[0]:
            if current is None:
                current = {"text": "", "location": "", "items": []}
                raw_blocks.append(current)
            current["items"].append(model.make(
                "Terminal", number=row[0], quantity=row[1],
                function_type=row[2], connection_type=row[3], purpose=row[4]))
    blocks = []
    for b in raw_blocks:
        block = model.make("TerminalBlock", text=b["text"])
        row_obj = model.make("TerminalRow", location=b["location"])
        model.attach(row_obj, "TerminalRow", "Terminal", b["items"])
        model.attach(block, "TerminalBlock", "TerminalRow", [row_obj])
        blocks.append(block)
    model.attach(kit, "Kit", "TerminalBlock", blocks)

    # --- сборка ИЭУ, комплекта, шкафа -----------------------------------
    ieds = []
    for number, _ in enumerate(ied_names, start=1):
        ied = model.make("IED", number=number)
        if number == 1:
            model.attach(ied, "IED", "port", ports)
            for cls, items in ied_children.items():
                model.attach(ied, "IED", cls, items)
        ieds.append(ied)
    model.attach(kit, "Kit", "IED", ieds)     # композиция Cabinet → Kit → IED
    model.attach(cabinet, "Cabinet", "Kit", [kit])
    return {"источник": source, "Cabinet": cabinet, "CabinetReport": report}


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------
def write_report(path, model, result, errors, problems, uml_path, doc_source):
    lines = []
    add = lines.append
    add("# Шкафы стандарта по UML-модели EA")
    add("")
    add("Собрано: %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    add("")
    add("| Источник | Файл |")
    add("| --- | --- |")
    add("| UML-схема (XMI) | `%s` |" % os.path.relpath(uml_path, ROOT).replace("\\", "/"))
    add("| Стандарт | `%s` |" % os.path.relpath(doc_source, ROOT).replace("\\", "/"))
    add("| Результат | `EA/cabinets_uml.json` |")
    add("")
    add("Модель: **классов — %d, атрибутов — %d, ассоциаций — %d**. Имена полей "
        "в JSON совпадают с атрибутами XMI; вложенность повторяет связи классов. "
        "В XMI два элемента `TerminalRow` (дубликат с атрибутом `Location`), "
        "поэтому уникальных имён классов на один меньше."
        % (len(model.classes), sum(len(a) for a in model.classes.values()),
           len(model.links)))
    add("")
    add("## Шкафы")
    add("")
    add("| Раздел | Шифр | Наименование | Комплекты / ИЭУ | Функций | Сигналов | Клемм |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for entry in result["шкафы"]:
        cab = entry["Cabinet"]
        kit = cab.get("Kit", [{}])[0]
        ied = kit.get("IED", [{}])[0]
        fn = len(ied.get("Function", []))
        sig = sum(len(ds.get("Signal", []))
                  for msg in ied.get("OutcomingMessage", [])
                  for ds in msg.get("DataSet", []))
        sig += sum(len(ds.get("Signal", [])) for ds in ied.get("DataSet", []))
        term = sum(len(row.get("Terminal", []))
                   for block in kit.get("TerminalBlock", [])
                   for row in block.get("TerminalRow", []))
        add("| %s | %s | %s | %d / %d | %d | %d | %d |" % (
            entry["источник"]["раздел"], cab.get("cypher", ""),
            cab.get("name", ""), len(cab.get("Kit", [])),
            len(kit.get("IED", [])), fn, sig, term))
    add("")
    add("## Покрытие UML-классов")
    add("")
    add("| Класс | Объектов | Заполнено атрибутов | Не заполнено |")
    add("| --- | ---: | --- | --- |")
    for cls in sorted(model.classes):
        attrs = model.classes[cls]
        have = model.filled[cls]
        empty = [a for a in attrs if not have[a]]
        add("| `%s` | %d | %s | %s |" % (
            cls, model.counts[cls],
            ", ".join("`%s`" % a for a in attrs if have[a]) or "—",
            ", ".join("`%s`" % a for a in empty) or "—"))
    add("")
    add("## Соответствие таблиц стандарта и классов UML")
    add("")
    add("| Подпись таблицы (раздел 5.N) | Классы / блок |")
    add("| --- | --- |")
    for prefix, target in TABLE_PREFIX.items():
        add("| %s… | `%s` |" % (prefix, target))
    add("")
    add("Карточка «Описание ШЭТ» даёт `Cabinet` (шифр, архитектура, наименование, "
        "управляемый/защищаемый элементы, область применения), `PowerSupply`, `port`, "
        "`Kit`, первый абзац раздела — `Cabinet.description`. `CabinetReport` — "
        "сводная карточка с `components`. Поле `Cabinet.standard` содержит имя файла "
        "исходного стандарта без расширения (%s) — оно одинаково у всех шкафов тома "
        "и позволяет отличать выгрузки разных томов при сборке новых шкафов."
        % os.path.splitext(os.path.basename(doc_source))[0])
    add("")
    add("## Оговорки")
    add("")
    add("* В XMI два класса `TerminalRow` (атрибуты `location` и `Location`), а "
        "композитные концы связей `Kit`/`TerminalRow`/`TerminalBlock`/`Terminal` "
        "образуют кольцо. Использована иерархия самой таблицы «Ряды зажимов»: "
        "`Kit.TerminalBlock → TerminalRow → Terminal`; `TerminalRow.location` — "
        "маркировка колодки из строки-заголовка.")
    add("* `OutcomingMessage` в UML не имеет атрибутов, только связь с `DataSet`: "
        "строки GOOSE таблицы «Сообщения и отчеты…» стали контейнерами, а sender / "
        "id / class / note лежат во вложенном `DataSet`. Отчёты `dsrpt_*` лежат "
        "непосредственно в `IED.DataSet` (по связи IED → DataSet), а их описания — "
        "в `IED.OutcomingReport`.")
    add("* `Function.isMainFunction` / `isInITS` выведены из полей «Основные функции» "
        "и «Функции ИТС [14]» карточки: для групп таблицы 5.N.13 берётся самое "
        "длинное совпадение кода, функции без группы добавлены отдельно. Обозначения "
        "со скобками («ДТЗ СО (ДЗР ШР)») раскрываются в синонимы, чтобы оба списка "
        "сопоставлялись; группы «Параметры ТН/ТТ», «КСВ», «ЛО …», «ЗПО» и т.п. "
        "в перечнях карточки не значатся и получают `false / false`. Атрибуты "
        "`iec_name` и `russian_path` в стандарте отсутствуют и не записаны.")
    add("* Значения «» («то же, что выше») развёрнуты по столбцу, пустые ячейки и "
        "строки-заголовки («Имя набора данных», «Сообщения», «Отчеты», примечания) "
        "в объекты не превращаются. Строки «Разделитель цепи» в таблице рядов "
        "зажимов не являются клеммами и пропущены.")
    add("* Набор `dsrpt_DR` («Данные РАС») заявлен в таблице сообщений, но отдельной "
        "таблицы сигналов для него в разделе нет — `DataSet` создан без `Signal`.")
    add("* `Signal.info_model` для отчётов собран из `DO.DA`, сами `DO` и `DA` "
        "сохранены отдельно; `destination` есть только у GOOSE-сигналов.")
    add("* Атрибутов, для которых в таблицах стандарта нет колонок, в JSON нет: "
        "`Function.iec_name`, `Function.russian_path`, `LED.note`, `Signal.note`, "
        "`IncomingGooseSignal.note`, `IncomingGooseSignal.source_number`, "
        "`OscAnalogSignal.canal` (столбец «Канал» в документе пуст).")
    add("* Проверка результата по модели: **%s**." % (
        "ошибок нет" if not errors else "%d ошибок: %s" % (len(errors), "; ".join(errors[:10]))))
    if model.skipped:
        add("* Пропущено при разборе: %s." % "; ".join(
            "%s — %d" % (k, v) for k, v in model.skipped.most_common(8)))
    if model.notes:
        add("* Дополнительно: %s." % "; ".join(sorted(set(model.notes))))
    if problems:
        add("")
        add("### Замечания парсера DOCX")
        add("")
        for problem in problems:
            add("* %s" % problem)
    add("")
    add("## Повторить")
    add("")
    add("```bash")
    add("python3 tools/docx_to_uml.py")
    add("python3 tools/docx_to_uml.py --docx \"EA/Раздел 4.16_т. 5_СТО ШЭТ СКРМ II_Ред.2.docx\"")
    add("```")
    add("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uml", default=DEFAULT_UML, help="XMI-экспорт EA")
    parser.add_argument("--docx", default=None, help="DOCX стандарта (по умолчанию из EA/)")
    parser.add_argument("--std-json", default=None, help="взять готовый JSON вместо DOCX")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    model = UmlModel(args.uml)
    data, problems, doc_source = read_standard(args.docx, args.std_json)
    content = data["Содержимое стандарта"]
    standard = os.path.splitext(os.path.basename(doc_source))[0]
    entries = [build_cabinet(name, block, model, standard)
               for name, block in content.items()
               if isinstance(block, dict) and "Шифр шкафа" in block]
    if not entries:
        raise SystemExit("шкафы в стандарте не найдены")

    # IED вложен в Kit вручную (в XMI связь IED → Kit проведена в обратную
    # сторону); остальное проверяем строго по ассоциациям.
    errors = []
    for entry in entries:
        model.validate(entry["Cabinet"], "Cabinet", errors, "Cabinet")
        model.validate(entry["CabinetReport"], "CabinetReport", errors, "CabinetReport")
        kit = entry["Cabinet"]["Kit"][0]
        model.validate(kit.get("IED", []), "IED", errors, "Kit.IED")
        for ied in kit.get("IED", []):
            if "Kit" in ied:
                errors.append("лишняя связь IED.Kit")

    result = OrderedDict()
    result["версия"] = 1
    result["схема"] = OrderedDict([
        ("файл", os.path.relpath(args.uml, ROOT).replace("\\", "/")),
        ("классов", len(model.classes)),
        ("ассоциаций", len(model.links)),
        ("классы", OrderedDict(
            (name, OrderedDict([
                ("атрибуты", OrderedDict(attrs)),
                ("связи", sorted(model.children[name])),
            ])) for name, attrs in model.classes.items())),
    ])
    result["стандарт"] = OrderedDict([
        ("обозначение", data.get("Обозначение стандарта", "")),
        ("шифр", data.get("Шифр стандарта", "")),
        ("принадлежность", data.get("Принадлежность стандарта", "")),
        ("источник", os.path.relpath(doc_source, ROOT).replace("\\", "/")),
    ])
    result["шкафы"] = entries
    result["итого"] = OrderedDict(
        [("шкафов", len(entries))] +
        [(cls, model.counts[cls]) for cls in sorted(model.counts)])
    result["проверка"] = OrderedDict([
        ("ошибки", errors),
        ("пропущено значений", dict(model.skipped)),
        ("замечания", sorted(set(model.notes))),
    ])

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    write_report(args.report, model, result, errors, problems, args.uml, doc_source)

    print("шкафов: %d" % len(entries))
    for cls in sorted(model.counts):
        print("  %-22s %5d" % (cls, model.counts[cls]))
    print("проверка: %s" % ("OK" if not errors else "%d ошибок" % len(errors)))
    print("→ %s (%.1f МБ)" % (args.out, os.path.getsize(args.out) / 1024 / 1024))
    print("→ %s" % args.report)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
