# -*- coding: utf-8 -*-
"""Разбор исходного JSON каталога и приведение к нормализованной модели.

Исходный формат (``cabinets.json``)::

    {
      "custom": [ {контейнер}, ... ],
      "overrides": { "ключ": {контейнер}, ... },
      "deleted": ["ключ", ...]
    }

У контейнера массив ``komplets`` смешивает шкафы и комплекты. Комплекты
группируются по ``cabinet_key``; если ключа нет — объект считается
самостоятельным (inline) шкафом.

Дополнительно поддерживаются:

* ``test_blocks`` (dict с voltage/current) и ``test_block_list`` (список) —
  сводятся в :class:`~rza_catalog.models.TestBlocks`;
* обрывки функций вида ``["СЗ ВН (ДЗ", "ТНЗНП", ..., "БК)"]`` — склеиваются
  в одну функцию ``"СЗ ВН (ДЗ, ТНЗНП, ..., БК)"``;
* неизвестные поля не выбрасываются, а складываются в ``extensions``.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Optional

from .models import (
    AnalogInput,
    Cabinet,
    CircuitGroup,
    Container,
    ContainerOrigin,
    FunctionRef,
    Ied,
    Kit,
    KitKind,
    RzaCatalog,
    StandardRef,
    TagRef,
    TestBlockEntry,
    TestBlocks,
)

#: Поля комплекта, которые разбираются в явные атрибуты.
_KIT_MAPPED = {
    "key",
    "id",
    "kind",
    "name",
    "type",
    "functions",
    "desc",
    "description",
    "ieds",
    "test_blocks",
    "test_block_list",
    "analog_inputs",
    "tags",
    "has_ied",
    "source",
    "cabinet_id",
    "cabinet_key",
    "cabinet_index",
    "cabinet_code",
    "cabinet_name",
    "cabinet_group",
    "extensions",
}

#: Поля ИЭУ, которые разбираются в явные атрибуты.
_IED_MAPPED = {
    "id", "key", "name", "type", "desc", "description", "kit_id",
    "extensions",
}

#: Поля контейнера, которые разбираются в явные атрибуты.
_CONTAINER_MAPPED = {
    "key",
    "id",
    "standard_key",
    "code",
    "name",
    "title",
    "description",
    "desc",
    "voltage",
    "protected",
    "controlled",
    "its_functions",
    "functions",
    "applicability",
    "architecture",
    "source",
    "goose",
    "tags",
    "komplets",
    "cabinets",
    "group",
    "standard_title",
    "edition",
    "document",
    "standard",
    "extensions",
    "origin",
}


class MigrationError(ValueError):
    """Исходные данные не соответствуют ожидаемому формату."""


def container_entry_type(container: Container) -> str:
    """Тип записи в общем нормализованном каталоге.

    ``cabinet`` — запись каталога шкафов (Container → Cabinet → Kit → Ied),
    ``ket`` — контейнер КЭТ, который ссылается на шкафы по ключам.
    """

    return str(container.extensions.get("entry_type") or "cabinet")


# ---------------------------------------------------------------------------
# Вспомогательные преобразования
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    """Строка без пробелов по краям; None → пустая строка."""

    if value is None:
        return ""
    return str(value).strip()


def _optional_text(value: Any) -> Optional[str]:
    """Строка или None, если значение пустое."""

    text = _text(value)
    return text or None


def _is_empty(value: Any) -> bool:
    """Пустое значение, которое не нужно тащить в JSON."""

    if value is None:
        return True
    if isinstance(value, (str, list, tuple, dict, set)) and len(value) == 0:
        return True
    return False


def _dedupe(items: Iterable[str]) -> list[str]:
    """Убирает точные повторы, сохраняя порядок."""

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _text_list(value: Any) -> list[str]:
    """Список строк.

    Строка дробится по запятым/точкам с запятой/переводам строк (как в
    ``komplekts.split_list``), элементы готового списка не дробятся.
    """

    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            if isinstance(item, (list, tuple, set)):
                parts.extend(_text_list(item))
            elif item is not None:
                parts.append(str(item))
    else:
        parts = [str(value)]
    return _dedupe(_text(part) for part in parts)


def _function_list(value: Any) -> list[str]:
    """Список функций без дробления по запятым.

    Запятая внутри функции — часть названия, поэтому строка считается одной
    функцией; список разворачивается, но его элементы не режутся.
    """

    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            if isinstance(item, (list, tuple, set)):
                items.extend(_function_list(item))
            elif item is not None:
                items.append(str(item))
    else:
        items = [str(value)]
    return [_text(item) for item in items if _text(item)]


def _to_int(value: Any, default: int = 0) -> int:
    """Аккуратно приводит число к int.

    Встречаются значения вида ``"6+1"`` — берём ведущее целое.
    """

    if value is None or isinstance(value, bool):
        return int(value) if isinstance(value, bool) else default
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.match(r"\s*(\d+)", str(value))
        return int(match.group(1)) if match else default


def _to_bool(value: Any, default: bool = False) -> bool:
    """Приводит флаг к bool, не превращая строку ``"false"`` в True."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t", "да"}:
        return True
    if text in {"0", "false", "no", "n", "f", "нет", ""}:
        return False
    return default


def _extensions(obj: dict[str, Any], mapped: set[str]) -> dict[str, Any]:
    """Поля, не попавшие в явные атрибуты, без null/пустого шума."""

    return {
        key: copy.deepcopy(value)
        for key, value in obj.items()
        if key not in mapped and not _is_empty(value)
    }


# ---------------------------------------------------------------------------
# Починка обрывков functions
# ---------------------------------------------------------------------------


def repair_functions(raw: Iterable[Any]) -> list[str]:
    """Склеивает обрывки функций, разорванные по скобкам.

    ``["СЗ ВН (ДЗ", "ТНЗНП", "МТЗ", "ОУ", "АУ", "БНН", "БК)"]`` →
    ``["СЗ ВН (ДЗ, ТНЗНП, МТЗ, ОУ, АУ, БНН, БК)"]``.

    Склейка идёт до момента, когда баланс скобок станет нулевым. Если
    исходная строка сбалансирована, она остаётся самостоятельной.
    Незакрытая скобка в конце не теряет данные: хвост добавляется как есть.
    """

    items = [item for item in (_text(part) for part in raw) if item]
    result: list[str] = []
    buffer: list[str] = []
    depth = 0

    for item in items:
        if buffer:
            buffer.append(item)
            depth += item.count("(") - item.count(")")
            if depth <= 0:
                result.append(", ".join(buffer))
                buffer = []
                depth = 0
            continue

        item_depth = item.count("(") - item.count(")")
        if item_depth > 0:
            buffer = [item]
            depth = item_depth
        else:
            result.append(item)

    if buffer:
        # Незакрытая скобка: не выбрасываем хвост.
        result.append(", ".join(buffer))
    return _dedupe(result)


def _to_function_refs(raw: Any) -> list[FunctionRef]:
    """Список FunctionRef с каноническим кодом и объединением повторов."""

    result: dict[str, FunctionRef] = {}

    # Уже нормализованный вид: [{"code": "...", "title": "..."}, ...]
    if isinstance(raw, (list, tuple)) and raw and \
            all(isinstance(item, dict) for item in raw):
        for item in raw:
            code = _text(item.get("code") or item.get("name"))
            if not code:
                continue
            if code not in result:
                result[code] = FunctionRef(
                    code=code, title=_optional_text(item.get("title"))
                )
        return list(result.values())

    for code in repair_functions(_function_list(raw)):
        if code not in result:
            result[code] = FunctionRef(code=code)
    return list(result.values())


# ---------------------------------------------------------------------------
# Теги и стандарты
# ---------------------------------------------------------------------------


def _to_tags(raw: Any) -> list[TagRef]:
    if isinstance(raw, (list, tuple)):
        codes: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                codes.append(_text(item.get("code")))
            else:
                codes.append(_text(item))
        codes = [code for code in codes if code]
    else:
        codes = _text_list(raw)
    return [TagRef(code=code) for code in _dedupe(codes)]


def _parse_standard(obj: dict[str, Any]) -> Optional[StandardRef]:
    """Собирает StandardRef из полей standard/standard_*.

    Поле ``standard`` в исходниках бывает и строкой-подписью, и объектом.
    """

    raw = obj.get("standard")
    label: Optional[str] = None
    if isinstance(raw, dict):
        label = _optional_text(raw.get("label"))
        key = _text(raw.get("key") or obj.get("standard_key"))
        title = _optional_text(raw.get("title") or obj.get("standard_title"))
        edition = _optional_text(raw.get("edition") or obj.get("edition"))
        document = _optional_text(raw.get("document") or obj.get("document"))
    else:
        label = _optional_text(raw)
        key = _text(obj.get("standard_key"))
        title = _optional_text(obj.get("standard_title"))
        edition = _optional_text(obj.get("edition"))
        document = _optional_text(obj.get("document"))

    if not any((key, title, edition, document, label)):
        return None
    return StandardRef(
        key=key,
        title=title,
        edition=edition,
        document=document,
        label=label,
    )


# ---------------------------------------------------------------------------
# Испытательные блоки и аналоговые входы
# ---------------------------------------------------------------------------


def _parse_circuit_group(raw: Any) -> CircuitGroup:
    if isinstance(raw, dict):
        return CircuitGroup(
            count=_to_int(raw.get("count")),
            circuits=_text_list(raw.get("circuits")),
        )
    if isinstance(raw, (list, tuple, set)):
        return CircuitGroup(count=0, circuits=_text_list(raw))
    return CircuitGroup()


def _test_block_entry(raw: Any) -> Optional[TestBlockEntry]:
    if isinstance(raw, str):
        text = _text(raw)
        if not text:
            return None
        return TestBlockEntry(name=text, circuits="", count="", note=None)
    if not isinstance(raw, dict):
        return None

    name = _text(raw.get("name"))
    circuits = _text(raw.get("circuits"))
    count_raw = raw.get("count")
    count = "" if count_raw is None else _text(count_raw)
    note = _optional_text(raw.get("note"))
    if not any((name, circuits, count, note)):
        return None
    return TestBlockEntry(name=name, circuits=circuits, count=count, note=note)


def _extend_test_blocks(
    target: TestBlocks,
    raw: Any,
    *,
    context: str,
    report: list[str],
) -> None:
    """Добавляет строки перечня блоков из списка/словаря."""

    if raw is None:
        return
    if isinstance(raw, dict):
        entries: list[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        entries = list(raw)
    else:
        report.append(f"{context}: test_block_list имеет неожиданный тип "
                      f"{type(raw).__name__}, пропущен")
        return

    seen = {(b.name, b.circuits, b.count, b.note or "") for b in target.blocks}
    for item in entries:
        entry = _test_block_entry(item)
        if entry is None:
            report.append(f"{context}: пустая/некорректная строка "
                          f"test_block_list, пропущена")
            continue
        marker = (entry.name, entry.circuits, entry.count, entry.note or "")
        if marker in seen:
            continue
        seen.add(marker)
        target.blocks.append(entry)


def _parse_test_blocks(
    obj: dict[str, Any],
    *,
    context: str,
    report: list[str],
) -> TestBlocks:
    """Унифицирует ``test_blocks`` и ``test_block_list``."""

    result = TestBlocks()
    raw = obj.get("test_blocks")

    if isinstance(raw, dict):
        result.voltage = _parse_circuit_group(raw.get("voltage"))
        result.current = _parse_circuit_group(raw.get("current"))
        _extend_test_blocks(
            result, raw.get("blocks"), context=context, report=report
        )
    elif isinstance(raw, (list, tuple)):
        _extend_test_blocks(result, raw, context=context, report=report)
    elif raw is not None:
        report.append(f"{context}: test_blocks имеет неожиданный тип "
                      f"{type(raw).__name__}, пропущен")

    _extend_test_blocks(
        result, obj.get("test_block_list"), context=context, report=report
    )
    return result


def _parse_analog_inputs(
    obj: dict[str, Any],
    *,
    context: str,
    report: list[str],
) -> list[AnalogInput]:
    raw = obj.get("analog_inputs")
    if raw is None:
        return []
    if isinstance(raw, dict):
        entries: list[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        entries = list(raw)
    else:
        report.append(f"{context}: analog_inputs имеет неожиданный тип "
                      f"{type(raw).__name__}, пропущен")
        return []

    result: list[AnalogInput] = []
    for item in entries:
        if not isinstance(item, dict):
            report.append(f"{context}: некорректная строка analog_inputs, "
                          f"пропущена")
            continue
        result.append(AnalogInput(
            block=_text(item.get("block")),
            signals=_text(item.get("signals")),
            contacts=_text(item.get("contacts")),
            note=_optional_text(item.get("note")),
        ))
    return result


# ---------------------------------------------------------------------------
# ИЭУ
# ---------------------------------------------------------------------------


def _parse_ieds(
    raw: Any,
    kit_id: str,
    *,
    context: str,
    report: list[str],
    extras: dict[str, Any],
    used_ied_ids: set[str],
) -> list[Ied]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        entries: list[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        entries = list(raw)
    else:
        report.append(f"{context}: ieds имеет неожиданный тип "
                      f"{type(raw).__name__}, пропущен")
        return []

    result: list[Ied] = []
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            report.append(f"{context}: некорректная запись ieds, пропущена")
            continue

        ied_id = _text(item.get("id") or item.get("key"))
        if not ied_id:
            ied_id = f"{kit_id}:ied:{index}"
        if ied_id in used_ied_ids:
            original = ied_id
            suffix = 2
            while ied_id in used_ied_ids:
                ied_id = f"{original}:dup{suffix}"
                suffix += 1
            report.append(f"{context}: повтор id ИЭУ {original!r}, "
                          f"переименован в {ied_id!r}")
        used_ied_ids.add(ied_id)

        result.append(Ied(
            id=ied_id,
            name=_text(item.get("name")) or f"ИЭУ{index + 1}",
            type=_text(item.get("type")) or "МП РЗА",
            description=_optional_text(
                item.get("desc") or item.get("description")
            ),
            kit_id=kit_id,
        ))

        extra = _extensions(item, _IED_MAPPED)
        if extra:
            extras.setdefault("ied_extras", {})[ied_id] = extra
    return result


# ---------------------------------------------------------------------------
# Комплект
# ---------------------------------------------------------------------------


def _make_kit_id(
    cabinet_id: str,
    index: int,
    raw_key: Any,
    used: set[str],
) -> str:
    key = _text(raw_key)
    if not key:
        key = f"{cabinet_id}:kit:{index}"
    if key in used:
        # Ключи комплектов в исходниках могут повторяться; не теряем запись.
        base = key
        suffix = 2
        while key in used:
            key = f"{base}:dup{suffix}"
            suffix += 1
    used.add(key)
    return key


def _parse_kit(
    obj: dict[str, Any],
    index: int,
    cabinet_id: str,
    *,
    used_kit_ids: set[str],
    used_ied_ids: set[str],
    report: list[str],
) -> Kit:
    kit_id = _make_kit_id(
        cabinet_id, index, obj.get("key") or obj.get("id"), used_kit_ids
    )
    context = kit_id

    extras: dict[str, Any] = {}
    ieds = _parse_ieds(
        obj.get("ieds"), kit_id,
        context=context, report=report, extras=extras,
        used_ied_ids=used_ied_ids,
    )

    extensions = _extensions(obj, _KIT_MAPPED)
    if isinstance(obj.get("extensions"), dict):
        extensions.update(copy.deepcopy(obj["extensions"]))
    extensions.update(extras)

    return Kit(
        id=kit_id,
        name=_text(obj.get("name")) or f"Комплект {index + 1}",
        kind=_text(obj.get("kind")) or KitKind.TYPICAL.value,
        type=_text(obj.get("type")) or "МП РЗА",
        description=_optional_text(
            obj.get("description") or obj.get("desc")
        ),
        functions=_to_function_refs(obj.get("functions")),
        ieds=ieds,
        test_blocks=_parse_test_blocks(
            obj, context=context, report=report
        ),
        analog_inputs=_parse_analog_inputs(
            obj, context=context, report=report
        ),
        tags=_to_tags(obj.get("tags")),
        cabinet_id=cabinet_id,
        has_ied=_to_bool(obj.get("has_ied"), default=bool(ieds)),
        source=_optional_text(obj.get("source")),
        extensions=extensions,
    )


# ---------------------------------------------------------------------------
# Шкаф
# ---------------------------------------------------------------------------


def _first_text(objs: list[dict[str, Any]], *names: str) -> str:
    for obj in objs:
        for name in names:
            text = _text(obj.get(name))
            if text:
                return text
    return ""


def _unique_id(raw: str, used: set[str]) -> str:
    """Гарантирует уникальность id шкафа в пределах каталога."""

    key = raw
    if key in used:
        base = key
        suffix = 2
        while key in used:
            key = f"{base}:dup{suffix}"
            suffix += 1
    used.add(key)
    return key


def _parse_explicit_cabinets(
    raw: list[Any],
    container_key: str,
    *,
    used_cabinet_ids: set[str],
    used_kit_ids: set[str],
    used_ied_ids: set[str],
    report: list[str],
) -> list[Cabinet]:
    """Разбирает уже сгруппированное поле ``cabinets`` (список объектов)."""

    result: list[Cabinet] = []
    used_keys: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            report.append(f"{container_key}: некорректный cabinet, пропущен")
            continue

        raw_id = _text(item.get("id") or item.get("key"))
        if not raw_id:
            raw_id = f"{container_key}:cabinet:{index}"
        cabinet_id = _unique_id(raw_id, used_cabinet_ids)

        cabinet_key = _text(item.get("key")) or raw_id
        if cabinet_key in used_keys:
            original_key = cabinet_key
            suffix = 2
            while cabinet_key in used_keys:
                cabinet_key = f"{original_key}:dup{suffix}"
                suffix += 1
            report.append(f"{container_key}: повтор ключа шкафа "
                          f"{original_key!r}, переименован в {cabinet_key!r}")
        used_keys.add(cabinet_key)

        kits_raw = item.get("kits")
        if kits_raw is None:
            kits_raw = item.get("komplets") or []
        if not isinstance(kits_raw, (list, tuple)):
            report.append(f"{container_key}/{cabinet_id}: kits имеет "
                          f"неожиданный тип, пропущен")
            kits_raw = []

        kits = [
            _parse_kit(
                kit, kit_index, cabinet_id,
                used_kit_ids=used_kit_ids,
                used_ied_ids=used_ied_ids,
                report=report,
            )
            for kit_index, kit in enumerate(kits_raw)
            if isinstance(kit, dict)
        ]
        if len(kits) != len(kits_raw):
            report.append(f"{container_key}/{cabinet_id}: часть kits "
                          f"пропущена (не объекты)")

        mapped = _KIT_MAPPED | {
            "id", "key", "code", "name", "group", "source", "kits",
            "komplets", "cabinet_key", "cabinet_code", "cabinet_name",
            "cabinet_group", "cabinet_index",
        }
        result.append(Cabinet(
            id=cabinet_id,
            key=cabinet_key,
            code=_text(item.get("code")) or cabinet_key,
            name=_text(item.get("name")) or _text(item.get("code")) or cabinet_key,
            group=_text(item.get("group")) or "Прочие",
            source=_text(item.get("source")) or "cabinet",
            kits=kits,
            extensions={
                **_extensions(item, mapped),
                **(copy.deepcopy(item["extensions"])
                   if isinstance(item.get("extensions"), dict) else {}),
            },
        ))
    return result


def _group_into_cabinets(
    komplets: list[Any],
    container_key: str,
    *,
    used_cabinet_ids: set[str],
    used_kit_ids: set[str],
    used_ied_ids: set[str],
    report: list[str],
) -> list[Cabinet]:
    """Группирует смешанный список ``komplets`` в шкафы.

    Ключ группировки — ``cabinet_key``. Если его нет, объект становится
    самостоятельным inline-шкафом (так приходят черновики ``draft-*``).
    """

    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []

    for index, item in enumerate(komplets):
        if not isinstance(item, dict):
            report.append(f"{container_key}: некорректный komplet, пропущен")
            continue
        cabinet_key = _text(item.get("cabinet_key"))
        if cabinet_key:
            key = cabinet_key
        else:
            key = f"{container_key}:inline-cabinet:{index}"
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)

    cabinets: list[Cabinet] = []
    for raw_key in order:
        objs = grouped[raw_key]
        cabinet_id = _unique_id(raw_key, used_cabinet_ids)

        code = _first_text(objs, "cabinet_code", "code")
        name = _first_text(objs, "cabinet_name", "name")
        group = _first_text(objs, "cabinet_group", "group") or "Прочие"
        source = _first_text(objs, "source") or "cabinet_entry"

        # Если метаданные шкафа в разных комплектах расходятся — фиксируем.
        header = (code, name, group)
        for obj in objs[1:]:
            other = (
                _text(obj.get("cabinet_code") or obj.get("code")),
                _text(obj.get("cabinet_name") or obj.get("name")),
                _text(obj.get("cabinet_group") or obj.get("group")),
            )
            if any(other) and other != header:
                report.append(
                    f"{container_key}/{raw_key}: метаданные шкафа различаются "
                    f"между комплектами, взяты из первого"
                )
                break

        cabinet_extensions: dict[str, Any] = {}
        for obj in objs:
            for key, value in obj.items():
                if key.startswith("cabinet_") and key not in {
                    "cabinet_key", "cabinet_index", "cabinet_code",
                    "cabinet_name", "cabinet_group",
                } and not _is_empty(value):
                    cabinet_extensions.setdefault(key, copy.deepcopy(value))

        kits = [
            _parse_kit(
                obj, index, cabinet_id,
                used_kit_ids=used_kit_ids,
                used_ied_ids=used_ied_ids,
                report=report,
            )
            for index, obj in enumerate(objs)
        ]

        cabinets.append(Cabinet(
            id=cabinet_id,
            key=raw_key,
            code=code or raw_key,
            name=name or code or raw_key,
            group=group,
            source=source,
            kits=kits,
            extensions=cabinet_extensions,
        ))

    return cabinets


# ---------------------------------------------------------------------------
# Контейнер
# ---------------------------------------------------------------------------


def _container_key(
    obj: dict[str, Any],
    fallback: Optional[str],
    index: int,
) -> str:
    for candidate in (
        obj.get("key"),
        obj.get("id"),
        fallback,
        obj.get("standard_key"),
        obj.get("code"),
        obj.get("name"),
        obj.get("title"),
    ):
        text = _text(candidate)
        if text:
            return text
    return f"container:{index}"


def _parse_container(
    obj: dict[str, Any],
    origin: str,
    *,
    key: str,
    used_cabinet_ids: set[str],
    used_kit_ids: set[str],
    used_ied_ids: set[str],
    report: list[str],
) -> Container:
    komplets_raw = obj.get("komplets")
    cabinets_raw = obj.get("cabinets")
    explicit_cabinets: list[Any] = []

    if isinstance(cabinets_raw, list) and cabinets_raw and \
            all(isinstance(item, dict) for item in cabinets_raw):
        explicit_cabinets = cabinets_raw

    if komplets_raw is not None and not isinstance(komplets_raw, (list, tuple)):
        report.append(f"{key}: komplets имеет неожиданный тип "
                      f"{type(komplets_raw).__name__}, пропущен")
        komplets_raw = []
    komplets = list(komplets_raw or [])

    if komplets:
        cabinets = _group_into_cabinets(
            komplets, key,
            used_cabinet_ids=used_cabinet_ids,
            used_kit_ids=used_kit_ids,
            used_ied_ids=used_ied_ids,
            report=report,
        )
        if explicit_cabinets:
            report.append(f"{key}: найдены и komplets, и cabinets; "
                          f"использованы komplets")
    elif explicit_cabinets:
        cabinets = _parse_explicit_cabinets(
            explicit_cabinets, key,
            used_cabinet_ids=used_cabinet_ids,
            used_kit_ids=used_kit_ids,
            used_ied_ids=used_ied_ids,
            report=report,
        )
    else:
        cabinets = []
        if isinstance(cabinets_raw, list) and cabinets_raw:
            # Например, containers.json: cabinets — список ключей шкафов,
            # а сами шкафы лежат в другом каталоге. Не теряем ссылки.
            report.append(f"{key}: cabinets содержит ссылки, а не объекты; "
                          f"ключи сохранены в extensions.cabinet_keys")

    extensions = _extensions(obj, _CONTAINER_MAPPED)
    if obj.get("its_functions") is not None and \
            obj.get("functions") is not None and \
            obj.get("functions") != obj.get("its_functions"):
        # Оба поля есть и различаются — второе не выбрасываем.
        if not _is_empty(obj.get("functions")):
            extensions["functions"] = copy.deepcopy(obj["functions"])
    if isinstance(obj.get("extensions"), dict):
        extensions.update(copy.deepcopy(obj["extensions"]))
    if isinstance(cabinets_raw, list) and cabinets_raw and not explicit_cabinets:
        extensions["cabinet_keys"] = copy.deepcopy(cabinets_raw)

    its_functions_raw = obj.get("its_functions")
    if its_functions_raw is None and obj.get("functions") is not None:
        its_functions_raw = obj.get("functions")

    standard = _parse_standard(obj)
    standard_key = (
        _optional_text(obj.get("standard_key"))
        or (standard.key if standard and standard.key else None)
    )
    origin = _text(obj.get("origin")) or origin

    return Container(
        id=key,
        key=key,
        code=_text(obj.get("code")),
        name=_text(obj.get("name")),
        title=_text(obj.get("title")) or _text(obj.get("name")),
        description=_text(obj.get("description") or obj.get("desc")),
        group=_text(obj.get("group")) or "Прочие",
        voltage=_text(obj.get("voltage")),
        protected=_text(obj.get("protected")),
        controlled=_text_list(obj.get("controlled")),
        its_functions=_to_function_refs(its_functions_raw),
        applicability=_optional_text(obj.get("applicability")),
        architecture=_optional_text(obj.get("architecture")),
        source=_optional_text(obj.get("source")),
        goose=_to_bool(obj.get("goose")),
        tags=_to_tags(obj.get("tags")),
        cabinets=cabinets,
        standard=standard,
        standard_key=standard_key,
        origin=origin,
        extensions=extensions,
    )


# ---------------------------------------------------------------------------
# Слияние custom + overrides
# ---------------------------------------------------------------------------


def _deep_merge(base: Any, override: Any) -> Any:
    """Рекурсивно накладывает override на base.

    Словари сливаются, остальные значения (включая списки) заменяются.
    """

    if isinstance(base, dict) and isinstance(override, dict):
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result:
                result[key] = _deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result
    return copy.deepcopy(override)


def _release_container_ids(
    container: Container,
    used_cabinet_ids: set[str],
    used_kit_ids: set[str],
    used_ied_ids: set[str],
) -> None:
    """Освобождает id заменяемого контейнера перед разбором override."""

    for cabinet in container.cabinets:
        used_cabinet_ids.discard(cabinet.id)
        for kit in cabinet.kits:
            used_kit_ids.discard(kit.id)
            for ied in kit.ieds:
                used_ied_ids.discard(ied.id)


def _iter_overrides(
    raw: Any,
    report: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        result = []
        for key, value in raw.items():
            if isinstance(value, dict):
                result.append((_text(key), value))
            else:
                report.append(f"override {key!r} — не объект, пропущен")
        return result
    if isinstance(raw, (list, tuple)):
        result = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                report.append(f"override[{index}] — не объект, пропущен")
                continue
            key = _text(item.get("key") or item.get("id"))
            if not key:
                report.append(f"override[{index}] без ключа, пропущен")
                continue
            result.append((key, item))
        return result
    report.append(f"overrides имеет неожиданный тип {type(raw).__name__}, "
                  f"пропущен")
    return []


def load_catalog(
    raw: Any,
    *,
    report: Optional[list[str]] = None,
    strict: bool = False,
) -> RzaCatalog:
    """Загружает исходный документ и возвращает нормализованный каталог.

    ``report`` — необязательный список, куда складываются предупреждения.
    ``strict=True`` превращает повторы ключей и ошибки формата в исключение.
    """

    if report is None:
        report = []

    if isinstance(raw, list):
        custom: Any = raw
        overrides: Any = {}
        deleted: Any = []
        deleted_containers: Any = []
    elif isinstance(raw, dict):
        # Нормализованный документ проверяем первым: у него тоже есть deleted.
        if "containers" in raw and "custom" not in raw:
            containers = raw.get("containers") or []
            if not isinstance(containers, list):
                raise MigrationError("Поле containers должно быть списком")
            custom = containers
            overrides = {}
            deleted = raw.get("deleted") or []
            deleted_containers = raw.get("deleted_containers") or []
        elif "custom" in raw or "overrides" in raw or "deleted" in raw:
            custom = raw.get("custom") or []
            overrides = raw.get("overrides") or {}
            deleted = raw.get("deleted") or []
            deleted_containers = raw.get("deleted_containers") or []
        elif "key" in raw or "komplets" in raw or "cabinets" in raw:
            custom = [raw]
            overrides = {}
            deleted = []
            deleted_containers = []
        else:
            raise MigrationError(
                "Неизвестный формат документа: ожидались custom/overrides/"
                "deleted, containers или один контейнер"
            )
    else:
        raise MigrationError(
            f"Ожидался объект или список, получено {type(raw).__name__}"
        )

    if not isinstance(custom, list):
        if strict:
            raise MigrationError("Поле custom должно быть списком")
        report.append("custom не список — прочитан как пустой")
        custom = []
    if not isinstance(deleted, (list, tuple, set)):
        if strict:
            raise MigrationError("Поле deleted должно быть списком")
        report.append("deleted не список — прочитан как пустой")
        deleted = []
    if not isinstance(deleted_containers, (list, tuple, set)):
        if strict:
            raise MigrationError("Поле deleted_containers должно быть списком")
        report.append("deleted_containers не список — прочитан как пустой")
        deleted_containers = []

    catalog = RzaCatalog()
    used_cabinet_ids: set[str] = set()
    used_kit_ids: set[str] = set()
    used_ied_ids: set[str] = set()
    raw_by_key: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(custom):
        if not isinstance(item, dict):
            message = f"custom[{index}] — не объект, пропущен"
            if strict:
                raise MigrationError(message)
            report.append(message)
            continue

        key = _container_key(item, None, index)
        if key in catalog.containers:
            message = f"Повтор ключа контейнера {key!r} в custom"
            if strict:
                raise MigrationError(message)
            report.append(message + " — запись переименована")
            base_key = key
            suffix = 2
            while key in catalog.containers:
                key = f"{base_key}:dup{suffix}"
                suffix += 1

        container = _parse_container(
            item,
            ContainerOrigin.CUSTOM.value,
            key=key,
            used_cabinet_ids=used_cabinet_ids,
            used_kit_ids=used_kit_ids,
            used_ied_ids=used_ied_ids,
            report=report,
        )
        catalog.containers[container.key] = container
        raw_by_key[container.key] = item

    for mapping_key, override_raw in _iter_overrides(overrides, report):
        key = _text(override_raw.get("key") or override_raw.get("id")) or mapping_key
        if not key:
            message = "override без ключа, пропущен"
            if strict:
                raise MigrationError(message)
            report.append(message)
            continue

        base_raw = raw_by_key.get(key)
        merged = _deep_merge(base_raw, override_raw) if base_raw else copy.deepcopy(override_raw)

        old = catalog.containers.get(key)
        if old is not None:
            _release_container_ids(
                old, used_cabinet_ids, used_kit_ids, used_ied_ids
            )

        # Разбираем с уже занятыми id, чтобы не плодить дубли шкафов/комплектов.
        container = _parse_container(
            merged,
            ContainerOrigin.OVERRIDE.value,
            key=key,
            used_cabinet_ids=used_cabinet_ids,
            used_kit_ids=used_kit_ids,
            used_ied_ids=used_ied_ids,
            report=report,
        )
        catalog.containers[container.key] = container

    for key in (_text(item) for item in deleted):
        if not key:
            continue
        catalog.deleted.add(key)
        container = catalog.containers.get(key)
        if container is not None and container_entry_type(container) != "ket":
            catalog.containers.pop(key, None)

    for key in (_text(item) for item in deleted_containers):
        if not key:
            continue
        catalog.deleted_containers.add(key)
        container = catalog.containers.get(key)
        if container is not None and container_entry_type(container) == "ket":
            catalog.containers.pop(key, None)

    _build_references(catalog)
    return catalog


# ---------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------


def _build_references(catalog: RzaCatalog) -> None:
    """Собирает глобальные справочники функций и стандартов."""

    for container in catalog.containers.values():
        for function in container.its_functions:
            catalog.functions.setdefault(function.code, function)

        if container.standard_key:
            if container.standard and container.standard.key:
                catalog.standards.setdefault(
                    container.standard.key, container.standard
                )
            else:
                catalog.standards.setdefault(
                    container.standard_key,
                    StandardRef(key=container.standard_key),
                )
        elif container.standard and container.standard.key:
            catalog.standards.setdefault(
                container.standard.key, container.standard
            )

        for cabinet in container.cabinets:
            for kit in cabinet.kits:
                for function in kit.functions:
                    catalog.functions.setdefault(function.code, function)


def iter_kits(catalog: RzaCatalog) -> Iterable[tuple[Container, Cabinet, Kit]]:
    """Плоский обход всех комплектов каталога."""

    for container in catalog.containers.values():
        for cabinet in container.cabinets:
            for kit in cabinet.kits:
                yield container, cabinet, kit
