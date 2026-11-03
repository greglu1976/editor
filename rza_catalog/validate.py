# -*- coding: utf-8 -*-
"""Проверка целостности нормализованного каталога."""

from __future__ import annotations

from .models import RzaCatalog


class CatalogValidationError(ValueError):
    """Каталог нарушает инварианты нормализованной модели."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        preview = "; ".join(problems[:5])
        if len(problems) > 5:
            preview += f"; … ещё {len(problems) - 5}"
        super().__init__(preview)


def validate_catalog(
    catalog: RzaCatalog,
    *,
    raise_error: bool = True,
) -> list[str]:
    """Проверяет уникальность id и обратные ссылки.

    Возвращает список найденных проблем. При ``raise_error=True``
    (по умолчанию) дополнительно бросает :class:`CatalogValidationError`.
    """

    problems: list[str] = []
    container_ids: set[str] = set()
    cabinet_ids: set[str] = set()
    kit_ids: set[str] = set()
    ied_ids: set[str] = set()

    for container in catalog.containers.values():
        if not container.id:
            problems.append("контейнер с пустым id")
        if container.id != container.key:
            problems.append(
                f"контейнер {container.id!r}: id не совпадает с key "
                f"{container.key!r}"
            )
        if container.id in container_ids:
            problems.append(f"повтор id контейнера {container.id!r}")
        container_ids.add(container.id)

        for function in container.its_functions:
            if function.code not in catalog.functions:
                problems.append(
                    f"контейнер {container.key!r}: функция "
                    f"{function.code!r} отсутствует в справочнике"
                )

        if container.standard_key and \
                container.standard_key not in catalog.standards:
            problems.append(
                f"контейнер {container.key!r}: стандарт "
                f"{container.standard_key!r} отсутствует в справочнике"
            )

        for cabinet in container.cabinets:
            if not cabinet.id:
                problems.append(
                    f"контейнер {container.key!r}: шкаф с пустым id"
                )
            if cabinet.id in cabinet_ids:
                problems.append(f"повтор id шкафа {cabinet.id!r}")
            cabinet_ids.add(cabinet.id)

            for kit in cabinet.kits:
                if kit.cabinet_id != cabinet.id:
                    problems.append(
                        f"комплект {kit.id!r}: cabinet_id "
                        f"{kit.cabinet_id!r} не совпадает с {cabinet.id!r}"
                    )
                if not kit.id:
                    problems.append(
                        f"шкаф {cabinet.id!r}: комплект с пустым id"
                    )
                if kit.id in kit_ids:
                    problems.append(f"повтор id комплекта {kit.id!r}")
                kit_ids.add(kit.id)

                for function in kit.functions:
                    if function.code not in catalog.functions:
                        problems.append(
                            f"комплект {kit.id!r}: функция "
                            f"{function.code!r} отсутствует в справочнике"
                        )

                for ied in kit.ieds:
                    if not ied.id:
                        problems.append(
                            f"комплект {kit.id!r}: ИЭУ с пустым id"
                        )
                    if ied.id in ied_ids:
                        problems.append(f"повтор id ИЭУ {ied.id!r}")
                    ied_ids.add(ied.id)
                    if ied.kit_id != kit.id:
                        problems.append(
                            f"ИЭУ {ied.id!r}: kit_id {ied.kit_id!r} "
                            f"не совпадает с {kit.id!r}"
                        )

    for key in catalog.deleted:
        if not isinstance(key, str) or not key:
            problems.append(f"некорректный ключ в deleted: {key!r}")
    for key in catalog.deleted_containers:
        if not isinstance(key, str) or not key:
            problems.append(
                f"некорректный ключ в deleted_containers: {key!r}"
            )

    if problems and raise_error:
        raise CatalogValidationError(problems)
    return problems
