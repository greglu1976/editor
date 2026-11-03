# -*- coding: utf-8 -*-
"""Сериализация нормализованного каталога обратно в JSON."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import RzaCatalog, SCHEMA_VERSION


def catalog_to_dict(catalog: RzaCatalog) -> dict[str, Any]:
    """Нормализованное представление каталога.

    Контейнеры остаются списком (порядок каталога важен), справочники —
    словарями по ключу. ``deleted`` сортируется для воспроизводимости.
    """

    return {
        "schema_version": SCHEMA_VERSION,
        "containers": [asdict(container) for container in catalog.containers.values()],
        "deleted": sorted(catalog.deleted),
        "standards": {
            key: asdict(standard)
            for key, standard in catalog.standards.items()
        },
        "functions": {
            key: asdict(function)
            for key, function in catalog.functions.items()
        },
    }


def dump_catalog(catalog: RzaCatalog, path: str | os.PathLike[str]) -> None:
    """Пишет нормализованный JSON атомарно (через временный файл)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(
                catalog_to_dict(catalog),
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def catalog_counts(catalog: RzaCatalog) -> dict[str, int]:
    """Сводные счётчики для отчёта CLI и тестов."""

    cabinets = 0
    kits = 0
    ieds = 0
    test_blocks = 0
    analog_inputs = 0
    kits_with_ied = 0

    for container in catalog.containers.values():
        for cabinet in container.cabinets:
            cabinets += 1
            for kit in cabinet.kits:
                kits += 1
                ieds += len(kit.ieds)
                if kit.ieds or kit.has_ied:
                    kits_with_ied += 1
                test_blocks += len(kit.test_blocks.blocks)
                if kit.test_blocks.voltage.count or kit.test_blocks.voltage.circuits:
                    test_blocks += 1
                if kit.test_blocks.current.count or kit.test_blocks.current.circuits:
                    test_blocks += 1
                analog_inputs += len(kit.analog_inputs)

    return {
        "containers": len(catalog.containers),
        "cabinets": cabinets,
        "kits": kits,
        "kits_with_ied": kits_with_ied,
        "ieds": ieds,
        "functions": len(catalog.functions),
        "standards": len(catalog.standards),
        "test_blocks": test_blocks,
        "analog_inputs": analog_inputs,
        "deleted": len(catalog.deleted),
    }
