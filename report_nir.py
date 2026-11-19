# -*- coding: utf-8 -*-
"""Отчёты по НИР и текстовые отчёты схемы.

Методы этого миксина подключаются к ``main.CircuitEditor`` и строят
документы по форме «Форма отчета.docx»: отчёт по НИР (раздел «Шкафы» и
раздел «Контейнеры»), расширенный отчёт с сигналами, отчёт по схеме и по
выделению, а также окна показа собранных отчётов и сохранения их в файл.

Данные берутся из схемы (``elements``, ``protection_links``,
``analog_links``) и каталогов (:mod:`cabs`, :mod:`komplekts`), поэтому
отчёт и полотно не расходяются. Секция перенесена из ``main.py`` без
изменений логики.
"""

from __future__ import annotations

import re
from datetime import datetime

import cabs
import docxreport
import komplekts

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:                                # pragma: no cover
    tk = None


class NirReportMixin:
    # ================= ОТЧЁТ ПО НИР =================
    # Документ строится по форме «Форма отчета.docx»: раздел «Шкафы»
    # (общие положения, перечень шкафов и таблица функций ИЭУ по каждому
    # шкафу) и раздел «Контейнеры» (спецификация контейнера). Отчёт
    # делается либо по одному контейнеру с его шкафами, либо по схеме без
    # контейнеров: два и более контейнеров не допускаются.

    @staticmethod
    def _nir_kit_text(kit):
        """Графа «Комплект»: откуда взят комплект шкафа."""
        kind = kit.get("kind")
        if kind == "typical":
            reference = (kit.get("cabinet_code") or kit.get("cabinet_name")
                         or "").strip()
            if reference:
                return "В составе типового шкафа {}".format(reference)
            return "Типовой комплект"
        if kind == "other":
            return "Нетиповой комплект"
        return "Добавленный комплект"

    @staticmethod
    def _nir_device_text(kit):
        """Графа «Устройство»: ИЭУ комплекта."""
        return ", ".join(ied.get("name") or "ИЭУ"
                         for ied in komplekts.effective_ieds(kit)) or "—"

    def _nir_cabinet_fields(self, cabinet):
        """Шифр, наименование и стандарт шкафа для отчёта по НИР.

        Стандарт — документ целиком: обозначение и наименование, а не
        только шифр («СТО …-2019 «Типовые шкафы ШЭТ …»»).
        """
        code, name, _group = self._report_cabinet_type(cabinet)
        if not code or code == "—":
            code = cabinet.name or cabinet.id
        if not name or name == "—":
            name = cabinet.name or cabinet.id
        info = getattr(cabinet, "info", {}) or {}
        return code, name, self._nir_standard_text(info)

    @staticmethod
    def _nir_standard_text(info):
        """Документ-стандарт шкафа: «СТО … «Наименование документа»»."""
        code = (info.get("standard") or "").strip()
        title = (info.get("standard_title") or "").strip()
        if code and title:
            return "{} «{}»".format(code, title)
        return code or title or "Нетиповой"

    def _nir_cabinet_place(self, cabinet):
        """Место шкафа на схеме: «EL9, Слот 6» или «EL3» вне контейнера.

        Нужно, чтобы одинаковые по типу шкафы в отчёте были различимы:
        у каждого своё обозначение на схеме, а у привязанного — ещё и слот.
        """
        name = cabinet.name or cabinet.id
        container = self._container_of(cabinet.id)
        if container is None:
            return name or ""
        slot = container.slot_of(cabinet.id)
        if slot is None:
            return name or ""
        return "{}, Слот {}".format(name, slot + 1)

    def _nir_cabinet_heading(self, cabinet):
        """Заголовок подраздела шкафа: «Шкаф <шифр> <наименование>»."""
        code, name, _standard = self._nir_cabinet_fields(cabinet)
        text = code if name == code else "{} {}".format(code, name)
        if text.casefold().startswith(("шкаф", "ящик")):
            return text
        return "Шкаф {}".format(text)

    def _nir_cabinet_type_key(self, cabinet):
        """Ключ типа шкафа: одинаковые типы описываются в отчёте один раз."""
        code, name, _standard = self._nir_cabinet_fields(cabinet)
        key = code if code and code != "—" else name
        if not key or key == "—":
            key = cabinet.id
        return str(key).strip().casefold()

    def _nir_kit_rows(self, cabinet):
        """Таблица функций шкафа: устройство, комплект, функции."""
        rows = []
        for kit in getattr(cabinet, "komplets", []):
            rows.append([
                self._nir_device_text(kit),
                self._nir_kit_text(kit),
                ", ".join(kit.get("functions") or []) or "—",
            ])
        return rows

    def _nir_functions_text(self, cabinet):
        """Функции шкафа одной строкой: все устройства без префикса ИЭУ."""
        functions = []
        for kit in getattr(cabinet, "komplets", []):
            functions.extend(kit.get("functions") or [])
        return ", ".join(functions) or "—"

    def _nir_target(self):
        """Что описывает отчёт: (контейнер, шкафы, ошибка)."""
        containers = sorted(
            (el for el in self.elements.values() if el.type == "container"),
            key=lambda el: self._natural_key(
                el.name or getattr(el, "code", "") or el.id))
        if len(containers) > 1:
            return None, [], (
                "Отчёт по НИР строится либо по одному контейнеру с его "
                "шкафами,\nлибо по схеме без контейнеров.\n"
                "Сейчас на схеме контейнеров: {}.\n"
                "Оставьте один контейнер и повторите.".format(
                    len(containers)))
        container = containers[0] if containers else None
        if container is not None:
            cabinets = []
            for cabinet_id in container.bound_ids():
                cabinet = self.elements.get(cabinet_id)
                if cabinet is not None and cabinet.type == "cabinet":
                    cabinets.append(cabinet)
            if not cabinets:
                return None, [], (
                    "К контейнеру «{}» не привязано ни одного шкафа — "
                    "отчёт по НИР строить не из чего.".format(
                        container.name or getattr(container, "code", "")
                        or "КЭТ"))
            return container, cabinets, None
        cabinets = sorted(
            (el for el in self.elements.values() if el.type == "cabinet"),
            key=lambda el: (self._natural_key(
                self._nir_cabinet_fields(el)[0]), self._natural_key(el.name)))
        if not cabinets:
            return None, [], ("На схеме нет шкафов РЗА — отчёт по НИР "
                              "строить не из чего.")
        return None, cabinets, None

    def _collect_nir_report(self):
        """Данные отчёта по НИР: (отчёт, ошибка)."""
        container, cabinets, error = self._nir_target()
        if error:
            return None, error

        blocks = [
            {"kind": "heading", "text": "Шкафы", "level": 1},
            {"kind": "heading", "text": "Общие положения", "level": 2},
            {"kind": "paragraph", "text": (
                "Полный перечень шкафов контейнера приведен в таблице."
                if container is not None else
                "Полный перечень шкафов приведен в таблице.")},
        ]

        table_number = 1
        blocks.append({"kind": "caption",
                       "text": "Таблица {} – Перечень шкафов".format(
                           table_number)})
        overview_rows = []
        for cabinet in cabinets:
            code, _name, standard = self._nir_cabinet_fields(cabinet)
            overview_rows.append([code, standard,
                                  self._nir_cabinet_place(cabinet)])
        blocks.append({
            "kind": "table",
            "header": ["Шкаф", "Стандарт", "Примечание"],
            "rows": overview_rows,
            "widths": [2600, 5038, 2000],
            "aligns": ["left", "left", "left"],
            "empty_text": "",
        })

        described_types = set()
        for cabinet in cabinets:
            type_key = self._nir_cabinet_type_key(cabinet)
            if type_key in described_types:
                # Однотипные шкафы описываем один раз: функции и состав
                # у них одинаковые, а в перечне выше указаны все экземпляры.
                continue
            described_types.add(type_key)
            code = self._nir_cabinet_fields(cabinet)[0]
            table_number += 1
            blocks.append({"kind": "heading", "level": 2,
                           "text": self._nir_cabinet_heading(cabinet)})
            blocks.append({"kind": "paragraph",
                           "text": "Реализуемые функции ИЭУ шкафа "
                                   "представлены в таблице {}.".format(
                                       table_number)})
            blocks.append({"kind": "caption",
                           "text": "Таблица {} – Функции в составе ИЭУ "
                                   "шкафа {}".format(table_number, code)})
            blocks.append({
                "kind": "table",
                "header": ["Устройство", "Комплект",
                           "Реализуемые функции"],
                "rows": self._nir_kit_rows(cabinet),
                "widths": [1500, 2900, 5238],
                "aligns": ["left", "left", "left"],
                "font_size": 8,
            })

        if container is not None:
            code = (getattr(container, "code", "") or "").strip() or "КЭТ"
            info = getattr(container, "info", {}) or {}
            title = (info.get("name")
                     or getattr(container, "title", "") or "").strip()
            table_number += 1
            blocks.append({"kind": "heading", "text": "Контейнеры",
                           "level": 1})
            blocks.append({"kind": "heading", "level": 2,
                           "text": "Контейнер типа {} {}".format(
                               code, title).strip()})
            blocks.append({"kind": "heading", "text": "Спецификация",
                           "level": 3})
            blocks.append({"kind": "paragraph",
                           "text": "Шкафы и ящики РЗА в составе контейнера "
                                   "{} представлены в таблице {}.".format(
                                       code, table_number)})
            blocks.append({"kind": "caption",
                           "text": "Таблица {} – Шкафы и ящики в составе "
                                   "контейнера {}".format(table_number, code)})
            specification_rows = []
            for cabinet in cabinets:
                cab_code, cab_name, standard = self._nir_cabinet_fields(
                    cabinet)
                place = self._nir_cabinet_place(cabinet)
                if place:
                    cab_name = "{} ({})".format(cab_name, place)
                type_text = cab_code
                if standard == "Нетиповой":
                    type_text = "{} (нетиповой)".format(cab_code)
                specification_rows.append([
                    cab_name, type_text, self._nir_functions_text(cabinet)])
            blocks.append({
                "kind": "table",
                "header": ["Состав оборудования", "Тип ШЭТ",
                           "Реализуемые функции"],
                "rows": specification_rows,
                "widths": [3100, 1700, 4838],
                "aligns": ["left", "left", "left"],
                "font_size": 8,
            })

        return {
            "title": "Отчет по НИР",
            "format": "blocks",
            "footer": "Отчет по НИР",
            "blocks": blocks,
        }, None

    def report_nir(self):
        """Отчёт по НИР по форме «Форма отчета.docx»."""
        report, error = self._collect_nir_report()
        if report is None:
            messagebox.showinfo("Отчет по НИР", error)
            return
        self._show_report_window(report,
                                 self._report_filename("Отчет по НИР"))

    # ---------- расширенный отчёт по НИР: все контейнеры и их шкафы ------
    #: Строки, которые в расширенный отчёт по НИР не выводятся.
    NIR_HIDDEN_ROWS = ("Источник", "Группа", "Вводы (цепи) питания",
                       "Поясняющая схема подключения",
                       "Основные компоненты", "Эскиз общего вида",
                       "Схема электрическая принципиальная", "Параметры функций ИЭУ", "Структурно-функциональная схема")

    @classmethod
    def _nir_pairs_table(cls, rows):
        """Таблица «показатель — значение» для блоков отчёта."""
        hidden = set(cls.NIR_HIDDEN_ROWS)
        rows = [row for row in rows if not row or row[0] not in hidden]
        return {
            "kind": "table",
            "header": ["Показатель", "Значение"],
            "rows": rows,
            "widths": [2600, 7038],
            "aligns": ["left", "left"],
            "font_size": 8,
        }

    def _nir_bound_cabinets(self, container):
        """Шкафы, реально привязанные к контейнеру, в порядке слотов.

        Возвращает пары «номер слота (с 1) — элемент шкафа». Ссылки на
        удалённые элементы и пустые слоты пропускаются, поэтому в отчёт
        попадают только оставленные в контейнере шкафы.
        """
        result = []
        for index in range(container.slot_count()):
            cabinet_id = (container.cabinets[index]
                          if index < len(container.cabinets) else "")
            cabinet = self.elements.get(cabinet_id) if cabinet_id else None
            if cabinet is not None and cabinet.type == "cabinet":
                result.append((index + 1, cabinet))
        return result

    def _nir_container_rows(self, container):
        """Описание контейнера: обозначение, тип, привязанные шкафы, габариты."""
        code = (getattr(container, "code", "") or "").strip() or "КЭТ"
        info = getattr(container, "info", {}) or {}
        bound = self._nir_bound_cabinets(container)
        rows = [["Обозначение", container.name or code],
                ["Тип контейнера", code],
                ["Наименование", info.get("name") or container.title or "—"]]
        for key, label in (("group", "Группа"),
                           ("standard_title", "Стандарт"),
                           ("architecture", "Архитектура"),
                           ("size_title", "Типоразмер"),
                           ("dimensions", "Габариты"),
                           ("climate", "Климатическое исполнение"),
                           ("ip", "Степень защиты оболочки")):
            if info.get(key):
                rows.append([label, str(info[key])])
        if info.get("standard") and not info.get("standard_title"):
            rows.append(["Стандарт", str(info["standard"])])
        rows.append(["Слотов в контейнере", str(container.slot_count())])
        rows.append(["Шкафов привязано", str(len(bound))])
        if info.get("description"):
            rows.append(["Назначение", str(info["description"])])
        if bound:
            composition = []
            for slot, cabinet in bound:
                cabinet_code, cabinet_name, _standard = (
                    self._nir_cabinet_fields(cabinet))
                composition.append("{} {} ({}, Слот {})".format(
                    cabinet_code, cabinet_name,
                    cabinet.name or cabinet.id, slot))
            rows.append(["Состав контейнера", "\n".join(composition)])
        else:
            rows.append(["Состав контейнера", "Шкафы не привязаны"])
        if info.get("note"):
            rows.append(["Примечание", str(info["note"])])
        if info.get("source"):
            rows.append(["Источник", str(info["source"])])
        return rows

    def _nir_cabinet_rows(self, cabinet, with_blocks=True):
        """Расширенное описание шкафа: тип, функции, питание, порты, БИ.

        with_blocks=False — без испытательных блоков (для краткого отчёта).
        """
        code, name, standard = self._nir_cabinet_fields(cabinet)
        info = getattr(cabinet, "info", {}) or {}
        kits = list(getattr(cabinet, "komplets", []) or [])
        signals = cabs.signals_for(
            {"key": getattr(cabinet, "cabinet_key", "") or ""})
        rows = [["Тип (шифр)", code], ["Наименование", name],
                ["Стандарт", standard]]
        for key, label in (("group", "Группа"), ("voltage", "Напряжение"),
                           ("architecture", "Архитектура")):
            value = info.get(key) or (cabs.find_cabinet(
                getattr(cabinet, "cabinet_key", "") or "") or {}).get(key)
            if value:
                rows.append([label, str(value)])
        if info.get("protected"):
            rows.append(["Защищаемый элемент", str(info["protected"])])
        if info.get("controlled"):
            rows.append(["Управляемые элементы",
                         ", ".join(info["controlled"])])
        functions = self._nir_functions_text(cabinet)
        rows.append(["Функции ИЭУ", functions or "—"])
        rows.append(["Комплектов / ИЭУ", "{} / {}".format(
            len(kits),
            sum(len(komplekts.effective_ieds(kit)) for kit in kits))])
        blocks_text = [komplekts.test_blocks_text(kit) for kit in kits
                       if komplekts.has_test_blocks(kit)]
        if blocks_text and with_blocks:
            rows.append(["Испытательные блоки (комплекты)",
                         "; ".join(blocks_text)])
        if blocks_text and not with_blocks:
            # краткий отчёт: по строке на каждый комплект с испытательными
            # блоками — обозначения и характеристики из стандарта
            for number, kit in enumerate(kits, start=1):
                if not komplekts.has_test_blocks(kit):
                    continue
                rows.append([
                    "ИБ комплекта {}{}".format(
                        number,
                        " ({})".format(kit["name"])
                        if kit.get("name")
                        and kit["name"] != "Комплект {}".format(number)
                        else ""),
                    komplekts.test_blocks_text(kit)])
        if info.get("applicability"):
            rows.append(["Применимость", str(info["applicability"])])
        catalogue = cabs.find_cabinet(
            getattr(cabinet, "cabinet_key", "") or "") or {}
        for field, label in komplekts.DETAIL_LABELS:
            value = (komplekts.detail_value(info, field)
                     or komplekts.detail_value(catalogue, field))
            if value:
                rows.append([label, str(value)])
        if signals.get("test_blocks") and with_blocks:
            rows.append(["Испытательные блоки (СТО)", ", ".join(
                block.get("name", "") for block in signals["test_blocks"])])
        if info.get("source"):
            rows.append(["Источник", str(info["source"])])
        return rows

    def _collect_nir_extended_report(self, with_signals=True):
        """Расширенный отчёт по НИР: раздел на каждый контейнер и его шкафы.

        with_signals=False — краткий вариант: описания контейнеров и шкафов
        без таблиц входных/выходных сигналов и испытательных блоков.
        """
        containers = sorted(
            (el for el in self.elements.values() if el.type == "container"),
            key=lambda el: self._natural_key(
                el.name or getattr(el, "code", "") or el.id))
        if not containers:
            return None, ("На схеме нет контейнеров — расширенный отчёт "
                          "по НИР строить не из чего.")

        blocks = []
        tables = {"number": 0}

        def next_table():
            tables["number"] += 1
            return tables["number"]

        def add_cabinet(cabinet, prefix):
            code = self._nir_cabinet_fields(cabinet)[0]
            blocks.append({"kind": "heading", "level": 2,
                           "text": "{} {}".format(
                               prefix, self._nir_cabinet_heading(cabinet))})
            number = next_table()
            blocks.append({"kind": "caption",
                           "text": "Таблица {} – Описание шкафа {}".format(
                               number, code)})
            blocks.append(self._nir_pairs_table(
                self._nir_cabinet_rows(cabinet, with_blocks=with_signals)))

            if not with_signals:
                return
            signals = cabs.signals_for(
                {"key": getattr(cabinet, "cabinet_key", "") or ""})
            present = [(kind, title) for kind, title, _short in
                       cabs.SIGNAL_KINDS if signals.get(kind)]
            if not present:
                blocks.append({"kind": "paragraph",
                               "text": "Перечни сигналов и испытательных "
                                       "блоков в стандарте не приведены."})
                return
            for kind, title in present:
                items = signals.get(kind) or []
                number = next_table()
                blocks.append({"kind": "caption",
                               "text": "Таблица {} – {} шкафа {}".format(
                                   number, title, code)})
                if kind == "test_blocks":
                    rows = [[str(position), item.get("name", ""),
                             item.get("spec", ""), item.get("count", "")]
                            for position, item in enumerate(items, start=1)]
                    blocks.append({
                        "kind": "table",
                        "header": ["№", "Испытательный блок", "Цепи",
                                   "Кол-во"],
                        "rows": rows,
                        "widths": [600, 4000, 4000, 1038],
                        "aligns": ["center", "left", "left", "center"],
                        "font_size": 8,
                    })
                else:
                    rows = [[str(item.get("num") or position),
                             item.get("name", ""), item.get("code", ""),
                             item.get("details", "")]
                            for position, item in enumerate(items, start=1)]
                    blocks.append({
                        "kind": "table",
                        "header": ["№", "Наименование сигнала",
                                   "Обозначение по МЭК 61850", "Сведения"],
                        "rows": rows,
                        "widths": [600, 3400, 1900, 3738],
                        "aligns": ["center", "left", "left", "left"],
                        "font_size": 8,
                    })

        for index, container in enumerate(containers, start=1):
            code = (getattr(container, "code", "") or "").strip() or "КЭТ"
            name = (getattr(container, "info", {}) or {}).get("name") \
                or container.title or ""
            if index > 1:
                blocks.append({"kind": "pagebreak"})
            blocks.append({"kind": "heading", "level": 1,
                           "text": "{}. Контейнер {} {}".format(
                               index, code, name).strip()})
            number = next_table()
            blocks.append({"kind": "paragraph",
                           "text": "Описание контейнера приведено "
                                   "в таблице {}.".format(number)})
            blocks.append({"kind": "caption",
                           "text": "Таблица {} – Контейнер {}".format(
                               number, code)})
            blocks.append(self._nir_pairs_table(
                self._nir_container_rows(container)))

            cabinets = [cabinet for _slot, cabinet
                        in self._nir_bound_cabinets(container)]
            if not cabinets:
                blocks.append({"kind": "paragraph",
                               "text": "К контейнеру не привязано ни одного "
                                       "шкафа."})
                continue
            described_types = set()
            described = 0
            for cabinet in cabinets:
                type_key = self._nir_cabinet_type_key(cabinet)
                if type_key in described_types:
                    # Однотипные шкафы описываем один раз; все экземпляры
                    # перечислены в составе контейнера выше.
                    continue
                described_types.add(type_key)
                described += 1
                add_cabinet(cabinet, "{}.{}.".format(index, described))

        bound = set()
        for container in containers:
            bound.update(container.bound_ids())
        free = sorted(
            (el for el in self.elements.values()
             if el.type == "cabinet" and el.id not in bound),
            key=lambda el: self._natural_key(self._nir_cabinet_fields(el)[0]))
        if free:
            blocks.append({"kind": "heading", "level": 1,
                           "text": "Шкафы вне контейнеров"})
            described_types = set()
            described = 0
            for cabinet in free:
                type_key = self._nir_cabinet_type_key(cabinet)
                if type_key in described_types:
                    continue
                described_types.add(type_key)
                described += 1
                add_cabinet(cabinet, "{}.{}.".format(len(containers) + 1,
                                                    described))

        title = ("Расширенный отчет по НИР" if with_signals else
                 "Расширенный отчет по НИР (без сигналов и БИ)")
        return {
            "title": title,
            "format": "blocks",
            "footer": title,
            "blocks": blocks,
        }, None

    def report_nir_extended(self):
        """Расширенный отчёт по НИР: все контейнеры, их шкафы, сигналы и БИ."""
        report, error = self._collect_nir_extended_report()
        if report is None:
            messagebox.showinfo("Расширенный отчет по НИР", error)
            return
        self._show_report_window(
            report, self._report_filename("Расширенный отчет по НИР"))

    def report_nir_extended_short(self):
        """Расширенный отчёт по НИР без входных/выходных сигналов и БИ."""
        report, error = self._collect_nir_extended_report(with_signals=False)
        if report is None:
            messagebox.showinfo("Расширенный отчет по НИР", error)
            return
        self._show_report_window(
            report, self._report_filename(
                "Расширенный отчет по НИР без сигналов и БИ"))

    def report_unbound(self):
        """Отчёт по непривязанным элементам схемы."""
        if not self.elements:
            messagebox.showinfo("Отчёты", "Схема пуста — проверять нечего.")
            return
        try:
            report = self._collect_unbound_report()
        except Exception as error:
            messagebox.showerror(
                "Отчёты", "Не удалось сформировать отчёт:\n{}".format(error))
            return
        self._show_report_window(
            report,
            self._report_filename("Отчёт по непривязанным элементам"))

    @staticmethod
    def _report_filename(stem):
        """Имя файла отчёта: без запрещённых символов, с датой."""
        safe = re.sub(r'[\\/:*?"<>|]+', "-", str(stem or "Отчёт")).strip()
        safe = re.sub(r"\s+", " ", safe).strip(" -") or "Отчёт"
        return "{} {}.docx".format(safe, datetime.now().strftime("%d.%m.%Y"))

    @staticmethod
    def _table_text(header, rows):
        """Строки таблицы для моноширинного предпросмотра.

        Ячейка может содержать переводы строк (например, функции ИЭУ —
        по строке на устройство): такая ячейка занимает несколько
        физических строк таблицы.
        """
        table = [list(header)] + [list(row) for row in rows]
        columns = len(header)
        cells_rows = []
        for row in table:
            cells_rows.append([
                str(row[index] if index < len(row) else "").split("\n")
                for index in range(columns)])
        widths = [0] * columns
        for cells in cells_rows:
            for index in range(columns):
                for part in cells[index]:
                    widths[index] = min(34, max(widths[index], len(part)))
        lines = []
        for number, cells in enumerate(cells_rows):
            height = max(len(parts) for parts in cells)
            for line_index in range(height):
                rendered = []
                for index in range(columns):
                    parts = cells[index]
                    value = (parts[line_index]
                             if line_index < len(parts) else "")
                    if len(value) > widths[index]:
                        value = value[:widths[index] - 1] + "…"
                    rendered.append(value.ljust(widths[index]))
                lines.append("  " + " | ".join(rendered).rstrip())
            if number == 0:
                lines.append("  " + "-+-".join("-" * w for w in widths))
        return lines

    def _blocks_report_to_text(self, report):
        """Текст документа по форме: заголовки, абзацы, подписи, таблицы."""
        lines = [report.get("title", "Отчёт"), "=" * 60, ""]
        for block in report.get("blocks") or []:
            kind = block.get("kind")
            if kind == "heading":
                text = block.get("text") or ""
                level = int(block.get("level", 1))
                indent = "  " * (level - 1)
                lines.append(indent + text)
                lines.append(indent + "-" * max(
                    12 if level > 1 else 20, min(60 - 4 * (level - 1),
                                                len(text))))
                lines.append("")
            elif kind == "caption":
                lines.append("  " + (block.get("text") or ""))
            elif kind == "pagebreak":
                lines.append("")
                lines.append("-" * 60 + " разрыв страницы")
                lines.append("")
            elif kind == "table":
                header = block.get("header") or []
                if header:
                    lines.extend(self._table_text(header,
                                                  block.get("rows") or []))
                lines.append("")
            else:
                text = block.get("text") or ""
                if text:
                    lines.append("  " + text)
        if report.get("footer"):
            lines.append("")
            lines.append(str(report["footer"]))
        return "\n".join(lines)

    def _report_to_text(self, report):
        """Текст отчёта для окна предпросмотра (моноширинный шрифт)."""
        if report.get("format") == "blocks":
            return self._blocks_report_to_text(report)
        lines = [report.get("title", "Отчёт"), "=" * 60]
        for line in report.get("subtitle") or []:
            lines.append(line)
        lines.append("")

        for section in report.get("sections") or []:
            text = section.get("title") or ""
            lines.append(text)
            lines.append("-" * max(20, min(60, len(text))))
            if section.get("note"):
                lines.append("  " + str(section["note"]))
                lines.append("")

            rows = section.get("rows") or []
            blocks = section.get("blocks") or []
            header = section.get("header")

            if header:
                lines.extend(self._table_text(header, rows))
            elif rows:
                label_w = min(28, max((len(str(row[0])) for row in rows),
                                      default=0))
                for row in rows:
                    label = str(row[0]) if row else ""
                    value = str(row[1]) if len(row) > 1 else ""
                    lines.append("  " + label.ljust(label_w) + " : " + value)

            for block in blocks:
                lines.append("")
                if block.get("head"):
                    lines.append("  " + str(block["head"]))
                if block.get("note"):
                    lines.append("    " + str(block["note"]))
                block_rows = block.get("rows") or []
                label_w = min(24, max((len(str(row[0])) for row in block_rows),
                                      default=0))
                for row in block_rows:
                    label = str(row[0]) if row else ""
                    value = str(row[1]) if len(row) > 1 else ""
                    lines.append("    " + label.ljust(label_w) + " : " + value)
            lines.append("")

        for line in report.get("footer") or []:
            lines.append("")
            lines.append(str(line))
        return "\n".join(lines)

    def _show_report_window(self, report, default_name):
        """Окно предпросмотра отчёта с сохранением в Word."""
        window = tk.Toplevel(self.root)
        window.title(report.get("title", "Отчёт"))
        window.transient(self.root)
        width, height = 940, 620
        window.geometry("{}x{}".format(width, height))
        window.minsize(560, 360)
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 4)
        window.geometry("+{}+{}".format(x, y))

        body = tk.Frame(window)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        text = tk.Text(body, wrap="none", font=("Courier New", 9),
                       bg="#fdfdf7", relief="solid", bd=1)
        yscroll = tk.Scrollbar(body, orient=tk.VERTICAL, command=text.yview)
        xscroll = tk.Scrollbar(window, orient=tk.HORIZONTAL, command=text.xview)
        text.config(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text.insert("1.0", self._report_to_text(report))
        text.config(state="disabled")
        xscroll.pack(fill=tk.X, padx=8, pady=(0, 4))

        buttons = tk.Frame(window)
        buttons.pack(fill=tk.X, padx=8, pady=6)

        def save_docx():
            path = filedialog.asksaveasfilename(
                parent=window, title="Сохранить отчёт",
                defaultextension=".docx", initialfile=default_name,
                filetypes=[("Документ Word", "*.docx")])
            if not path:
                return
            try:
                if report.get("format") == "blocks":
                    docxreport.build_nir_report(path, report)
                else:
                    docxreport.build_selection_report(path, report)
            except Exception as error:
                messagebox.showerror("Отчёты",
                                     "Не удалось сохранить отчёт:\n{}".format(error),
                                     parent=window)
                return
            if messagebox.askyesno("Отчёты",
                                   "Отчёт сохранён:\n{}\n\nОткрыть документ?"
                                   .format(path), parent=window):
                self._open_document(path)

        def copy_text():
            window.clipboard_clear()
            window.clipboard_append(self._report_to_text(report))
            copy_button.config(text="✓ Скопировано")

        tk.Button(buttons, text="Сохранить в Word…", width=20,
                  command=save_docx).pack(side=tk.LEFT)
        copy_button = tk.Button(buttons, text="Копировать текст", width=18,
                                command=copy_text)
        copy_button.pack(side=tk.LEFT, padx=8)
        tk.Button(buttons, text="Закрыть", width=12,
                  command=window.destroy).pack(side=tk.RIGHT)
        text.focus_set()
        window.bind("<Escape>", lambda event: window.destroy())
        window.grab_set()

    def report_by_selection(self):
        """Отчёт по выделенному шкафу или контейнеру."""
        target, error = self._selection_report_target()
        if target is None:
            messagebox.showinfo("Отчёты", error)
            return
        try:
            if target.type == "cabinet":
                report = self._cabinet_report(target)
                label = target.name or target.id
                kind_label = "шкафу"
            else:
                report = self._container_report(target)
                label = (target.name or getattr(target, "code", "")
                         or target.id)
                kind_label = "контейнеру"
            default_name = self._report_filename(
                "Отчёт по {} {}".format(kind_label, label))
        except Exception as error:
            messagebox.showerror(
                "Отчёты", "Не удалось сформировать отчёт:\n{}".format(error))
            return
        self._show_report_window(report, default_name)

    def report_by_scheme(self):
        """Отчёт по схеме в формате DOCX."""
        if not self.elements:
            messagebox.showinfo("Отчёты", "Схема пуста — нечего выгружать.")
            return
        default_name = "Отчёт по схеме {}.docx".format(
            datetime.now().strftime("%d.%m.%Y"))
        path = filedialog.asksaveasfilename(
            title="Сохранить отчёт по схеме",
            defaultextension=".docx",
            initialfile=default_name,
            filetypes=[("Документ Word", "*.docx")])
        if not path:
            return
        try:
            report = self._collect_scheme_report()
            docxreport.build_scheme_report(path, report)
        except Exception as error:
            messagebox.showerror(
                "Отчёты",
                "Не удалось сформировать отчёт:\n{}".format(error))
            return
        cabinets = len([el for el in self.elements.values()
                        if el.type == "cabinet"])
        containers = len([el for el in self.elements.values()
                          if el.type == "container"])
        if messagebox.askyesno(
                "Отчёты",
                "Отчёт сохранён:\n{}\n\nШкафов: {} · контейнеров: {} · "
                "аналоговых цепей: {}\n\nОткрыть документ?".format(
                    path, cabinets, containers, len(self.analog_links))):
            self._open_document(path)

