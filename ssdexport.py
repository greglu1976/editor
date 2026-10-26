"""Экспорт схемы редактора в SSD (System Specification Description) по МЭК 61850-6.

SSD — это SCL-документ, в котором описана только силовая часть подстанции:
Substation → VoltageLevel → Bay с оборудованием (ConductingEquipment,
PowerTransformer), узлами (ConnectivityNode) и выводами (Terminal).
Файл соответствует схеме SCL «2007B4» (МЭК 61850-6:2009/AMD1:2018, изд. 2.1).

Как элементы схемы переводятся в SCL:

* выключатели, разъединители, ТТ, ТН, ОПН, реакторы и т. п. —
  ConductingEquipment с типом из tCommonConductingEquipmentEnum;
  для типов, которых в стандарте нет (ВЧЗ, ФП, предохранитель),
  используется расширение вида «E…», предусмотренное самим SCL;
* трансформаторы (в т. ч. с расщеплением и трёхобмоточные) — PowerTransformer
  с обмотками TransformerWinding; вывод нейтрали — NeutralPoint;
* шины, узлы, уголки и заземления — ConnectivityNode: в SCL это точки
  соединения, а не оборудование (у ConductingEquipment не может быть
  больше двух выводов). Имя шины становится именем узла;
* провода — общий ConnectivityNode: все порты, связанные проводами,
  и все порты одной шины попадают в один узел;
* заземляющий разъединитель, подключённый к схеме, получает второй вывод
  на узел «GND»;
* элементы, не участвующие в соединениях, экспортируются без выводов.

Имена элементов сохраняются как есть (tName допускает любые символы, кроме
переводов строк). Если имя пустое или повторяется после нормализации,
к нему добавляется суффикс «_2», «_3» и т. д.
"""

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime

SCL_NAMESPACE = "http://www.iec.ch/61850/2003/SCL"
TOOL_ID = "SchematicEditor"

#: Типы оборудования SCL (tCommonConductingEquipmentEnum, SCL 2007B4).
#: Значения, начинающиеся с «E», — разрешённые стандартом расширения
#: (tExtensionEquipmentEnum: E[A-Z]*, не короче трёх символов).
CONDUCTING_EQUIPMENT_TYPES = {
    "breaker": "CBR",                  # выключатель
    "av_breaker": "CBR",               # автоматический выключатель 0,4 кВ
    "disconnector": "DIS",             # разъединитель
    "grounding_switch": "DIS",         # заземляющий разъединитель
    "voltage_transformer": "VTR",      # трансформатор напряжения
    "current_transformer": "CTR",      # трансформатор тока
    "opn": "SAR",                      # ограничитель перенапряжений
    "coupling_capacitor": "CAP",       # конденсатор связи
    "reactor": "REA",                  # реактор
    "line": "LIN",                     # ЛЭП
    "line_trap": "ELT",                # ВЧ-заградитель (расширение SCL)
    "connection_filter": "ECF",        # фильтр присоединения (расширение SCL)
    "fuse": "EFU",                     # предохранитель (расширение SCL)
}

#: Обмотки трансформатора: (имя обмотки в SCL, имя порта на схеме).
TRANSFORMER_WINDINGS = {
    "transformer": (("HV", "HV"), ("LV", "LV")),
    "split_transformer": (("HV", "HV"), ("LV1", "LV1"), ("LV2", "LV2")),
    "three_winding_transformer": (("HV", "HV"), ("MV", "MV"), ("LV", "LV")),
    "autotransformer": (("HV", "HV"), ("MV", "MV"), ("LV", "LV")),
}

#: Обмотка, к которой относится вывод нейтрали «N».
TRANSFORMER_NEUTRAL_WINDING = {
    "transformer": "HV",
    "split_transformer": "HV",
    "three_winding_transformer": "HV",
    "autotransformer": "MV",
}

#: Уточнение типа трансформатора в атрибуте desc (тип PTR у всех одинаковый).
TRANSFORMER_DESCRIPTIONS = {
    "split_transformer": "Трансформатор с расщеплением обмоток",
    "three_winding_transformer": "Трёхобмоточный трансформатор",
    "autotransformer": "Автотрансформатор",
}

#: Элементы, которые в SSD становятся узлами, а не оборудованием.
JUNCTION_TYPES = ("bus", "node", "corner", "ground")

#: Служебный ключ узла заземления — не совпадает ни с одним node_id схемы.
EARTH_NODE_KEY = "\u0000EARTH"
EARTH_TERMINAL_NAME = "earth"
EARTH_NODE_NAME = "GND"

SINGLE_LINE_TYPES = set(CONDUCTING_EQUIPMENT_TYPES) | set(TRANSFORMER_WINDINGS)

_NAMES_MAX_LENGTH = 64
_NAME_FORBIDDEN = re.compile(r"[\\/]")

ET.register_namespace("", SCL_NAMESPACE)


def _tag(name):
    return "{{{}}}{}".format(SCL_NAMESPACE, name)


class _UnionFind:
    """Система непересекающихся множеств для склейки электрических узлов."""

    def __init__(self):
        self._parent = {}

    def add(self, key):
        if key not in self._parent:
            self._parent[key] = key
        return key

    def find(self, key):
        if key not in self._parent:
            self._parent[key] = key
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, first, second):
        root_a = self.find(first)
        root_b = self.find(second)
        if root_a != root_b:
            self._parent[root_b] = root_a
        return root_a


class _NameAllocator:
    """Выдаёт уникальные имена в пределах одного контейнера SCL."""

    def __init__(self):
        self._used = set()

    def allocate(self, name, fallback):
        base = _clean_name(name, fallback)
        candidate = base
        index = 2
        while candidate.casefold() in self._used:
            candidate = "{}_{}".format(base, index)
            index += 1
        self._used.add(candidate.casefold())
        return candidate


def _clean_name(value, fallback):
    """Приводит имя к безопасному виду: без переводов строк и «/»."""
    text = (value or "").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = _NAME_FORBIDDEN.sub("-", text)
    if len(text) > _NAMES_MAX_LENGTH:
        text = text[:_NAMES_MAX_LENGTH].rstrip()
    return text or fallback


def _format_number(value):
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return "{:.4f}".format(number).rstrip("0").rstrip(".")


def _resolve_port(element, port_name, node_id):
    """Имя порта: прямое совпадение, затем поиск по node_id (старые файлы)."""
    if port_name in element.ports:
        return port_name
    if node_id:
        for name, port in element.ports.items():
            if port.get("node_id") == node_id:
                return name
    return None


def suggest_options(underlay_path=None):
    """Параметры по умолчанию для диалога экспорта.

    Имя подстанции и напряжение берутся из имени файла подложки
    (например, «ПС 500 кВ Дорохово.pdf» → «ПС 500 кВ Дорохово», 500 кВ).
    """
    stem = os.path.splitext(os.path.basename(underlay_path or ""))[0]
    stem = re.sub(r"\s+", " ", stem).strip()

    voltage = None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:кВ|КВ|kB|kV|KB)", stem)
    if match:
        try:
            voltage = float(match.group(1).replace(",", "."))
        except ValueError:
            voltage = None

    substation = stem[:_NAMES_MAX_LENGTH].rstrip() if stem else "ПС1"
    return {
        "substation": substation or "ПС1",
        "voltage_level": "РУ1",
        "bay": "Отсек1",
        "voltage_kv": voltage,
        "frequency_hz": 50,
    }


def safe_file_name(name):
    """Имя файла из имени подстанции (без запрещённых в Windows символов)."""
    text = re.sub(r'[\\/:*?"<>|]+', "-", (name or "").strip())
    return text.rstrip(". ") or "substation"


def build_ssd(elements, connections, substation="ПС1", voltage_level="РУ1",
              bay="Отсек1", voltage_kv=None, frequency_hz=50, header_id=None):
    """Строит SCL-документ SSD и возвращает (ElementTree, статистика)."""
    stats = {"equipment": 0, "connectivity_nodes": 0, "terminals": 0,
             "warnings": []}
    warnings = stats["warnings"]

    items = dict(elements)
    sub_name = _clean_name(substation, "SUB1")
    vl_name = _clean_name(voltage_level, "VL1")
    bay_name = _clean_name(bay, "BAY1")

    # ---- индексы портов -------------------------------------------------
    port_nodes = {}
    for element in items.values():
        for port_name, port in element.ports.items():
            key = port.get("node_id") or "N_{}_{}".format(element.id, port_name)
            port_nodes[(element.id, port_name)] = key

    uf = _UnionFind()
    for key in port_nodes.values():
        uf.add(key)

    # ---- провода: связанные порты — один узел --------------------------
    used_ports = set()
    for connection in connections:
        # В рабочей схеме связи хранятся как from/to, в JSON — как element_from/element_to.
        element_from = items.get(connection.get("element_from")
                                 or connection.get("from"))
        element_to = items.get(connection.get("element_to")
                               or connection.get("to"))
        if element_from is None or element_to is None:
            warnings.append("Провод ссылается на отсутствующий элемент — пропущен.")
            continue

        port_from = _resolve_port(element_from, connection.get("port_from"),
                                  connection.get("node_from"))
        port_to = _resolve_port(element_to, connection.get("port_to"),
                                connection.get("node_to"))
        if not port_from or not port_to:
            warnings.append("Не найден порт провода «{}» — «{}».".format(
                getattr(element_from, "name", element_from.id),
                getattr(element_to, "name", element_to.id)))
            continue

        uf.union(port_nodes[(element_from.id, port_from)],
                 port_nodes[(element_to.id, port_to)])
        used_ports.add((element_from.id, port_from))
        used_ports.add((element_to.id, port_to))

    # ---- шины, узлы, уголки и заземления — точки соединения -------------
    junctions = [el for el in items.values() if el.type in JUNCTION_TYPES]
    for element in junctions:
        keys = [port_nodes[(element.id, name)] for name in element.ports]
        if not keys:
            continue
        for key in keys[1:]:
            uf.union(keys[0], key)
        if element.type == "ground":
            uf.add(EARTH_NODE_KEY)
            uf.union(keys[0], EARTH_NODE_KEY)

    needs_earth = any(el.type in ("ground", "grounding_switch")
                      for el in items.values())
    if needs_earth:
        uf.add(EARTH_NODE_KEY)

    junction_by_root = {}
    for element in junctions:
        if not element.ports:
            continue
        first_port = next(iter(element.ports))
        root = uf.find(port_nodes[(element.id, first_port)])
        junction_by_root.setdefault(root, []).append(element)

    # ---- оборудование ---------------------------------------------------
    equipment = []
    for element in items.values():
        if element.type in JUNCTION_TYPES:
            continue
        if element.type in ("cabinet", "container"):
            # шкафы РЗА, IED и контейнеры КЭТ — не силовое оборудование,
            # в SSD не входят
            continue
        if element.type not in SINGLE_LINE_TYPES:
            warnings.append("Элемент «{}» типа «{}» не поддерживается и пропущен.".format(
                getattr(element, "name", "") or element.id, element.type))
            continue
        equipment.append(element)
    equipment.sort(key=lambda el: (float(el.y), float(el.x), str(el.id)))

    allocator = _NameAllocator()
    names = {}
    for index, element in enumerate(equipment, 1):
        names[element.id] = allocator.allocate(element.name, "EL{}".format(index))

    # ---- выводы и узлы, на которые они ссылаются ------------------------
    connected_ids = {element_id for element_id, _ in used_ports}
    references = []
    for element in equipment:
        for port_name in element.ports:
            if (element.id, port_name) in used_ports:
                references.append(uf.find(port_nodes[(element.id, port_name)]))
        if element.type == "grounding_switch" and element.id in connected_ids:
            references.append(uf.find(EARTH_NODE_KEY))

    connectivity_nodes = {}
    node_order = []
    fallback_index = 0
    earth_root = uf.find(EARTH_NODE_KEY) if needs_earth else None
    for root in references:
        if root in connectivity_nodes:
            continue
        label = _component_label(root, junction_by_root)
        if label is None and root == earth_root:
            label = EARTH_NODE_NAME
        if label is None:
            fallback_index += 1
            label = "CN{}".format(fallback_index)
        name = allocator.allocate(label, "CN{}".format(fallback_index + 1))
        connectivity_nodes[root] = {
            "name": name,
            "pathName": "{}/{}/{}/{}".format(sub_name, vl_name, bay_name, name),
        }
        node_order.append(root)

    # ---- сборка XML -----------------------------------------------------
    scl = ET.Element(_tag("SCL"), {
        "version": "2007",
        "revision": "B",
        "release": "4",
    })
    ET.SubElement(scl, _tag("Header"), {
        "id": header_id or "{}-{}".format(sub_name,
                                          datetime.now().strftime("%Y%m%dT%H%M%S")),
        "version": "1.0",
        "revision": "1",
        "toolID": TOOL_ID,
    })

    substation_el = ET.SubElement(scl, _tag("Substation"), {"name": sub_name})
    vl_attrs = {"name": vl_name}
    if frequency_hz:
        vl_attrs["nomFreq"] = _format_number(frequency_hz)
    vl_attrs["numPhases"] = "3"
    vl_el = ET.SubElement(substation_el, _tag("VoltageLevel"), vl_attrs)

    if voltage_kv:
        voltage_el = ET.SubElement(vl_el, _tag("Voltage"),
                                   {"unit": "V", "multiplier": "k"})
        voltage_el.text = _format_number(voltage_kv)

    bay_el = ET.SubElement(vl_el, _tag("Bay"), {"name": bay_name})

    def ref(root):
        return connectivity_nodes[root]

    def add_terminal(parent, port_name, root):
        node = ref(root)
        ET.SubElement(parent, _tag("Terminal"), {
            "name": port_name,
            "connectivityNode": node["pathName"],
            "cNodeName": node["name"],
            "substationName": sub_name,
            "voltageLevelName": vl_name,
            "bayName": bay_name,
        })
        stats["terminals"] += 1

    def add_transformer(element):
        name = names[element.id]
        transformer = ET.SubElement(bay_el, _tag("PowerTransformer"),
                                    {"name": name, "type": "PTR"})
        description = TRANSFORMER_DESCRIPTIONS.get(element.type)
        if (element.name or "").strip() != name:
            description = (element.name or "").strip()
        if description:
            transformer.set("desc", description)
        neutral_winding = TRANSFORMER_NEUTRAL_WINDING.get(element.type)
        for winding_name, port_name in TRANSFORMER_WINDINGS[element.type]:
            winding = ET.SubElement(transformer, _tag("TransformerWinding"),
                                    {"name": winding_name, "type": "PTW"})
            if (element.id, port_name) in used_ports:
                add_terminal(winding, port_name,
                             uf.find(port_nodes[(element.id, port_name)]))
            if winding_name == neutral_winding and (element.id, "N") in used_ports:
                node = ref(uf.find(port_nodes[(element.id, "N")]))
                ET.SubElement(winding, _tag("NeutralPoint"), {
                    "name": "N",
                    "connectivityNode": node["pathName"],
                    "cNodeName": node["name"],
                    "substationName": sub_name,
                    "voltageLevelName": vl_name,
                    "bayName": bay_name,
                })
                stats["terminals"] += 1
        stats["equipment"] += 1

    def add_conducting_equipment(element):
        equipment_el = ET.SubElement(bay_el, _tag("ConductingEquipment"), {
            "name": names[element.id],
            "type": CONDUCTING_EQUIPMENT_TYPES[element.type],
        })
        if (element.name or "").strip() != names[element.id] and (element.name or "").strip():
            equipment_el.set("desc", (element.name or "").strip())
        for port_name in element.ports:
            if (element.id, port_name) not in used_ports:
                continue
            add_terminal(equipment_el, port_name,
                         uf.find(port_nodes[(element.id, port_name)]))
        if element.type == "grounding_switch" and element.id in connected_ids:
            add_terminal(equipment_el, EARTH_TERMINAL_NAME, earth_root)
        stats["equipment"] += 1

    # В схеме SCL сначала идут все PowerTransformer, затем ConductingEquipment
    # и только потом ConnectivityNode — порядок задан последовательностью tBay.
    for element in equipment:
        if element.type in TRANSFORMER_WINDINGS:
            add_transformer(element)
    for element in equipment:
        if element.type not in TRANSFORMER_WINDINGS:
            add_conducting_equipment(element)

    for root in node_order:
        node = ref(root)
        ET.SubElement(bay_el, _tag("ConnectivityNode"), {
            "name": node["name"],
            "pathName": node["pathName"],
        })
    stats["connectivity_nodes"] = len(node_order)

    return ET.ElementTree(scl), stats


def _component_label(root, junction_by_root):
    """Имя узла по элементу-соединителю: шина → уголок → узел."""
    elements = junction_by_root.get(root, [])
    for kind in ("bus", "corner", "node"):
        candidates = [el for el in elements
                      if el.type == kind and (getattr(el, "name", "") or "").strip()]
        if candidates:
            candidates.sort(key=lambda el: (float(el.y), float(el.x), str(el.id)))
            return candidates[0].name
    return None


def _indent(element, level=0):
    """Аккуратные отступы: ElementTree.indent появился только в Python 3.9."""
    indent = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indent + "  "
        for child in element:
            _indent(child, level + 1)
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = indent
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indent


def export_ssd(elements, connections, filepath, substation="ПС1",
               voltage_level="РУ1", bay="Отсек1", voltage_kv=None,
               frequency_hz=50, header_id=None):
    """Строит SSD и сохраняет его в файл. Возвращает статистику экспорта."""
    tree, stats = build_ssd(elements, connections, substation=substation,
                            voltage_level=voltage_level, bay=bay,
                            voltage_kv=voltage_kv, frequency_hz=frequency_hz,
                            header_id=header_id)
    root = tree.getroot()
    _indent(root)
    with open(filepath, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")
    return stats
