# -*- coding: utf-8 -*-
"""Проверка structure.json: полнота, ссылки, поля образца, стыковка со схемами.

Контролирует:

1. каталог редактора целиком покрыт — каждый шкаф (``cabs.all_cabinets()``) и
   каждый комплект (``komplekts.cabinet_komplekts()``) имеет свою запись;
2. идентификаторы уникальны, ссылки «Комплект N» ↔ «Шкаф» разрешаются и
   соответствуют количеству комплектов;
3. в каждой записи есть поля образца (``standards/structure.json``);
4. модуль ``structure`` находит запись по ключам элементов реальных схем из
   ``schemes/`` — то есть структура стыкуется с редактором.

Запуск:
    python3 tools/check_structure.py
    python3 tools/check_structure.py --quiet      # только итог и ошибки
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cabs                # noqa: E402
import komplekts           # noqa: E402
import structure           # noqa: E402

CABINET_FIELDS = (
    "Полное имя шкафа", "Назначение шкафа", "Шифр шкафа",
    "Архитектура построения ПС", "Наименование шкафа", "Защищаемый элемент",
    "Управляемый элемент", "Вводы питания оперативного постоянного тока",
    "Основные компоненты шкафа",
)
KIT_FIELDS = (
    "Обозначение ИЭУ", "Полное имя комплекта", "Назначение комплекта",
    "Шифр комплекта", "Входные аналоговые измерения", "Внутренние дискретные цепи",
    "Входные GOOSE сообщения", "Выходные GOOSE сообщения",
    "Функциональные клавиши со светодиодной индикацией",
    "Светодиодная сигнализация", "Команды управления от АСУ ТП",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=os.path.join(ROOT, "structure.json"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    document = structure.load(force=True, path=args.file)
    if document is None:
        print("НЕ ЗАГРУЖЕНО: %s" % structure.error(), file=sys.stderr)
        return 2

    cabinets = document.get("Шкаф") or []
    kits = document.get("комплекты") or []
    problems = []
    notes = []

    cab_ids = [c.get("id") for c in cabinets]
    kit_ids = [k.get("id") for k in kits]
    if len(set(cab_ids)) != len(cab_ids):
        problems.append("дубли id шкафов")
    if len(set(kit_ids)) != len(kit_ids):
        problems.append("дубли id комплектов")

    catalog = cabs.all_cabinets()
    missing_cabinets = [c.get("key") for c in catalog
                        if c.get("key") not in set(cab_ids)]
    if missing_cabinets:
        problems.append("в структуре нет %d шкафов каталога: %s"
                        % (len(missing_cabinets), missing_cabinets[:8]))

    catalog_kits = {k.get("key") for k in komplekts.cabinet_komplekts(catalog)}
    missing_kits = sorted(catalog_kits - set(kit_ids))
    if missing_kits:
        problems.append("в структуре нет %d комплектов каталога: %s"
                        % (len(missing_kits), missing_kits[:8]))

    by_id = {c.get("id"): c for c in cabinets}
    kit_by_id = {k.get("id"): k for k in kits}
    for cabinet in cabinets:
        linked = [v for name, v in cabinet.items()
                  if name.startswith("Комплект ")]
        for target in linked:
            if target not in kit_by_id:
                problems.append("%s: ссылка «%s» ни на что не указывает"
                                % (cabinet.get("id"), target))
        for field in CABINET_FIELDS:
            if field not in cabinet:
                problems.append("%s: нет поля образца «%s»"
                                % (cabinet.get("id"), field))
                break
        if len(linked) != len(structure.kits_of(cabinet.get("id"))):
            problems.append("%s: ссылок «Комплект N» %d, записей комплектов %d"
                            % (cabinet.get("id"), len(linked),
                               len(structure.kits_of(cabinet.get("id")))))
    for kit in kits:
        if kit.get("Шкаф") not in by_id:
            problems.append("%s: ссылается на отсутствующий шкаф %r"
                            % (kit.get("id"), kit.get("Шкаф")))
        for field in KIT_FIELDS:
            if field not in kit:
                problems.append("%s: нет поля образца «%s»" % (kit.get("id"), field))
                break

    # --- стыковка с редактором: ключи элементов реальных схем --------------
    checked = matched = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "schemes", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                scheme = json.load(handle)
        except Exception:
            continue
        for element in scheme.get("elements") or []:
            if element.get("type") != "cabinet":
                continue
            key = (element.get("cabinet_key")
                   or (element.get("cabinet") or {}).get("key") or "")
            if not key:
                continue
            checked += 1
            if structure.cabinet(key):
                matched += 1
            else:
                notes.append("%s: шкаф-элемент %s (%s) не найден в структуре"
                             % (os.path.basename(path), element.get("name"), key))

    # --- заполненность ------------------------------------------------------
    filled = {}
    for field in CABINET_FIELDS:
        filled["шкаф · " + field] = sum(
            1 for c in cabinets
            if c.get(field) not in (None, "", [], {}, "нет данных"))
    for field in KIT_FIELDS[4:]:
        filled["комплект · " + field] = sum(
            1 for k in kits if k.get(field))

    if not args.quiet:
        print("structure.json: %d шкафов, %d комплектов" % (len(cabinets), len(kits)))
        print("стыковка со схемами: %d/%d элементов-шкафов найдено" % (matched, checked))
        print("заполнение полей образца:")
        for name, count in filled.items():
            total = len(cabinets) if name.startswith("шкаф") else len(kits)
            print("  %-58s %4d / %d" % (name, count, total))

    for note in notes[:10]:
        print("  ! %s" % note)
    if problems:
        print("\nПРОБЛЕМЫ (%d):" % len(problems), file=sys.stderr)
        for problem in problems[:30]:
            print("  ✗ %s" % problem, file=sys.stderr)
        return 1
    print("\nОшибок нет: структура полная, ссылки замкнуты, поля образца на месте.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
