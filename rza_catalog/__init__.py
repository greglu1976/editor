# -*- coding: utf-8 -*-
"""Нормализованная модель каталога РЗА: container → cabinet → kit → ied.

Два слоя, один источник данных (``catalog.normalized.json``):

* ``models`` — нормализованная модель хранения (словари, ссылки, extensions);
* ``domain`` — классовый подход для работы с данными: Container (КЭТ)
  содержит шкафы, шкафы набираются из комплектов (с ИЭУ/без ИЭУ,
  входные/выходные цепи, БИ и прочее); ``DomainCatalog.load()`` заполняет
  классы из базы, ``Container.write_report()`` генерит отчёт Word.
"""

from .export import catalog_counts, catalog_to_dict, dump_catalog
from .migrate import (
    MigrationError,
    iter_kits,
    container_entry_type,
    load_catalog,
    repair_functions,
)
from .models import (
    AnalogInput,
    Cabinet,
    CircuitGroup,
    Container,
    ContainerOrigin,
    FunctionRef,
    Ied,
    IedType,
    Kit,
    KitKind,
    RzaCatalog,
    SCHEMA_VERSION,
    SignalEntry,
    StandardRef,
    TagRef,
    TestBlockEntry,
    TestBlocks,
)
from .to_sqlite import export_sqlite
from .validate import CatalogValidationError, validate_catalog

from .domain import (
    DETAIL_FIELDS,
    KIND_TITLES,
    SIGNAL_FIELDS,
    AnalogInput as DomainAnalogInput,
    Cabinet as DomainCabinet,
    CircuitGroup as DomainCircuitGroup,
    Container as DomainContainer,
    Ied as DomainIed,
    Kit as DomainKit,
    SignalEntry as DomainSignalEntry,
    TestBlockEntry as DomainTestBlockEntry,
    TestBlocks as DomainTestBlocks,
    DomainCatalog,
    container_from_app_dict,
    report_to_text,
)

__all__ = [
    "AnalogInput",
    "Cabinet",
    "CatalogValidationError",
    "CircuitGroup",
    "Container",
    "ContainerOrigin",
    "FunctionRef",
    "Ied",
    "IedType",
    "Kit",
    "KitKind",
    "MigrationError",
    "RzaCatalog",
    "SCHEMA_VERSION",
    "SignalEntry",
    "StandardRef",
    "TagRef",
    "TestBlockEntry",
    "TestBlocks",
    "catalog_counts",
    "catalog_to_dict",
    "container_entry_type",
    "dump_catalog",
    "export_sqlite",
    "iter_kits",
    "load_catalog",
    "repair_functions",
    "validate_catalog",
    # доменная модель (классовый подход к хранению данных)
    "DETAIL_FIELDS",
    "KIND_TITLES",
    "SIGNAL_FIELDS",
    "DomainAnalogInput",
    "DomainCabinet",
    "DomainCircuitGroup",
    "DomainContainer",
    "DomainIed",
    "DomainKit",
    "DomainSignalEntry",
    "DomainTestBlockEntry",
    "DomainTestBlocks",
    "DomainCatalog",
    "container_from_app_dict",
    "report_to_text",
]
