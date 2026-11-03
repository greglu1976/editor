# -*- coding: utf-8 -*-
"""Доменная модель каталога РЗА: классовый подход к хранению данных.

Иерархия предметных классов::

    Container (Контейнер / КЭТ)
      └── Cabinet   (Шкаф) — набирается из комплектов
            └── Kit       (Комплект) — с ИЭУ или без, входные/выходные
                  │                      цепи, аналоговые измерения,
                  │                      испытательные блоки (БИ), прочее
                  └── Ied   (Устройство ИЭУ)

Классы work with dataclasses и конвертируются в нормализованную модель
хранения ``models.py`` (``from_model`` / ``to_model``) и в словари
приложения (``from_dict`` / ``to_dict``), поэтому это объектный интерфейс
к тем же данным в ``catalog.normalized.json``, а не второй источник правды.

Второе действие — заполнение классов из существующей базы:

    from rza_catalog.domain import DomainCatalog

    catalog = DomainCatalog.load()            # шкафы, комплекты, КЭТ из базы
    ket = catalog.container("ket-6-1-ii")     # Контейнер
    ket.write_report("output/КЭТ-6-1-II.docx")  # отчёт Word

"""

from __future__ import annotations

import copy
import json
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from . import models
from .models import (
    Cabinet as CabinetModel,
    Container as ContainerModel,
    FunctionRef,
    Ied as IedModel,
    Kit as KitModel,
    RzaCatalog,
    StandardRef,
    TagRef,
)

#: Подписи видов комплектов (как в каталоге комплектов приложения).
KIND_TITLES = {"typical": "Типовой", "custom": "Нетиповой", "other": "Прочий"}

#: Виды дискретных сигналов комплекта: поле → подпись для отчётов.
SIGNAL_FIELDS = (
    ("io_in", "Входные сигналы"),
    ("io_out", "Выходные сигналы"),
    ("goose_in", "Входные GOOSE"),
    ("goose_out", "Выходные GOOSE"),
)

#: Описательные поля из СТО — живут в ``Kit.details`` / ``Cabinet.details``.
DETAIL_FIELDS = (
    "mp_functions", "its_functions_desc", "power_supply", "ports",
    "connection_scheme", "components", "additional_equipment",
    "parameters", "general_view", "structural_scheme", "schematic",
    "climate", "enclosure", "cooling", "communication", "notes",
)

#: Что умеет менять пользовательская правка типового комплекта.
_OVERRIDABLE_FIELDS = (
    "name", "type", "functions", "desc", "has_ied", "ieds",
    "test_blocks", "test_block_list", "analog_inputs", "tags",
    "io_in", "io_out", "goose_in", "goose_out",
)


def _split_list(value: Any) -> list[str]:
    """«Ua, Ub; Uc» или список → список непустых строк (строки-списки не дробим)."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in re.split(r"[,;\n]+", value)]
    else:
        items = []
        for item in value:
            if isinstance(item, str):
                items.append(item.strip())
            elif item is not None:
                items.extend(_split_list(item))
    return [item for item in items if item]


def _details_of(data: dict[str, Any]) -> dict[str, Any]:
    return {name: copy.deepcopy(data[name]) for name in DETAIL_FIELDS
            if data.get(name) not in (None, "", [], {})}


# ---------------------------------------------------------------------------
# ИЭУ
# ---------------------------------------------------------------------------


@dataclass
class Ied:
    """Устройство (ИЭУ) внутри комплекта."""

    id: str = ""
    name: str = "ИЭУ"
    type: str = "МП РЗА"
    description: str = ""
    kit_id: str = ""

    def label(self) -> str:
        return self.name or "ИЭУ"

    def to_model(self) -> IedModel:
        return IedModel(
            id=self.id, name=self.name, type=self.type,
            description=self.description or None, kit_id=self.kit_id or None,
        )

    @classmethod
    def from_model(cls, model: IedModel) -> Ied:
        return cls(id=model.id, name=model.name, type=model.type,
                   description=model.description or "",
                   kit_id=model.kit_id or "")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type,
                "desc": self.description, "id": self.id, "kit_id": self.kit_id}

    @classmethod
    def from_dict(cls, data: Any) -> Ied:
        if isinstance(data, str):
            data = {"name": data}
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "ИЭУ").strip() or "ИЭУ",
            type=str(data.get("type") or "МП РЗА").strip() or "МП РЗА",
            description=str(data.get("desc") or data.get("description") or ""),
            kit_id=str(data.get("kit_id") or ""),
        )


# ---------------------------------------------------------------------------
# Цепи комплекта: сигналы, аналоговые измерения, испытательные блоки
# ---------------------------------------------------------------------------


@dataclass
class SignalEntry:
    """Дискретная цепь комплекта (вход/выход, GOOSE)."""

    name: str = ""
    code: str = ""
    details: str = ""

    def label(self) -> str:
        text = self.name or "—"
        if self.code:
            text += " [{}]".format(self.code)
        if self.details:
            text += " — {}".format(self.details)
        return text

    def to_model(self) -> models.SignalEntry:
        return models.SignalEntry(name=self.name, code=self.code or None,
                                  details=self.details or None)

    @classmethod
    def from_model(cls, model: models.SignalEntry) -> SignalEntry:
        return cls(name=model.name or "", code=model.code or "",
                   details=model.details or "")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "code": self.code, "details": self.details}

    @classmethod
    def from_dict(cls, data: Any) -> SignalEntry:
        if isinstance(data, str):
            data = {"name": data}
        return cls(name=str(data.get("name") or "").strip(),
                   code=str(data.get("code") or "").strip(),
                   details=str(data.get("details") or "").strip())


@dataclass
class AnalogInput:
    """Аналоговая измерительная цепь из таблицы испытательных блоков."""

    block: str = ""
    signals: str = ""
    contacts: str = ""
    note: str = ""

    def to_model(self) -> models.AnalogInput:
        return models.AnalogInput(block=self.block, signals=self.signals,
                                  contacts=self.contacts, note=self.note or None)

    @classmethod
    def from_model(cls, model: models.AnalogInput) -> AnalogInput:
        return cls(block=model.block or "", signals=model.signals or "",
                   contacts=model.contacts or "", note=model.note or "")

    def to_dict(self) -> dict[str, Any]:
        return {"block": self.block, "signals": self.signals,
                "contacts": self.contacts, "note": self.note}

    @classmethod
    def from_dict(cls, data: Any) -> AnalogInput:
        if isinstance(data, str):
            data = {"signals": data}
        return cls(block=str(data.get("block") or ""),
                   signals=str(data.get("signals") or ""),
                   contacts=str(data.get("contacts") or ""),
                   note=str(data.get("note") or ""))


@dataclass
class CircuitGroup:
    """Группа цепей испытательного блока (напряжение или ток)."""

    count: int = 0
    circuits: list[str] = field(default_factory=list)

    def label(self) -> str:
        if not self.count and not self.circuits:
            return ""
        circuits = ", ".join(self.circuits)
        return "{}{}".format(self.count or len(self.circuits),
                             " ({})".format(circuits) if circuits else "")

    def to_model(self) -> models.CircuitGroup:
        return models.CircuitGroup(count=self.count, circuits=list(self.circuits))

    @classmethod
    def from_model(cls, model: models.CircuitGroup) -> CircuitGroup:
        return cls(count=model.count, circuits=list(model.circuits))

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "circuits": list(self.circuits)}

    @classmethod
    def from_dict(cls, data: Any) -> CircuitGroup:
        data = data if isinstance(data, dict) else {}
        try:
            count = int(data.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        return cls(count=max(0, count), circuits=_split_list(data.get("circuits")))


@dataclass
class TestBlockEntry:
    """Строка перечня испытательных блоков (БИ)."""

    name: str = ""
    circuits: str = ""
    count: str = ""
    note: str = ""

    def label(self) -> str:
        text = self.name or "БИ"
        if self.circuits:
            text += ": " + self.circuits
        if self.count:
            text += " ({})".format(self.count)
        if self.note:
            text += " — " + self.note
        return text

    def to_model(self) -> models.TestBlockEntry:
        return models.TestBlockEntry(name=self.name, circuits=self.circuits,
                                     count=self.count, note=self.note or None)

    @classmethod
    def from_model(cls, model: models.TestBlockEntry) -> TestBlockEntry:
        return cls(name=model.name or "", circuits=model.circuits or "",
                   count=str(model.count or ""), note=model.note or "")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "circuits": self.circuits,
                "count": self.count, "note": self.note}

    @classmethod
    def from_dict(cls, data: Any) -> TestBlockEntry:
        if isinstance(data, str):
            data = {"name": data}
        return cls(name=str(data.get("name") or ""),
                   circuits=str(data.get("circuits") or data.get("spec") or ""),
                   count=str(data.get("count") or ""),
                   note=str(data.get("note") or ""))


@dataclass
class TestBlocks:
    """Испытательные блоки (БИ): группы цепей U/I и построчный перечень."""

    voltage: CircuitGroup = field(default_factory=CircuitGroup)
    current: CircuitGroup = field(default_factory=CircuitGroup)
    blocks: list[TestBlockEntry] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.blocks or self.voltage.count or self.voltage.circuits
                    or self.current.count or self.current.circuits)

    def text(self) -> str:
        """Подпись БИ: построчный перечень, иначе сводка U/I."""
        if self.blocks:
            return "; ".join(entry.label() for entry in self.blocks)
        parts = []
        if self.voltage.count or self.voltage.circuits:
            parts.append("U: {}".format(self.voltage.label()))
        if self.current.count or self.current.circuits:
            parts.append("I: {}".format(self.current.label()))
        return "; ".join(parts)

    def to_model(self) -> models.TestBlocks:
        return models.TestBlocks(
            voltage=self.voltage.to_model(), current=self.current.to_model(),
            blocks=[entry.to_model() for entry in self.blocks],
        )

    @classmethod
    def from_model(cls, model: models.TestBlocks) -> TestBlocks:
        return cls(
            voltage=CircuitGroup.from_model(model.voltage),
            current=CircuitGroup.from_model(model.current),
            blocks=[TestBlockEntry.from_model(entry) for entry in model.blocks],
        )

    def to_dict(self) -> dict[str, Any]:
        return {"voltage": self.voltage.to_dict(),
                "current": self.current.to_dict(),
                "blocks": [entry.to_dict() for entry in self.blocks]}

    @classmethod
    def from_dict(cls, data: Any,
                  block_list: Optional[list[Any]] = None) -> TestBlocks:
        data = data if isinstance(data, dict) else {}
        blocks = data.get("blocks") or block_list or []
        return cls(
            voltage=CircuitGroup.from_dict(data.get("voltage")),
            current=CircuitGroup.from_dict(data.get("current")),
            blocks=[TestBlockEntry.from_dict(entry) for entry in blocks
                    if isinstance(entry, (dict, str))],
        )


# ---------------------------------------------------------------------------
# Комплект
# ---------------------------------------------------------------------------


@dataclass
class Kit:
    """Комплект РЗА — подключаемая единица шкафа.

    Состав данных:

    * ИЭУ: ``has_ied`` («с ИЭУ» / «без ИЭУ») и список ``ieds``;
    * входные цепи: ``io_in`` (дискретные), ``goose_in``, ``analog_inputs``;
    * выходные цепи: ``io_out`` (дискретные) и ``goose_out``;
    * БИ: ``test_blocks`` (группы напряжения/тока + перечень);
    * прочее: ``functions``, ``tags``, тип, описание, описательные поля СТО
      (``details``) и всё остальное (``extensions``).
    """

    id: str = ""
    name: str = "Комплект"
    kind: str = "typical"
    type: str = "МП РЗА"
    description: str = ""
    functions: list[str] = field(default_factory=list)
    has_ied: bool = False
    ieds: list[Ied] = field(default_factory=list)
    io_in: list[SignalEntry] = field(default_factory=list)
    io_out: list[SignalEntry] = field(default_factory=list)
    goose_in: list[SignalEntry] = field(default_factory=list)
    goose_out: list[SignalEntry] = field(default_factory=list)
    analog_inputs: list[AnalogInput] = field(default_factory=list)
    test_blocks: TestBlocks = field(default_factory=TestBlocks)
    tags: list[str] = field(default_factory=list)
    cabinet_id: str = ""
    cabinet_index: int = 0
    source: str = ""
    #: Ключ шкафа-носителя в каталоге шкафов (для типовых комплектов).
    cabinet_key: str = ""
    #: Описательные поля СТО (mp_functions, ports, components, …).
    details: dict[str, Any] = field(default_factory=dict)
    #: Прочие поля, не ставшие явными атрибутами.
    extensions: dict[str, Any] = field(default_factory=dict)

    # ---------- классификация и сводка ----------

    def is_typical(self) -> bool:
        return self.kind == "typical"

    def kind_title(self) -> str:
        return KIND_TITLES.get(self.kind, "Нетиповой")

    def ied_count(self) -> int:
        """Число ИЭУ с учётом признака «с ИЭУ / без ИЭУ»."""
        return len(self.ieds) if self.has_ied else 0

    def signal_count(self, direction: str) -> int:
        return len(getattr(self, direction, []))

    def signals_text(self, direction: str) -> str:
        return "; ".join(row.label() for row in getattr(self, direction, []))

    def has_analog(self) -> bool:
        return bool(self.analog_inputs)

    def analog_text(self) -> str:
        parts = []
        for analog in self.analog_inputs:
            text = analog.signals or "—"
            if analog.contacts:
                text += " ({})".format(analog.contacts)
            if analog.note:
                text += " — {}".format(analog.note)
            parts.append("{}: {}".format(analog.block, text) if analog.block
                         else text)
        return "; ".join(parts)

    def has_test_blocks(self) -> bool:
        return not self.test_blocks.is_empty()

    def test_blocks_text(self) -> str:
        return self.test_blocks.text()

    def functions_text(self) -> str:
        return ", ".join(self.functions) or "—"

    def ieds_text(self) -> str:
        if not self.has_ied:
            return "—"
        return ", ".join(ied.label() for ied in self.ieds) or "—"

    def app_key(self) -> str:
        """Ключ комплекта в каталоге комплектов (как в ``komplekts.py``).

        Комплект шкафа: ``typ:<ключ шкафа>:<номер>`` для типового и
        ``cab:<ключ шкафа>:<номер>`` для нетипового; самостоятельные
        комплекты сохраняют свой ``id``.
        """
        if self.cabinet_id:
            prefix = "typ" if self.kind == "typical" else "cab"
            return "{}:{}:{}".format(prefix, self.cabinet_id, self.cabinet_index)
        return self.id

    # ---------- изменение ----------

    def add_ied(self, ied: Ied) -> None:
        """Добавить ИЭУ — комплект становится «с ИЭУ»."""
        ied.kit_id = self.id
        self.ieds.append(ied)
        self.has_ied = True

    def remove_ied(self, ied_id: str) -> bool:
        for i, ied in enumerate(self.ieds):
            if ied.name == ied_id or ied.id == ied_id:
                self.ieds.pop(i)
                self.has_ied = bool(self.ieds)
                return True
        return False

    def add_signal(self, signal: SignalEntry, direction: str = "io_in") -> None:
        """Направить сигнал во входные или выходные цепи комплекта."""
        labels = dict(SIGNAL_FIELDS)
        if direction not in labels:
            raise ValueError("Неизвестное направление цепей: {!r}".format(direction))
        getattr(self, direction).append(signal)

    def apply_override(self, override: dict[str, Any]) -> None:
        """Наложить пользовательскую правку комплекта (формат каталога).

        Меняются только поля комплекта; ссылка на шкаф остаётся каталожной.
        """
        if not isinstance(override, dict):
            return
        for name in _OVERRIDABLE_FIELDS:
            if name not in override:
                continue
            value = override[name]
            if name == "desc":
                self.description = str(value or "")
            elif name == "functions":
                self.functions = _split_list(value)
            elif name == "has_ied":
                self.has_ied = bool(value)
            elif name == "ieds":
                self.ieds = [Ied.from_dict(ied) for ied in value or []]
            elif name in ("io_in", "io_out", "goose_in", "goose_out"):
                setattr(self, name,
                        [SignalEntry.from_dict(row) for row in value or []])
            elif name == "analog_inputs":
                self.analog_inputs = [AnalogInput.from_dict(row)
                                      for row in value or []]
            elif name == "test_blocks":
                blocks = value if isinstance(value, dict) else {}
                block_list = (blocks.get("blocks")
                              if blocks.get("blocks") is not None
                              else override.get("test_block_list"))
                self.test_blocks = TestBlocks.from_dict(blocks, block_list)
            elif name == "test_block_list":
                if "test_blocks" not in override:
                    self.test_blocks = replace(
                        self.test_blocks,
                        blocks=[TestBlockEntry.from_dict(row)
                                for row in value or []])
            elif name == "tags":
                self.tags = _split_list(value)
            else:
                setattr(self, name, copy.deepcopy(value))
        for name in DETAIL_FIELDS:
            if name in override:
                value = override[name]
                if value in (None, "", [], {}):
                    self.details.pop(name, None)
                else:
                    self.details[name] = copy.deepcopy(value)

    # ---------- конвертация ----------

    _EXPLICIT = ("id", "name", "kind", "type", "description", "functions",
                 "has_ied", "ieds", "io_in", "io_out", "goose_in", "goose_out",
                 "analog_inputs", "test_blocks", "tags", "cabinet_id",
                 "cabinet_index", "source", "cabinet_key", "details", "extra")

    def to_model(self) -> KitModel:
        extensions = copy.deepcopy(self.extensions)
        if self.details:
            extensions.update(copy.deepcopy(self.details))
        return KitModel(
            id=self.id, name=self.name, kind=self.kind, type=self.type,
            description=self.description or None,
            functions=[FunctionRef(code=code) for code in self.functions],
            ieds=[ied.to_model() for ied in self.ieds],
            test_blocks=self.test_blocks.to_model(),
            analog_inputs=[analog.to_model() for analog in self.analog_inputs],
            io_in=[row.to_model() for row in self.io_in],
            io_out=[row.to_model() for row in self.io_out],
            goose_in=[row.to_model() for row in self.goose_in],
            goose_out=[row.to_model() for row in self.goose_out],
            tags=[TagRef(code=code) for code in self.tags],
            cabinet_id=self.cabinet_id or None,
            has_ied=self.has_ied, source=self.source or None,
            extensions=extensions,
        )

    @classmethod
    def from_model(cls, model: KitModel) -> Kit:
        extensions = copy.deepcopy(model.extensions or {})
        details = {name: extensions.pop(name) for name in DETAIL_FIELDS
                   if extensions.get(name) not in (None, "", [], {})}
        return cls(
            id=model.id, name=model.name, kind=model.kind, type=model.type,
            description=model.description or "",
            functions=[function.code for function in model.functions],
            has_ied=bool(model.has_ied),
            ieds=[Ied.from_model(ied) for ied in model.ieds],
            io_in=[SignalEntry.from_model(row) for row in model.io_in],
            io_out=[SignalEntry.from_model(row) for row in model.io_out],
            goose_in=[SignalEntry.from_model(row) for row in model.goose_in],
            goose_out=[SignalEntry.from_model(row) for row in model.goose_out],
            analog_inputs=[AnalogInput.from_model(row)
                           for row in model.analog_inputs],
            test_blocks=TestBlocks.from_model(model.test_blocks),
            tags=[tag.code for tag in model.tags],
            cabinet_id=model.cabinet_id or "",
            source=model.source or "",
            details=details, extensions=extensions,
        )

    def to_dict(self) -> dict[str, Any]:
        """Словарь комплекта в формате каталога комплектов."""
        result: dict[str, Any] = {
            "id": self.id,
            "key": self.app_key() or self.id,
            "kind": self.kind,
            "name": self.name,
            "type": self.type,
            "desc": self.description,
            "functions": list(self.functions),
            "has_ied": self.has_ied,
            "ieds": [ied.to_dict() for ied in self.ieds],
            "io_in": [row.to_dict() for row in self.io_in],
            "io_out": [row.to_dict() for row in self.io_out],
            "goose_in": [row.to_dict() for row in self.goose_in],
            "goose_out": [row.to_dict() for row in self.goose_out],
            "analog_inputs": [row.to_dict() for row in self.analog_inputs],
            "test_blocks": self.test_blocks.to_dict(),
            "tags": list(self.tags),
            "cabinet_id": self.cabinet_id,
            "cabinet_key": self.cabinet_id,
            "cabinet_index": self.cabinet_index,
            "source": self.source,
            "details": copy.deepcopy(self.details),
            "extra": copy.deepcopy(self.extensions),
        }
        for name, value in self.details.items():
            result.setdefault(name, value)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Kit:
        """Комплект из словаря (формат каталога или дайджест домена)."""
        test_blocks_data = dict(data.get("test_blocks") or {})
        if not test_blocks_data.get("blocks") and data.get("test_block_list"):
            test_blocks_data["blocks"] = data["test_block_list"]
        extensions = {
            name: copy.deepcopy(value) for name, value in data.items()
            if name not in cls._EXPLICIT and name not in DETAIL_FIELDS
            and name not in ("key", "test_block_list", "description")
            and value not in (None, "", [], {})
        }
        extensions.update(copy.deepcopy(data.get("extra") or {}))
        return cls(
            id=str(data.get("id") or data.get("key") or ""),
            name=str(data.get("name") or "Комплект").strip() or "Комплект",
            kind=str(data.get("kind") or "typical"),
            type=str(data.get("type") or "МП РЗА").strip() or "МП РЗА",
            description=str(data.get("desc") or data.get("description") or ""),
            functions=_split_list(data.get("functions")),
            has_ied=bool(data.get("has_ied", data.get("ieds"))),
            ieds=[Ied.from_dict(ied) for ied in data.get("ieds") or []],
            io_in=[SignalEntry.from_dict(row) for row in data.get("io_in") or []],
            io_out=[SignalEntry.from_dict(row) for row in data.get("io_out") or []],
            goose_in=[SignalEntry.from_dict(row)
                      for row in data.get("goose_in") or []],
            goose_out=[SignalEntry.from_dict(row)
                       for row in data.get("goose_out") or []],
            analog_inputs=[AnalogInput.from_dict(row)
                           for row in data.get("analog_inputs") or []],
            test_blocks=TestBlocks.from_dict(test_blocks_data),
            tags=[str(tag) for tag in _split_list(data.get("tags"))],
            cabinet_id=str(data.get("cabinet_id") or data.get("cabinet_key") or ""),
            cabinet_index=int(data.get("cabinet_index") or 0),
            source=str(data.get("source") or ""),
            details=_details_of(data) or copy.deepcopy(data.get("details") or {}),
            extensions=extensions,
        )


# ---------------------------------------------------------------------------
# Шкаф
# ---------------------------------------------------------------------------


@dataclass
class Cabinet:
    """Шкаф РЗА — набирается из комплектов."""

    id: str = ""
    key: str = ""
    code: str = ""
    name: str = ""
    kind: str = "typical"
    group: str = "Прочие"
    description: str = ""
    voltage: str = ""
    protected: str = ""
    controlled: list[str] = field(default_factory=list)
    its_functions: list[str] = field(default_factory=list)
    applicability: str = ""
    architecture: str = ""
    source: str = ""
    goose: bool = False
    tags: list[str] = field(default_factory=list)
    standard_key: str = ""
    #: Описательные поля из СТО (mp_functions, ports, …).
    details: dict[str, Any] = field(default_factory=dict)
    #: Прочие поля без явного атрибута.
    extensions: dict[str, Any] = field(default_factory=dict)
    kits: list[Kit] = field(default_factory=list)

    # ---------- комплекты ----------

    def add_kit(self, kit: Kit) -> None:
        """Поставить комплект в шкаф: обратная ссылка и порядковый номер."""
        kit.cabinet_id = self.key
        kit.cabinet_index = len(self.kits)
        if not kit.name:
            kit.name = "Комплект {}".format(len(self.kits) + 1)
        self.kits.append(kit)

    def remove_kit(self, kit_id: str) -> bool:
        for i, kit in enumerate(self.kits):
            if kit.id == kit_id or kit.app_key() == kit_id:
                self.kits.pop(i)
                for index, remaining in enumerate(self.kits):
                    remaining.cabinet_index = index
                return True
        return False

    def kit(self, index: int) -> Optional[Kit]:
        if 0 <= index < len(self.kits):
            return self.kits[index]
        return None

    # ---------- вид и сводка ----------

    def is_typical(self) -> bool:
        """Шкаф типовой, только если все его комплекты типовые."""
        if not self.kits:
            return bool(self.standard_key) or self.kind == "typical"
        return all(kit.kind == "typical" for kit in self.kits)

    def kind_title(self) -> str:
        return "Типовой" if self.is_typical() else "Нетиповой"

    def kit_count(self) -> int:
        return len(self.kits)

    def ied_count(self) -> int:
        return sum(kit.ied_count() for kit in self.kits)

    def has_ied(self) -> bool:
        """Есть ли в шкафу комплекты с ИЭУ."""
        return any(kit.has_ied for kit in self.kits)

    def signals_total(self, direction: str) -> int:
        return sum(kit.signal_count(direction) for kit in self.kits)

    def test_blocks_total(self) -> int:
        return sum(1 for kit in self.kits if kit.has_test_blocks())

    # ---------- конвертация ----------

    def to_model(self) -> CabinetModel:
        return CabinetModel(
            id=self.id or self.key, key=self.key, code=self.code,
            name=self.name, group=self.group,
            source=self.source or "cabinet_entry",
            kits=[kit.to_model() for kit in self.kits],
            extensions=copy.deepcopy(self.extensions),
        )

    @classmethod
    def from_app_dict(cls, data: dict[str, Any]) -> Cabinet:
        """Шкаф из словаря каталога шкафов (``cabs.py``)."""
        cabinet = cls(
            id=str(data.get("key") or data.get("id") or ""),
            key=str(data.get("key") or data.get("id") or ""),
            code=str(data.get("code") or ""),
            name=str(data.get("name") or data.get("title") or ""),
            kind=str(data.get("kind") or "typical"),
            group=str(data.get("group") or "Прочие"),
            description=str(data.get("description") or data.get("title") or ""),
            voltage=str(data.get("voltage") or ""),
            protected=str(data.get("protected") or ""),
            controlled=[str(x) for x in data.get("controlled") or []],
            its_functions=_split_list(data.get("its_functions")),
            applicability=str(data.get("applicability") or ""),
            architecture=str(data.get("architecture") or ""),
            source=str(data.get("source") or ""),
            goose=bool(data.get("goose")),
            tags=[str(tag) for tag in _split_list(data.get("tags"))],
            standard_key=str(data.get("standard_key") or ""),
            details=_details_of(data),
            extensions={
                name: copy.deepcopy(value)
                for name, value in data.items()
                if name not in _KNOWN_CABINET_FIELDS
                and value not in (None, "", [], {})
            },
        )
        for kit_data in data.get("komplets") or data.get("kits") or []:
            if isinstance(kit_data, dict):
                cabinet.add_kit(Kit.from_dict(kit_data))
        # Вид шкафа определяется комплектами.
        if cabinet.kits:
            cabinet.kind = "typical" if cabinet.is_typical() else "custom"
        return cabinet

    def to_app_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key": self.key,
            "standard_key": self.standard_key,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "voltage": self.voltage,
            "protected": self.protected,
            "controlled": list(self.controlled),
            "its_functions": list(self.its_functions),
            "applicability": self.applicability,
            "architecture": self.architecture,
            "source": self.source,
            "goose": self.goose,
            "tags": list(self.tags),
            "group": self.group,
            "kind": "typical" if self.is_typical() else "custom",
            "details": copy.deepcopy(self.details),
            "komplets": [kit.to_dict() for kit in self.kits],
        }
        result.update(copy.deepcopy(self.extensions))
        for name, value in self.details.items():
            result.setdefault(name, value)
        return result

    @classmethod
    def from_container_model(cls, container: ContainerModel) -> Cabinet:
        """Шкаф-запись каталога: метаданные контейнера + все его комплекты.

        Ключ шкафа — ключ контейнера-записи (как в ``store`` → ``cabs``),
        комплекты берутся поочерёдно из всех внутренних шкафов модели.
        """
        cabinet = cls(
            id=container.id,
            key=container.key,
            code=container.code,
            name=container.name,
            kind="typical" if container.standard_key else "custom",
            group=container.group or "Прочие",
            description=container.description,
            voltage=container.voltage,
            protected=container.protected,
            controlled=list(container.controlled),
            its_functions=[function.code for function in container.its_functions],
            applicability=container.applicability or "",
            architecture=container.architecture or "",
            source=container.source or "",
            goose=bool(container.goose),
            tags=[tag.code for tag in container.tags],
            standard_key=container.standard_key or "",
            extensions={
                name: copy.deepcopy(value)
                for name, value in (container.extensions or {}).items()
                if name not in ("entry_type",)
                and value not in (None, "", [], {})
            },
        )
        extensions = container.extensions or {}
        details = {}
        for name in DETAIL_FIELDS:
            value = extensions.get(name)
            if value not in (None, "", [], {}):
                details[name] = copy.deepcopy(value)
                extensions.pop(name, None)
        cabinet.details = details
        for inner in container.cabinets:
            for kit_model in inner.kits:
                kit = Kit.from_model(kit_model)
                cabinet.add_kit(kit)
        return cabinet


# _KNOWN_CABINET_FIELDS — для from_app_dict: поля, не едущие в extensions.
_KNOWN_CABINET_FIELDS = frozenset({
    "key", "id", "code", "name", "title", "kind", "group", "description",
    "voltage", "protected", "controlled", "its_functions", "applicability",
    "architecture", "source", "goose", "tags", "komplets", "kits",
    "standard", "standard_key", "standard_title", "edition", "document",
    "details", "extra",
}) | frozenset(DETAIL_FIELDS)


# ---------------------------------------------------------------------------
# Контейнер (КЭТ)
# ---------------------------------------------------------------------------


@dataclass
class Container:
    """Контейнер (КЭТ) — содержит шкафы и генерит отчёт."""

    id: str = ""
    key: str = ""
    code: str = ""
    name: str = ""
    title: str = ""
    description: str = ""
    group: str = "Прочие"
    voltage: str = ""
    protected: str = ""
    controlled: list[str] = field(default_factory=list)
    its_functions: list[str] = field(default_factory=list)
    applicability: str = ""
    architecture: str = ""
    source: str = ""
    goose: bool = False
    tags: list[str] = field(default_factory=list)
    origin: str = "custom"
    #: Типоразмер КЭТ: 20dc | 20hc | 40dc и производные данные.
    size: str = ""
    size_title: str = ""
    dimensions: str = ""
    climate: str = ""
    ip: str = ""
    slots: int = 0
    composition: list[str] = field(default_factory=list)
    standard: str = ""
    standard_title: str = ""
    #: Шкафы, входящие в контейнер.
    cabinets: list[Cabinet] = field(default_factory=list)
    #: Ключи шкафов, на которые ссылается КЭТ (состав по стандарту).
    cabinet_keys: list[str] = field(default_factory=list)
    #: Ключи, которые не удалось разрешить в шкафы каталога.
    missing_cabinet_keys: list[str] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)

    # ---------- шкафы ----------

    def add_cabinet(self, cabinet: Cabinet) -> None:
        """Поставить шкаф в контейнер."""
        self.cabinets.append(cabinet)
        if cabinet.key not in self.cabinet_keys:
            self.cabinet_keys.append(cabinet.key)

    def remove_cabinet(self, key: str) -> bool:
        for i, cabinet in enumerate(self.cabinets):
            if cabinet.key == key or cabinet.id == key:
                self.cabinets.pop(i)
                self.cabinet_keys = [
                    cab.key for cab in self.cabinets]
                return True
        return False

    def resolve_cabinets(self, registry: dict[str, Cabinet],
                         *, copy_items: bool = False) -> list[Cabinet]:
        """Набрать шкафы по ``cabinet_keys`` из реестра каталога."""
        resolved: list[Cabinet] = []
        missing: list[str] = []
        for key in self.cabinet_keys:
            cabinet = registry.get(key)
            if cabinet is None:
                if key:
                    missing.append(key)
                continue
            resolved.append(copy.deepcopy(cabinet) if copy_items else cabinet)
        self.cabinets = resolved
        self.missing_cabinet_keys = missing
        return resolved

    # ---------- сводка ----------

    def kit_count(self) -> int:
        return sum(cabinet.kit_count() for cabinet in self.cabinets)

    def ied_count(self) -> int:
        return sum(cabinet.ied_count() for cabinet in self.cabinets)

    def kits(self) -> list[Kit]:
        result: list[Kit] = []
        for cabinet in self.cabinets:
            result.extend(cabinet.kits)
        return result

    # ---------- отчёт ----------

    def report_data(self, title: Optional[str] = None) -> dict[str, Any]:
        """Структура отчёта, совместимая с docxreport.build_selection_report."""
        general: list[list[str]] = [
            ["Обозначение", self.code or self.name or "—"],
            ["Наименование", self.name or "—"],
            ["Назначение", self.description or "—"],
            ["Группа", self.group or "—"],
            ["Типоразмер", self.size_title or self.size or "—"],
            ["Габариты", self.dimensions or "—"],
            ["Слотов", str(self.slots or "—")],
            ["Шкафов в составе", str(len(self.cabinets))],
        ]
        if self.standard_title or self.standard:
            general.append(["Стандарт", self.standard_title or self.standard])
        if self.its_functions:
            general.append(["Функции", ", ".join(self.its_functions)])
        if self.composition:
            general.append(["Состав по стандарту", "; ".join(self.composition)])
        if self.applicability:
            general.append(["Применимость", self.applicability])
        if self.source:
            general.append(["Источник", self.source])
        if self.missing_cabinet_keys:
            general.append(["Не найдены шкафы",
                            ", ".join(self.missing_cabinet_keys)])

        cabinet_rows: list[list[str]] = []
        kit_blocks: list[dict[str, Any]] = []
        total_kits = 0
        total_ieds = 0
        for slot, cabinet in enumerate(self.cabinets, start=1):
            total_kits += cabinet.kit_count()
            total_ieds += cabinet.ied_count()
            cabinet_rows.append([
                str(slot),
                cabinet.code or cabinet.key or "—",
                cabinet.name or "—",
                cabinet.kind_title(),
                str(cabinet.kit_count()),
                str(cabinet.ied_count()),
            ])
            for index, kit in enumerate(cabinet.kits, start=1):
                rows: list[list[str]] = [
                    ["Вид", kit.kind_title()],
                    ["Тип", kit.type],
                    ["Есть ИЭУ", "да" if kit.has_ied else "нет"],
                    ["ИЭУ", kit.ieds_text()],
                    ["Функции", kit.functions_text()],
                ]
                for direction, label in SIGNAL_FIELDS[:2]:
                    if kit.signal_count(direction):
                        rows.append([label, kit.signals_text(direction)])
                if kit.signal_count("goose_in"):
                    rows.append(["Входные GOOSE", kit.signals_text("goose_in")])
                if kit.signal_count("goose_out"):
                    rows.append(["Выходные GOOSE",
                                 kit.signals_text("goose_out")])
                if kit.has_analog():
                    rows.append(["Аналоговые измерения", kit.analog_text()])
                if kit.has_test_blocks():
                    rows.append(["Испытательные блоки", kit.test_blocks_text()])
                if kit.description:
                    rows.append(["Примечание", kit.description])
                if kit.tags:
                    rows.append(["Теги", ", ".join(kit.tags)])
                kit_blocks.append({
                    "head": "{} · слот {} · комплект {} — {}".format(
                        cabinet.code or cabinet.key or "Шкаф",
                        slot, index, kit.name or "Комплект"),
                    "rows": rows,
                })

        sections = [
            {"title": "1. Общие сведения о контейнере", "rows": general},
            {
                "title": "2. Шкафы в контейнере",
                "header": ["№", "Шифр", "Наименование", "Тип",
                           "Комплектов", "ИЭУ"],
                "rows": cabinet_rows,
                "widths": [500, 1500, 3600, 1400, 1200, 900],
                "aligns": ["center", "left", "left", "center",
                           "center", "center"],
                "note": "Комплектов всего: {}; ИЭУ всего: {}.".format(
                    total_kits, total_ieds),
            },
        ]
        if kit_blocks:
            sections.append({"title": "3. Комплекты шкафов",
                             "blocks": kit_blocks})
        else:
            sections.append({"title": "3. Комплекты шкафов",
                             "note": "В шкафах контейнера нет комплектов."})

        return {
            "title": title or "Отчёт по каталогу: {}".format(
                self.code or self.name or "КЭТ"),
            "subtitle": [
                "Сформирован: {}".format(
                    datetime.now().strftime("%d.%m.%Y %H:%M")),
                "Источник: {} · шкафов: {} · комплектов: {} · ИЭУ: {}".format(
                    self.source or "каталог",
                    len(self.cabinets), total_kits, total_ieds),
            ],
            "sections": sections,
            "footer": [
                "Тип шкафа определяется комплектами: шкаф типовой, только "
                "если все его комплекты типовые.",
                "Сигналы и аналоговые измерения приведены по данным "
                "комплектов; для многокомплектных шкафов перечни задаются "
                "на уровне комплекта.",
            ],
        }

    def generate_report(self, title: str = "") -> dict[str, Any]:
        """Отчёт по контейнеру: шкафы, комплекты, ИЭУ, сигналы, БИ."""
        return self.report_data(title or None)

    def write_report(self, path: str | Path) -> Path:
        """Сохранить отчёт контейнера в DOCX (сборка OOXML без зависимостей)."""
        try:
            import docxreport
        except ImportError:  # пакет может вызываться не из корня репозитория
            import sys
            root = str(Path(__file__).resolve().parent.parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            import docxreport

        target = Path(path)
        if target.suffix.lower() != ".docx":
            target = target.with_suffix(".docx")
        target.parent.mkdir(parents=True, exist_ok=True)
        docxreport.build_selection_report(str(target), self.report_data())
        return target

    # ---------- конвертация ----------

    @classmethod
    def from_model(cls, model: ContainerModel) -> Container:
        extensions = copy.deepcopy(model.extensions or {})
        standard = model.standard
        try:
            slots = int(extensions.get("slots") or 0)
        except (TypeError, ValueError):
            slots = 0
        container = cls(
            id=model.id, key=model.key, code=model.code, name=model.name,
            title=model.title, description=model.description,
            group=model.group or "Прочие", voltage=model.voltage,
            protected=model.protected, controlled=list(model.controlled),
            its_functions=[function.code for function in model.its_functions],
            applicability=model.applicability or "",
            architecture=model.architecture or "",
            source=model.source or "", goose=bool(model.goose),
            tags=[tag.code for tag in model.tags],
            origin=model.origin,
            size=str(extensions.get("size") or ""),
            size_title=str(extensions.get("size_title") or ""),
            dimensions=str(extensions.get("dimensions") or ""),
            climate=str(extensions.get("climate") or ""),
            ip=str(extensions.get("ip") or ""),
            slots=slots,
            composition=[str(item) for item in extensions.get("composition") or []],
            standard=(standard.label if standard else "") or "",
            standard_title=(standard.title if standard else "") or "",
            cabinet_keys=[str(key) for key in extensions.get("cabinet_keys") or []
                          if str(key).strip()],
            extensions=extensions,
        )
        for inner in model.cabinets:
            for kit_model in inner.kits:
                kit = Kit.from_model(kit_model)
                container_cabinet = container._find_or_create_cabinet(inner)
                container_cabinet.add_kit(kit)
        return container

    def _find_or_create_cabinet(self, inner: CabinetModel) -> Cabinet:
        for cabinet in self.cabinets:
            if cabinet.id == inner.id:
                return cabinet
        cabinet = Cabinet(id=inner.id, key=inner.key, code=inner.code,
                          name=inner.name, group=inner.group,
                          source=inner.source)
        self.cabinets.append(cabinet)
        return cabinet

    def to_model_dict(self) -> dict[str, Any]:
        """Словарь контейнера для JSON-дампа (шкафы — объектами + ключи)."""
        data: dict[str, Any] = {
            "id": self.id, "key": self.key, "code": self.code,
            "name": self.name, "title": self.title,
            "description": self.description, "group": self.group,
            "voltage": self.voltage, "protected": self.protected,
            "controlled": list(self.controlled),
            "its_functions": list(self.its_functions),
            "applicability": self.applicability,
            "architecture": self.architecture, "source": self.source,
            "goose": self.goose, "tags": list(self.tags),
            "origin": self.origin, "size": self.size,
            "size_title": self.size_title, "dimensions": self.dimensions,
            "climate": self.climate, "ip": self.ip, "slots": self.slots,
            "composition": list(self.composition), "standard": self.standard,
            "standard_title": self.standard_title,
            "cabinet_keys": list(self.cabinet_keys),
            "missing_cabinet_keys": list(self.missing_cabinet_keys),
            "extra": copy.deepcopy(self.extensions),
        }
        if self.cabinets and self.cabinet_keys:
            # Полный объект шкафа лежит в разделе cabinets дампа;
            # контейнер ссылается на него ключами.
            data["cabinets"] = [cabinet.key for cabinet in self.cabinets]
        else:
            data["cabinets"] = [cabinet.to_app_dict()
                                for cabinet in self.cabinets]
        return data

    def to_model(self) -> ContainerModel:
        extensions = copy.deepcopy(self.extensions)
        extensions["entry_type"] = "ket"
        if self.cabinet_keys:
            extensions["cabinet_keys"] = list(self.cabinet_keys)
        if self.size:
            extensions["size"] = self.size
        if self.size_title:
            extensions["size_title"] = self.size_title
        if self.dimensions:
            extensions["dimensions"] = self.dimensions
        if self.climate:
            extensions["climate"] = self.climate
        if self.ip:
            extensions["ip"] = self.ip
        if self.slots:
            extensions["slots"] = self.slots
        if self.composition:
            extensions["composition"] = list(self.composition)
        standard_key = extensions.get("standard_key") or ""
        standard = None
        if standard_key or self.standard or self.standard_title:
            standard = StandardRef(key=standard_key,
                                   title=self.standard_title or None,
                                   label=self.standard or None)
        return ContainerModel(
            id=self.id or self.key, key=self.key, code=self.code,
            name=self.name, title=self.title, description=self.description,
            group=self.group, voltage=self.voltage,
            protected=self.protected, controlled=list(self.controlled),
            its_functions=[FunctionRef(code=code)
                           for code in self.its_functions],
            applicability=self.applicability or None,
            architecture=self.architecture or None,
            source=self.source or None, goose=self.goose,
            tags=[TagRef(code=code) for code in self.tags],
            cabinets=[cabinet.to_model() for cabinet in self.cabinets],
            standard=standard, standard_key=standard_key or None,
            origin=self.origin, extensions=extensions,
        )


_KNOWN_CONTAINER_FIELDS = frozenset({
    "key", "id", "code", "name", "title", "description", "group", "voltage",
    "protected", "controlled", "its_functions", "functions", "applicability",
    "architecture", "source", "goose", "tags", "cabinets", "composition",
    "slots", "size", "origin", "cabinet_keys", "missing_cabinet_keys",
    "standard", "standard_key", "standard_title", "edition", "document",
    "size_code", "size_title", "dimensions", "climate", "ip", "ports",
    "details", "extra",
})


def container_from_app_dict(data: dict[str, Any]) -> Container:
    """Контейнер КЭТ из словаря ``containers.py`` (шкафы — по ключам)."""
    extensions = {
        name: copy.deepcopy(value) for name, value in data.items()
        if name not in _KNOWN_CONTAINER_FIELDS
        and value not in (None, "", [], {})
    }
    return Container(
        id=str(data.get("key") or data.get("id") or ""),
        key=str(data.get("key") or data.get("id") or ""),
        code=str(data.get("code") or ""),
        name=str(data.get("name") or ""),
        title=str(data.get("title") or data.get("name") or ""),
        description=str(data.get("description") or ""),
        group=str(data.get("group") or "Прочие"),
        voltage=str(data.get("voltage") or ""),
        protected=str(data.get("protected") or ""),
        controlled=[str(x) for x in data.get("controlled") or []],
        its_functions=_split_list(data.get("functions")
                                  or data.get("its_functions")),
        applicability=str(data.get("applicability") or ""),
        architecture=str(data.get("architecture") or ""),
        source=str(data.get("source") or ""),
        goose=bool(data.get("goose")),
        tags=[str(tag) for tag in _split_list(data.get("tags"))],
        origin=str(data.get("origin") or "builtin"),
        size=str(data.get("size") or ""),
        size_title=str(data.get("size_title") or ""),
        dimensions=str(data.get("dimensions") or ""),
        climate=str(data.get("climate") or ""),
        ip=str(data.get("ip") or ""),
        slots=int(data.get("slots") or 0),
        composition=[str(item) for item in data.get("composition") or []],
        standard=str(data.get("standard") or ""),
        standard_title=str(data.get("standard_title") or ""),
        cabinet_keys=[str(key) for key in data.get("cabinets") or []
                      if str(key).strip()],
        extensions=extensions,
    )


# ---------------------------------------------------------------------------
# Каталог: заполнение классов из базы (catalog.normalized.json)
# ---------------------------------------------------------------------------


class DomainCatalog:
    """Корневой объект: библиотеки Kit → Cabinet → Container из базы данных.

    Заполнение повторяет семантику приложения:

    * шкафы — встроенные записи и пользовательские записи каталога шкафов
      (``origin="override"`` заменяет встроенный шкаф тем же ключом);
    * сигнальные цепи одно-комплектных шкафов подтягиваются из
      ``cabs_signals.json`` (как в ``komplekts.kit_from_cabinet``);
    * правки из каталога комплектов накладываются по ключам, удалённые
      комплекты исключаются из библиотеки комплектов;
    * контейнеры (КЭТ) разрешают ``cabinet_keys`` в реальные шкафы.
    """

    def __init__(self) -> None:
        #: Библиотека комплектов по ключу каталога (typ:/cab:/user).
        self.kits: dict[str, Kit] = {}
        #: Библиотека шкафов по ключу.
        self.cabinets: dict[str, Cabinet] = {}
        #: Контейнеры (КЭТ) по ключу.
        self.containers: dict[str, Container] = {}
        #: Нормализованная модель хранилища-источника.
        self.store: Optional[RzaCatalog] = None

    # ---------- доступ ----------

    def kit(self, key: str) -> Optional[Kit]:
        return self.kits.get(key)

    def cabinet(self, key: str) -> Optional[Cabinet]:
        return self.cabinets.get(key)

    def container(self, key: str) -> Optional[Container]:
        return self.containers.get(key)

    def kits_of_kind(self, kind: str) -> list[Kit]:
        return [kit for kit in self.kits.values() if kit.kind == kind]

    def typical_kits(self) -> list[Kit]:
        return self.kits_of_kind("typical")

    def custom_kits(self) -> list[Kit]:
        return [kit for kit in self.kits.values() if kit.kind != "typical"]

    # ---------- заполнение из базы ----------

    @classmethod
    def load(cls, path: str | Path | None = None,
             signals_path: str | Path | None = None) -> DomainCatalog:
        """Второе действие: заполнить комплекты и шкафы, которые есть в базе.

        База — ``catalog.normalized.json`` (читается через ``store.py``).
        """
        from . import store as store_module

        catalog = store_module.read_store(path)
        instance = cls()
        instance.store = catalog
        instance._fill_cabinets(catalog, signals_path)
        instance._fill_kit_catalog(catalog)
        instance._fill_containers(catalog)
        return instance

    # ---------- заполнение шкафов и комплектов ----------

    def _fill_cabinets(self, catalog: RzaCatalog,
                       signals_path: str | Path | None) -> None:
        from . import store as store_module

        signals = self._read_signals(signals_path)
        deleted = catalog.deleted

        containers = (list(store_module.builtin_cabinet_entries(catalog))
                      + list(store_module.cabinet_entries(catalog)))
        for container_model in containers:
            if container_model.key in deleted:
                continue
            cabinet = Cabinet.from_container_model(container_model)
            self._attach_signals(cabinet, signals.get(container_model.key))
            self.cabinets[cabinet.key] = cabinet
        # Регистрация комплектов — по финальному набору шкафов: пользовательская
        # правка (override) полностью заменяет встроенный шкаф, его старые
        # комплекты в библиотеке оставаться не должны.
        for cabinet in self.cabinets.values():
            for kit in cabinet.kits:
                self.kits[kit.app_key()] = kit

    @staticmethod
    def _read_signals(path: str | Path | None) -> dict[str, Any]:
        if path is None:
            path = Path(__file__).resolve().parent.parent / "cabs_signals.json"
        target = Path(path)
        if not target.exists():
            return {}
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _attach_signals(cabinet: Cabinet, entry: Optional[dict]) -> None:
        """Сигналы шкафа из СТО → единственному комплекту шкафа."""
        if not isinstance(entry, dict) or len(cabinet.kits) != 1:
            return
        kit = cabinet.kits[0]
        if kit.io_in or kit.io_out:
            return
        for direction in ("io_in", "io_out"):
            setattr(kit, direction,
                    [SignalEntry.from_dict(row)
                     for row in entry.get(direction) or []
                     if isinstance(row, dict)])

    # ---------- каталог комплектов: custom/overrides/deleted ----------

    def _fill_kit_catalog(self, catalog: RzaCatalog) -> None:
        from . import store as store_module

        data = store_module.kit_catalog_data(catalog)
        for key, override in (data.get("overrides") or {}).items():
            kit = self.kits.get(str(key))
            if kit is not None:
                kit.apply_override(override)
        deleted = {str(key) for key in data.get("deleted") or []}
        for entry in data.get("custom") or []:
            if not isinstance(entry, dict):
                continue
            kit = Kit.from_dict(entry)
            key = str(entry.get("key") or kit.id)
            if not key or key in deleted:
                continue
            kit.id = key
            kit.source = kit.source or "user"
            kit.cabinet_id = ""  # самостоятельный комплект
            self.kits[key] = kit
        for key in deleted:
            self.kits.pop(key, None)

    # ---------- контейнеры КЭТ ----------

    def _fill_containers(self, catalog: RzaCatalog) -> None:
        from . import store as store_module

        entries = (list(store_module.builtin_ket_entries(catalog))
                   + list(store_module.ket_entries(catalog)))
        deleted = catalog.deleted_containers
        for container_model in entries:
            if container_model.key in deleted:
                continue
            container = Container.from_model(container_model)
            if not container.cabinets:
                container.resolve_cabinets(self.cabinets)
            elif not container.cabinet_keys:
                container.cabinet_keys = [cabinet.key
                                          for cabinet in container.cabinets]
            self.containers[container.key] = container

    # ---------- сводка ----------

    def stats(self) -> dict[str, int]:
        kits = list(self.kits.values())
        return {
            "kits": len(kits),
            "typical_kits": sum(1 for kit in kits if kit.kind == "typical"),
            "custom_kits": sum(1 for kit in kits if kit.kind != "typical"),
            "kits_with_ied": sum(1 for kit in kits if kit.has_ied),
            "kits_without_ied": sum(1 for kit in kits if not kit.has_ied),
            "kit_ieds": sum(kit.ied_count() for kit in kits),
            "kit_signals": sum(kit.signal_count(direction) for kit in kits
                               for direction, _label in SIGNAL_FIELDS),
            "kits_with_io_in": sum(1 for kit in kits if kit.io_in),
            "kits_with_io_out": sum(1 for kit in kits if kit.io_out),
            "kits_with_test_blocks": sum(1 for kit in kits
                                         if kit.has_test_blocks()),
            "kits_with_analog": sum(1 for kit in kits if kit.has_analog()),
            "cabinets": len(self.cabinets),
            "typical_cabinets": sum(1 for cabinet in self.cabinets.values()
                                    if cabinet.is_typical()),
            "containers": len(self.containers),
            "missing_cabinet_keys": sum(len(container.missing_cabinet_keys)
                                        for container in self.containers.values()),
        }

    def report_text(self) -> str:
        stats = self.stats()
        lines = [
            "Доменная модель заполнена из базы:",
            "  Шкафов:                    {}".format(stats["cabinets"]),
            "    типовых:                 {}".format(stats["typical_cabinets"]),
            "  Комплектов:                {} (с ИЭУ: {}, без ИЭУ: {})".format(
                stats["kits"], stats["kits_with_ied"],
                stats["kits_without_ied"]),
            "    типовых: {} · нетиповых/прочих: {}".format(
                stats["typical_kits"], stats["custom_kits"]),
            "  ИЭУ в комплектах:          {}".format(stats["kit_ieds"]),
            "  С входными цепями:         {}".format(stats["kits_with_io_in"]),
            "  С выходными цепями:        {}".format(stats["kits_with_io_out"]),
            "  С аналоговыми измерениями: {}".format(stats["kits_with_analog"]),
            "  С испытательными блоками:  {}".format(
                stats["kits_with_test_blocks"]),
            "  Контейнеров (КЭТ):         {}".format(stats["containers"]),
            "  Неразрешённых ключей шкафов в КЭТ: {}".format(
                stats["missing_cabinet_keys"]),
        ]
        return "\n".join(lines)

    # ---------- дамп доменной модели ----------

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_schema": 1,
            "kits": [kit.to_dict() for kit in self.kits.values()],
            "cabinets": [cabinet.to_app_dict()
                         for cabinet in self.cabinets.values()],
            "containers": [container.to_model_dict()
                           for container in self.containers.values()],
        }

    def save(self, path: str | Path) -> Path:
        """Сохранить заполненную доменную модель в JSON-дамп."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return target

    @classmethod
    def from_dump(cls, path: str | Path) -> DomainCatalog:
        """Прочитать доменную модель из дампа, сохранённого ``save``."""
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        catalog = cls()
        for kit_data in raw.get("kits") or []:
            kit = Kit.from_dict(kit_data)
            if kit.id:
                catalog.kits[kit.app_key() or kit.id] = kit
        for cabinet_data in raw.get("cabinets") or []:
            cabinet = Cabinet.from_app_dict(cabinet_data)
            catalog.cabinets[cabinet.key] = cabinet
            for kit in cabinet.kits:
                catalog.kits.setdefault(kit.app_key() or kit.id, kit)
        for container_data in raw.get("containers") or []:
            container = Container(
                id=str(container_data.get("id") or container_data.get("key") or ""),
                key=str(container_data.get("key") or ""),
                code=str(container_data.get("code") or ""),
                name=str(container_data.get("name") or ""),
                title=str(container_data.get("title") or ""),
                description=str(container_data.get("description") or ""),
                group=str(container_data.get("group") or "Прочие"),
                voltage=str(container_data.get("voltage") or ""),
                protected=str(container_data.get("protected") or ""),
                controlled=[str(x) for x in container_data.get("controlled") or []],
                its_functions=_split_list(container_data.get("its_functions")),
                applicability=str(container_data.get("applicability") or ""),
                architecture=str(container_data.get("architecture") or ""),
                source=str(container_data.get("source") or ""),
                goose=bool(container_data.get("goose")),
                tags=[str(t) for t in _split_list(container_data.get("tags"))],
                origin=str(container_data.get("origin") or "custom"),
                size=str(container_data.get("size") or ""),
                size_title=str(container_data.get("size_title") or ""),
                dimensions=str(container_data.get("dimensions") or ""),
                climate=str(container_data.get("climate") or ""),
                ip=str(container_data.get("ip") or ""),
                slots=int(container_data.get("slots") or 0),
                composition=[str(x) for x in container_data.get("composition") or []],
                standard=str(container_data.get("standard") or ""),
                standard_title=str(container_data.get("standard_title") or ""),
                cabinet_keys=[str(x) for x in container_data.get("cabinet_keys") or []],
                missing_cabinet_keys=[
                    str(x) for x in container_data.get("missing_cabinet_keys") or []],
                extensions=copy.deepcopy(container_data.get("extra") or {}),
            )
            for cabinet_data in container_data.get("cabinets") or []:
                if isinstance(cabinet_data, str):
                    inner = catalog.cabinets.get(cabinet_data)
                    if inner is not None:
                        container.add_cabinet(inner)
                    else:
                        container.missing_cabinet_keys.append(cabinet_data)
                elif isinstance(cabinet_data, dict):
                    inner = catalog.cabinets.get(
                        str(cabinet_data.get("key") or ""))
                    container.add_cabinet(inner or Cabinet.from_app_dict(cabinet_data))
            catalog.containers[container.key] = container
        return catalog

    def __repr__(self) -> str:
        return "<DomainCatalog cabinets={} containers={} kits={}>".format(
            len(self.cabinets), len(self.containers), len(self.kits))


# ---------------------------------------------------------------------------
# Текстовый предпросмотр отчёта
# ---------------------------------------------------------------------------


def report_to_text(report: dict[str, Any]) -> str:
    """Текстовый вид отчёта (как предпросмотр в окне редактора)."""
    lines = [report.get("title", "Отчёт"), "=" * 60, ""]
    for line in report.get("subtitle") or []:
        lines.append(str(line))
    for section in report.get("sections") or []:
        lines.append("")
        lines.append(section.get("title", ""))
        lines.append("-" * len(section.get("title", "")))
        if section.get("note"):
            lines.append(str(section["note"]))
            lines.append("")
        header = section.get("header")
        rows = section.get("rows") or []
        if header:
            lines.append("  |  ".join(str(cell) for cell in header))
        for row in rows:
            if header:
                lines.append("  |  ".join(str(cell) for cell in row))
            elif len(row) >= 2:
                lines.append("  {} : {}".format(row[0], row[1]))
        for block in section.get("blocks") or []:
            lines.append("")
            if block.get("head"):
                lines.append("  " + str(block["head"]))
            for row in block.get("rows") or []:
                if len(row) >= 2:
                    lines.append("    {} : {}".format(row[0], row[1]))
    for line in report.get("footer") or []:
        lines.append("")
        lines.append(str(line))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: python3 -m rza_catalog.domain
# ---------------------------------------------------------------------------


def build_parser() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        prog="rza_catalog.domain",
        description=(
            "Заполняет доменную модель (Kit → Cabinet → Container) из базы "
            "catalog.normalized.json; генерит отчёт Word по контейнеру."
        ),
    )
    parser.add_argument("--store", type=Path, default=None,
                        help="путь к catalog.normalized.json (по умолчанию — рабочий)")
    parser.add_argument("--list", action="store_true",
                        help="перечислить контейнеры (КЭТ)")
    parser.add_argument("--dump", type=Path, default=None,
                        help="сохранить доменную модель в JSON-дамп")
    parser.add_argument("--report", metavar="КЛЮЧ_КЭТ", default=None,
                        help="ключ контейнера для отчёта")
    parser.add_argument("--out", type=Path, default=None,
                        help="куда писать отчёт (.docx или .txt)")
    return parser


def domain_main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    catalog = DomainCatalog.load(args.store)
    print(catalog.report_text())

    if args.list:
        print()
        print("Контейнеры (КЭТ):")
        for container in catalog.containers.values():
            print("  {:<28} {} — {} шкафов, {} комплектов".format(
                container.key, container.code or container.name,
                len(container.cabinets), container.kit_count()))

    if args.dump is not None:
        path = catalog.save(args.dump)
        print("\nДамп доменной модели: {} ({:,} байт)".format(
            path, path.stat().st_size))

    if args.report is not None:
        container = catalog.container(args.report)
        if container is None:
            available = ", ".join(sorted(catalog.containers))[:600]
            print("Контейнер {!r} не найден. Есть: {}".format(
                args.report, available), file=sys.stderr)
            return 2
        out = args.out or Path("output/report_{}.docx".format(container.key))
        suffix = out.suffix.lower()
        if suffix == ".txt":
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report_to_text(container.report_data()),
                           encoding="utf-8")
        else:
            out = container.write_report(out)
        print("\nОтчёт: {} ({:,} байт)".format(out, out.stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(domain_main())



