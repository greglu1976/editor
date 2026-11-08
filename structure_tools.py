# -*- coding: utf-8 -*-
"""Пересборка и проверка структуры из интерфейса редактора.

Обёртки над ``tools/build_structure.py`` и ``tools/check_structure.py``:
GUI не запускает Python отдельным процессом, а вызывает их функции в этом же
интерпретаторе и показывает результат в окне.

    rebuild()      — пересобрать structure.json (dict: ok/текст/ошибка)
    check()        — отчёт проверки (dict из check_structure.inspect)
    check_text()   — тот же отчёт в виде текста для окна
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys

import structure

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(ROOT, "tools")


def _tool(name):
    """Импорт модуля из ``tools/`` (папка не пакет, поэтому через sys.path)."""
    for path in (TOOLS_DIR, ROOT):
        if path not in sys.path:
            sys.path.insert(0, path)
    return importlib.import_module(name)


def rebuild(path=None):
    """Пересобирает structure.json из каталога и standards_base.

    Возвращает словарь: ``ok``, ``текст`` (сводка сборщика), ``ошибка``,
    ``путь``. Сводка вида «308 шкафов, 341 комплект…» показывается в окне.
    """
    try:
        module = _tool("build_structure")
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "текст": "", "путь": path,
                "ошибка": f"не удалось загрузить сборщик: {exc}"}
    target = path or structure.DEFAULT_PATH
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), \
                contextlib.redirect_stderr(buffer):
            code = module.main(["--out", target])
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "текст": buffer.getvalue().strip(),
                "путь": target, "ошибка": f"сборка прервана: {exc}"}
    text = buffer.getvalue().strip()
    if code not in (0, None):
        return {"ok": False, "текст": text, "путь": target,
                "ошибка": text or f"сборщик вернул код {code}"}
    structure.load(force=True, path=target)
    return {"ok": True, "текст": text or "structure.json пересобран",
            "путь": target, "ошибка": None}


def check(path=None):
    """Проверка структуры: иерархия, ссылки, стыковка со схемами."""
    try:
        module = _tool("check_structure")
    except Exception as exc:                       # noqa: BLE001
        return {"проблемы": [f"не удалось загрузить проверку: {exc}"],
                "замечания": [], "загружено": False}
    if path:
        structure.load(force=True, path=path)
    try:
        return module.inspect()
    except Exception as exc:                       # noqa: BLE001
        return {"проблемы": [f"проверка прервана: {exc}"],
                "замечания": [], "загружено": False}


def check_text(report, path=None):
    """Текст проверки для окна: сводка, ошибки, замечания, заполнение."""
    report = report or {}
    if not report.get("загружено"):
        return "structure.json не прочитан: %s" % (
            structure.error() or "файл отсутствует")
    containers = report.get("контейнеры", 0)
    cabinets = report.get("шкафы", 0)
    kits = report.get("комплекты", 0)
    with_ied = report.get("с_иэу", 0)
    without_ied = report.get("без_иэу", 0)
    ieds = report.get("иэу", 0)
    lines = [
        f"Файл: {path or structure.path()}",
        f"Версия: {report.get('версия')}",
        f"Контейнеров КЭТ: {containers}, шкафов: {cabinets}, "
        f"комплектов: {kits} (с ИЭУ {with_ied}, без ИЭУ {without_ied}), "
        f"ИЭУ: {ieds}",
    ]
    links = report.get("ссылки") or {}
    if links:
        lines.append("Ссылки КЭТ → шкафы: %d, шкафы → КЭТ: %d"
                     % (links.get("КЭТ → шкафы", 0),
                        links.get("шкафы → КЭТ", 0)))
    schemes = report.get("схемы") or {}
    if schemes:
        lines.append("Стыковка со схемами: шкафы %s, КЭТ %s"
                     % (schemes.get("шкафы", "—"), schemes.get("КЭТ", "—")))
    singles = report.get("одно_иэу")
    if singles:
        lines.append("Одно ИЭУ в описании шкафа → в комплекте: %s" % singles)
    problems = report.get("проблемы") or []
    lines.append("")
    lines.append(f"ОШИБКИ ({len(problems)})")
    if problems:
        for problem in problems:
            lines.append(f"  • {problem}")
    else:
        lines.append("  нет")
    notes = report.get("замечания") or []
    lines.append("")
    lines.append(f"ЗАМЕЧАНИЯ ({len(notes)})")
    if notes:
        for note in notes:
            lines.append(f"  • {note}")
    else:
        lines.append("  нет")
    coverage = report.get("покрытие_полей") or {}
    if coverage:
        lines.append("")
        lines.append("ЗАПОЛНЕНИЕ")
        for name, value in coverage.items():
            lines.append("  %-44s %s" % (name, value))
    return "\n".join(lines)


def plan_text(items=None):
    """План сверки стандартов (см. standards_sync.plan_text)."""
    import standards_sync
    return standards_sync.plan_text(items)


def main(argv=None):
    """Проверка из консоли: python structure_tools.py [--rebuild]."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--rebuild" in argv:
        result = rebuild()
        print(result.get("текст") or result.get("ошибка"))
        return 0 if result.get("ok") else 1
    report = check()
    print(check_text(report))
    return 1 if report.get("проблемы") else 0


if __name__ == "__main__":
    sys.exit(main())
