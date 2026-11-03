# -*- coding: utf-8 -*-
"""Нормализованная модель каталога РЗА.

Иерархия хранения::

    Container (КЭТ / контейнер)
      └── Cabinet (шкаф)
            └── Kit (комплект)
                  └── Ied (устройство / ИЭУ)

Данные ниже — dataclass-модель, не зависящая от формата исходного JSON.
Обратная ссылка ``cabinet_id`` у комплекта и ``kit_id`` у ИЭУ позволяют
собирать плоские выборки для SQLite и отчётов, не теряя вложенность.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

#: Версия нормализованного JSON/SQLite. Меняется при несовместимом изменении.
SCHEMA_VERSION = 1


class IedType(str, Enum):
    """Типы устройств. Значение — как в исходных данных."""

    MP_RZA = "МП РЗА"
    PA = "ПА"
    ARNT = "АРНТ"
    OTHER = "OTHER"


class KitKind(str, Enum):
    """Вид комплекта."""

    TYPICAL = "typical"
    CUSTOM = "custom"
    OTHER = "other"


class CabinetGroup(str, Enum):
    """Группа шкафа (для навигации, необязательно)."""

    T_AT = "Т/АТ"
    LEP = "ЛЭП"
    SSH = "СШ"
    SKRM = "СКРМ"
    PA = "ПА"
    OTHER = "Прочие"


class ContainerOrigin(str, Enum):
    """Откуда взялся контейнер в итоговом каталоге."""

    CUSTOM = "custom"
    OVERRIDE = "override"


# ---------------------------------------------------------------------------
# Ссылочные значения
# ---------------------------------------------------------------------------


@dataclass
class FunctionRef:
    """Ссылка на функцию РЗА/ПА.

    ``code`` — канонический код, ``title`` — необязательное пояснение.
    """

    code: str
    title: Optional[str] = None


@dataclass
class TagRef:
    """Метка (тег) каталога."""

    code: str


@dataclass
class StandardRef:
    """Ссылка на стандарт.

    ``label`` сохранён отдельно от ``title``: в исходных данных поле
    ``standard`` иногда содержит короткую подпись («СТО (проект, ред. 2)»),
    а не полное наименование.
    """

    key: str
    title: Optional[str] = None
    edition: Optional[str] = None
    document: Optional[str] = None
    label: Optional[str] = None


# ---------------------------------------------------------------------------
# Нижний уровень: ИЭУ
# ---------------------------------------------------------------------------


@dataclass
class Ied:
    """Устройство (ИЭУ) внутри комплекта."""

    id: str
    name: str
    type: str
    description: Optional[str] = None
    kit_id: Optional[str] = None  # обратная ссылка


# ---------------------------------------------------------------------------
# Испытательные блоки и аналоговые входы
# ---------------------------------------------------------------------------


@dataclass
class CircuitGroup:
    """Группа цепей испытательных блоков (напряжение или ток)."""

    count: int = 0
    circuits: list[str] = field(default_factory=list)


@dataclass
class TestBlockEntry:
    """Строка перечня испытательных блоков."""

    name: str
    circuits: str
    count: str
    note: Optional[str] = None


@dataclass
class TestBlocks:
    """Унифицированное представление ``test_blocks`` и ``test_block_list``."""

    voltage: CircuitGroup = field(default_factory=CircuitGroup)
    current: CircuitGroup = field(default_factory=CircuitGroup)
    blocks: list[TestBlockEntry] = field(default_factory=list)


@dataclass
class AnalogInput:
    """Аналоговый вход из таблицы испытательных блоков."""

    block: str
    signals: str
    contacts: str
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Комплект
# ---------------------------------------------------------------------------


@dataclass
class Kit:
    """Комплект РЗА — подключаемая единица шкафа."""

    id: str
    name: str
    kind: str
    type: str
    description: Optional[str] = None
    functions: list[FunctionRef] = field(default_factory=list)
    ieds: list[Ied] = field(default_factory=list)
    test_blocks: TestBlocks = field(default_factory=TestBlocks)
    analog_inputs: list[AnalogInput] = field(default_factory=list)
    tags: list[TagRef] = field(default_factory=list)
    cabinet_id: Optional[str] = None  # обратная ссылка
    has_ied: bool = False
    source: Optional[str] = None
    #: Поля, не попавшие в явные атрибуты (описательные поля СТО и т. п.).
    extensions: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Шкаф
# ---------------------------------------------------------------------------


@dataclass
class Cabinet:
    """Шкаф внутри контейнера."""

    id: str
    key: str
    code: str
    name: str
    group: str
    source: str = "cabinet_entry"
    kits: list[Kit] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Контейнер
# ---------------------------------------------------------------------------


@dataclass
class Container:
    """Контейнер (КЭТ) — верхний уровень каталога."""

    id: str
    key: str
    code: str
    name: str
    title: str
    description: str
    group: str
    voltage: str
    protected: str
    controlled: list[str] = field(default_factory=list)
    its_functions: list[FunctionRef] = field(default_factory=list)
    applicability: Optional[str] = None
    architecture: Optional[str] = None
    source: Optional[str] = None
    goose: bool = False
    tags: list[TagRef] = field(default_factory=list)
    cabinets: list[Cabinet] = field(default_factory=list)
    standard: Optional[StandardRef] = None
    standard_key: Optional[str] = None
    origin: str = ContainerOrigin.CUSTOM.value
    #: Поля, не попавшие в явные атрибуты (размер, состав, примечания и т. п.).
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class RzaCatalog:
    """Корневой объект нормализованного каталога."""

    #: Контейнеры по ключу. Порядок вставки сохраняется.
    containers: dict[str, Container] = field(default_factory=dict)
    #: Удалённые ключи шкафов (в т. ч. встроенных) и КЭТ-контейнеров.
    deleted: set[str] = field(default_factory=set)
    deleted_containers: set[str] = field(default_factory=set)
    standards: dict[str, StandardRef] = field(default_factory=dict)
    functions: dict[str, FunctionRef] = field(default_factory=dict)
