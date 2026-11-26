# -*- coding: utf-8 -*-
"""Отчёт по выбранному элементу стандарта EA (DOCX).

Дерево редактора стандарта (:mod:`ea_editor`) по правому клику строит
отчёт по любому узлу: разделу, подразделу, пункту, таблице, рисунку,
шкафу, комплекту, ИЭУ, блоку, функции, входу/выходу, уставке, параметру
или выделенной группе узлов.

Отчёт перечисляет поля элемента и их значения. Набор полей берётся из
исполняемой схемы structure2 (:mod:`ea_schema`), поэтому новый класс
модели попадает в отчёт без правок этого модуля. Для контейнеров
(стандарт, раздел, шкаф, комплект, ИЭУ, функция) после полей выводятся
вложенные элементы — тоже полями и значениями. Таблица выводится своей
шапкой и строками, собранными из шкафа через
:func:`ea_standard.table_view`.

Пока это отчёт «как есть», без шаблонов: оформление — общие helpers
:mod:`ea_docx` (шрифт, кегль 10, сетка таблиц).

    import ea_report
    ea_report.build(data, [ea_report.target("Cabinet", cabinet)],
                    "Шкаф.docx")
"""

from __future__ import annotations

import json
import os

import ea_docx as ed
import ea_schema as sc
import ea_standard as es

Document = ed.Document
DocxError = ed.DocxError

#: Вид узла дерева редактора → класс схемы, когда вид неоднозначен.
TEXT_CLASS = {"section": "Section", "subsection": "Subsection",
              "clause": "Clause", "subclause": "Subclause"}
SLOT_CLASS = {"in": "Input", "out": "Output"}

#: Коллекции, которые не обходятся как дочерние элементы.
#: ``Table.rows`` выводится самой таблицей, ``Standard.functional_blocks``
#: дублирует блоки из шкафов и выносится отдельным отчётом по каталогу.
SKIP_CHILDREN = {("Table", "rows"), ("Standard", "functional_blocks")}

#: Заголовки классов — для отчёта и подписей вложенных элементов.
CLASS_TITLES = {
    "Standard": "Стандарт",
    "Section": "Раздел",
    "Subsection": "Подраздел",
    "Clause": "Пункт",
    "Subclause": "Подпункт",
    "Table": "Таблица",
    "Figure": "Рисунок",
    "Cabinet": "Шкаф",
    "Kit": "Комплект",
    "IED": "ИЭУ",
    "FunctionBlock": "Блок",
    "Function": "Функция",
    "Input": "Вход",
    "Output": "Выход",
    "Setting": "Уставка",
    "Parameter": "Параметр",
    "Component": "Компонент",
    "PowerSupply": "Ввод питания",
    "TerminalBlock": "Клеммник",
    "TerminalRow": "Ряд клемм",
    "Terminal": "Клемма",
    "AnalogInput": "Аналоговый вход",
    "ControlCommand": "Команда управления",
    "DataSet": "Набор данных",
    "Signal": "Сигнал",
    "FunctionalButton": "Функциональная кнопка",
    "IncomingGooseSignal": "Входящий GOOSE",
    "InnerDiscreteCircuit": "Внутренняя дискретная цепь",
    "LED": "Светодиод",
    "OscAnalogSignal": "Аналоговый сигнал осциллограммы",
    "Port": "Порт",
    "Container": "Контейнер",
    "FunctionalBlockEntry": "Функциональный блок",
}

#: Сколько уровней вложенности выводить (стандарт → шкаф → комплект →
#: ИЭУ → блок → функция → слот).
DEFAULT_DEPTH = 8


def _text(value):
    if value is None:
        return ""
    return str(value)


def _join(*parts):
    """Склеить непустые части подписи через тире."""
    return " — ".join(_text(part).strip() for part in parts
                      if _text(part).strip())


def target(class_name, item, title="", children=True):
    """Описание одного элемента отчёта.

    ``children=False`` — только поля элемента, без вложенных коллекций
    (например, отчёт по реквизитам стандарта).
    """
    return {"class": class_name, "item": item,
            "title": title or element_title(class_name, item),
            "children": children}


def element_title(class_name, item):
    """Подпись элемента в отчёте: «Шкаф …», «Функция …», «Таблица …»."""
    item = item if isinstance(item, dict) else {}
    number = _text(item.get("number"))
    name = _text(item.get("name") or item.get("header")
                 or item.get("description"))
    if class_name == "Standard":
        return _text(item.get("name")).strip() or "Стандарт"
    if class_name in ("Section", "Subsection"):
        return ("%s %s" % (number, name)).strip() \
            or CLASS_TITLES.get(class_name, class_name)
    if class_name in ("Clause", "Subclause"):
        return ("%s %s" % (CLASS_TITLES.get(class_name, class_name),
                           number)).strip()
    if class_name == "Table":
        return _join(item.get("reference") or "Таблица", item.get("name"))
    if class_name == "Figure":
        return _join(item.get("reference") or "Рисунок", item.get("name"))
    if class_name == "Cabinet":
        return _join("Шкаф", item.get("cypher"), item.get("name"))
    if class_name == "Kit":
        return _join("Комплект", number, item.get("description"))
    if class_name == "IED":
        return _join("ИЭУ", number, item.get("description"))
    if class_name == "FunctionBlock":
        return _join("Блок", name or item.get("russian_path"))
    if class_name == "Function":
        return _join("Функция", name)
    if class_name == "FunctionalBlockEntry":
        return es.functional_block_label(item)
    return _join(CLASS_TITLES.get(class_name, class_name), name)


def _value_text(value):
    """Значение поля для ячейки таблицы отчёта."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        return ("%g" % value).replace(".", ",")
    if isinstance(value, (list, tuple)):
        parts = [_value_text(item) for item in value]
        return "; ".join(part for part in parts if part)
    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
        return text if len(text) <= 800 else text[:799] + "…"
    return str(value).strip()


def _child_keys(class_name):
    return {key for key, _child in sc.children(class_name)}


def field_rows(class_name, item):
    """Пары «подпись поля — значение» для заполненных полей элемента."""
    if not isinstance(item, dict):
        return []
    rows = []
    known = set()
    for key, _kind, _default in sc.fields(class_name):
        known.add(key)
        if key not in item:
            continue
        value = item.get(key)
        if class_name in ("Input", "Output") and key == "type":
            # В JSON хранится код типа слота — в отчёте показываем подпись.
            value = es.SLOT_TYPES.get(_text(value), value)
        text = _value_text(value)
        if text:
            rows.append([sc.label(key), text])
    children = _child_keys(class_name)
    for key, value in item.items():
        if key in known or key in children or key.startswith("_"):
            continue
        text = _value_text(value)
        if text:
            rows.append([sc.label(key), text])
    return rows


def _render_table(doc, data, table, max_rows, counters):
    """Таблица элемента: шапка из формы, строки — из шкафа."""
    headers, rows = es.table_view(data, table)
    text_style = data.get(ed.TEXT_STYLE_FIELD)
    counters["таблицы"] += 1
    if not headers:
        ed._body(doc, "Таблица пуста.", text_style)
        return
    shown = ed._table(doc, headers, rows, max_rows=max_rows,
                      widths_mm=table.get("colums_width") or [],
                      header_rows=es.table_header_rows(table),
                      style=table.get("table_style"),
                      merge=ed._merge_enabled(table))
    if max_rows and len(rows) > shown:
        ed._body(doc, "Показано %d из %d строк." % (shown, len(rows)),
                 text_style)


def _render_fields(doc, class_name, item, counters, text_style=""):
    rows = field_rows(class_name, item)
    if rows:
        counters["поля"] += len(rows)
        ed._table(doc, ["Поле", "Значение"], rows, size=10,
                  widths_mm=[55, 125])
    else:
        ed._body(doc, "Заполненных полей нет.", text_style)


def _is_leaf(class_name):
    """У класса нет собственных дочерних коллекций (вход, уставка, сигнал)."""
    return not [key for key, _child in sc.children(class_name)
                if (class_name, key) not in SKIP_CHILDREN]


def _leaf_rows(class_name, values):
    """Строки «элемент — поле — значение» для коллекции листовых элементов."""
    rows = []
    for index, value in enumerate(values, 1):
        if not isinstance(value, dict):
            continue
        title = element_title(class_name, value)
        if not _text(value.get("name")).strip():
            title = "%s %d" % (title, index)
        for label, text in field_rows(class_name, value):
            rows.append([title, label, text])
    return rows


def _render_children(doc, data, class_name, item, level, depth, max_rows,
                     counters):
    """Вложенные коллекции элемента: заголовок, подпись и поля каждого."""
    if depth <= 0:
        return
    for key, child_class in sc.children(class_name):
        if (class_name, key) in SKIP_CHILDREN:
            continue
        values = item.get(key)
        if not isinstance(values, list) or not values:
            continue
        ed._heading(doc, "%s (%d)" % (sc.label(key), len(values)),
                    min(level, 3), numbered=False)
        if child_class == "Table":
            for value in values:
                if not isinstance(value, dict):
                    continue
                ed._caption(doc, element_title(child_class, value), bold=True)
                _render_table(doc, data, value, max_rows, counters)
            continue
        if _is_leaf(child_class):
            # Входы, выходы, уставки, параметры, сигналы: одна таблица на
            # коллекцию, иначе у шкафа получаются сотни таблиц по две строки.
            rows = _leaf_rows(child_class, values)
            if rows:
                counters["поля"] += len(rows)
                ed._table(doc, ["Элемент", "Поле", "Значение"], rows,
                          size=10, widths_mm=[65, 45, 70])
            continue
        for value in values:
            if not isinstance(value, dict):
                ed._body(doc, _value_text(value),
                         data.get(ed.TEXT_STYLE_FIELD))
                continue
            ed._caption(doc, element_title(child_class, value), bold=True)
            _render_fields(doc, child_class, value, counters,
                           data.get(ed.TEXT_STYLE_FIELD))
            _render_children(doc, data, child_class, value, level + 1,
                             depth - 1, max_rows, counters)


def _render_target(doc, data, item, max_rows, depth, counters):
    class_name = item["class"]
    heading = item.get("title") or element_title(class_name, item.get("item"))
    ed._heading(doc, heading, 1, numbered=False)
    _render_fields(doc, class_name, item.get("item"), counters,
                   data.get(ed.TEXT_STYLE_FIELD))
    if class_name == "Table":
        # Собственные строки таблицы — не поле, а отдельная таблица отчёта.
        _render_table(doc, data, item.get("item"), max_rows, counters)
        return
    if not item.get("children", True):
        return
    _render_children(doc, data, class_name, item.get("item"), 2, depth,
                     max_rows, counters)


def build(data, targets, path, title="", max_rows=0,
          depth=DEFAULT_DEPTH):
    """Записать отчёт по ``targets`` в DOCX. Возвращает счётчики."""
    if Document is None:
        raise DocxError("не установлен python-docx: "
                        "python -m pip install python-docx")
    targets = [item for item in (targets or [])
               if isinstance(item, dict) and item.get("item") is not None]
    if not targets:
        raise DocxError("не выбрано ни одного элемента для отчёта")
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        raise DocxError("нет папки: %s" % folder)

    doc = Document()
    ed._setup(doc, layout=False)
    section = doc.sections[0]
    section.orientation = ed.WD_ORIENT.PORTRAIT
    section.page_width = ed.Cm(21.0)
    section.page_height = ed.Cm(29.7)
    for name in ("left_margin", "right_margin", "top_margin",
                 "bottom_margin"):
        setattr(section, name, ed.Cm(1.5))
    ed._page_number(section)

    ed._heading(doc, title or "Отчёт по стандарту", 1, numbered=False)
    text_style = data.get(ed.TEXT_STYLE_FIELD)
    standard = _join(data.get("code"), data.get("name"))
    if standard:
        ed._body(doc, "Стандарт: %s." % standard, text_style)
    if len(targets) > 1:
        ed._body(doc, "Элементов в отчёте: %d." % len(targets), text_style)
        for index, item in enumerate(targets, 1):
            ed._body(doc, "%d. %s" % (
                index, item.get("title") or element_title(
                    item["class"], item.get("item"))), text_style)
    elif targets[0]["class"] == "Standard":
        ed._body(doc, "Элемент: реквизиты%s."
                 % (" и состав стандарта"
                    if targets[0].get("children", True) else " стандарта"),
                 text_style)

    counters = {"элементы": len(targets), "таблицы": 0, "поля": 0}
    for item in targets:
        _render_target(doc, data, item, max_rows, depth, counters)

    doc.save(path)
    counters["размер"] = os.path.getsize(path)
    return counters
