# -*- coding: utf-8 -*-
"""Создание нового стандарта на основе выбранного (клонирование с правкой).

Модуль берёт существующий JSON стандарта, копирует его и превращает в
НОВЫЙ базовый стандарт: меняются реквизиты (шифр, обозначение, дата,
принадлежность, область применения), при необходимости — набор шкафов и
текстовые замены (коды ШЭТ, номера разделов, архитектура).

Исходный файл не изменяется. Результат — самостоятельный JSON, который
можно открыть в редакторе изменений как новую базу.

Правила:
- замены применяются и к именам полей, и к строковым значениям; все пары
  срабатывают одновременно, поэтому «I тип => II тип» не превращается
  заодно в «III тип»;
- «Общий перечень шкафов стандарта» пересобирается под оставленные шкафы;
- при перенумерации разделы шкафов идут подряд 5.2, 5.3, … и вместе с
  ними переименовываются таблицы «Таблица 5.x.y» и ссылки «Рисунок 5.x.y»;
- после сборки выполняется проверка целостности: реквизиты, уникальность
  шифров, нумерация разделов, счётчики строк таблиц, ссылки на таблицы,
  соответствие общего перечня шкафам.

Командная строка:
    python make_standard.py --base "СТО ...279-2019.json" --out "new.json" \\
        --code "СТО 56947007-33.040.20.282-2019" \\
        --title "Типовые шкафы ... Архитектура IV типа" \\
        --date 26.12.2019 --owner "ПАО «ФСК ЕЭС»" \\
        --replace "431.02-0 => 431.02-3" --replace "279-2019 => 282-2019" \\
        --keep "ШЭТ 430.01-0" --keep "ШЭТ 431.02-0"
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from collections import OrderedDict

import apply_changes as ac

CONTENT_KEY = "Содержимое стандарта"
LIST_KEY = "Общий перечень шкафов стандарта"

META_FIELDS = (
    "Обозначение стандарта",
    "Шифр стандарта",
    "Дата введения",
    "Принадлежность стандарта",
    "Область применения стандарта",
)

CABINET_FIELDS = (
    "Раздел стандарта",
    "Шифр шкафа",
    "Назначение шкафа",
    "Описание шкафа",
    "Таблицы",
)

SECTION_RE = re.compile(r"^5\.(\d+)$")
TABLE_REF_RE = re.compile(r"(Таблица|Рисунок)(\s+)5\.(\d+)\.(\d+)")
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
CODE_RE = re.compile(r"^СТО\s+\S+-\d{4}$")


class StandardError(Exception):
    """Ошибка создания стандарта (несовместимая структура, плохие замены)."""


# ---------------------------------------------------------------------------
# Чтение структуры
# ---------------------------------------------------------------------------
def norm_cipher(value):
    """«ШЭТ 431.02-0» -> «431.02-0» (для сравнения шифров)."""
    text = "" if value is None else str(value).strip()
    return re.sub(r"^ШЭТ\s+", "", text, flags=re.IGNORECASE).strip()


def is_cabinet(value):
    return isinstance(value, dict) and "Шифр шкафа" in value \
        and "Раздел стандарта" in value


def cabinets(data):
    """[(имя шкафа в объекте, сам объект)] в порядке файла."""
    content = data.get(CONTENT_KEY) if isinstance(data, dict) else None
    if not isinstance(content, dict):
        raise StandardError(
            "в файле нет объекта «%s» — это не стандарт" % CONTENT_KEY)
    out = []
    for name, value in content.items():
        if is_cabinet(value):
            out.append((name, value))
    return out


def cabinet_list(data):
    """Краткая информация о шкафах для диалогов: имя, шифр, раздел."""
    return [{"name": name, "cipher": cab.get("Шифр шкафа", ""),
             "section": cab.get("Раздел стандарта", ""),
             "tables": len(cab.get("Таблицы") or {})}
            for name, cab in cabinets(data)]


def table_keys(data):
    """Все имена таблиц стандарта (шкафы, разделы 4/5.1, приложения)."""
    keys = set()
    content = data.get(CONTENT_KEY) or {}
    for name, value in content.items():
        if is_cabinet(value):
            keys.update((value.get("Таблицы") or {}).keys())
        elif isinstance(value, dict):
            keys.update(value.keys())
    return keys


def all_tables(data):
    """[(путь, объект таблицы)] по всему стандарту."""
    out = []
    content = data.get(CONTENT_KEY) or {}
    for name, value in content.items():
        if is_cabinet(value):
            for tname, table in (value.get("Таблицы") or {}).items():
                out.append(("%s / %s" % (name, tname), table))
        elif isinstance(value, dict) and name != LIST_KEY:
            for tname, table in value.items():
                out.append(("%s / %s" % (name, tname), table))
    return out


# ---------------------------------------------------------------------------
# Правки
# ---------------------------------------------------------------------------
def apply_meta(data, meta):
    """Заменить реквизиты стандарта. Возвращает список изменённых полей."""
    if not meta:
        return []
    unknown = [key for key in meta if key not in META_FIELDS]
    if unknown:
        raise StandardError(
            "неизвестные реквизиты: %s. Допустимы: %s"
            % (", ".join(map(str, unknown)), ", ".join(META_FIELDS)))
    changed = []
    for key in META_FIELDS:
        if key not in meta:
            continue
        value = meta[key]
        if not isinstance(value, str):
            raise StandardError("реквизит «%s» должен быть строкой" % key)
        value = value.strip()
        if not value:
            raise StandardError("реквизит «%s» не может быть пустым" % key)
        if data.get(key) != value:
            data[key] = value
            changed.append(key)
    code = data.get("Шифр стандарта")
    if not isinstance(code, str) or not code.strip():
        raise StandardError("не задан «Шифр стандарта»")
    return changed


def code_replacements(old_code, new_code):
    """Подсказка замен при смене шифра: полный шифр и его номерная часть."""
    old = str(old_code or "").strip()
    new = str(new_code or "").strip()
    if not old or not new or old == new:
        return []
    out = [{"Старое": old, "Новое": new}]
    m_old = re.search(r"(\d+(?:\.\d+)+)-\d{4}$", old)
    m_new = re.search(r"(\d+(?:\.\d+)+)-\d{4}$", new)
    if m_old and m_new and m_old.group(1) != m_new.group(1):
        out.append({"Старое": m_old.group(1), "Новое": m_new.group(1)})
    return out


def normalize_replacements(raw):
    """Приводит замены к [{"Старое", "Новое"}] (строки «a => b» тоже годятся)."""
    out = []
    for i, item in enumerate(raw or [], 1):
        if isinstance(item, str):
            old, sep, new = item.partition("=>")
            if not sep:
                raise StandardError(
                    "замена %d: ожидается «старое => новое»" % i)
        elif isinstance(item, dict):
            old = item.get("Старое", item.get("Было", ""))
            new = item.get("Новое", item.get("Стало", ""))
        else:
            raise StandardError("замена %d: ожидается строка или объект" % i)
        old, new = str(old or "").strip(), str(new or "").strip()
        if not old:
            raise StandardError("замена %d: пустое «Старое»" % i)
        if old == new:
            raise StandardError(
                "замена %d: «Старое» и «Новое» совпадают (%r)" % (i, old))
        out.append({"Старое": old, "Новое": new})
    return out


def apply_replacements(data, replacements):
    """Заменить подстроки в ключах и значениях одним проходом.

    Все пары срабатывают одновременно по исходному тексту, поэтому
    «I тип => II тип» и «II тип => III тип» не наслаиваются друг на друга.
    """
    if not replacements:
        return {"keys": 0, "values": 0, "items": 0}
    mapping = {}
    for rep in replacements:
        old = rep["Старое"]
        if old in mapping:
            raise StandardError("замена %r задана дважды" % old)
        mapping[old] = rep["Новое"]
    pattern = re.compile("|".join(
        re.escape(old) for old in sorted(mapping, key=len, reverse=True)))

    def sub(text):
        return pattern.sub(lambda m: mapping[m.group(0)], text)

    stats = {"keys": 0, "values": 0, "items": len(mapping)}

    def walk(value, path=""):
        if isinstance(value, dict):
            out = OrderedDict()
            for key, item in value.items():
                new_key = sub(key) if isinstance(key, str) else key
                if isinstance(key, str) and new_key != key:
                    stats["keys"] += 1
                    if not new_key:
                        raise StandardError(
                            "замена: поле %r стало пустым (%s)"
                            % (key, path or "/"))
                if new_key in out:
                    raise StandardError(
                        "замена: в объекте %s два поля стали %r"
                        % (path or "/", new_key))
                out[new_key] = walk(item, path + "/" + str(new_key))
            value.clear()
            value.update(out)
            return value
        if isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = walk(item, path + "/#%d" % i)
            return value
        if isinstance(value, str):
            new = sub(value)
            if new != value:
                stats["values"] += 1
            return new
        return value

    walk(data)
    return stats


def keep_only(data, keep):
    """Оставить только перечисленные шкафы; пересобрать общий перечень."""
    cabs = cabinets(data)
    if not cabs:
        raise StandardError("в стандарте нет шкафов — нечего выбирать")

    def aliases(name, cab):
        cipher = norm_cipher(cab.get("Шифр шкафа"))
        return {name.casefold(), cipher.casefold(), ("ШЭТ " + cipher).casefold()}

    wanted = []
    for item in keep or []:
        text = str(item or "").strip()
        if text and text not in wanted:
            wanted.append(text)
    if not wanted:
        raise StandardError("не выбран ни один шкаф")

    chosen = []
    for name, cab in cabs:
        names = aliases(name, cab)
        if any(item.casefold() in names for item in wanted):
            chosen.append(name)

    known = set()
    for name, cab in cabs:
        known |= aliases(name, cab)
    unknown = [item for item in wanted if item.casefold() not in known]
    if unknown:
        raise StandardError(
            "не найдены шкафы: %s. Доступны: %s"
            % (", ".join(unknown),
               ", ".join(cab.get("Шифр шкафа", "?") for _, cab in cabs)))
    if not chosen:
        raise StandardError("ни один шкаф не выбран")

    content = data[CONTENT_KEY]
    for name, _ in cabs:
        if name not in chosen:
            del content[name]

    kept_codes = {norm_cipher(cab.get("Шифр шкафа"))
                  for name, cab in cabs if name in chosen}
    rows = content.get(LIST_KEY)
    if isinstance(rows, list):
        left = [row for row in rows
                if isinstance(row, dict)
                and norm_cipher(row.get("Код ШЭТ")) in kept_codes]
        content[LIST_KEY] = left
    return chosen


def renumber_sections(data):
    """Разделы шкафов -> 5.2…5.N, таблицы и ссылки переименовать.

    Возвращает отображение старый номер раздела -> новый (цифры после «5.»).
    """
    cabs = cabinets(data)
    mapping = OrderedDict()
    for i, (_, cab) in enumerate(cabs):
        old = str(cab.get("Раздел стандарта") or "").strip()
        new = "5.%d" % (i + 2)
        match = SECTION_RE.match(old)
        if match and match.group(1) != str(i + 2):
            mapping[match.group(1)] = str(i + 2)
        cab["Раздел стандарта"] = new
    if not mapping:
        return {}

    def fix(text):
        return TABLE_REF_RE.sub(
            lambda m: "%s%s5.%s.%s" % (
                m.group(1), m.group(2),
                mapping.get(m.group(3), m.group(3)), m.group(4)), text)

    _rewrite(data, fix)
    return dict(mapping)


def _rewrite(value, fix, path=""):
    if isinstance(value, dict):
        out = OrderedDict()
        for key, item in value.items():
            new_key = fix(key) if isinstance(key, str) else key
            if new_key in out:
                raise StandardError(
                    "после перенумерации в объекте %s два поля стали %r"
                    % (path or "/", new_key))
            out[new_key] = _rewrite(item, fix, path + "/" + str(new_key))
        value.clear()
        value.update(out)
        return value
    if isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = _rewrite(item, fix, path + "/#%d" % i)
        return value
    if isinstance(value, str):
        return fix(value)
    return value


# ---------------------------------------------------------------------------
# Проверка целостности
# ---------------------------------------------------------------------------
def _check_table(name, table, problems, warnings):
    if not isinstance(table, dict):
        problems.append("таблица %r: ожидается объект" % name)
        return
    rows = table.get("Строки")
    if not isinstance(rows, list):
        problems.append("таблица %r: нет массива «Строки»" % name)
        return
    count = table.get("Количество строк")
    if not isinstance(count, int):
        warnings.append("таблица %r: «Количество строк» не число" % name)
    elif count != len(rows):
        problems.append("таблица %r: «Количество строк» %d, а строк %d"
                        % (name, count, len(rows)))
    columns = table.get("Столбцы")
    if not isinstance(columns, list) or not columns:
        warnings.append("таблица %r: пустой список «Столбцы»" % name)
    if not str(table.get("Наименование") or "").strip():
        warnings.append("таблица %r: пустое «Наименование»" % name)
    bad = [i for i, row in enumerate(rows, 1) if not isinstance(row, dict)]
    if bad:
        problems.append("таблица %r: строки %s — не объекты"
                        % (name, ", ".join(map(str, bad[:5]))))


def validate_standard(data, must_not_contain=()):
    """Проверить собранный стандарт. Возвращает (проблемы, предупреждения)."""
    problems, warnings = [], []
    if not isinstance(data, dict):
        return ["корень JSON должен быть объектом"], []

    for field in META_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append("не заполнен реквизит «%s»" % field)

    date = data.get("Дата введения")
    if isinstance(date, str) and date.strip() and not DATE_RE.match(date.strip()):
        warnings.append("«Дата введения» %r не в формате ДД.ММ.ГГГГ" % date)

    try:
        cabs = cabinets(data)
    except StandardError as exc:
        return [str(exc)], warnings
    if not cabs:
        return ["в стандарте нет ни одного шкафа"], warnings

    ciphers = {}
    for name, cab in cabs:
        for field in CABINET_FIELDS:
            if field not in cab:
                problems.append("шкаф %r: нет поля «%s»" % (name, field))
        cipher = cab.get("Шифр шкафа")
        if not isinstance(cipher, str) or not cipher.strip():
            problems.append("шкаф %r: пустой «Шифр шкафа»" % name)
        else:
            key = norm_cipher(cipher)
            if key in ciphers:
                problems.append(
                    "шифр %s повторяется у шкафов %r и %r"
                    % (cipher, ciphers[key], name))
            else:
                ciphers[key] = name
        section = cab.get("Раздел стандарта")
        if not isinstance(section, str) or not SECTION_RE.match(section):
            problems.append("шкаф %r: «Раздел стандарта» %r не вида 5.N"
                            % (name, section))
        tables = cab.get("Таблицы")
        if not isinstance(tables, dict) or not tables:
            problems.append("шкаф %r: нет таблиц" % name)
        else:
            for tname, table in tables.items():
                _check_table("%s / %s" % (cipher or name, tname), table,
                             problems, warnings)

    sections = [str(cab.get("Раздел стандарта") or "").strip()
                for _, cab in cabs]
    expected = ["5.%d" % (i + 2) for i in range(len(cabs))]
    if len(set(sections)) != len(sections):
        problems.append("разделы шкафов повторяются: %s"
                        % ", ".join(sections))
    elif sections != expected:
        warnings.append("разделы шкафов идут не подряд: %s (ожидалось %s); "
                        "включите перенумерацию, если это не задумано"
                        % (", ".join(sections), ", ".join(expected)))

    content = data[CONTENT_KEY]
    for name, value in content.items():
        if is_cabinet(value) or name == LIST_KEY:
            continue
        if not isinstance(value, dict):
            problems.append("раздел %r: ожидается объект с таблицами" % name)
            continue
        for tname, table in value.items():
            _check_table("%s / %s" % (name, tname), table, problems, warnings)

    rows = content.get(LIST_KEY)
    if not isinstance(rows, list):
        problems.append("нет массива «%s»" % LIST_KEY)
    else:
        codes = [norm_cipher(row.get("Код ШЭТ")) for row in rows
                 if isinstance(row, dict)]
        bad = [i for i, row in enumerate(rows, 1)
               if not isinstance(row, dict) or not norm_cipher(
                   row.get("Код ШЭТ"))]
        if bad:
            problems.append("«%s»: строки %s без «Код ШЭТ»"
                            % (LIST_KEY, ", ".join(map(str, bad[:5]))))
        missing = sorted(set(ciphers) - set(codes))
        extra = sorted(set(codes) - set(ciphers))
        if missing:
            problems.append("в общем перечне нет шкафов: %s"
                            % ", ".join(missing))
        if extra:
            problems.append("в общем перечне лишние шкафы: %s"
                            % ", ".join(extra))
        if len(codes) != len(set(codes)):
            problems.append("в общем перечне повторяются коды ШЭТ")

    known = table_keys(data)
    text = json.dumps(data, ensure_ascii=False)
    refs = set(re.findall(r"Таблица 5\.\d+\.\d+", text))
    dangling = sorted(refs - known)
    if dangling:
        problems.append("ссылки на отсутствующие таблицы: %s"
                        % ", ".join(dangling[:10]))

    for needle in must_not_contain:
        needle = str(needle or "").strip()
        if needle and needle in text:
            problems.append("в новом стандарте осталось %r" % needle)

    return problems, warnings


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------
def stats_of(data):
    cabs = cabinets(data)
    tables = all_tables(data)
    return {
        "cabinets": len(cabs),
        "sections": len(cabs),
        "tables": len(tables),
        "rows": sum(len(t.get("Строки") or []) for _, t in tables
                    if isinstance(t, dict)),
    }


def build(source, meta=None, replacements=None, keep=None, renumber=True,
          must_not_contain=None, source_label=""):
    """Собрать новый стандарт из исходного.

    source           — уже загруженный объект стандарта (не изменяется);
    meta             — переопределяемые реквизиты (см. META_FIELDS);
    replacements     — [{"Старое","Новое"}] или ["a => b"];
    keep             — имена/шифры шкафов, которые остаются (None — все);
    renumber         — перенумеровать разделы 5.2…5.N;
    must_not_contain — подстроки, которых в результате быть не должно.

    Возвращает dict: data, problems, warnings, stats, notes, replacements.
    """
    if not isinstance(source, dict):
        raise StandardError("исходный стандарт должен быть объектом JSON")
    source_cabs = cabinets(source)  # проверка структуры
    data = copy.deepcopy(source)
    notes = []

    if keep:
        before = len(source_cabs)
        chosen = keep_only(data, keep)
        if len(chosen) < before:
            notes.append("оставлено шкафов: %d из %d" % (len(chosen), before))
    elif keep is not None:
        raise StandardError("список оставляемых шкафов пуст")

    reps = normalize_replacements(replacements)
    rep_stats = apply_replacements(data, reps) if reps else {
        "keys": 0, "values": 0, "items": 0}

    changed_meta = apply_meta(data, meta or {})
    if changed_meta:
        notes.append("изменены реквизиты: %s" % ", ".join(changed_meta))

    mapping = {}
    if renumber:
        mapping = renumber_sections(data)
        if mapping:
            notes.append("разделы перенумерованы: %s"
                         % ", ".join("5.%s→5.%s" % (old, new)
                                     for old, new in mapping.items()))

    problems, warnings = validate_standard(
        data, must_not_contain=must_not_contain or ())

    if keep:
        kept_codes = {norm_cipher(cab.get("Шифр шкафа"))
                      for _, cab in cabinets(data)}
        dropped = sorted({norm_cipher(cab.get("Шифр шкафа"))
                          for _, cab in source_cabs} - kept_codes)
        if dropped:
            text = json.dumps(data, ensure_ascii=False)
            still = [code for code in dropped if code and code in text]
            if still:
                warnings.append(
                    "в тексте остались упоминания снятых шкафов (%s) — "
                    "проверьте «Приложение А» и общие таблицы"
                    % ", ".join(still))

    old_code = source.get("Шифр стандарта")
    new_code = data.get("Шифр стандарта")
    if isinstance(old_code, str) and isinstance(new_code, str) \
            and old_code.strip() and old_code != new_code:
        if old_code in json.dumps(data, ensure_ascii=False):
            warnings.append("старый шифр %r ещё встречается в тексте — "
                            "добавьте замену" % old_code)

    return {
        "data": data,
        "problems": problems,
        "warnings": warnings,
        "notes": notes,
        "stats": stats_of(data),
        "source_stats": stats_of(source),
        "replacements": rep_stats,
        "renumbered": mapping,
        "source_label": source_label,
    }


def write_standard(data, path, overwrite=False):
    """Записать стандарт в JSON. Возвращает размер файла."""
    if os.path.exists(path) and not overwrite:
        raise StandardError("файл уже существует: %s" % path)
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        raise StandardError("нет папки: %s" % folder)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return os.path.getsize(path)


def report(result, path=None):
    """Текст отчёта о созданном стандарте."""
    data = result["data"]
    stats = result["stats"]
    was = result["source_stats"]
    lines = ["СОЗДАНИЕ СТАНДАРТА НА ОСНОВЕ ВЫБРАННОГО", "=" * 60]
    if result.get("source_label"):
        lines.append("Источник: %s" % result["source_label"])
    lines.append("Новый шифр: %s" % data.get("Шифр стандарта", ""))
    lines.append("Обозначение: %s" % data.get("Обозначение стандарта", ""))
    lines.append("Дата введения: %s" % data.get("Дата введения", ""))
    lines.append("Принадлежность: %s" % data.get("Принадлежность стандарта", ""))
    lines.append("")
    lines.append("Шкафов: %d (было %d), таблиц: %d (было %d), строк: %d (было %d)"
                 % (stats["cabinets"], was["cabinets"], stats["tables"],
                    was["tables"], stats["rows"], was["rows"]))
    if result["replacements"]["items"]:
        rep = result["replacements"]
        lines.append("Замен: %d (ключей %d, значений %d)"
                     % (rep["items"], rep["keys"], rep["values"]))
    for note in result.get("notes") or []:
        lines.append("• %s" % note)
    if path:
        lines.append("Файл: %s" % path)
    lines.append("")
    if result["problems"]:
        lines.append("ПРОВЕРКА: %d проблем(ы)" % len(result["problems"]))
        for item in result["problems"]:
            lines.append("  ! %s" % item)
    else:
        lines.append("ПРОВЕРКА: OK")
    if result["warnings"]:
        lines.append("Предупреждения (%d):" % len(result["warnings"]))
        for item in result["warnings"]:
            lines.append("  ~ %s" % item)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Создать новый стандарт на основе выбранного JSON")
    parser.add_argument("--base", required=True, help="исходный стандарт")
    parser.add_argument("--out", help="куда записать новый стандарт")
    parser.add_argument("--title", help="«Обозначение стандарта»")
    parser.add_argument("--code", help="«Шифр стандарта»")
    parser.add_argument("--date", help="«Дата введения» (ДД.ММ.ГГГГ)")
    parser.add_argument("--owner", help="«Принадлежность стандарта»")
    parser.add_argument("--scope", help="«Область применения стандарта»")
    parser.add_argument("--meta", action="append", default=[],
                        metavar="КЛЮЧ=ЗНАЧЕНИЕ", help="реквизит целиком")
    parser.add_argument("--replace", action="append", default=[],
                        metavar="СТАРОЕ=>НОВОЕ", help="замена в тексте и полях")
    parser.add_argument("--keep", action="append", default=[],
                        metavar="ШИФР", help="оставить только этот шкаф")
    parser.add_argument("--no-renumber", action="store_true",
                        help="не перенумеровывать разделы 5.2…5.N")
    parser.add_argument("--forbid", action="append", default=[],
                        metavar="ТЕКСТ", help="чего не должно остаться")
    parser.add_argument("--report", help="файл отчёта")
    parser.add_argument("--force", action="store_true",
                        help="записать даже при проблемах проверки")
    parser.add_argument("--dry-run", action="store_true",
                        help="только проверить, ничего не писать")
    args = parser.parse_args(argv)

    meta = {}
    for field, value in (("Обозначение стандарта", args.title),
                         ("Шифр стандарта", args.code),
                         ("Дата введения", args.date),
                         ("Принадлежность стандарта", args.owner),
                         ("Область применения стандарта", args.scope)):
        if value:
            meta[field] = value
    for item in args.meta:
        key, sep, value = item.partition("=")
        if not sep:
            parser.error("--meta: ожидается «Ключ=Значение», получено %r" % item)
        meta[key.strip()] = value.strip()

    try:
        source = ac.load_json(args.base)
        result = build(source, meta=meta, replacements=args.replace,
                       keep=args.keep or None,
                       renumber=not args.no_renumber,
                       must_not_contain=args.forbid,
                       source_label=os.path.basename(args.base))
    except (StandardError, OSError, ValueError) as exc:
        print("ОШИБКА: %s" % exc, file=sys.stderr)
        return 2

    text = report(result)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)

    if result["problems"] and not args.force:
        print("\nСтандарт не записан: сначала устраните проблемы.",
              file=sys.stderr)
        return 1
    if args.dry_run or not args.out:
        print("\nЗапись не выполнялась (dry-run/нет --out).")
        return 0 if not result["problems"] else 1
    try:
        size = write_standard(result["data"], args.out, overwrite=True)
    except (StandardError, OSError) as exc:
        print("ОШИБКА ЗАПИСИ: %s" % exc, file=sys.stderr)
        return 2
    print("\nЗаписано: %s (%d байт)" % (args.out, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
