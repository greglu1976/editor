# -*- coding: utf-8 -*-
"""Стандарты СТО в машинном виде — папка ``standards_base/``.

В папке лежат стандарты целиком (по файлу на стандарт): шапка, общий перечень
шкафов, карточка каждого шкафа с описанием и всеми таблицами, прочие таблицы
и приложения. Это не «таблицы по ИЭУ», а документ СТО, разложенный по полям.

Три уровня доступа:

* :func:`standards` — шапки стандартов (шифр, дата, число шкафов и таблиц);
* :func:`cabinets` — карточки шкафов, :func:`cabinet` — одна карточка по шифру;
* :func:`record` — карточка, развёрнутая в запись ``structure.json`` v3
  (``шифр``, ``назначение``, ``комплекты`` → ``иэу`` → таблицы), чтобы её можно
  было сравнить с каталогом и подмешать в сборку структуры.

Две модели комплектов приводятся к одной:

* **неявная** — в карточке одно поле ``Комплект`` (имя ИЭУ и аналоговые
  измерения), а таблицы ИЭУ описаны на уровне шкафа ссылками
  («Функциональные клавиши ИЭУ…»: ``Таблица 5.2.5``);
* **явная** — ``Комплект 1`` и ``Комплект 2`` со своими ``Таблицы комплекта``;
  если у комплекта таблицы нет, берётся общешкафная.

Ссылки на таблицы разворачиваются в строки (:func:`table`), ссылки на рисунки
остаются ссылками — изображений в JSON нет.

Запуск для проверки::

    python3 standards_base.py                 # сводка по папке
    python3 standards_base.py "ШЭТ 430.01-0"  # запись v3 одного шкафа
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

import apppaths

HERE = os.path.dirname(os.path.abspath(__file__))
STANDARDS_DIR = apppaths.data_dir("standards_base")

#: Раздел файла стандарта со всем содержимым.
SECTION = "Содержимое стандарта"
CODE_FIELD = "Шифр шкафа"
DESCRIPTION_FIELD = "Описание шкафа"
TABLES_FIELD = "Таблицы"
SOURCE_FIELD = "Раздел стандарта"

#: Поля шапки стандарта.
HEADER_FIELDS = ("Шифр стандарта", "Обозначение стандарта", "Дата введения",
                 "Принадлежность стандарта", "Область применения стандарта")

#: Таблицы ИЭУ: поле ``structure.json`` → названия в стандарте.
IED_FIELDS = (
    ("входные GOOSE", ("Входные GOOSE сообщения",
                       "Информационные сигналы в составе входящих сообщений")),
    ("выходные GOOSE", ("Выходные GOOSE сообщения",
                        "Информационные сигналы в составе исходящих сообщений")),
    ("входные SV", ("Входные SV потоки",)),
    ("функциональные клавиши",
     ("Функциональные клавиши ИЭУ со светодиодной индикацией",
      "Функциональные клавиши")),
    ("светодиодная сигнализация", ("Светодиодная сигнализация ИЭУ",
                                    "Светодиодная сигнализация")),
    ("команды управления от АСУ ТП",
     ("Команды управления от АСУ ТП", "Команды управления от АСУ ТП для ИЭУ")),
    ("аналоговые значения", ("Аналоговые значения, формируемые ИЭУ",)),
    ("отчеты в АСУ ТП", ("Отчеты в АСУ ТП",)),
    ("входные дискретные сигналы",
     ("Входные дискретные сигналы", "Входные дискретные сигналы ИЭУ")),
    ("выходные дискретные воздействия", ("Выходные дискретные воздействия",)),
    ("дискретные сигналы, формируемые ИЭУ",
     ("Дискретные сигналы, формируемые ИЭУ",)),
    ("дискретные сигналы внешних устройств",
     ("Дискретные сигналы, формируемые внешними устройствами",
      "Дискретные сигналы, формируемые внешними устройствами для ИЭУ")),
)

#: Таблицы комплекта (не ИЭУ).
KIT_TABLE_FIELDS = (
    ("входные аналоговые измерения", ("Входные аналоговые измерения",)),
    ("внутренние дискретные цепи", ("Внутренние дискретные цепи",)),
)

#: Таблицы шкафа.
CABINET_TABLE_FIELDS = (
    ("ряды зажимов", ("Ряды зажимов",)),
    ("основные компоненты", ("Основные компоненты шкафа",
                             "Основные компоненты")),
    ("параметры функций ИЭУ", ("Основные параметры функций ИЭУ",
                                "Основные параметры функций РЗА")),
)

#: Текстовые поля шкафа: поле v3 → названия в стандарте, «дробить на список».
CABINET_FIELDS = (
    ("наименование", ("Наименование шкафа",), False),
    ("защищаемый элемент", ("Защищаемый элемент",), False),
    ("управляемый элемент", ("Управляемый элемент",), True),
    ("архитектура ПС", ("Архитектура построения ПС",), False),
    ("функции МП ИЭУ", ("Основные функции МП ИЭУ",
                        "Основные функции МП ИЭУ1 (ИЭУ2)"), False),
    ("применимость", ("Область применения в рамках типовых схем РУ",), False),
    ("функции ИТС", ("Функции ИТС в составе шкафа",), True),
    ("вводы питания", ("Вводы питания оперативного постоянного тока",), True),
    ("порты", ("Цифровые порты ИЭУ",), True),
    ("описание функций ИТС", ("Функции ИТС в составе шкафа",), False),
)

#: Поля блока «Комплект N» → поля записи комплекта.
KIT_FIELDS = (
    ("функции РЗА", ("Основные функции МП ИЭУ",
                     "Основные функции МП ИЭУ1 (ИЭУ2)"), True),
    ("функции ИТС", ("Функции ИТС в составе шкафа",), True),
)

#: Поля-ссылки на рисунки: в структуру не переносятся (файлов нет).
FIGURE_FIELDS = (
    ("поясняющая схема подключения",
     ("Поясняющая схема подключения", "Поясняющие схемы подключения")),
    ("эскиз общего вида", ("Эскиз общего вида",)),
    ("структурно-функциональная схема",
     ("Структурно-функциональная схема",)),
    ("схема электрическая принципиальная",
     ("Схема электрическая принципиальная",)),
)

#: Служебные колонки таблиц: в структуру не пишутся.
TABLE_SERVICE_COLUMNS = ("№", "N", "п/п")

#: Значение — ссылка на таблицу, рисунок или приложение стандарта.
_REFERENCE_RE = re.compile(r"^\s*(таблиц|рисун|приложени)", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(r"\s*\[\d+\]")
#: Транслитерация для ключей каталога (ШЭТ → shet).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}

_standards = None
_error = None


# ---------------------------------------------------------------------------
# Нормализация значений
# ---------------------------------------------------------------------------
def norm_key(text):
    """Ключ сравнения названий: без сносок ``[15]``, пробелов и регистра."""
    value = _FOOTNOTE_RE.sub("", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value.strip(" .:")


def norm_code(code):
    """Шифр шкафа для сравнения: ``ШЭТ 430.01-0`` (тире и регистр — к одному)."""
    value = re.sub(r"\s+", " ", str(code or "")).strip().upper()
    return value.replace("–", "-").replace("—", "-")


def key_of_code(code):
    """Ключ каталога из шифра: ``ШЭТ 430.01-0`` → ``shet-430-01-0``."""
    value = norm_code(code).replace(" ", "-").replace(".", "-")
    value = re.sub(r"-+", "-", value).strip("-").lower()
    return "".join(_TRANSLIT.get(char, char) for char in value)


def is_reference(value):
    """Значение — ссылка на таблицу, рисунок или приложение стандарта."""
    return isinstance(value, str) and bool(_REFERENCE_RE.match(value))


def split_list(value):
    """«- питание цепей; - освещение» → два элемента.

    Готовый список не дробится: «СЗ (ДЗ, ТЗНП, МТЗ)» — одна функция.
    Строка делится по ``;`` и переводу строки, а по запятой — только если
    точек с запятой нет.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value)
    parts = re.split(r"[;\n]+", text) if (";" in text or "\n" in text) \
        else re.split(r",", text)
    result = []
    for part in parts:
        item = part.strip().lstrip("-–—•*").strip()
        if item:
            result.append(item)
    return result


def _split_commas(text):
    """Делит перечень по запятым вне скобок: «СЗ (ДЗ, ТЗНП), МТЗ» → 2."""
    parts, current, depth = [], [], 0
    for char in str(text or ""):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def split_items(value):
    """Перечень функций: строка или список строк (каждая — через запятую)."""
    if isinstance(value, str):
        return split_list(value)
    result = []
    for item in value or ():
        if isinstance(item, str):
            result.extend(_split_commas(item))
        elif isinstance(item, (list, tuple)):
            result.extend(split_items(item))
    return _unique([item for item in result if item])


def format_functions(value):
    """Функции МП ИЭУ: список по ИЭУ → «…; …» (без префикса ИЭУ)."""
    if isinstance(value, (list, tuple)):
        items = [" ".join(str(item).split()) for item in value
                 if str(item).strip()]
        if not items:
            return ""
        return "; ".join(items)
    return clean_text(value)


def table_rows(table, drop_ordinal=True):
    """Строки таблицы стандарта без служебной колонки «№»."""
    rows = (table or {}).get("Строки") or []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned = {}
        for column, value in row.items():
            if drop_ordinal and column in TABLE_SERVICE_COLUMNS:
                continue
            text = "" if value is None else str(value).strip()
            if text:
                cleaned[column] = text
        if cleaned:
            result.append(cleaned)
    return result


def files():
    """Файлы стандартов в папке."""
    return sorted(glob.glob(os.path.join(STANDARDS_DIR, "*.json")))


def load(force=False):
    """Читает все файлы папки (с кешем). Возвращает список стандартов."""
    global _standards, _error
    if _standards is not None and not force:
        return _standards
    result = []
    _error = None
    paths = files()
    if not paths:
        _error = "папка standards_base пуста — положите в неё JSON стандартов"
        _standards = []
        return _standards
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:                      # noqa: BLE001
            _error = "%s: %s" % (os.path.basename(path), exc)
            continue
        section = data.get(SECTION)
        if not isinstance(section, dict):
            _error = "%s: нет раздела «%s»" % (os.path.basename(path), SECTION)
            continue
        result.append({
            "файл": os.path.basename(path),
            "путь": path,
            "шапка": {name: str(data.get(name) or "").strip()
                      for name in HEADER_FIELDS},
            "шифр": str(data.get("Шифр стандарта") or "").strip(),
            "обозначение": str(data.get("Обозначение стандарта") or "").strip(),
            "дата": str(data.get("Дата введения") or "").strip(),
            "содержимое": section,
        })
    _standards = result
    return _standards


def reload():
    return load(force=True)


def error():
    """Текст последней ошибки чтения (None, если всё прочитано)."""
    load()
    return _error


def _cards(standard):
    """Карточки шкафов в разделе стандарта (в порядке документа)."""
    cards = []
    for name, block in (standard.get("содержимое") or {}).items():
        if not isinstance(block, dict) or CODE_FIELD not in block:
            continue
        cards.append({
            "стандарт": standard["шифр"],
            "обозначение": standard["обозначение"],
            "файл": standard["файл"],
            "раздел": str(block.get(SOURCE_FIELD) or "").strip(),
            "шифр": norm_code(block.get(CODE_FIELD)),
            "заголовок": name,
            "карточка": block,
            "описание": block.get(DESCRIPTION_FIELD) or {},
            "назначение": " ".join(str(block.get("Назначение шкафа") or "").split()),
            "таблицы": block.get(TABLES_FIELD) or {},
        })
    return cards


def standards():
    """Шапки стандартов: шифр, дата, число шкафов и таблиц."""
    result = []
    for standard in load():
        cards = _cards(standard)
        result.append({
            "шифр": standard["шифр"],
            "обозначение": standard["обозначение"],
            "дата": standard["дата"],
            "шкафов": len(cards),
            "таблиц": sum(len(card["таблицы"]) for card in cards),
            "файл": standard["файл"],
        })
    return result


def cabinets():
    """Все карточки шкафов всех стандартов."""
    result = []
    for standard in load():
        result.extend(_cards(standard))
    return result


def cabinet(code):
    """Карточка шкафа по шифру (None, если такого нет)."""
    wanted = norm_code(code)
    for card in cabinets():
        if card["шифр"] == wanted:
            return card
    return None


def tables(card):
    """Таблицы карточки: имя → таблица."""
    return (card or {}).get("таблицы") or {}


def ref_key(name):
    """Имя таблицы для сравнения (регистр и пробелы не важны)."""
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def table(card, reference):
    """Таблица по ссылке вида «Таблица 5.2.4» (None, если её нет)."""
    if not isinstance(reference, str) or not is_reference(reference):
        return None
    wanted = ref_key(reference)
    for name, value in tables(card).items():
        if ref_key(name) == wanted:
            return value
    return None


# ---------------------------------------------------------------------------
# Поля карточки и комплектов
# ---------------------------------------------------------------------------
def _value(description, names):
    """Значение поля по названию: точное совпадение, затем — по началу строки.

    Действующие стандарты называют поля «Функциональные клавиши ИЭУ со
    светодиодной индикацией», проект редакции 2 — коротко «Функциональные
    клавиши»; «Область применения в рамках типовых схем РУ [16]» в проекте —
    «…РУ 35 кВ (ГОСТ Р 59279 и [14])». Поэтому после точного совпадения
    ищем поле, чьё название начинается на искомое (граница слова обязательна).
    """
    keys = list((description or {}).items())
    for key, value in keys:
        if norm_key(key) in {norm_key(name) for name in names}:
            return value
    for name in names:                       # порядок перечисления важнее множества
        want = norm_key(name)
        if not want:
            continue
        for key, value in keys:
            found = norm_key(key)
            if found.startswith(want) \
                    and (len(found) == len(want) or found[len(want)] in " ("):
                return value
    return None


def clean_text(value):
    """Текст поля: один пробел вместо переводов строк, без маркеров «- »."""
    if value in (None, "", [], {}):
        return ""
    text = " ".join(str(value).split())
    text = re.sub(r"(^|[;:,])\s*[-–—•*]\s+", r"\1 ", text)
    return " ".join(text.split()).strip()


def _text(description, names):
    """Текст поля (пробелы и переводы строк — к одному пробелу)."""
    value = _value(description, names)
    if isinstance(value, (list, tuple)):
        return "; ".join(clean_text(item) for item in value
                         if clean_text(item))
    return clean_text(value)


def _list(description, names):
    """Поле-список (функции через запятую и т. п.)."""
    value = _value(description, names)
    return split_list(value) if value not in (None, "", [], {}) else []


def _table_of(card, names, block=None):
    """Таблица по ссылке из блока комплекта или из описания шкафа."""
    sources = []
    if block:
        sources.append(block.get("Таблицы комплекта") or {})
        sources.append(block)
    sources.append((card or {}).get("описание") or {})
    wanted = {norm_key(name) for name in names}
    for source in sources:
        for key, value in source.items():
            if norm_key(key) in wanted and is_reference(value):
                found = table(card, value)
                if found is not None:
                    return found
    return None


def kit_blocks(card):
    """Блоки «Комплект», «Комплект 1», … в порядке номера."""
    blocks = []
    for key, value in ((card or {}).get("описание") or {}).items():
        match = re.match(r"^Комплект(?:\s+(\d+))?$", str(key).strip())
        if match and isinstance(value, dict):
            blocks.append((int(match.group(1) or 1), value))
    blocks.sort(key=lambda pair: pair[0])
    return blocks


def _make_kit(card, number, block, multiple):
    """Комплект в едином виде: имя, ИЭУ, поля и таблицы."""
    name = "Комплект %d" % number
    if not multiple:
        title = _text(card.get("описание"), ("Наименование шкафа",))
        if title:
            name = title
    ied_name = _text(block, ("Имя ИЭУ",)) if block else ""
    kit = {
        "номер": number,
        "имя": name,
        "полное имя": "%s шкафа %s" % (name, card["шифр"]),
        "иэу": [{"обозначение": ied_name}] if ied_name else [],
        "поля": {},
        "таблицы": {},
        "таблицы иэу": {},
    }
    if kit["иэу"]:
        kit["полное имя"] += " (%s)" % ied_name
    for field, names in KIT_TABLE_FIELDS:
        found = _table_of(card, names, block)
        if found is not None:
            kit["таблицы"][field] = found
    for field, names, as_list in KIT_FIELDS:
        value = _value(block, names) if block else None
        if value in (None, '', [], {}):
            value = _value(card.get('описание'), names)
        if value in (None, "", [], {}):
            continue
        if as_list:
            kit["поля"][field] = split_items(value)
        else:
            kit["поля"][field] = clean_text(value)
    for field, names in IED_FIELDS:
        found = _table_of(card, names, block)
        if found is not None:
            kit["таблицы иэу"][field] = found
    return kit


def kits(card):
    """Комплекты карточки в едином виде (неявная и явная модели)."""
    blocks = kit_blocks(card)
    if not blocks:
        return [_make_kit(card, 1, None, False)]
    return [_make_kit(card, number, block, len(blocks) > 1)
            for number, block in blocks]


def fields(card):
    """Текстовые поля шкафа в виде {поле v3: значение}."""
    description = (card or {}).get("описание") or {}
    result = {}
    value = _value(description, ("Основные функции МП ИЭУ",
                                 "Основные функции МП ИЭУ1 (ИЭУ2)"))
    if value not in (None, "", [], {}):
        text = format_functions(value)
        if text:
            result["функции МП ИЭУ"] = text
    for field, names, as_list in CABINET_FIELDS:
        if field == "функции МП ИЭУ":
            continue
        if as_list:
            items = _list(description, names)
            if items:
                result[field] = items
        else:
            text = _text(description, names)
            if text:
                result[field] = text
    return result


def record(card, cabinet_id=None):
    """Карточка стандарта → запись ``structure.json`` v3.

    ``cabinet_id`` — ключ каталога редактора (``shet-430-01-0``): тогда
    ``id`` и ключи комплектов совпадают с каталогом, и запись стыкуется со
    схемами. Без ключа id строится из шифра.
    """
    import komplekts

    if card is None:
        return None
    key = cabinet_id or key_of_code(card["шифр"])
    result = {"id": key, "шифр": card["шифр"]}
    card_fields = fields(card)
    result.update(card_fields)
    if card.get("назначение"):
        result["назначение"] = card["назначение"]
    result["наименование"] = card_fields.get("наименование") \
        or card.get("заголовок") or ""

    kit_list = kits(card)
    kit_records = []
    aggregated_its = []
    aggregated_mp = []
    for kit in kit_list:
        kit_record = {
            "id": komplekts.typical_key(key, kit["номер"] - 1),
            "номер": kit["номер"],
            "полное имя": kit["полное имя"],
            "есть ИЭУ": bool(kit["иэу"]),
        }
        for name, value in kit["поля"].items():
            if name == "функции ИТС":
                aggregated_its.extend(value)
                continue
            kit_record[name] = value
        if kit["поля"].get("функции РЗА") and len(kit_list) > 1:
            aggregated_mp.append(", ".join(kit["поля"]["функции РЗА"]))
        for field, rows in kit["таблицы"].items():
            rows_list = table_rows(rows)
            if rows_list:
                kit_record[field] = rows_list
        if kit["иэу"]:
            ied_records = []
            for ied in kit["иэу"]:
                ied_record = {"обозначение": ied["обозначение"]}
                for field, rows in kit["таблицы иэу"].items():
                    rows_list = table_rows(rows)
                    if rows_list:
                        ied_record[field] = rows_list
                ied_records.append(ied_record)
            kit_record["иэу"] = ied_records
        kit_records.append(kit_record)

    # Общешкафные функции: из карточки, а если их там нет — из комплектов.
    if not result.get("функции МП ИЭУ") and aggregated_mp:
        result["функции МП ИЭУ"] = "; ".join(aggregated_mp)
    if not result.get("функции ИТС") and aggregated_its:
        result["функции ИТС"] = _unique(aggregated_its)

    for field, names in CABINET_TABLE_FIELDS:
        rows = _table_of(card, names)
        if rows is not None:
            rows_list = table_rows(rows)
            if rows_list:
                result[field] = rows_list

    description = card.get("описание") or {}
    for field, names in FIGURE_FIELDS:
        text = _text(description, names)
        if text:
            result[field] = text

    result["комплекты"] = kit_records
    result["стандарт"] = card["стандарт"]
    if card.get("раздел"):
        result["источник"] = card["раздел"]
    return {name: value for name, value in result.items()
            if value not in (None, "", [], {})}


#: Поле записи → названия в «Описании шкафа» (для записи обратно в стандарт).
FIELD_NAMES = {field: names for field, names, _as_list in CABINET_FIELDS}
FIELD_NAMES.update(dict(FIGURE_FIELDS))


def _description_key(description, names):
    """Ключ «Описания шкафа» для поля: точное совпадение, затем по началу."""
    keys = list((description or {}).keys())
    for name in names:
        want = norm_key(name)
        for key in keys:
            if norm_key(key) == want:
                return key
    for name in names:
        want = norm_key(name)
        if not want:
            continue
        for key in keys:
            found = norm_key(key)
            if found.startswith(want) \
                    and (len(found) == len(want) or found[len(want)] in " ("):
                return key
    return None


def _format_field_value(existing, value):
    """Значение в том же виде, в каком поле хранится в стандарте."""
    if isinstance(existing, list):
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return split_list(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item).strip() for item in value
                         if str(item).strip())
    return clean_text(value)


def update_card(code, updates):
    """Записывает поля карточки стандарта обратно в её JSON-файл.

    ``updates`` — {поле записи: значение}. «назначение» пишется в блок
    «Назначение шкафа», остальные — в «Описание шкафа» (ключ ищется с
    учётом сносок «[16]»). Файл пишется целиком (отступ 2, как в папке) и
    перечитывается. Возвращает ``файл``, ``поля`` (сколько записано),
    ``пропущено`` (нет такого поля) и ``ошибка``.
    """
    result = {"файл": None, "поля": 0, "пропущено": [], "ошибка": None}
    card = cabinet(code)
    if card is None:
        result["ошибка"] = "карточка %s не найдена" % code
        return result
    standard = None
    for entry in load():
        if norm_code(entry["шифр"]) == norm_code(card["стандарт"]):
            standard = entry
            break
    if standard is None:
        result["ошибка"] = "стандарт %s не найден" % card["стандарт"]
        return result
    path = standard["путь"]
    result["файл"] = standard["файл"]
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:                      # noqa: BLE001
        result["ошибка"] = "%s: %s" % (standard["файл"], exc)
        return result
    block = None
    for item in (data.get(SECTION) or {}).values():
        if isinstance(item, dict) \
                and norm_code(item.get(CODE_FIELD)) == card["шифр"]:
            block = item
            break
    if block is None:
        result["ошибка"] = "в файле нет карточки %s" % card["шифр"]
        return result
    description = block.get(DESCRIPTION_FIELD)
    if not isinstance(description, dict):
        description = block[DESCRIPTION_FIELD] = {}
    for field, value in (updates or {}).items():
        if field == "назначение":
            block["Назначение шкафа"] = clean_text(value)
            result["поля"] += 1
            continue
        key = _description_key(description, FIELD_NAMES.get(field) or ())
        if key is None:
            result["пропущено"].append(field)
            continue
        description[key] = _format_field_value(description[key], value)
        result["поля"] += 1
    if result["поля"]:
        temporary = path + ".tmp"
        try:
            mode = os.stat(path).st_mode
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        except Exception as exc:                  # noqa: BLE001
            result["ошибка"] = "%s: %s" % (standard["файл"], exc)
            return result
        reload()
    return result


def _unique(items):
    """Список без повторов, порядок сохраняется."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def structure(cabinet_key=None):
    """Все карточки записями v3 (``cabinet_key`` — функция карточка → ключ)."""
    result = []
    for card in cabinets():
        key = cabinet_key(card) if callable(cabinet_key) else cabinet_key
        result.append(record(card, key))
    return result


def summary():
    """Сводка по папке: стандартов, шкафов, комплектов, ИЭУ, таблиц."""
    cards = cabinets()
    kits_list = [kit for card in cards for kit in kits(card)]
    return {
        "стандартов": len(standards()),
        "шкафов": len(cards),
        "комплектов": len(kits_list),
        "иэу": sum(len(kit["иэу"]) for kit in kits_list),
        "таблиц": sum(len(tables(card)) for card in cards),
        "файлов": [standard["файл"] for standard in standards()],
    }


def coverage(catalog_codes=()):
    """Сверка шифров стандартов с каталогом редактора."""
    codes = {norm_code(code) for code in catalog_codes}
    found, missing = [], []
    for card in cabinets():
        (found if card["шифр"] in codes else missing).append(card["шифр"])
    return {"в каталоге": len(found), "нет в каталоге": missing,
            "шифры": found}


def main(argv=None):
    """Сводка по папке или запись v3 одного шкафа."""
    argv = list(sys.argv[1:] if argv is None else argv)
    stats = summary()
    if not stats["шкафов"]:
        print("standards_base: %s" % (error() or "нет стандартов"))
        return 1
    if argv:
        card = cabinet(argv[0])
        if card is None:
            print("шкаф «%s» не найден в standards_base" % argv[0])
            return 1
        print(json.dumps(record(card), ensure_ascii=False, indent=1))
        return 0
    print("standards_base: %d стандартов, %d шкафов, %d комплектов, "
          "%d ИЭУ, %d таблиц"
          % (stats["стандартов"], stats["шкафов"], stats["комплектов"],
             stats["иэу"], stats["таблиц"]))
    for standard in standards():
        print("  %s · %s · %d шкафов, %d таблиц"
              % (standard["шифр"], standard["дата"], standard["шкафов"],
                 standard["таблиц"]))
    if error():
        print("ошибка: %s" % error(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
