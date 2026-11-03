# -*- coding: utf-8 -*-
"""Единое хранилище каталога для приложения.

Файл ``catalog.normalized.json`` — единственный источник пользовательских
данных каталога. Встроенные шкафы и КЭТ остаются в коде (``cabs_data.py``,
``cabs_sto.py``, ``containers.py``), а пользовательские записи и правки
хранятся здесь в нормализованной иерархии:

    Container → Cabinet → Kit → Ied

Записи двух видов:

* ``entry_type = "cabinet"`` — запись каталога шкафов (вложенные шкафы и
  комплекты);
* ``entry_type = "ket"`` — контейнер КЭТ, который ссылается на шкафы по
  ключам (``extensions.cabinet_keys``).

Модуль также умеет один раз собрать хранилище из старых
``cabinets.json`` / ``containers.json``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

from .export import catalog_to_dict, dump_catalog
from .migrate import container_entry_type, load_catalog
from .models import (
    Cabinet,
    Container,
    FunctionRef,
    Kit,
    RzaCatalog,
    StandardRef,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE_PATH = ROOT / "catalog.normalized.json"
LEGACY_CABINETS_PATH = ROOT / "cabinets.json"
LEGACY_CONTAINERS_PATH = ROOT / "containers.json"
LEGACY_KITS_PATH = ROOT / "komplekts.json"

#: Служебный контейнер для пользовательских комплектов вне шкафов.
KIT_CATALOG_KEY = "__kit_catalog__"


class CatalogStoreError(ValueError):
    """Хранилище каталога отсутствует или повреждено."""


_cache: dict[Path, tuple[int, RzaCatalog]] = {}


# ---------------------------------------------------------------------------
# Чтение и запись
# ---------------------------------------------------------------------------


def read_store(path: str | Path | None = None) -> RzaCatalog:
    """Читает нормализованный каталог (с кэшем по mtime)."""

    target = Path(path) if path is not None else DEFAULT_STORE_PATH
    if not target.exists():
        return RzaCatalog()

    mtime = target.stat().st_mtime_ns
    cached = _cache.get(target)
    if cached and cached[0] == mtime:
        return copy.deepcopy(cached[1])

    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogStoreError(
            f"Не удалось прочитать {target}: {exc}"
        ) from exc

    catalog = load_catalog(raw, report=[], strict=False)
    _cache[target] = (mtime, copy.deepcopy(catalog))
    return catalog


def write_store(
    catalog: RzaCatalog,
    path: str | Path | None = None,
) -> None:
    """Записывает нормализованный каталог и сбрасывает кэш."""

    target = Path(path) if path is not None else DEFAULT_STORE_PATH
    rebuild_references(catalog)
    dump_catalog(catalog, target)
    try:
        mtime = target.stat().st_mtime_ns
    except OSError:
        mtime = 0
    _cache[target] = (mtime, copy.deepcopy(catalog))


def update_store(
    mutator: Callable[[RzaCatalog], Any],
    path: str | Path | None = None,
) -> RzaCatalog:
    """Загружает каталог, применяет mutator и сохраняет."""

    catalog = read_store(path)
    mutator(catalog)
    write_store(catalog, path)
    return catalog


def ensure_store(path: str | Path | None = None) -> RzaCatalog:
    """Возвращает хранилище, при первом запуске собирая его из старых JSON."""

    target = Path(path) if path is not None else DEFAULT_STORE_PATH
    if target.exists():
        return read_store(target)
    catalog = bootstrap_from_legacy()
    write_store(catalog, target)
    return catalog


def rebuild_references(catalog: RzaCatalog) -> None:
    """Пересобирает справочники функций и стандартов после правок."""

    catalog.functions.clear()
    catalog.standards.clear()

    for container in catalog.containers.values():
        for function in container.its_functions:
            if function.code not in catalog.functions:
                catalog.functions[function.code] = function

        if container.standard_key:
            if container.standard and container.standard.key:
                key = container.standard.key
                if key not in catalog.standards:
                    catalog.standards[key] = container.standard
            elif container.standard_key not in catalog.standards:
                catalog.standards[container.standard_key] = StandardRef(
                    key=container.standard_key
                )
        elif container.standard and container.standard.key:
            key = container.standard.key
            if key not in catalog.standards:
                catalog.standards[key] = container.standard

        for cabinet in container.cabinets:
            for kit in cabinet.kits:
                for function in kit.functions:
                    if function.code not in catalog.functions:
                        catalog.functions[function.code] = function

        if entry_type(container) == "kit_catalog":
            for kit in (container.extensions.get("custom") or []):
                if not isinstance(kit, dict):
                    continue
                for code in kit.get("functions") or []:
                    code = str(code).strip()
                    if code and code not in catalog.functions:
                        catalog.functions[code] = FunctionRef(code=code)
            for override in (container.extensions.get("overrides") or {}).values():
                if not isinstance(override, dict):
                    continue
                for code in override.get("functions") or []:
                    code = str(code).strip()
                    if code and code not in catalog.functions:
                        catalog.functions[code] = FunctionRef(code=code)


# ---------------------------------------------------------------------------
# Типы записей
# ---------------------------------------------------------------------------


def entry_type(container: Container) -> str:
    return container_entry_type(container)


def cabinet_entries(catalog: RzaCatalog) -> list[Container]:
    return [
        container for container in catalog.containers.values()
        if entry_type(container) == "cabinet"
    ]


def ket_entries(catalog: RzaCatalog) -> list[Container]:
    return [
        container for container in catalog.containers.values()
        if entry_type(container) == "ket"
    ]


def _drop_entries(catalog: RzaCatalog, kind: str) -> None:
    for key in [
        key for key, container in catalog.containers.items()
        if entry_type(container) == kind
    ]:
        catalog.containers.pop(key, None)


def reset_cabinet_entries(catalog: RzaCatalog) -> None:
    _drop_entries(catalog, "cabinet")
    catalog.deleted.clear()


def reset_ket_entries(catalog: RzaCatalog) -> None:
    _drop_entries(catalog, "ket")
    catalog.deleted_containers.clear()


def kit_catalog_data(catalog: RzaCatalog) -> dict[str, Any]:
    """Пользовательские комплекты и правки вне каталога шкафов."""

    container = catalog.containers.get(KIT_CATALOG_KEY)
    if container is None:
        return {"custom": [], "overrides": {}, "deleted": []}
    extensions = container.extensions
    return {
        "custom": copy.deepcopy(extensions.get("custom") or []),
        "overrides": copy.deepcopy(extensions.get("overrides") or {}),
        "deleted": list(extensions.get("deleted") or []),
    }


def write_kit_catalog(catalog: RzaCatalog, data: dict[str, Any]) -> None:
    """Сохраняет пользовательские комплекты в служебном контейнере."""

    custom = data.get("custom") or []
    overrides = data.get("overrides") or {}
    deleted = data.get("deleted") or []
    if not custom and not overrides and not deleted:
        catalog.containers.pop(KIT_CATALOG_KEY, None)
        return

    container = catalog.containers.get(KIT_CATALOG_KEY)
    if container is None:
        container = Container(
            id=KIT_CATALOG_KEY,
            key=KIT_CATALOG_KEY,
            code="user-kits",
            name="Пользовательские комплекты",
            title="Пользовательские комплекты",
            description="Комплекты и правки, не привязанные к шкафу",
            group="Прочие",
            voltage="",
            protected="",
            origin="custom",
        )
        catalog.containers[KIT_CATALOG_KEY] = container

    container.extensions["entry_type"] = "kit_catalog"
    container.extensions["custom"] = copy.deepcopy(custom)
    container.extensions["overrides"] = copy.deepcopy(overrides)
    container.extensions["deleted"] = list(deleted)


def reset_kit_catalog(catalog: RzaCatalog) -> None:
    catalog.containers.pop(KIT_CATALOG_KEY, None)


# ---------------------------------------------------------------------------
# Сборка из старых JSON
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def bootstrap_from_legacy(
    cabinets_path: str | Path | None = None,
    containers_path: str | Path | None = None,
) -> RzaCatalog:
    """Собирает нормализованный каталог из старых пользовательских JSON."""

    cabinets_source = Path(cabinets_path) if cabinets_path is not None \
        else LEGACY_CABINETS_PATH
    containers_source = Path(containers_path) if containers_path is not None \
        else LEGACY_CONTAINERS_PATH

    combined = RzaCatalog()

    cabinet_raw = _read_json(cabinets_source)
    if cabinet_raw:
        cabinet_catalog = load_catalog(cabinet_raw, report=[], strict=False)
        for container in cabinet_catalog.containers.values():
            container.extensions["entry_type"] = "cabinet"
            combined.containers[container.key] = container
        combined.deleted.update(cabinet_catalog.deleted)

    kit_raw = _read_json(LEGACY_KITS_PATH)
    if kit_raw:
        write_kit_catalog(combined, {
            "custom": kit_raw.get("custom") or [],
            "overrides": kit_raw.get("overrides") or {},
            "deleted": kit_raw.get("deleted") or [],
        })

    ket_raw = _read_json(containers_source)
    if ket_raw:
        ket_catalog = load_catalog(ket_raw, report=[], strict=False)
        for container in ket_catalog.containers.values():
            container.extensions["entry_type"] = "ket"
            container.extensions["cabinet_keys"] = _cabinet_keys(container)
            container.cabinets = []
            combined.containers[container.key] = container
        combined.deleted.update(ket_catalog.deleted)
        combined.deleted_containers.update(ket_catalog.deleted_containers)

    if not combined.containers:
        return combined

    # Повторный разбор пересобирает справочники функций/стандартов и
    # применяет deleted/deleted_containers к нужным типам записей.
    return load_catalog(
        {
            "containers": [
                asdict(container)
                for container in combined.containers.values()
            ],
            "deleted": sorted(combined.deleted),
            "deleted_containers": sorted(combined.deleted_containers),
        },
        report=[],
        strict=False,
    )


def _cabinet_keys(container: Container) -> list[str]:
    keys = container.extensions.get("cabinet_keys")
    if isinstance(keys, list):
        return [str(key) for key in keys if str(key).strip()]
    return []


# ---------------------------------------------------------------------------
# Нормализованная запись → словари приложения
# ---------------------------------------------------------------------------


def _function_codes(functions: Any) -> list[str]:
    return [function.code for function in functions]


def _tag_codes(tags: Any) -> list[str]:
    return [tag.code for tag in tags]


def _standard_fields(container: Container) -> dict[str, Any]:
    standard = container.standard
    if standard is None:
        return {}
    result: dict[str, Any] = {}
    label = standard.label or standard.title or standard.key
    if label:
        result["standard"] = label
    if standard.title:
        result["standard_title"] = standard.title
    if standard.edition:
        result["edition"] = standard.edition
    if standard.document:
        result["document"] = standard.document
    return result


def _kit_to_dict(kit: Kit, cabinet: Cabinet, index: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": kit.id,
        "kind": kit.kind,
        "name": kit.name,
        "type": kit.type,
        "functions": _function_codes(kit.functions),
        "desc": kit.description or "",
        "has_ied": kit.has_ied,
        "ieds": [],
        "test_blocks": {
            "voltage": {
                "count": kit.test_blocks.voltage.count,
                "circuits": list(kit.test_blocks.voltage.circuits),
            },
            "current": {
                "count": kit.test_blocks.current.count,
                "circuits": list(kit.test_blocks.current.circuits),
            },
        },
        "cabinet_key": cabinet.key,
        "cabinet_index": index,
        "cabinet_code": cabinet.code,
        "cabinet_name": cabinet.name,
        "cabinet_group": cabinet.group,
        "source": kit.source or "cabinet_entry",
    }

    ied_extras = kit.extensions.get("ied_extras")
    if not isinstance(ied_extras, dict):
        ied_extras = {}
    for ied in kit.ieds:
        item = {
            "name": ied.name,
            "type": ied.type,
            "desc": ied.description or "",
        }
        extra = ied_extras.get(ied.id)
        if isinstance(extra, dict):
            item.update(copy.deepcopy(extra))
        result["ieds"].append(item)

    if kit.test_blocks.blocks:
        result["test_block_list"] = [
            {
                "name": entry.name,
                "circuits": entry.circuits,
                "count": entry.count,
                "note": entry.note,
            }
            for entry in kit.test_blocks.blocks
        ]

    if kit.analog_inputs:
        result["analog_inputs"] = [
            {
                "block": analog.block,
                "signals": analog.signals,
                "contacts": analog.contacts,
                "note": analog.note,
            }
            for analog in kit.analog_inputs
        ]

    if kit.tags:
        result["tags"] = _tag_codes(kit.tags)

    for key, value in kit.extensions.items():
        if key == "ied_extras":
            continue
        if key not in result:
            result[key] = copy.deepcopy(value)
    return result


def container_to_cabinet_dict(container: Container) -> dict[str, Any]:
    """Нормализованная запись → словарь шкафа для ``cabs.py``."""

    result: dict[str, Any] = {
        "key": container.key,
        "standard_key": container.standard_key or "",
        "code": container.code,
        "name": container.name,
        "title": container.title,
        "description": container.description,
        "voltage": container.voltage,
        "protected": container.protected,
        "controlled": list(container.controlled),
        "its_functions": _function_codes(container.its_functions),
        "applicability": container.applicability,
        "architecture": container.architecture,
        "source": container.source,
        "goose": container.goose,
        "tags": _tag_codes(container.tags),
        "group": container.group,
        "komplets": [],
    }

    for cabinet in container.cabinets:
        for index, kit in enumerate(cabinet.kits):
            result["komplets"].append(_kit_to_dict(kit, cabinet, index))

    result.update(_standard_fields(container))
    for key, value in container.extensions.items():
        if key in {"entry_type", "cabinet_keys"}:
            continue
        if key not in result:
            result[key] = copy.deepcopy(value)
    return result


def container_to_ket_dict(container: Container) -> dict[str, Any]:
    """Нормализованная запись → словарь КЭТ для ``containers.py``."""

    result: dict[str, Any] = {
        "key": container.key,
        "standard_key": container.standard_key or "",
        "code": container.code,
        "name": container.name,
        "title": container.title,
        "description": container.description,
        "group": container.group,
        "voltage": container.voltage,
        "protected": container.protected,
        "controlled": list(container.controlled),
        "functions": _function_codes(container.its_functions),
        "applicability": container.applicability,
        "architecture": container.architecture,
        "source": container.source,
        "goose": container.goose,
        "tags": _tag_codes(container.tags),
        "cabinets": _cabinet_keys(container),
    }
    result.update(_standard_fields(container))
    for key, value in container.extensions.items():
        if key in {"entry_type", "cabinet_keys"}:
            continue
        if key not in result:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# Словари приложения → нормализованная запись
# ---------------------------------------------------------------------------


def cabinet_dict_to_container(
    definition: dict[str, Any],
    origin: str = "custom",
) -> Container:
    catalog = load_catalog(
        {"custom": [copy.deepcopy(definition)]},
        report=[],
        strict=False,
    )
    container = next(iter(catalog.containers.values()))
    container.origin = origin
    container.extensions["entry_type"] = "cabinet"
    return container


def ket_dict_to_container(
    definition: dict[str, Any],
    origin: str = "custom",
) -> Container:
    catalog = load_catalog(
        {"custom": [copy.deepcopy(definition)]},
        report=[],
        strict=False,
    )
    container = next(iter(catalog.containers.values()))
    container.origin = origin
    container.extensions["entry_type"] = "ket"
    container.extensions["cabinet_keys"] = _cabinet_keys_from_definition(
        definition
    )
    container.cabinets = []
    return container


def _cabinet_keys_from_definition(definition: dict[str, Any]) -> list[str]:
    raw = definition.get("cabinets")
    if not isinstance(raw, list):
        return []
    return [str(key).strip() for key in raw if str(key).strip()]
