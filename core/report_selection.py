# -*- coding: utf-8 -*-
"""Отчёт по выделенному элементу: шкафы, контейнеры, непривязанные выводы.

Методы этого миксина подключаются к ``main.CircuitEditor`` и собирают
отчёты по текущему выделению (шкаф или контейнер) и по схеме целиком:
используемые/неиспользуемые комплекты, подключённые порты, непривязанные
комплекты и пустые контейнеры. Данные берутся из тех же списков схемы
(``elements``, ``protection_links``, ``analog_links``), что видит
пользователь, поэтому отчёт и полотно не расходятся.

Секция перенесена из ``main.py`` без изменений логики.
"""

from __future__ import annotations

from datetime import datetime

import cabs
import komplekts
from element_info import ELEMENT_TYPE_TITLES


class SelectionReportMixin:
    # ================= ОТЧЁТ ПО ВЫДЕЛЕННОМУ ЭЛЕМЕНТУ =========================
    # Шкаф  → используемые и неиспользуемые комплекты.
    # КЭТ   → все шкафы в контейнере и их комплекты.

    def _selection_report_target(self):
        """Шкаф или контейнер из выделения: (элемент, ошибка)."""
        selected = [self.elements[el_id] for el_id in self.selected_elements
                    if el_id in self.elements]
        if not selected:
            return None, "Сначала выделите шкаф или контейнер на схеме."
        cabinets = [el for el in selected if el.type == "cabinet"]
        containers = [el for el in selected if el.type == "container"]
        if len(selected) == 1:
            element = selected[0]
            if element.type in ("cabinet", "container"):
                return element, None
            return None, ("Отчёт по выделению строится для шкафа РЗА или "
                          "контейнера КЭТ.\nВыделен элемент «{}».".format(
                              ELEMENT_TYPE_TITLES.get(element.type,
                                                      element.type)))
        if len(cabinets) == 1 and not containers:
            return cabinets[0], None
        if len(containers) == 1 and not cabinets:
            return containers[0], None
        return None, ("Выделено элементов: {}.\nВыделите ровно один шкаф "
                      "или один контейнер.".format(len(selected)))

    def _komplekt_links(self, cabinet, index):
        """Связи комплекта: (защищаемые элементы, аналоговые цепи)."""
        ref = "{}#{}".format(cabinet.id, index)
        protections = []
        for link in self.protection_links:
            if self._link_ref(link) != ref:
                continue
            element = self.elements.get(link.get("element"))
            if element is not None:
                name = element.name or element.id
                title = ELEMENT_TYPE_TITLES.get(element.type, "")
                protections.append("{} ({})".format(name, title) if title else name)
        analogs = []
        for link in self.analog_links:
            other = None
            if link.get("from") == ref:
                other = link.get("to")
            elif link.get("to") == ref:
                other = link.get("from")
            if other is None:
                continue
            signals = self._analog_signals_text(link)
            analogs.append(self._report_ref_label(other)
                           + (" · " + signals if signals else ""))
        return protections, analogs

    def _report_ref_label(self, ref):
        """Подпись конца связи для отчёта: «T1 · комплект 1 (Трансформатор)»."""
        element_id, index = self._split_ref(ref)
        element = self.elements.get(element_id)
        if element is None:
            return "— (элемент удалён)"
        name = element.name or element.id
        if index is not None:
            kit_name = ""
            kits = getattr(element, "komplets", []) or []
            if 0 <= index < len(kits):
                kit_name = kits[index].get("name") or ""
            return "{} · комплект {}{}".format(
                name, index + 1, " «{}»".format(kit_name) if kit_name else "")
        title = (ELEMENT_TYPE_TITLES.get(element.type)
                 or getattr(element, "title", "") or element.type)
        return "{} ({})".format(name, title)

    def _komplekt_report_rows(self, kit, index):
        """Пары «параметр — значение» для одного комплекта."""
        ieds = komplekts.effective_ieds(kit)
        rows = [
            ["Комплект", kit.get("name") or "Комплект {}".format(index + 1)],
            ["Вид", komplekts.kind_title(kit)],
        ]
        if kit.get("type"):
            rows.append(["Тип устройства", str(kit["type"])])
        if kit.get("kind") == "typical":
            rows.append(["Типовой шкаф", komplekts.cabinet_ref_text(kit)])
        rows.append(["Функции", ", ".join(kit.get("functions") or []) or "—"])
        rows.append(["ИЭУ", ", ".join(ied.get("name") or "ИЭУ" for ied in ieds)
                     if ieds else "нет"])
        rows.append(["Испытательные блоки", komplekts.test_blocks_text(kit)])
        if kit.get("desc"):
            rows.append(["Описание", str(kit["desc"])])
        return rows

    def _cabinet_report(self, cabinet):
        """Отчёт по шкафу: используемые и неиспользуемые комплекты."""
        code, name, group = self._report_cabinet_type(cabinet)
        info = getattr(cabinet, "info", {}) or {}
        container = self._container_of(cabinet.id)
        if container is not None:
            slot = container.slot_of(cabinet.id)
            place = "{} · слот {}".format(
                container.name or getattr(container, "code", "") or "КЭТ",
                (slot or 0) + 1)
        else:
            place = "не привязан к контейнеру"

        kits = list(getattr(cabinet, "komplets", []))
        used, unused = [], []
        for index, kit in enumerate(kits):
            protections, analogs = self._komplekt_links(cabinet, index)
            if protections or analogs:
                used.append((index, kit, protections, analogs))
            else:
                unused.append((index, kit))

        ied_count = sum(len(komplekts.effective_ieds(kit)) for kit in kits)

        general = [
            ["Обозначение", cabinet.name or "—"],
            ["Тип (шифр)", code],
            ["Наименование типа", name],
            ["Группа", group],
            ["Контейнер КЭТ", place],
            ["Напряжение", info.get("voltage") or "—"],
            ["Защищаемый элемент", info.get("protected") or "—"],
            ["Управляет", ", ".join(info.get("controlled") or []) or "—"],
        ]
        if info.get("its_functions"):
            general.append(["Функции ИТС",
                            ", ".join(info["its_functions"])])
        for label, value in komplekts.visible_details(info):
            general.append([label, value])
        if info.get("standard_title") or info.get("standard"):
            general.append(["Стандарт",
                            info.get("standard_title") or info.get("standard")])
        if info.get("goose") is not None:
            general.append(["GOOSE", "да" if info["goose"] else "нет"])
        general += [
            ["Комплектов в шкафу", str(len(kits))],
            ["Устройств ИЭУ", str(ied_count)],
        ]
        signal_data = cabs.signals_for(
            {"key": getattr(cabinet, "cabinet_key", "") or ""})
        if signal_data:
            for kind, title, _short in cabs.SIGNAL_KINDS:
                items = signal_data.get(kind) or []
                if items:
                    general.append(["{} (из СТО)".format(title), str(len(items))])

        total = [
            ["Всего комплектов", str(len(kits))],
            ["Используется", str(len(used))],
            ["Не используется", str(len(unused))],
        ]

        used_blocks = []
        for index, kit, protections, analogs in used:
            head = "Комплект {} — «{}» · {}".format(
                index + 1, kit.get("name") or "без названия",
                komplekts.kind_title(kit))
            rows = [
                ["Функции", ", ".join(kit.get("functions") or []) or "—"],
                ["ИЭУ", ", ".join(ied.get("name") or "ИЭУ"
                                  for ied in komplekts.effective_ieds(kit))
                 or "нет"],
                ["Защищаемые элементы", "; ".join(protections) or "—"],
                ["Аналоговые цепи", "; ".join(analogs) or "—"],
            ]
            used_blocks.append({"head": head, "rows": rows})

        unused_blocks = []
        for index, kit in unused:
            head = "Комплект {} — «{}» · {}".format(
                index + 1, kit.get("name") or "без названия",
                komplekts.kind_title(kit))
            unused_blocks.append({
                "head": head,
                "note": "Связей с оборудованием нет.",
                "rows": self._komplekt_report_rows(kit, index)[3:],
            })

        sections = [
            {"title": "1. Общие сведения", "rows": general},
            {"title": "2. Сводка по комплектам", "rows": total},
        ]
        if used_blocks:
            sections.append({"title": "3. Используемые комплекты",
                             "blocks": used_blocks})
        else:
            sections.append({
                "title": "3. Используемые комплекты",
                "note": "Ни один комплект шкафа не подключён к оборудованию "
                        "защитными связями или аналоговыми цепями."})
        if unused_blocks:
            sections.append({"title": "4. Неиспользуемые комплекты",
                             "blocks": unused_blocks})
        else:
            sections.append({
                "title": "4. Неиспользуемые комплекты",
                "note": "Все комплекты шкафа используются (свободных нет)."})

        return {
            "title": "Отчёт по шкафу {}".format(
                cabinet.name or cabinet.id),
            "subtitle": [
                "Сформирован: {}".format(
                    datetime.now().strftime("%d.%m.%Y %H:%M")),
                "Тип: {} — {}".format(code, name),
            ],
            "sections": sections,
            "footer": [
                "Используемым считается комплект, у которого есть хотя бы "
                "одна связь: защита → оборудование или аналоговые цепи.",
            ],
        }

    def _cabinet_kits_brief(self, cabinet):
        """Краткое описание комплектов шкафа для отчёта по контейнеру."""
        used, unused = [], []
        for index, kit in enumerate(getattr(cabinet, "komplets", [])):
            protections, analogs = self._komplekt_links(cabinet, index)
            title = kit.get("name") or "Комплект {}".format(index + 1)
            functions = ", ".join(kit.get("functions") or [])
            label = "Комплект {}. «{}»".format(index + 1, title)
            if functions:
                label += " ({})".format(functions)
            if protections or analogs:
                targets = "; ".join(protections + analogs)
                used.append("{} → {}".format(label, targets))
            else:
                unused.append(label)
        return used, unused

    def _container_report(self, container):
        """Отчёт по контейнеру: все шкафы в нём и их комплекты."""
        info = getattr(container, "info", {}) or {}
        cabinets = [self.elements[cabinet_id]
                    for cabinet_id in container.bound_ids()
                    if cabinet_id in self.elements]

        slots = container.slot_count()
        general = [
            ["Обозначение", container.name or getattr(container, "code", "")
             or "—"],
            ["Код", getattr(container, "code", "") or "—"],
            ["Наименование", info.get("name") or
             getattr(container, "title", "") or "—"],
            ["Типоразмер", info.get("size_code") or
             info.get("size") or getattr(container, "size", "") or "—"],
            ["Слотов", str(slots)],
            ["Шкафов привязано", str(len(cabinets))],
            ["Свободных слотов", str(max(0, slots - len(cabinets)))],
        ]
        for key, label in (("dimensions", "Габариты"), ("climate", "Климат"),
                           ("ip", "Степень защиты"), ("group", "Группа")):
            if info.get(key):
                general.append([label, str(info[key])])
        if info.get("standard_title") or info.get("standard"):
            general.append(["Стандарт",
                            info.get("standard_title") or info.get("standard")])
        if info.get("description"):
            general.append(["Назначение", str(info["description"])])

        total_komplets = sum(len(getattr(el, "komplets", [])) for el in cabinets)
        total_used = 0
        for cabinet in cabinets:
            for index in range(len(getattr(cabinet, "komplets", []))):
                protections, analogs = self._komplekt_links(cabinet, index)
                if protections or analogs:
                    total_used += 1
        general += [
            ["Комплектов в шкафах", str(total_komplets)],
            ["Из них используется", str(total_used)],
        ]

        cabinet_rows = []
        for slot in range(slots):
            cabinet_id = container.cabinets[slot] if slot < len(container.cabinets) else ""
            cabinet = self.elements.get(cabinet_id) if cabinet_id else None
            if cabinet is None:
                cabinet_rows.append([str(slot + 1), "— свободен —", "—", "—",
                                     "—", "—", "—"])
                continue
            code, name, _group = self._report_cabinet_type(cabinet)
            kits = list(getattr(cabinet, "komplets", []))
            used_count = 0
            for index in range(len(kits)):
                protections, analogs = self._komplekt_links(cabinet, index)
                if protections or analogs:
                    used_count += 1
            cabinet_rows.append([
                str(slot + 1),
                cabinet.name or cabinet.id,
                code,
                name,
                str(len(kits)),
                str(used_count),
                str(len(kits) - used_count),
            ])

        blocks = []
        for slot in range(slots):
            cabinet_id = container.cabinets[slot] if slot < len(container.cabinets) else ""
            cabinet = self.elements.get(cabinet_id) if cabinet_id else None
            if cabinet is None:
                continue
            code, name, _group = self._report_cabinet_type(cabinet)
            used, unused = self._cabinet_kits_brief(cabinet)
            rows = [
                ["Слот", str(slot + 1)],
                ["Тип шкафа", "{} — {}".format(code, name)],
                ["Комплектов", str(len(getattr(cabinet, "komplets", [])))],
                ["Используются", "; ".join(used) or "—"],
                ["Не используются", "; ".join(unused) or "—"],
            ]
            blocks.append({"head": "{} · слот {}".format(
                               cabinet.name or cabinet.id, slot + 1),
                           "rows": rows})

        sections = [
            {"title": "1. Общие сведения о контейнере", "rows": general},
            {
                "title": "2. Шкафы в контейнере",
                "header": ["Слот", "Шкаф", "Шифр", "Наименование",
                           "Комплектов", "Использ.", "Свободно"],
                "rows": cabinet_rows,
                "widths": [600, 1200, 1400, 3200, 1100, 1000, 1100],
                "aligns": ["center", "left", "left", "left",
                           "center", "center", "center"],
            },
        ]
        if blocks:
            sections.append({"title": "3. Комплекты шкафов", "blocks": blocks})
        else:
            sections.append({
                "title": "3. Комплекты шкафов",
                "note": "К контейнеру не привязано ни одного шкафа."})

        return {
            "title": "Отчёт по контейнеру {}".format(
                container.name or getattr(container, "code", "")
                or container.id),
            "subtitle": [
                "Сформирован: {}".format(
                    datetime.now().strftime("%d.%m.%Y %H:%M")),
                "Шкафов в контейнере: {} из {}".format(len(cabinets), slots),
            ],
            "sections": sections,
            "footer": [
                "«Используются» — комплекты со связями защиты или "
                "аналоговых цепей; остальные комплекты свободны.",
            ],
        }

    # ---------- отчёт по непривязанным элементам ----------
    # Проверка ищет всё, что осталось «ни к чему не привязано»:
    #   * пустые контейнеры КЭТ — без единого шкафа;
    #   * комплекты шкафов без защитных и аналоговых связей;
    #   * элементы первичной схемы со свободными выводами (к выводу не
    #     подходит ни один провод).
    # Нейтраль (N) трансформаторов и автотрансформаторов, второй вывод ФП и
    # уходящая сторона ЛЭП не проверяются — см. UNBOUND_IGNORED_PORTS.

    def _connected_ports(self):
        """Пары (id элемента, имя вывода), к которым подходит провод.

        Второй результат — id элементов, у соединений которых имя вывода не
        совпадает с текущей схемой портов (например, элемент повернули после
        создания провода). Такие элементы в отчёт не попадают: судить об их
        выводах по устаревшим именам нельзя.
        """
        used, stale = set(), set()
        for connection in self.connections:
            for side, port_key in (("from", "port_from"),
                                   ("to", "port_to")):
                element = self.elements.get(connection.get(side))
                if element is None:
                    continue
                port = connection.get(port_key)
                if port in element.ports:
                    used.add((element.id, port))
                else:
                    stale.add(element.id)
        return used, stale

    @staticmethod
    def _element_ref_text(element):
        """Обозначение элемента для отчёта (имя, иначе id)."""
        name = (element.name or "").strip()
        if name and name != element.id:
            return name
        return element.id

    @staticmethod
    def _port_title(port_name):
        """Подпись вывода для отчёта: «верх (top)», «нейтраль (N)»…"""
        title = PORT_TITLES.get(port_name)
        if title is None:
            digits = (str(port_name)[2:]
                      if str(port_name).startswith("p_") else "")
            title = ("отпайка {}".format(digits) if digits.isdigit()
                     else port_name)
        return "{} ({})".format(title, port_name)

    def _unbound_ignored_ports(self, element):
        """Выводы элемента, которые не обязаны быть подключены."""
        return UNBOUND_IGNORED_PORTS.get(element.type, ())

    def _unbound_elements(self, used, stale):
        """Свободные выводы элементов.

        Возвращает (строки ведомости, проверено выводов, свободно выводов).
        """
        per_element_connections = {}
        for connection in self.connections:
            for side in ("from", "to"):
                element_id = connection.get(side)
                if element_id:
                    per_element_connections[element_id] = (
                        per_element_connections.get(element_id, 0) + 1)

        rows = []
        checked_total = 0
        free_total = 0
        candidates = [
            element for element in self.elements.values()
            if element.type not in ("cabinet", "container")
        ]
        candidates.sort(key=lambda el: (self._natural_key(
            self._element_ref_text(el)), el.type))
        for element in candidates:
            if element.id in stale:
                continue
            ignored = self._unbound_ignored_ports(element)
            checked = [port for port in element.ports if port not in ignored]
            if not checked:
                continue
            checked_total += len(checked)
            if element.type in UNBOUND_CONNECTOR_TYPES:
                # Шина, узел и уголок свободны на отпайках — их проверяем
                # только целиком: элемент вообще не участвует в соединениях.
                if per_element_connections.get(element.id):
                    continue
                free_total += len(checked)
                rows.append([
                    str(len(rows) + 1),
                    self._element_ref_text(element),
                    ELEMENT_TYPE_TITLES.get(element.type, element.type),
                    "—",
                    "0 — нет ни одного соединения",
                ])
                continue
            free = [port for port in checked if (element.id, port) not in used]
            if not free:
                continue
            free_total += len(free)
            rows.append([
                str(len(rows) + 1),
                self._element_ref_text(element),
                ELEMENT_TYPE_TITLES.get(element.type, element.type),
                ", ".join(self._port_title(port) for port in free),
                "{} из {}".format(len(checked) - len(free), len(checked)),
            ])
        return rows, checked_total, free_total

    def _empty_container_rows(self):
        """Контейнеры КЭТ, к которым не привязан ни один шкаф."""
        rows = []
        containers = sorted(
            (el for el in self.elements.values() if el.type == "container"),
            key=lambda el: self._natural_key(
                el.name or getattr(el, "code", "") or el.id))
        for container in containers:
            if container.bound_ids():
                continue
            info = getattr(container, "info", {}) or {}
            slots = container.slot_count()
            rows.append([
                str(len(rows) + 1),
                container.name or getattr(container, "code", "") or container.id,
                getattr(container, "code", "—") or "—",
                info.get("name") or getattr(container, "title", "—") or "—",
                info.get("size_code") or getattr(container, "size", "—") or "—",
                str(slots),
                str(slots),
            ])
        return rows

    def _unbound_komplekt_rows(self):
        """Комплекты шкафов без защитных и аналоговых связей."""
        rows = []
        cabinets = sorted(
            (el for el in self.elements.values() if el.type == "cabinet"),
            key=lambda el: self._natural_key(
                self._element_ref_text(el)))
        for cabinet in cabinets:
            container = self._container_of(cabinet.id)
            if container is not None:
                slot = container.slot_of(cabinet.id) or 0
                place = "{} · слот {}".format(
                    container.name or getattr(container, "code", "")
                    or "КЭТ", slot + 1)
            else:
                place = "—"
            for index, kit in enumerate(getattr(cabinet, "komplets", [])):
                protections, analogs = self._komplekt_links(cabinet, index)
                if protections or analogs:
                    continue
                ieds = komplekts.effective_ieds(kit)
                rows.append([
                    str(len(rows) + 1),
                    self._element_ref_text(cabinet),
                    place,
                    kit.get("name") or "Комплект {}".format(index + 1),
                    komplekts.kind_title(kit),
                    ", ".join(kit.get("functions") or []) or "—",
                    ", ".join(ied.get("name") or "ИЭУ" for ied in ieds)
                    or "нет",
                ])
        return rows

    def _collect_unbound_report(self):
        """Готовит данные отчёта по непривязанным элементам."""
        used, stale = self._connected_ports()
        element_rows, checked_ports, free_ports = self._unbound_elements(
            used, stale)
        container_rows = self._empty_container_rows()
        komplekt_rows = self._unbound_komplekt_rows()

        containers = [el for el in self.elements.values()
                      if el.type == "container"]
        cabinets = [el for el in self.elements.values()
                    if el.type == "cabinet"]
        total_kits = sum(len(getattr(el, "komplets", [])) for el in cabinets)

        summary = [
            ["Элементов первичной схемы", str(len([
                el for el in self.elements.values()
                if el.type not in ("cabinet", "container", "comment_node")]))],
            ["Проверено выводов (без исключений)", str(checked_ports)],
            ["Свободных выводов", str(free_ports)],
            ["Элементов со свободными выводами", str(len(element_rows))],
            ["Контейнеров КЭТ", str(len(containers))],
            ["Пустых контейнеров", str(len(container_rows))],
            ["Комплектов в шкафах", str(total_kits)],
            ["Непривязанных комплектов", str(len(komplekt_rows))],
            ["Связей РЗА (комплект → оборудование)",
             str(len(self.protection_links))],
            ["Аналоговых цепей", str(len(self.analog_links))],
        ]

        def empty_section(title, label, message):
            """Раздел-заглушка: проверка пройдена, замечаний нет."""
            return {"title": title,
                    "rows": [[label, message]],
                    "widths": [3400, 6238],
                    "aligns": ["left", "left"]}

        sections = [
            {
                "title": "1. Сводка проверки",
                "header": ["Показатель", "Значение"],
                "rows": summary,
                "widths": [6200, 3438],
                "aligns": ["left", "center"],
            },
        ]

        if container_rows:
            sections.append({
                "title": "2. Пустые контейнеры КЭТ",
                "note": "Пустой контейнер размещён на схеме, но ни один шкаф "
                        "к нему не привязан: все слоты свободны.",
                "header": ["№", "Обозначение", "Тип КЭТ", "Наименование",
                           "Типоразмер", "Слотов", "Свободно"],
                "rows": container_rows,
                "widths": [500, 1400, 1100, 3400, 1200, 1000, 1038],
                "aligns": ["center", "left", "center", "left", "left",
                           "center", "center"],
            })
        else:
            sections.append(empty_section(
                "2. Пустые контейнеры КЭТ", "Пустые контейнеры",
                "не обнаружены — все контейнеры привязаны хотя бы к одному "
                "шкафу"))

        if komplekt_rows:
            sections.append({
                "title": "3. Непривязанные комплекты",
                "note": "Комплект без единой связи: ни защитной "
                        "(комплект → оборудование), ни аналоговой "
                        "(комплект ↔ ТТ/ТН или комплект резервирования).",
                "header": ["№", "Шкаф", "Контейнер", "Комплект", "Вид",
                           "Функции", "ИЭУ"],
                "rows": komplekt_rows,
                "widths": [500, 1200, 1600, 1900, 1000, 1938, 1500],
                "aligns": ["center", "left", "left", "left", "center",
                           "left", "left"],
                "font_size": 10,
            })
        else:
            sections.append(empty_section(
                "3. Непривязанные комплекты", "Непривязанные комплекты",
                "не обнаружены — у каждого комплекта есть хотя бы одна "
                "связь"))

        if element_rows:
            sections.append({
                "title": "4. Элементы со свободными выводами",
                "note": "Свободный вывод — вывод элемента, к которому не "
                        "подходит ни один провод. Шины, узлы и уголки "
                        "проверяются целиком: у них свободные отпайки — "
                        "норма, замечание выдаётся, только если у элемента "
                        "нет ни одного соединения.",
                "header": ["№", "Обозначение", "Тип элемента",
                           "Свободные выводы", "Подключено"],
                "rows": element_rows,
                "widths": [500, 1500, 3000, 3438, 1200],
                "aligns": ["center", "left", "left", "left", "center"],
                "font_size": 10,
            })
        else:
            sections.append(empty_section(
                "4. Элементы со свободными выводами", "Свободные выводы",
                "не обнаружены — к каждому проверяемому выводу подходит "
                "провод"))

        sections.append({
            "title": "5. Выводы, которые не проверяются",
            "header": ["Вывод", "Почему не проверяется"],
            "rows": [
                ["Нейтраль (N) трансформаторов, автотрансформаторов, "
                 "расщеплённых и трёхобмоточных",
                 "узел подключения без нарисованного вывода — провод к "
                 "нейтрали на схеме не подводят"],
                ["Второй вывод (низ) фильтра присоединения — ФП",
                 "подключается по месту, на схеме часто остаётся свободным"],
                ["Вход (in) ЛЭП",
                 "уходящая сторона линии: стрелка уходит за пределы схемы "
                 "подстанции, узел на этой стороне свободен по определению"],
                ["Свободные отпайки шин, узлов и уголков",
                 "проверяются только целиком: элемент попадает в отчёт, "
                 "если у него нет ни одного соединения"],
            ],
            "widths": [4000, 5638],
            "aligns": ["left", "left"],
            "font_size": 10,
        })

        return {
            "title": "Отчёт по непривязанным элементам",
            "subtitle": [
                "Сформирован: {}".format(
                    datetime.now().strftime("%d.%m.%Y %H:%M")),
                "Источник: текущая схема редактора",
            ],
            "sections": sections,
            "footer": [
                "Проверяются выводы элементов первичной схемы: свободным "
                "считается вывод, к которому не подходит ни один провод. "
                "Комплект считается непривязанным, если у него нет ни "
                "защитных, ни аналоговых связей.",
            ],
        }

