# -*- coding: utf-8 -*-
"""Проверка чтения стандартов СТО из папки ``standards_base/``.

Запуск:
    python3 tests/test_standards_base.py

Проверяет:

1. загрузку трёх стандартов: 13 шкафов, 15 комплектов, 15 ИЭУ, 191 таблица;
2. поля карточки шкафа: наименование, назначение, функции ИТС/МП ИЭУ,
   применимость, вводы питания, порты; ссылки на рисунки остаются ссылками;
3. таблицы ИЭУ разворачиваются в строки, служебная колонка «№» убирается;
4. обе модели комплектов приводятся к одной: «Комплект» и «Комплект 1/2»;
5. :func:`standards_base.record` даёт запись ``structure.json`` v3 с id
   каталога и ключами комплектов ``typ:<key>:<n>``;
6. нормализацию значений: сноски ``[16]``, тире, шифры, перечни.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import standards_base as sb     # noqa: E402

FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


#: действующие стандарты: их состав — константа, её и проверяем
#: (279, 280-2019, 280-XXXX «Изменение 1», 281)
ACTIVE = "СТО 56947007-"
ACTIVE_STANDARDS = 4
ACTIVE_CARDS = 15
ACTIVE_KITS = 19
ACTIVE_TABLES = 219


def test_loading():
    print("1. загрузка папки standards_base")
    error = sb.error()
    check(not error, "стандарты читаются без ошибок (%s)" % (error or "нет"))
    stats = sb.summary()
    check(stats["стандартов"] >= 3, "стандартов: %d" % stats["стандартов"])
    active = [standard for standard in sb.load()
              if standard["шифр"].startswith(ACTIVE)]
    cards = [card for card in sb.cabinets()
             if card["стандарт"].startswith(ACTIVE)]
    kits = [kit for card in cards for kit in sb.kits(card)]
    check(len(active) == ACTIVE_STANDARDS,
          "действующих стандартов: %d" % len(active))
    check(len(cards) == ACTIVE_CARDS,
          "шкафов действующих стандартов: %d" % len(cards))
    check(len(kits) == ACTIVE_KITS, "комплектов: %d" % len(kits))
    check(sum(len(kit["иэу"]) for kit in kits) == ACTIVE_KITS,
          "ИЭУ: %d" % sum(len(kit["иэу"]) for kit in kits))
    check(sum(len(sb.tables(card)) for card in cards) == ACTIVE_TABLES,
          "таблиц: %d" % sum(len(sb.tables(card)) for card in cards))
    codes = {standard["шифр"] for standard in sb.standards()}
    check(all(code.startswith("СТО") for code in codes),
          "шифры стандартов: %s" % ", ".join(sorted(codes)))
    check(sb.load() is sb.load(), "повторное чтение берётся из кеша")
    check(len(sb.reload()) == len(codes), "reload() перечитывает папку")


def test_card_fields():
    print("2. поля карточки шкафа")
    card = sb.cabinet("ШЭТ 430.01-0")
    check(card is not None, "карточка ШЭТ 430.01-0 найдена")
    record = sb.record(card)
    check(record["наименование"].startswith("Комплект защит батареи"),
          "наименование: %s" % record["наименование"])
    check(record["назначение"].startswith("Шкаф комплекта защит БСК"),
          "назначение заполнено")
    check(record["архитектура ПС"] == "I тип",
          "архитектура ПС: %s" % record["архитектура ПС"])
    check(record["применимость"] == "РУ №220(330)-16, 17",
          "применимость: %s" % record["применимость"])
    check(isinstance(record["функции ИТС"], list)
          and len(record["функции ИТС"]) == 11,
          "функции ИТС: %d значений" % len(record["функции ИТС"]))
    check("ДТЗ" in record["функции ИТС"], "в функциях ИТС есть ДТЗ")
    check(isinstance(record["функции МП ИЭУ"], str)
          and record["функции МП ИЭУ"].startswith("ДТЗ"),
          "функции МП ИЭУ текстом")
    check(len(record["вводы питания"]) == 3,
          "вводы питания: %d" % len(record["вводы питания"]))
    check(len(record["порты"]) == 2, "порты: %d" % len(record["порты"]))
    check(record["поясняющая схема подключения"] == "Рисунок 5.2.1",
          "ссылка на рисунок сохранена как ссылка")
    check(sb.cabinet("ШЭТ 999.99-9") is None, "неизвестный шифр → None")


def test_tables():
    print("3. таблицы ИЭУ")
    card = sb.cabinet("ШЭТ 430.01-0")
    table = sb.table(card, "Таблица 5.2.5")
    check(table is not None, "таблица 5.2.5 найдена по ссылке")
    check(table["Количество строк"] == 4,
          "строк в 5.2.5: %d" % table["Количество строк"])
    rows = sb.table_rows(table)
    check(len(rows) == 4, "строк после разворачивания: %d" % len(rows))
    check(all("№" not in row for row in rows), "служебная колонка «№» убрана")
    check(rows[0].get("Назначение ФК") == "Режим управления ИЭУ (М/Д)",
          "первая строка таблицы ФК прочитана")
    check(sb.table(card, "Рисунок 5.2.1") is None,
          "ссылка на рисунок таблицей не считается")
    record = sb.record(card)
    ied = record["комплекты"][0]["иэу"][0]
    table_fields = [name for name, value in ied.items()
                    if isinstance(value, list)]
    check(len(table_fields) >= 9,
          "таблиц ИЭУ в записи: %d" % len(table_fields))
    check(all(len(ied[name]) > 0 for name in table_fields),
          "все таблицы ИЭУ непустые")
    first = ied["входные дискретные сигналы"][0]
    check(any(str(value).strip() for value in first.values()),
          "строка входных дискретных сигналов читается")


def test_kit_models():
    print("4. две модели комплектов")
    one = sb.record(sb.cabinet("ШЭТ 430.01-0"))
    check(len(one["комплекты"]) == 1, "неявная модель: один комплект")
    check(one["комплекты"][0]["иэу"][0]["обозначение"] == "ИЭУ",
          "имя ИЭУ из карточки: %s"
          % one["комплекты"][0]["иэу"][0]["обозначение"])
    two = sb.record(sb.cabinet("ШЭТ 431.02-0"))
    check(len(two["комплекты"]) == 2, "явная модель: два комплекта")
    names = [kit["иэу"][0]["обозначение"] for kit in two["комплекты"]]
    check(names == ["ИЭУ1", "ИЭУ2"], "имена ИЭУ: %s" % ", ".join(names))
    second = two["комплекты"][1]
    check(second["функции РЗА"] == ["УРОВ", "ЗНФ", "АУВ", "РАС"],
          "функции второго комплекта: %s" % ", ".join(second["функции РЗА"]))
    check(len([name for name, value in second["иэу"][0].items()
               if isinstance(value, list)]) >= 8,
          "у второго ИЭУ есть свои таблицы")
    check(not two["функции МП ИЭУ"].startswith("ИЭУ")
          and "; " in two["функции МП ИЭУ"],
          "функции шкафа объединены без префикса ИЭУ")


def test_record():
    print("5. запись structure.json v3")
    record = sb.record(sb.cabinet("ШЭТ 430.01-0"), "shet-430-01-0")
    check(record["id"] == "shet-430-01-0", "id = ключ каталога")
    check(record["шифр"] == "ШЭТ 430.01-0", "шифр нормализован")
    kit = record["комплекты"][0]
    check(kit["id"] == "typ:shet-430-01-0:0", "ключ комплекта: %s" % kit["id"])
    check(kit["номер"] == 1 and kit["есть ИЭУ"] is True,
          "номер и признак «есть ИЭУ»")
    check(kit["полное имя"].startswith("Комплект защит батареи"),
          "полное имя комплекта: %s" % kit["полное имя"])
    check(record["источник"] == "5.2",
          "раздел стандарта: %s" % record["источник"])
    check("стандарт" in record and record["стандарт"].startswith("СТО"),
          "шифр стандарта записан")
    check(not any(value in (None, "", [], {}) for value in record.values()),
          "пустых полей в записи нет")


def test_normalization():
    print("6. нормализация значений")
    check(sb.norm_code("шэт 430.01–0") == "ШЭТ 430.01-0",
          "шифр: регистр, пробелы и тире приводятся к одному виду")
    check(sb.key_of_code("ШЭТ 430.01-0") == "shet-430-01-0",
          "ключ каталога из шифра")
    check(sb.norm_key("Функции ИТС [16] в составе шкафа")
          == "функции итс в составе шкафа", "сноска [16] отбрасывается")
    check(sb.split_list("- питание цепей; - освещение")
          == ["питание цепей", "освещение"], "перечень «- …; - …»")
    check(sb.split_list(["СЗ (ДЗ, ТЗНП, МТЗ)"]) == ["СЗ (ДЗ, ТЗНП, МТЗ)"],
          "готовый список не дробится")
    check(sb.clean_text("- a; - b") == "a; b", "маркеры «- » убираются")
    check(sb.clean_text("РУ 110-330 кВ: - одно; - другое")
          == "РУ 110-330 кВ: одно; другое",
          "маркеры внутри строки убираются")
    check(sb.table_rows({"Строки": [{"№": "1", "Поле": "значение"}]})
          == [{"Поле": "значение"}], "строка таблицы без «№»")
    active_codes = [card["шифр"] for card in sb.cabinets()
                    if card["стандарт"].startswith(ACTIVE)]
    covered = sb.coverage(active_codes)
    check(covered["в каталоге"] == ACTIVE_CARDS,
          "все шифры действующих стандартов есть в каталоге")


def main():
    print("Проверка чтения standards_base\n")
    test_loading()
    test_card_fields()
    test_tables()
    test_kit_models()
    test_record()
    test_normalization()
    print()
    if FAILURES:
        print("ПРОВАЛЕНО: %d" % len(FAILURES))
        for message in FAILURES:
            print("  - %s" % message)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
