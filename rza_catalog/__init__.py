# -*- coding: utf-8 -*-
"""Нормализованная модель каталога РЗА: container → cabinet → kit → ied."""

from .export import catalog_counts, catalog_to_dict, dump_catalog
from .migrate import (
    MigrationError,
    iter_kits,
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
    StandardRef,
    TagRef,
    TestBlockEntry,
    TestBlocks,
)
from .to_sqlite import export_sqlite
from .validate import CatalogValidationError, validate_catalog

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
    "StandardRef",
    "TagRef",
    "TestBlockEntry",
    "TestBlocks",
    "catalog_counts",
    "catalog_to_dict",
    "dump_catalog",
    "export_sqlite",
    "iter_kits",
    "load_catalog",
    "repair_functions",
    "validate_catalog",
]
