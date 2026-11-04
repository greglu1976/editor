# -*- coding: utf-8 -*-
"""Каталог шкафов РЗА и устройств (IED) для редактора схем.

Шкаф помещается на схему и **состоит из комплектов** (от 1 до
MAX_KOMPLETS). Комплект — подключаемая единица: к его порту идут защитные
связи к защитным узлам первичного оборудования (узел — в центре символа
оборудования). ИЭУ хранится внутри комплекта, причём комплект может быть
и без ИЭУ; единственное ИЭУ в описании шкафа входит в его комплект.

Формат записи:
    {
        "key":  "уникальный код шкафа",
        "standard_key": "ключ стандарта из STANDARDS (tat, skrm, lep, sch)",
        "code": "шифр по стандарту (необязательно)",
        "name": "название шкафа для списка",
        "title": "полное наименование (необязательно)",
        "description": "назначение",
        "voltage": "класс напряжения (необязательно)",
        "protected": "защищаемый элемент (необязательно)",
        "controlled": ["управляемые выключатели"],
        "its_functions": ["функции ИТС"],
        "applicability": "применимость по типовым схемам",
        "source": "раздел СТО",
        "tags": ["произвольные метки, например «Невыпущенные СТО»"],
        "komplets": [
            {"name": "Комплект 1", "type": "МП РЗА",
             "kind": "typical | custom | other",
             "functions": ["ДЗТ", "..."], "desc": "...",
             "has_ied": True,
             "ieds": [{"name": "ИЭУ1", "type": "МП РЗА", "desc": "..."}],
             "test_blocks": {
                 "voltage": {"count": 2, "circuits": ["Ua", "Ub", "Uc"]},
                 "current": {"count": 1, "circuits": ["Ia", "Ib", "Ic"]},
             }},
        ],
    }

Комплектов в шкафу — от 1 до MAX_KOMPLETS (7). Комплект — подключаемая
единица: у него свой порт, к которому идут защитные связи; ИЭУ внутри
комплекта может не быть. У комплекта есть вид (типовой — из типового шкафа,
нетиповой, прочий), функции, признак наличия ИЭУ и испытательные блоки по
напряжению и току. Комплекты ведутся также в отдельном каталоге
(komplekts.py), а в шкафу хранится их копия.

Описательные поля из стандартов (komplekts.DETAIL_FIELDS) — универсальные,
одинаковые у шкафов и у комплектов. Заполняются из таблиц «Описание ШЭТ…»
соответствующих СТО; если в стандарте поле не описано, хранится None:

    mp_functions          основные функции МП ИЭУ;
    its_functions_desc    функции ИТС (в т. ч. отображаемые на схеме ИТС);
    power_supply          вводы (цепи) питания оперативного тока;
    ports                 цифровые порты ИЭУ / порты шины;
    connection_scheme     поясняющая схема подключения;
    components            основные компоненты шкафа;
    additional_equipment  дополнительная аппаратура;
    parameters            основные параметры функций ИЭУ;
    general_view          эскиз общего вида;
    structural_scheme     структурно-функциональная схема;
    schematic             схема электрическая принципиальная;
    climate               климатическое исполнение;
    enclosure             степень защиты оболочки;
    cooling               охлаждение шкафа;
    communication         аппаратура связи;
    notes                 примечания.

Перечни сигналов и испытательные блоки в сам справочник не входят: они
объёмные и хранятся отдельно, в cabs_signals.json, по ключу шкафа:

    io_in        входные дискретные сигналы (внутренние дискретные цепи);
    io_out       выходные дискретные сигналы, формируемые ИЭУ;
    goose_in     входные GOOSE-сообщения;
    goose_out    выходные GOOSE-сообщения;
    test_blocks  испытательные блоки (тип БИ, число цепей, количество).

Каждый сигнал — {"name": наименование, "code": обозначение по МЭК 61850,
"details": прочие сведения из таблицы}. См. signals_for()/signal_counts().

Каталог содержит типовые шкафы ШЭТ по четырём стандартам ПАО «ФСК ЕЭС»
(архитектура II типа, введены 26.12.2019):

* СТО 56947007-33.040.20.277-2019 — (авто)трансформаторы 110-750 кВ;
* СТО 56947007-33.040.20.280-2019 — шунтирующие и компенсационные
  реакторы, батареи статических конденсаторов (СКРМ) 110-750 кВ;
* СТО 56947007-33.040.20.283-2019 — ЛЭП 110-750 кВ;
* СТО 56947007-33.040.20.286-2019 — сборные шины, ошиновки и шинные
  аппараты 6-750 кВ.

Шкафы тех же серий для архитектур I и III типа (СТО 276, 278, 279, 281,
282, 284, 285, 287), а также шкафы ШСО, ШСК (СТО 289, 290) и отсеки
ШЭТ/ОЭТ 6-35 кВ (СТО 296, 297) собраны в cabs_sto.py; там же хранятся
исправления полей записей cabs_data.py. См. CABINETS ниже.

Шкафы остальных стандартов (архитектура I типа, ОЭТ 6–35 кВ, УПАСК, ПДС,
АРНТ, ПА, ВК, ШКП, ШИП) собраны в едином справочнике cabs_data.py.
"""

import copy
import json
import os
import re
import uuid

import cabs_data
import cabs_sto
import komplekts

_COMMON_STANDARD = {
    "organization": "ПАО «ФСК ЕЭС»",
    "date": "26.12.2019",
    "architecture": "II тип",
    "dimensions": "800×600×2200 мм (Ш×Г×В, включая цоколь 200 мм)",
    "ports": ["порт A шины станции (Duplex LC)",
              "порт B шины станции (Duplex LC)"],
    "protocols": ["МЭК 61850-8-1: GOOSE, MMS"],
}


def _standard(group, code, title):
    standard = dict(_COMMON_STANDARD)
    standard.update({"group": group, "code": code, "title": title})
    return standard


#: Стандарты, по которым выполнены типовые шкафы каталога.
STANDARDS = {
    "tat": _standard(
        "Т/АТ",
        "СТО 56947007-33.040.20.277-2019",
        "Типовые шкафы ШЭТ РЗА (авто)трансформаторов 110-750 кВ. "
        "Архитектура II типа"),
    "skrm": _standard(
        "СКРМ",
        "СТО 56947007-33.040.20.280-2019",
        "Типовые шкафы ШЭТ РЗА шунтирующих реакторов, компенсационных "
        "реакторов и батарей статических конденсаторов 110-750 кВ. "
        "Архитектура II типа"),
    "lep": _standard(
        "ЛЭП",
        "СТО 56947007-33.040.20.283-2019",
        "Типовые шкафы ШЭТ РЗА ЛЭП 110-750 кВ. Архитектура II типа"),
    "sch": _standard(
        "СШ",
        "СТО 56947007-33.040.20.286-2019",
        "Типовые шкафы ШЭТ РЗА сборных шин, ошиновок и шинных аппаратов "
        "6-750 кВ. Архитектура II типа"),
}

#: Корпоративные шкафы вторичной коммутации, УПАСК, ПДС, ШПДС, АРНТ и 6–35 кВ.
STANDARDS.update({
    "vk": _standard(
        "ВК", "СТО 56947007-33.040.20.307-2020",
        "Корпоративные шкафы вторичной коммутации (ВК): шкафы зажимов "
        "измерительных трансформаторов, промежуточных согласующих "
        "трансформаторов, организации цепей напряжения, перевода на "
        "обходной выключатель"),
    "upask": _standard(
        "УПАСК", "СТО 56947007-33.040.20.288-2019",
        "Типовые шкафы УПАСК (устройств передачи аварийных сигналов и "
        "команд)"),
    "shpds": _standard(
        "ПДС", "СТО 34.01-4.1-017-2024",
        "Типовые шкафы. Шкафы преобразователей дискретных сигналов (ШПДС). "
        "Архитектуры II и III типа"),
    "pds": _standard(
        "ПДС", "СТО 56947007-29.240.10.308-2020",
        "Типовые шкафы ШЭТ ПДС (преобразователей дискретных сигналов)"),
    "arnt": _standard(
        "АРНТ", "СТО 34.01-4.1-018-2025",
        "Корпоративные шкафы РЗА плавки гололеда, автоматического "
        "регулирования напряжения трансформаторов и автотрансформаторов и "
        "автоматики пуска пожаротушения маслонаполненного оборудования. "
        "Архитектура II типа"),
    "kv35": _standard(
        "35 кВ", "СТО 34.01-4.1-021-2025",
        "Типовые шкафы ШЭТ и ОЭТ 6–35 кВ. Архитектура II типа"),
    "pa": _standard(
        "ПА", "СТО 56947007-33.040.20.320-2022",
        "Типовые шкафы противоаварийной автоматики. Архитектура I типа"),
})

#: Тег шкафов и комплектов из ещё не выпущенных (проектных) редакций СТО.
TAG_UNRELEASED = komplekts.TAG_UNRELEASED


def _draft_standard(group, title):
    """Стандарт, который ещё не выпущен (проект редакции 2, 2023 г.)."""
    standard = dict(_COMMON_STANDARD)
    standard.update({
        "group": group,
        "code": "СТО (проект, ред. 2)",
        "title": title,
        "date": "2023 (проект)",
        "edition": "Редакция 2",
        "released": False,
        "tags": [TAG_UNRELEASED],
    })
    return standard


#: Проекты СТО раздела 4.16 (редакция 2). Шкафы по ним помечены тегом
#: «Невыпущенные СТО»: приказ и дата введения в стандартах не заполнены.
STANDARDS.update({
    "sch2": _draft_standard(
        "СШ",
        "Типовые шкафы ШЭТ РЗА сборных шин, ошиновок и шинных аппаратов "
        "6–750 кВ. Архитектура II типа"),
    "lep2": _draft_standard(
        "ЛЭП",
        "Типовые шкафы ШЭТ РЗА ЛЭП 110–750 кВ. Архитектура II типа"),
    "skrm2": _draft_standard(
        "СКРМ",
        "Типовые шкафы ШЭТ РЗА шунтирующих реакторов, компенсационных "
        "реакторов и батарей статических конденсаторов 110–750 кВ. "
        "Архитектура II типа"),
    "tat2": _draft_standard(
        "Т/АТ",
        "Типовые шкафы ШЭТ РЗА (авто)трансформаторов 110–750 кВ. "
        "Архитектура II типа"),
})


def _typed_standard(group, code, title, architecture):
    """Стандарт с явной архитектурой построения ПС (I/II/III тип)."""
    standard = _standard(group, code, title)
    standard["architecture"] = architecture
    return standard


#: Выпущенные СТО 2019 года по архитектурам I, II и III типа (276–287) и
#: шкафы АСУ ТП (289–292). Ключи I и III типа отделены от базового ключа
#: II типа (tat, skrm, lep, sch), чтобы в карточке шкафа был верный СТО.
STANDARDS.update({
    "tat1": _typed_standard(
        "Т/АТ", "СТО 56947007-33.040.20.276-2019",
        "Типовые шкафы ШЭТ РЗА (авто)трансформаторов 110-750 кВ. "
        "Архитектура I типа", "I тип"),
    "tat3": _typed_standard(
        "Т/АТ", "СТО 56947007-33.040.20.278-2019",
        "Типовые шкафы ШЭТ РЗА (авто)трансформаторов 110-750 кВ. "
        "Архитектура III типа", "III тип"),
    "skrm1": _typed_standard(
        "СКРМ", "СТО 56947007-33.040.20.279-2019",
        "Типовые шкафы ШЭТ РЗА шунтирующих реакторов, компенсационных "
        "реакторов и батарей статических конденсаторов 110-750 кВ. "
        "Архитектура I типа", "I тип"),
    "skrm3": _typed_standard(
        "СКРМ", "СТО 56947007-33.040.20.281-2019",
        "Типовые шкафы ШЭТ РЗА шунтирующих реакторов, компенсационных "
        "реакторов и батарей статических конденсаторов 110-750 кВ. "
        "Архитектура III типа", "III тип"),
    "lep1": _typed_standard(
        "ЛЭП", "СТО 56947007-33.040.20.282-2019",
        "Типовые шкафы ШЭТ РЗА ЛЭП 110–750 кВ. Архитектура I типа",
        "I тип"),
    "lep3": _typed_standard(
        "ЛЭП", "СТО 56947007-33.040.20.284-2019",
        "Типовые шкафы ШЭТ РЗА ЛЭП 110–750 кВ. Архитектура III типа",
        "III тип"),
    "sch1": _typed_standard(
        "СШ", "СТО 56947007-33.040.20.285-2019",
        "Типовые шкафы ШЭТ РЗА сборных шин, ошиновок и шинных аппаратов "
        "6–750 кВ. Архитектура I типа", "I тип"),
    "sch3": _typed_standard(
        "СШ", "СТО 56947007-33.040.20.287-2019",
        "Типовые шкафы ШЭТ РЗА сборных шин, ошиновок и шинных аппаратов "
        "6–750 кВ. Архитектура III типа", "III тип"),
    "so": _typed_standard(
        "АСУ ТП", "СТО 56947007-33.040.20.289-2019",
        "Типовые шкафы серверного оборудования (ШСО). "
        "Архитектура II и III типа", "II и III тип"),
    "sk": _typed_standard(
        "АСУ ТП", "СТО 56947007-33.040.20.290-2019",
        "Типовые шкафы сетевой коммутации (ШСК). "
        "Архитектура II и III типа", "II и III тип"),
    "kp": _typed_standard(
        "АСУ ТП", "СТО 56947007-33.040.20.291-2019",
        "Типовые шкафы контроллеров присоединений (ШКП). "
        "Архитектура II и III типа", "II и III тип"),
    "ip": _typed_standard(
        "АСУ ТП", "СТО 56947007-33.040.20.292-2019",
        "Типовые шкафы измерительных преобразователей (ШИП). "
        "Архитектура II типа", "II тип"),
    "kv35i": _typed_standard(
        "6–35 кВ", "СТО 56947007-33.040.20.296-2019",
        "Типовые шкафы ШЭТ и ОЭТ 6-35 кВ. Архитектура I типа", "I тип"),
    "kv35ii": _typed_standard(
        "6–35 кВ", "СТО 56947007-33.040.20.297-2019",
        "Типовые шкафы ШЭТ и ОЭТ 6-35 кВ. Архитектура II типа", "II тип"),
})

#: Первый стандарт каталога (Т/АТ) — оставлен для обратной совместимости.
STANDARD = STANDARDS["tat"]


def cabinet_tags(cabinet):
    """Теги шкафа (например, «Невыпущенные СТО»)."""
    return komplekts.tags_of(cabinet)


def all_tags():
    """Все теги, встречающиеся в каталоге шкафов (по алфавиту)."""
    user = _read_user_catalog()
    tags = set()
    for cabinet in CABINETS:
        tags.update(cabinet_tags(cabinet))
    for cabinet in user["custom"]:
        tags.update(cabinet_tags(cabinet))
    for cabinet in user["overrides"].values():
        tags.update(cabinet_tags(cabinet))
    return sorted(tags)


def standard_for(cabinet):
    """Стандарт, по которому выполнен шкаф; None — для произвольного шкафа."""
    key = cabinet.get("standard_key")
    return STANDARDS.get(key) if key else None

#: Единый справочник шкафов: одна запись — один шкаф, одинаковый набор полей.
#: Шкафы, занесённые из выпущенных СТО (cabs_sto.py), дополняют встроенный
#: справочник; правки их полей применяются поверх cabs_data.
CABINETS = [copy.deepcopy(cabinet) for cabinet in cabs_data.CABINETS]
for _cabinet in CABINETS:
    _cabinet.update(cabs_sto.CORRECTIONS.get(_cabinet.get("key"), {}))
    _functions = cabs_sto.KIT_FUNCTIONS.get(_cabinet.get("key"))
    if _functions:
        for _komplet, _items in zip(_cabinet.get("komplets") or [], _functions):
            _komplet["functions"] = list(_items)
            for _ied in _komplet.get("ieds") or []:
                _ied["functions"] = list(_items)
CABINETS.extend(copy.deepcopy(cabs_sto.CABINETS))
del _cabinet, _functions

#: Универсальные описательные поля (одни и те же у шкафов и комплектов).
DETAIL_FIELDS = komplekts.DETAIL_FIELDS


# Привязка шкафов к стандартам: код → полное наименование СТО, группа, архитектура
def _apply_standard_defaults(cabinet):
    """Дополняет шкаф данными его стандарта (группа, архитектура, СТО)."""
    standard_key = cabinet.get("standard_key")
    if standard_key is None and cabinet.get("code"):
        standard_key = "tat"       # шкафы (авто)трансформаторов из первого СТО
        cabinet["standard_key"] = standard_key
    standard = STANDARDS.get(standard_key)
    if standard:
        cabinet.setdefault("standard", standard["code"])
        cabinet.setdefault("standard_title", standard["title"])
        cabinet.setdefault("architecture", standard["architecture"])
        cabinet.setdefault("group", standard["group"])
    else:
        cabinet.setdefault("group", "Прочие")
    # Описательные поля из стандартов: пустое значение — None.
    details = cabs_data.DETAILS_BY_CODE.get(
        (cabinet.get("code") or "").strip()) or {}
    for name in DETAIL_FIELDS:
        value = cabinet.get(name) or details.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        cabinet[name] = value


for cabinet in CABINETS:
    _apply_standard_defaults(cabinet)


# ---------------------------------------------------------------------------
# Пользовательский каталог: создание, изменение и удаление шкафов
# ---------------------------------------------------------------------------
# Встроенные шкафы из CABINETS не меняются. Всё, что пользователь создал или
# изменил, хранится в cabinets.json рядом с этим файлом:
#     {"custom": [...], "overrides": {"ключ": {...}}, "deleted": ["ключ", ...]}
#
# Шкаф содержит до MAX_KOMPLETS комплектов. Комплект — подключаемая единица
# (свой порт и защитные связи) и может содержать 0..N устройств ИЭУ.

MAX_KOMPLETS = 7

USER_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cabinets.json")

#: Сигналы и испытательные блоки из СТО (генерируется output/build_signals.py).
SIGNALS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cabs_signals.json")


def normalize_cabinet(cabinet):
    """Приводит шкаф к модели «шкаф состоит из комплектов».

    Старое поле ``ieds`` (ИЭУ прямо в описании шкафа) переносится в комплекты:
    одно ИЭУ входит в первый комплект, несколько — по комплекту на ИЭУ.
    После этого у шкафа есть только ``komplets``; ИЭУ на уровне шкафа не
    хранится. См. ``komplekts.ensure_cabinet_kits``.
    """
    # Теги: строка «а; б» или список → список строк (пустой — не храним).
    tags = komplekts.tags_of(cabinet)
    if tags:
        cabinet["tags"] = tags
    else:
        cabinet.pop("tags", None)
    # Типовой шкаф (есть стандарт) порождает типовые комплекты,
    # произвольный — нетиповые.
    default_kind = "typical" if cabinet.get("standard_key") else "custom"
    kits = komplekts.ensure_cabinet_kits(cabinet)
    cabinet["komplets"] = komplekts.normalize_komplets(
        kits[:MAX_KOMPLETS], default_kind, cabinet)
    return cabinet


def _read_user_catalog():
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
    if not data["custom"] and not data["overrides"] and not data["deleted"]:
        if os.path.exists(USER_CATALOG_PATH):
            os.remove(USER_CATALOG_PATH)
        return
    with open(USER_CATALOG_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def builtin_keys():
    return {cabinet.get("key") for cabinet in CABINETS}


def is_builtin(key):
    return key in builtin_keys()


def all_cabinets():
    """Встроенные шкафы + пользовательские, с учётом правок и удалений."""
    user = _read_user_catalog()
    result = []
    for cabinet in CABINETS:
        key = cabinet.get("key")
        if key in user["deleted"]:
            continue
        entry = copy.deepcopy(user["overrides"].get(key) or cabinet)
        normalize_cabinet(entry)
        _apply_standard_defaults(entry)
        result.append(entry)
    for entry in user["custom"]:
        if entry.get("key") in user["deleted"]:
            continue
        entry = copy.deepcopy(entry)
        normalize_cabinet(entry)
        _apply_standard_defaults(entry)
        result.append(entry)
    return result


def find_cabinet(key):
    for cabinet in all_cabinets():
        if cabinet.get("key") == key:
            return cabinet
    return None


def _make_key(code, name):
    base = code or name or "cabinet"
    slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", base).strip("-").lower()
    slug = slug or "cabinet"
    existing = {cabinet.get("key") for cabinet in all_cabinets()}
    key = slug
    while key in existing:
        key = "{}-{}".format(slug, uuid.uuid4().hex[:4])
    return key


def save_cabinet(definition, original_key=None):
    """Создаёт или изменяет шкаф в пользовательском каталоге.

    original_key — ключ изменяемого шкафа (None при создании).
    Возвращает ключ сохранённого шкафа.
    """
    user = _read_user_catalog()
    entry = copy.deepcopy(definition)
    key = original_key or entry.get("key")
    if not key or (original_key is None and not entry.get("key")):
        key = _make_key(entry.get("code"), entry.get("name"))
    entry["key"] = key
    normalize_cabinet(entry)
    _apply_standard_defaults(entry)

    if is_builtin(key):
        user["overrides"][key] = entry
    else:
        replaced = False
        for index, cabinet in enumerate(user["custom"]):
            if cabinet.get("key") == key:
                user["custom"][index] = entry
                replaced = True
                break
        if not replaced:
            user["custom"].append(entry)

    if key in user["deleted"]:
        user["deleted"].remove(key)
    _write_user_catalog(user)
    return key


def delete_cabinet(key):
    """Удаляет шкаф из каталога (встроенный — скрывается навсегда)."""
    user = _read_user_catalog()
    if is_builtin(key):
        if key not in user["deleted"]:
            user["deleted"].append(key)
        user["overrides"].pop(key, None)
    else:
        user["custom"] = [cabinet for cabinet in user["custom"]
                          if cabinet.get("key") != key]
    _write_user_catalog(user)


def duplicate_cabinet(key):
    """Создаёт копию шкафа из каталога и возвращает ключ копии.

    Копия всегда становится пользовательским шкафом (встроенный не меняется).
    """
    source = find_cabinet(key)
    if source is None:
        return None
    entry = copy.deepcopy(source)
    entry["key"] = ""
    name = entry.get("name", "Шкаф")
    entry["name"] = "{} (копия)".format(name)
    code = entry.get("code")
    if code:
        entry["code"] = "{} (копия)".format(code)
    return save_cabinet(entry, None)


def reset_user_catalog():
    """Возвращает каталог к встроенному набору (удаляет cabinets.json)."""
    if os.path.exists(USER_CATALOG_PATH):
        os.remove(USER_CATALOG_PATH)


# ---------------------------------------------------------------------------
# Сигналы и испытательные блоки: cabs_signals.json
# ---------------------------------------------------------------------------

#: Виды данных о сигналах: ключ, подпись, короткая подпись для карточки.
SIGNAL_KINDS = (
    ("io_in", "Входные дискретные сигналы", "вх. дискретных"),
    ("io_out", "Выходные дискретные сигналы", "вых. дискретных"),
    ("goose_in", "Входные GOOSE-сообщения", "GOOSE вход."),
    ("goose_out", "Выходные GOOSE-сообщения", "GOOSE исх."),
    ("test_blocks", "Испытательные блоки", "БИ"),
)

_signal_cache = {}


def _signals():
    """Ленивая загрузка cabs_signals.json (при отсутствии файла — пусто)."""
    if "data" not in _signal_cache:
        data = {}
        if os.path.exists(SIGNALS_PATH):
            try:
                with open(SIGNALS_PATH, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                data = {}
        _signal_cache["data"] = data
    return _signal_cache["data"]


def signals_for(cabinet):
    """Сигналы и испытательные блоки шкафа: {вид: [сигналы]}."""
    key = cabinet.get("key") if isinstance(cabinet, dict) else cabinet
    entry = _signals().get(key or "")
    if not entry:
        return {}
    result = {}
    for kind, _title, _short in SIGNAL_KINDS:
        items = entry.get(kind) or []
        if items:
            result[kind] = items
    return result


def signal_counts(cabinet):
    """Число записей по каждому виду данных: {вид: количество}."""
    entry = signals_for(cabinet)
    return {kind: len(entry.get(kind) or []) for kind, _t, _s in SIGNAL_KINDS}


def signal_title(kind):
    """Подпись вида данных о сигналах."""
    for name, title, _short in SIGNAL_KINDS:
        if name == kind:
            return title
    return kind


def has_signals(cabinet):
    """Есть ли для шкафа собранные сигналы или испытательные блоки."""
    return any(signal_counts(cabinet).values())
