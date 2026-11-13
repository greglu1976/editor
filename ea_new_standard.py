#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Новый стандарт на базе выбранного — в структуре EA.

Берёт JSON стандарта (см. :mod:`ea_standard`), копирует его и превращает в
самостоятельный новый стандарт: меняются реквизиты (шифр, наименование,
принадлежность, дата), при необходимости — набор шкафов и текстовые замены
(шифры ШЭТ, номера разделов, архитектура).

Правила:

* исходный файл не изменяется, результат — отдельный JSON;
* замены применяются одновременно ко всем строкам, поэтому
  «I тип => II тип» не превращается заодно в «III тип»;
* при отборе шкафов удаляются их подразделы, таблицы-формы, рисунки и строки
  общих таблиц, где упомянуты только снятые шкафы;
* перенумерация: подразделы шкафов идут подряд (5.3, 5.4, …), таблицы —
  сквозной нумерацией (5.2, 5.3, …), рисунки шкафов — своей; ссылки
  «Таблица 5.x» и «Рисунок 5.x» в тексте обновляются;
* после сборки — проверка целостности: реквизиты, уникальность шифров и
  номеров таблиц, ссылки таблиц на шкафы.

Командная строка:
    python ea_new_standard.py --base "EA/СТО ....json" --out "EA/new.json" \\
        --code "СТО (проект, ред. 3)" --name "Типовые шкафы ..." \\
        --keep "ШЭТ 431.11-1" --replace "431.11-1 => 431.11-3"
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys

import ea_standard as es

#: Реквизиты стандарта, которые можно заменить (ключ → подпись).
META_FIELDS = (
    ("code", "Шифр стандарта"),
    ("name", "Наименование"),
    ("property", "Принадлежность"),
    ("date", "Дата введения"),
)

#: Ссылка на таблицу или рисунок: «Таблица 5.12», «рисунке 5.3».
_REF_RE = re.compile(r"(таблиц\w*|рисун\w*)(\s+)5\.(\d+)", re.IGNORECASE)


class StandardError(Exception):
    """Ошибка сборки стандарта."""


# ---------------------------------------------------------------------------
# Чтение структуры
# ---------------------------------------------------------------------------
def cabinets(data):
    return data.get("cabinets") or []


def _containers(data):
    """Все объекты, в которых лежат таблицы: разделы, подразделы, пункты."""
    for section in es.sections(data):
        yield section
        for clause in section.get("clauses") or []:
            yield clause
        for sub in section.get("subsections") or []:
            yield sub
            for clause in sub.get("clauses") or []:
                yield clause


def _cabinet_subsections(data):
    """Подразделы, в которых лежат таблицы-формы шкафов (в порядке файла)."""
    result = []
    for section in es.sections(data):
        for sub in section.get("subsections") or []:
            if any(table.get("cabinet") for table in sub.get("tables") or []):
                result.append(sub)
    return result


def _norm_cypher(value):
    """«ШЭТ 431.11-1» → «431.11-1» для сравнения шифров."""
    text = str(value or "").strip().casefold().replace("ё", "е")
    text = re.sub(r"^шэт\s+", "", text)
    return re.sub(r"\s+", "", text)


def _minor(value):
    """Младшая часть номера: «5.12» → 12, иначе None."""
    match = re.match(r"^5\.(\d+)$", str(value or "").strip())
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Правки
# ---------------------------------------------------------------------------
def apply_meta(data, meta):
    """Заменить реквизиты стандарта. Возвращает список изменённых полей."""
    changed = []
    for key, _label in META_FIELDS:
        if key not in (meta or {}):
            continue
        value = meta[key]
        if value is None:
            continue
        value = str(value).strip()
        if value and data.get(key) != value:
            data[key] = value
            changed.append(key)
    return changed


def normalize_replacements(raw):
    """[«a => b» | {"old","new"}] → [(старое, новое)] без пустых пар."""
    result = []
    for item in raw or []:
        if isinstance(item, dict):
            old = item.get("old") or item.get("Старое") or ""
            new = item.get("new") or item.get("Новое") or ""
        elif isinstance(item, str) and "=>" in item:
            old, new = item.split("=>", 1)
        else:
            continue
        old, new = str(old).strip(), str(new).strip()
        if old and old != new and (old, new) not in result:
            result.append((old, new))
    return result


def apply_replacements(data, replacements):
    """Заменить подстроки во всех строках стандарта. Возвращает число замен."""
    if not replacements:
        return 0
    pattern = re.compile("|".join(
        re.escape(old) for old in sorted((old for old, _ in replacements),
                                         key=len, reverse=True)))
    lookup = dict(replacements)
    counter = [0]

    def fix(text):
        def repl(match):
            counter[0] += 1
            return lookup[match.group(0)]
        return pattern.sub(repl, text)

    _rewrite_strings(data, fix)
    return counter[0]


def _rewrite_strings(value, fix):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                value[key] = fix(item)
            else:
                _rewrite_strings(item, fix)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                value[index] = fix(item)
            else:
                _rewrite_strings(item, fix)


def _mentions(text, codes):
    """Шифры, упомянутые в тексте (с «ШЭТ» и без, с пробелами и без)."""
    flat = _norm_cypher(text)
    return [code for code in codes
            if _norm_cypher(code) and _norm_cypher(code) in flat]


def _figure_kept(figure, keep_codes, all_codes):
    """Рисунок остаётся, если не привязан только к снятым шкафам."""
    mentioned = _mentions(figure.get("name") or "", all_codes)
    if not mentioned:
        return True
    return any(code in keep_codes for code in mentioned)


def _filter_rows(table, keep_codes, all_codes):
    """Убирает строки общей таблицы, где упомянуты только снятые шкафы."""
    rows = table.get("rows") or []
    left = []
    for row in rows:
        if row.get("is_header_first_row") or row.get("is_header_second_row"):
            left.append(row)
            continue
        text = " ".join(str(cell) for cell in row.get("content") or [])
        mentioned = _mentions(text, all_codes)
        if mentioned and not any(code in keep_codes for code in mentioned):
            continue
        left.append(row)
    table["rows"] = left


def keep_only(data, keep):
    """Оставить только перечисленные шкафы. Возвращает список шифров."""
    items = cabinets(data)
    if not items:
        raise StandardError("в стандарте нет шкафов — нечего выбирать")
    wanted = []
    for value in keep or []:
        key = _norm_cypher(value)
        if key and key not in wanted:
            wanted.append(key)
    if not wanted:
        raise StandardError("не выбран ни один шкаф")

    all_codes = [str(item.get("cypher") or "") for item in items]
    keep_codes = {code for code in all_codes
                  if _norm_cypher(code) in wanted}
    unknown = [value for value in wanted
               if value not in {_norm_cypher(code) for code in all_codes}]
    if unknown:
        raise StandardError(
            "не найдены шкафы: %s. Доступны: %s"
            % (", ".join(unknown), ", ".join(all_codes)))
    if not keep_codes:
        raise StandardError("ни один шкаф не выбран")

    data["cabinets"] = [item for item in items
                        if item.get("cypher") in keep_codes]

    # Подразделы шкафов запоминаем до отбора: после него у снятых шкафов
    # не останется ни одной таблицы, и подраздел уйдёт целиком.
    cabinet_subs = {id(sub) for sub in _cabinet_subsections(data)}

    # Таблицы-формы снятых шкафов и строки общих таблиц с их упоминанием.
    for container in _containers(data):
        tables = container.get("tables")
        if tables:
            container["tables"] = [
                table for table in tables
                if not table.get("cabinet") or table.get("cabinet") in keep_codes]
            for table in container["tables"]:
                if not table.get("cabinet"):
                    _filter_rows(table, keep_codes, all_codes)
        figures = container.get("figures")
        if figures:
            container["figures"] = [
                figure for figure in figures
                if _figure_kept(figure, keep_codes, all_codes)]

    for section in es.sections(data):
        section["subsections"] = [
            sub for sub in section.get("subsections") or []
            if id(sub) not in cabinet_subs or sub.get("tables")]
    return sorted(keep_codes)


def starts_of(data):
    """Начальные номера подразделов, таблиц и рисунков шкафов в стандарте."""
    subs = _cabinet_subsections(data)
    tables = [table for table in es.iter_tables(data) if table.get("cabinet")]
    figures = [figure for sub in subs for figure in sub.get("figures") or []]
    return {
        "subs": _minor(subs[0].get("number")) if subs else None,
        "tables": _minor(tables[0].get("number")) if tables else None,
        "figures": _minor(figures[0].get("number")) if figures else None,
    }


def renumber_standard(data, starts=None):
    """Подразделы шкафов, таблицы и рисунки — подряд; ссылки в тексте.

    starts — начальные номера (см. :func:`starts_of`); если не указаны,
    берутся из самого стандарта. При отборе шкафов начальные номера нужно
    брать из исходного стандарта, иначе нумерация не сдвинется.

    Возвращает отображение «старый номер таблицы → новый».
    """
    subs = _cabinet_subsections(data)
    tables = [table for table in es.iter_tables(data) if table.get("cabinet")]
    figures = [figure for sub in subs for figure in sub.get("figures") or []]
    if not tables:
        return {}
    starts = starts or starts_of(data)
    table_start = starts.get("tables") or 2
    sub_start = starts.get("subs")
    figure_start = starts.get("figures")

    table_map = {}
    table_numbers = {}
    for index, table in enumerate(tables):
        old = str(table.get("number") or "")
        new = "5.%d" % (table_start + index)
        table_numbers[id(table)] = new
        if old and old != new:
            table_map[old] = new

    sub_numbers = {}
    for index, sub in enumerate(subs):
        old = str(sub.get("number") or "")
        new = "5.%d" % (sub_start + index) if sub_start else old
        sub_numbers[id(sub)] = new

    figure_map = {}
    figure_numbers = {}
    for index, figure in enumerate(figures):
        old = str(figure.get("number") or "")
        new = "5.%d" % (figure_start + index) if figure_start else old
        figure_numbers[id(figure)] = new
        if old and old != new:
            figure_map[old] = new

    def fix(text):
        def repl(match):
            word, space, minor = match.group(1), match.group(2), match.group(3)
            mapping = (table_map if word.lower().startswith("таблиц")
                       else figure_map)
            return "%s%s5.%s" % (word, space, mapping.get(minor, minor))
        return _REF_RE.sub(repl, text)

    _rewrite_strings(data, fix)

    for sub in subs:
        new = sub_numbers[id(sub)]
        old = str(sub.get("number") or "")
        sub["number"] = new
        for clause in sub.get("clauses") or []:
            number = str(clause.get("number") or "")
            if old and number.startswith(old + "."):
                clause["number"] = new + number[len(old):]
    for table in tables:
        new = table_numbers[id(table)]
        table["number"] = new
        table["reference"] = "Таблица %s" % new
    for figure in figures:
        new = figure_numbers[id(figure)]
        figure["number"] = new
        figure["reference"] = "Рисунок %s" % new
    return table_map


# ---------------------------------------------------------------------------
# Проверка
# ---------------------------------------------------------------------------
def validate(data):
    """Проблемы нового стандарта (пустой список — всё в порядке)."""
    problems = list(es.validate(data))
    for key, label in META_FIELDS:
        if not str(data.get(key) or "").strip():
            problems.append("не заполнено поле «%s»" % label)
    cyphers = [str(item.get("cypher") or "") for item in cabinets(data)]
    duplicates = sorted({code for code in cyphers if cyphers.count(code) > 1})
    if duplicates:
        problems.append("повторяются шифры шкафов: %s" % ", ".join(duplicates))
    numbers = [str(table.get("number") or "")
               for table in es.iter_tables(data) if table.get("cabinet")]
    duplicates = sorted({number for number in numbers
                         if numbers.count(number) > 1})
    if duplicates:
        problems.append("повторяются номера таблиц: %s"
                        % ", ".join(duplicates))
    return problems


def stats_of(data):
    return es.stats(data)


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------
def build(source, meta=None, replacements=None, keep=None, renumber=True):
    """Собрать новый стандарт из исходного (исходный не изменяется).

    Возвращает dict: data, problems, warnings, notes, stats, source_stats,
    replacements, renumbered.
    """
    if not isinstance(source, dict):
        raise StandardError("исходный стандарт должен быть объектом JSON")
    data = copy.deepcopy(source)
    notes = []
    warnings = []
    starts = starts_of(source)

    if keep:
        before = len(cabinets(data))
        kept = keep_only(data, keep)
        notes.append("оставлено шкафов: %d из %d" % (len(kept), before))

    reps = normalize_replacements(replacements)
    replaced = apply_replacements(data, reps)
    if replaced:
        notes.append("замен: %d (%s)" % (replaced, ", ".join(
            "%s → %s" % pair for pair in reps)))

    changed = apply_meta(data, meta or {})
    if changed:
        notes.append("изменены реквизиты: %s" % ", ".join(
            label for key, label in META_FIELDS if key in changed))

    mapping = renumber_standard(data, starts) if renumber else {}
    if mapping:
        notes.append("перенумеровано таблиц: %d" % len(mapping))

    problems = validate(data)
    if keep:
        text = json.dumps(data, ensure_ascii=False)
        dropped = [code for code in (item.get("cypher")
                                     for item in source.get("cabinets") or [])
                   if code and code not in kept and code in text]
        if dropped:
            warnings.append("в тексте остались упоминания снятых шкафов: %s"
                            % ", ".join(dropped))
    old_code = str(source.get("code") or "").strip()
    if old_code and old_code != data.get("code") \
            and old_code in json.dumps(data, ensure_ascii=False):
        warnings.append("старый шифр %r ещё встречается в тексте — "
                        "добавьте замену" % old_code)

    return {
        "data": data,
        "problems": problems,
        "warnings": warnings,
        "notes": notes,
        "stats": stats_of(data),
        "source_stats": stats_of(source),
        "replacements": replaced,
        "renumbered": mapping,
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
    stats, was = result["stats"], result["source_stats"]
    lines = ["НОВЫЙ СТАНДАРТ НА БАЗЕ ВЫБРАННОГО", "=" * 60]
    lines.append("Наименование: %s" % data.get("name", ""))
    lines.append("Шифр: %s" % data.get("code", ""))
    lines.append("Принадлежность: %s" % data.get("property", ""))
    lines.append("Дата введения: %s" % (data.get("date") or "—"))
    lines.append("")
    lines.append("Шкафов: %d (было %d), таблиц: %d (было %d), строк: %d (было %d)"
                 % (stats["шкафы"], was["шкафы"], stats["таблицы"],
                    was["таблицы"], stats["строк_в_шкафах"],
                    was["строк_в_шкафах"]))
    for note in result.get("notes") or []:
        lines.append("• %s" % note)
    if path:
        lines.append("Файл: %s" % path)
    lines.append("")
    if result["problems"]:
        lines.append("ПРОВЕРКА: проблем %d" % len(result["problems"]))
        for item in result["problems"]:
            lines.append("  ! %s" % item)
    else:
        lines.append("ПРОВЕРКА: OK")
    if result["warnings"]:
        lines.append("Предупреждения:")
        for item in result["warnings"]:
            lines.append("  ~ %s" % item)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Новый стандарт на базе выбранного (структура EA)")
    parser.add_argument("--base", help="исходный стандарт (путь или имя файла)")
    parser.add_argument("--out", help="куда записать новый стандарт")
    parser.add_argument("--code", help="шифр стандарта")
    parser.add_argument("--name", help="наименование стандарта")
    parser.add_argument("--property", help="принадлежность стандарта")
    parser.add_argument("--date", help="дата введения")
    parser.add_argument("--keep", action="append", default=[],
                        help="оставить шкаф (шифр); можно несколько раз")
    parser.add_argument("--replace", action="append", default=[],
                        help="замена «старое => новое»")
    parser.add_argument("--no-renumber", action="store_true",
                        help="не перенумеровывать разделы и таблицы")
    parser.add_argument("--force", action="store_true",
                        help="перезаписать существующий файл")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать отчёт, файл не писать")
    args = parser.parse_args(argv)

    base = args.base or es.default_base()
    if not base:
        print("Нет стандартов в папке %s" % es.folder())
        return 1
    if not os.path.isabs(base) and not os.path.exists(base):
        candidate = os.path.join(es.folder(), base)
        if os.path.exists(candidate):
            base = candidate
    try:
        source = es.load(base)
        result = build(
            source,
            meta={"code": args.code, "name": args.name,
                  "property": args.property, "date": args.date},
            replacements=args.replace,
            keep=args.keep or None,
            renumber=not args.no_renumber,
        )
    except (StandardError, OSError, ValueError) as exc:
        print("Ошибка: %s" % exc)
        return 1

    path = None
    if args.out and not args.dry_run:
        try:
            write_standard(result["data"], args.out, overwrite=args.force)
            path = args.out
        except (StandardError, OSError) as exc:
            print("Ошибка записи: %s" % exc)
            return 1
    print(report(result, path))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
