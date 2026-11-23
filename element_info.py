# -*- coding: utf-8 -*-
"""Общие таблицы обозначений и наименований элементов схемы.

Единый источник для ``main.py`` и модулей, вынесенных из него
(``report_selection``, ``report_nir``, ``scheme_io``): префиксы обозначений
по типу элемента и русские наименования типов. Таблицы собираются из
базового набора электрических элементов и набора элементов ФЛС
(:mod:`logic_library`), поэтому импортировать их из ``main`` нельзя —
получился бы циклический импорт.
"""

from __future__ import annotations

import logic_library

# Префиксы обозначений по типу элемента — единый источник для добавления,
# копирования, вставки из файла и развёртывания состава КЭТ.
# Все обозначения — латиницей: шкафы «EL», контейнеры «EK».
PREFIX_BY_TYPE = {
    "breaker": "Q", "disconnector": "QS", "transformer": "T",
    "split_transformer": "T", "three_winding_transformer": "T",
    "autotransformer": "AT", "reactor": "R", "double_reactor": "R",
    "line": "W",
    "bus": "BB", "node": "N", "corner": "C", "grounding_switch": "QSG",
    "ground": "G", "voltage_transformer": "TV", "current_transformer": "TA",
    "opn": "FV", "coupling_capacitor": "CC", "line_trap": "LT",
    "connection_filter": "CF", "av_breaker": "QF", "fuse": "FU",
    "cabinet": "EL", "container": "EK", "bushing_monitor": "BSH",
    "capacitor_battery": "BSK", "comment_node": "D",
}
# Элементы ФЛС: обозначения и названия — из logic_library.
PREFIX_BY_TYPE.update(logic_library.PREFIX_BY_TYPE)

# Русские наименования типов элементов (для отчётов и подсказок).
ELEMENT_TYPE_TITLES = {
    "breaker": "Выключатель",
    "disconnector": "Разъединитель",
    "bus": "Сборные шины",
    "transformer": "Трансформатор",
    "split_transformer": "Трансформатор с расщеплением обмоток",
    "three_winding_transformer": "Трёхобмоточный трансформатор",
    "autotransformer": "Автотрансформатор",
    "reactor": "Реактор",
    "double_reactor": "Двойной реактор",
    "line": "ЛЭП",
    "voltage_transformer": "Трансформатор напряжения",
    "current_transformer": "Трансформатор тока",
    "opn": "ОПН",
    "coupling_capacitor": "Конденсатор связи",
    "line_trap": "ВЧ-заградитель",
    "connection_filter": "Фильтр присоединения",
    "av_breaker": "Автоматический выключатель 0,4 кВ",
    "fuse": "Предохранитель",
    "grounding_switch": "Заземляющий разъединитель",
    "ground": "Заземление",
    "bushing_monitor": "КИВ — контроль изоляции вводов",
    "capacitor_battery": "БСК — батарея статических конденсаторов",
    "cabinet": "Шкаф РЗА",
    "container": "Контейнер КЭТ",
    "corner": "Уголок",
    "node": "Узел",
    "comment_node": "Декоративный узел",
}
ELEMENT_TYPE_TITLES.update(logic_library.ELEMENT_TYPE_TITLES)

#: Название программы: идёт в заголовок окна после имени чертежа.
APP_TITLE = "Редактор электрических схем v34"
