# -*- coding: utf-8 -*-
"""Проверка structure.json v3: иерархия, комплекты/ИЭУ, ссылки, стыковка.

Модель хранения (спецификация — STRUCTURE.md)::

    контейнеры (КЭТ) → шкафы → комплекты → ИЭУ

Контролирует:

1. версия 3 и разделы верхнего уровня «контейнеры» / «шкафы»;
2. **шкаф состоит из комплектов** — у каждого шкафа есть «комплекты»
   (минимум одна запись), ИЭУ на уровне шкафа не хранится;
3. **комплект бывает с ИЭУ или без** — обязательный булевый признак
   «есть ИЭУ»; «иэу» есть только у комплекта с ИЭУ, у каждого ИЭУ есть
   «обозначение» и «тип»;
4. уникальность id и стыковка id с каталогом редактора
   (``cabs.all_cabinets()``, ``komplekts.cabinet_komplekts()``,
   ``containers.all_containers()``);
5. замкнутость ссылок «контейнер.шкафы» ↔ «шкаф.контейнеры»;
6. **единственное ИЭУ в описании шкафа входит в комплект** — старое поле
   ``cabinet["ieds"]`` с одним устройством перенесено, сводные GOOSE и
   испытательные блоки не оставлены на уровне шкафа с одним владельцем;
7. ключи элементов реальных схем из ``schemes/`` разрешаются в записи
   структуры, то есть файл стыкуется с редактором;
8. заполненность полей (справочная сводка, не ошибка).

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
import containers          # noqa: E402
import komplekts           # noqa: E402
import structure           # noqa: E402

ID = structure.ID_FIELD                  # "id"
KITS = structure.KITS_FIELD              # "комплекты"
IEDS = structure.IEDS_FIELD              # "иэу"
HAS_IED = structure.HAS_IED_FIELD        # "есть ИЭУ"
CONTAINERS = structure.CONTAINERS_FIELD  # "контейнеры" (обратная ссылка шкафа)
CABINETS = structure.CABINETS_FIELD      # "шкафы" (ссылка контейнера)

#: Поля, обязательные для каждой записи своего уровня.
CABINET_REQUIRED = (ID, "полное имя", "шифр", KITS)
KIT_REQUIRED = (ID, "номер", "вид", "полное имя", HAS_IED)
IED_REQUIRED = ("обозначение", "тип")
CONTAINER_REQUIRED = (ID, "код", "название", CABINETS)

#: Поля «старой» плоской модели: их быть не должно.
CABINET_FORBIDDEN = ("ieds", "ИЭУ", IEDS, "Комплект 1", "Шкаф")

#: Сводные таблицы шкафа, которые при одном владельце уходят в комплект/ИЭУ.
SUMMARY_FIELDS = ("входные GOOSE", "выходные GOOSE", "испытательные блоки")

#: Поля для справочной сводки заполненности: уровень → имена полей.
COVERAGE = (
    ("шкаф", ("назначение", "архитектура ПС", "защищаемый элемент",
              "управляемый элемент", "вводы питания", "основные компоненты",
              "порты", "функции ИТС")),
    ("комплект", ("назначение", "шифр", "функции РЗА",
                  "входные аналоговые измерения",
                  "внутренние дискретные цепи", "испытательные блоки")),
    ("ИЭУ", ("описание", "входные GOOSE", "выходные GOOSE")),
    ("КЭТ", ("описание", "состав", "функции", "габариты")),
)


def _filled(record, field):
    return record.get(field) not in (None, "", [], {}, "нет данных")


def check_document(document, problems):
    """Проверка разделов верхнего уровня. Возвращает плоские списки записей."""
    version = document.get("версия")
    if version != 3:
        problems.append("версия файла %r, нужна 3 — пересоберите "
                        "tools/build_structure.py" % version)
    for section in (structure.CONTAINER_SECTION, structure.CABINET_SECTION):
        value = document.get(section)
        if not isinstance(value, list) or not value:
            problems.append("нет непустого раздела «%s»" % section)
    entities = document.get("сущности") or {}
    for name in ("контейнер", "шкаф", "комплект", "иэу"):
        if name not in entities:
            problems.append("в «сущностях» не описан уровень «%s»" % name)
    sources = document.get("источники")
    if not isinstance(sources, dict) or not sources:
        problems.append("не указаны «источники» сборки")

    def section(name):
        value = document.get(name)
        return [item for item in value if isinstance(item, dict)] \
            if isinstance(value, list) else []

    return section(structure.CONTAINER_SECTION), section(structure.CABINET_SECTION)


def check_cabinets(cabinets, problems):
    """Шкаф → комплекты → ИЭУ: состав, признак «есть ИЭУ», уникальность id."""
    all_kits = []
    all_ieds = []
    seen_cabinets, seen_kits = set(), set()
    for cabinet in cabinets:
        cabinet_id = cabinet.get(ID)
        if not cabinet_id:
            problems.append("шкаф без id: %r" % str(cabinet)[:80])
            continue
        if cabinet_id in seen_cabinets:
            problems.append("дубль id шкафа: %s" % cabinet_id)
        seen_cabinets.add(cabinet_id)

        for field in CABINET_REQUIRED:
            if not _filled(cabinet, field):
                problems.append("%s: нет обязательного поля «%s»"
                                % (cabinet_id, field))
        for field in CABINET_FORBIDDEN:
            if field in cabinet:
                problems.append("%s: поле «%s» на уровне шкафа запрещено "
                                "(ИЭУ хранится в комплекте)"
                                % (cabinet_id, field))

        kits = cabinet.get(KITS)
        if not isinstance(kits, list) or not kits:
            problems.append("%s: шкаф не состоит из комплектов" % cabinet_id)
            continue
        numbers = []
        for kit in kits:
            if not isinstance(kit, dict):
                problems.append("%s: комплект не является записью" % cabinet_id)
                continue
            kit_id = kit.get(ID)
            if not kit_id:
                problems.append("%s: комплект без id" % cabinet_id)
                continue
            if kit_id in seen_kits:
                problems.append("дубль id комплекта: %s" % kit_id)
            seen_kits.add(kit_id)
            if not (kit_id.startswith("typ:%s:" % cabinet_id)
                    or kit_id.startswith("cab:%s:" % cabinet_id)):
                problems.append("%s: id комплекта «%s» не соответствует шкафу"
                                % (cabinet_id, kit_id))
            if not isinstance(kit.get("номер"), int):
                problems.append("%s: у комплекта нет номера" % kit_id)
            else:
                numbers.append(kit["номер"])
            for field in KIT_REQUIRED:
                if not _filled(kit, field) and field != HAS_IED:
                    problems.append("%s: нет обязательного поля «%s»"
                                    % (kit_id, field))

            flag = kit.get(HAS_IED)
            if not isinstance(flag, bool):
                problems.append("%s: «%s» отсутствует или не булево значение "
                                "(%r)" % (kit_id, HAS_IED, flag))
                flag = None
            nested = kit.get(IEDS)
            if nested is not None and not isinstance(nested, list):
                problems.append("%s: «%s» должен быть списком" % (kit_id, IEDS))
                nested = None
            if flag is True and not nested:
                problems.append("%s: «%s: true», но вложенных ИЭУ нет"
                                % (kit_id, HAS_IED))
            if flag is False and nested:
                problems.append("%s: «%s: false», но «%s» заполнен"
                                % (kit_id, HAS_IED, IEDS))
            if flag is False and IEDS in kit:
                problems.append("%s: у комплекта без ИЭУ есть поле «%s»"
                                % (kit_id, IEDS))
            names = set()
            for ied in nested or []:
                if not isinstance(ied, dict):
                    problems.append("%s: ИЭУ не является записью" % kit_id)
                    continue
                name = ied.get("обозначение")
                if name in names:
                    problems.append("%s: дубль ИЭУ «%s» в комплекте"
                                    % (kit_id, name))
                names.add(name)
                for field in IED_REQUIRED:
                    if not _filled(ied, field):
                        problems.append("%s: у ИЭУ «%s» нет поля «%s»"
                                        % (kit_id, name, field))
                all_ieds.append(ied)
            all_kits.append(kit)

        if numbers and sorted(numbers) != list(range(1, len(numbers) + 1)):
            problems.append("%s: номера комплектов не 1..N (%s)"
                            % (cabinet_id, sorted(numbers)))

        ied_count = sum(len(k.get(IEDS) or []) for k in kits
                        if isinstance(k, dict))
        if len(kits) == 1 and ied_count == 1:
            left = [field for field in SUMMARY_FIELDS if cabinet.get(field)]
            if left:
                problems.append("%s: при одном комплекте с одним ИЭУ сводные "
                                "данные остались на уровне шкафа: %s"
                                % (cabinet_id, ", ".join(left)))
    return all_kits, all_ieds


def check_containers(containers_list, cabinets, problems):
    """Ссылки КЭТ ↔ шкафы и покрытие каталога контейнеров."""
    cabinet_by_id = {c.get(ID): c for c in cabinets}
    container_by_id = {}
    forward = 0
    for container in containers_list:
        container_id = container.get(ID)
        if not container_id:
            problems.append("КЭТ без id: %r" % str(container)[:80])
            continue
        if container_id in container_by_id:
            problems.append("дубль id КЭТ: %s" % container_id)
        container_by_id[container_id] = container
        for field in CONTAINER_REQUIRED:
            if not _filled(container, field):
                problems.append("%s: нет обязательного поля «%s»"
                                % (container_id, field))
        refs = container.get(CABINETS)
        if not isinstance(refs, list):
            problems.append("%s: «%s» должен быть списком id шкафов"
                            % (container_id, CABINETS))
            continue
        for target in refs:
            forward += 1
            cabinet = cabinet_by_id.get(target)
            if not cabinet:
                problems.append("%s: ссылка на отсутствующий шкаф «%s»"
                                % (container_id, target))
                continue
            if container_id not in (cabinet.get(CONTAINERS) or []):
                problems.append("%s: шкаф «%s» не ссылается обратно на КЭТ"
                                % (container_id, target))
    reverse = 0
    for cabinet in cabinets:
        for container_id in cabinet.get(CONTAINERS) or []:
            reverse += 1
            container = container_by_id.get(container_id)
            if not container:
                problems.append("%s: ссылка на отсутствующий КЭТ «%s»"
                                % (cabinet.get(ID), container_id))
            elif cabinet.get(ID) not in (container.get(CABINETS) or []):
                problems.append("%s: КЭТ «%s» не содержит этот шкаф"
                                % (cabinet.get(ID), container_id))
    return forward, reverse


def check_catalog(cabinets, all_kits, containers_list, problems):
    """Покрытие каталога редактора: все шкафы, комплекты и КЭТ на месте."""
    cabinet_ids = {c.get(ID) for c in cabinets}
    kit_ids = {k.get(ID) for k in all_kits}
    container_ids = {c.get(ID) for c in containers_list}

    catalog = cabs.all_cabinets()
    missing = [c.get("key") for c in catalog if c.get("key") not in cabinet_ids]
    if missing:
        problems.append("в структуре нет %d шкафов каталога: %s"
                        % (len(missing), missing[:8]))
    catalog_kits = {k.get("key") for k in komplekts.cabinet_komplekts(catalog)}
    missing = sorted(catalog_kits - kit_ids)
    if missing:
        problems.append("в структуре нет %d комплектов каталога: %s"
                        % (len(missing), missing[:8]))
    missing = [c.get("key") for c in containers.all_containers()
               if c.get("key") not in container_ids]
    if missing:
        problems.append("в структуре нет %d КЭТ каталога: %s"
                        % (len(missing), missing[:8]))
    return len(catalog), len(catalog_kits)


def check_single_ied(cabinets, problems, notes):
    """Правило: единственное ИЭУ в описании шкафа перенесено в комплект.

    Возвращает ``(проверено, без замечаний)``.
    """
    by_id = {c.get(ID): c for c in cabinets}
    checked = 0
    clean = 0
    for raw in getattr(cabs, "CABINETS", ()) or ():
        single = komplekts.cabinet_single_ied(raw)
        if not single:
            continue
        cabinet = by_id.get(raw.get("key"))
        if not cabinet:
            notes.append("шкаф %s с одним ИЭУ удалён из каталога пользователем"
                         % raw.get("key"))
            continue
        checked += 1
        clean += 1
        name = (single.get("name") or single.get("обозначение")
                or single.get("type") or "")
        names = {ied.get("обозначение") for kit in cabinet.get(KITS) or []
                 for ied in kit.get(IEDS) or []}
        if name not in names:
            clean -= 1
            problems.append("%s: ИЭУ «%s» из описания шкафа не вошло в "
                            "комплект (в комплектах: %s)"
                            % (cabinet.get(ID), name, sorted(map(str, names))))
        left = [field for field in SUMMARY_FIELDS if cabinet.get(field)]
        if left:
            clean -= 1
            problems.append("%s: при одном ИЭУ сводные данные остались на "
                            "уровне шкафа: %s"
                            % (cabinet.get(ID), ", ".join(left)))
    return checked, clean


def check_schemes(problems, notes):
    """Ключи элементов реальных схем должны находиться в структуре."""
    checked = matched = container_checked = container_matched = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "schemes", "*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                scheme = json.load(handle)
        except Exception:
            continue
        for element in scheme.get("elements") or []:
            kind = element.get("type")
            if kind == "cabinet":
                key = (element.get("cabinet_key")
                       or (element.get("cabinet") or {}).get("key") or "")
                if not key:
                    continue
                checked += 1
                if structure.cabinet(key):
                    matched += 1
                else:
                    problems.append("%s: шкаф-элемент %s (%s) не найден "
                                    "в структуре" % (os.path.basename(path),
                                                     element.get("name"), key))
            elif kind == "container":
                key = (element.get("container_key")
                       or (element.get("container") or {}).get("key") or "")
                if not key:
                    continue
                container_checked += 1
                if structure.container(key):
                    container_matched += 1
                else:
                    # копии КЭТ на схемах — пользовательские ключи, не ошибка
                    notes.append("%s: контейнер %s (%s) — пользовательская "
                                 "копия, записи в структуре нет"
                                 % (os.path.basename(path),
                                    element.get("name"), key))
    return matched, checked, container_matched, container_checked


def print_coverage(cabinets, all_kits, all_ieds, containers_list):
    groups = {"шкаф": cabinets, "комплект": all_kits,
              "ИЭУ": all_ieds, "КЭТ": containers_list}
    print("заполнение полей:")
    for level, fields in COVERAGE:
        entries = groups[level]
        for field in fields:
            count = sum(1 for entry in entries if _filled(entry, field))
            print("  %-10s %-38s %4d / %d"
                  % (level + " ·", field, count, len(entries)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=os.path.join(ROOT, "structure.json"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    document = structure.load(force=True, path=args.file)
    if document is None:
        print("НЕ ЗАГРУЖЕНО: %s" % structure.error(), file=sys.stderr)
        return 2

    problems = []
    notes = []
    containers_list, cabinets = check_document(document, problems)
    all_kits, all_ieds = check_cabinets(cabinets, problems)
    forward, reverse = check_containers(containers_list, cabinets, problems)
    catalog_cabinets, catalog_kits = check_catalog(
        cabinets, all_kits, containers_list, problems)
    singles, singles_clean = check_single_ied(cabinets, problems, notes)
    matched, checked, cont_matched, cont_checked = check_schemes(problems, notes)

    with_ied = sum(1 for kit in all_kits if structure.has_ied(kit))
    without_ied = len(all_kits) - with_ied
    no_kits = [c.get(ID) for c in cabinets if not c.get(KITS)]

    if not args.quiet:
        print("structure.json: версия %s · %d КЭТ, %d шкафов, %d комплектов "
              "(%d с ИЭУ / %d без ИЭУ), %d ИЭУ"
              % (document.get("версия") or "?", len(containers_list),
                 len(cabinets), len(all_kits), with_ied, without_ied,
                 len(all_ieds)))
        print("покрытие каталога: шкафы %d/%d, комплекты %d/%d, КЭТ %d/%d"
              % (len(cabinets), catalog_cabinets, len(all_kits), catalog_kits,
                 len(containers_list), len(containers.all_containers())))
        print("шкафов без комплектов: %d%s"
              % (len(no_kits), " — %s" % ", ".join(map(str, no_kits[:5]))
                 if no_kits else ""))
        print("ссылки: КЭТ → шкафы %d, шкафы → КЭТ %d (все разрешены)"
              % (forward, reverse))
        print("одно ИЭУ в описании шкафа → в комплекте: %d/%d"
              % (singles_clean, singles))
        print("стыковка со схемами: шкафы %d/%d, КЭТ %d/%d"
              % (matched, checked, cont_matched, cont_checked))
        print_coverage(cabinets, all_kits, all_ieds, containers_list)
        for note in notes[:10]:
            print("  ! %s" % note)

    if problems:
        print("\nПРОБЛЕМЫ (%d):" % len(problems), file=sys.stderr)
        for problem in problems[:30]:
            print("  x %s" % problem, file=sys.stderr)
        if len(problems) > 30:
            print("  ... и ещё %d" % (len(problems) - 30), file=sys.stderr)
        return 1
    print("\nОшибок нет: иерархия КЭТ → шкафы → комплекты → ИЭУ, признаки "
          "«есть ИЭУ», ссылки и стыковка с редактором в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
