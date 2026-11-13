# -*- coding: utf-8 -*-
"""Сборка «Редактора схем» с папкой данных ``db``.

Приложение читает и пишет каталоги, структуру и стандарты. В собранном виде
все эти файлы лежат **рядом с exe, в папке db** — их можно править, копировать
и переносить, не трогая программу (см. :mod:`apppaths`).

Поэтому сборка состоит из двух шагов:

1. собрать ``db`` — копии файлов данных, инструментов стандартов и
   сборщика структуры (без PDF и черновиков ``standard_editor/_parse``);
2. собрать сам exe (PyInstaller, режим «One Directory») и положить ``db``
   рядом с ним.

    python build_exe.py --check          # что есть, чего не хватает
    python build_exe.py --stage          # только db → dist/Редактор схем/db
    python build_exe.py                  # db + exe (onedir)
    python build_exe.py --onefile        # один exe, db всё равно рядом
    python build_exe.py --auto-py-to-exe # поля для auto-py-to-exe

PyInstaller в этом окружении может быть не установлен: тогда ``--stage`` и
``--check`` работают, а сборка exe честно скажет, чего не хватает. В
auto-py-to-exe те же значения вводятся в поля — см. ``--auto-py-to-exe``.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

import apppaths

ROOT = apppaths.app_dir()

#: Имя программы и папки сборки.
NAME = "Редактор схем"
DIST_ROOT = os.path.join(ROOT, "dist")
DIST_DIR = os.path.join(DIST_ROOT, NAME)
WORK_DIR = os.path.join(ROOT, "output", "_pyinstaller")
ICON = os.path.join(ROOT, "assets", "editor.ico")

#: Файлы каталогов и структуры: (имя, обязателен для работы).
DATA_FILES = (
    ("cabinets.json", True),
    ("cabs_signals.json", True),
    ("structure.json", True),
    ("containers.json", False),
    ("cabs_analog.json", False),
    ("komplekts.json", False),
)

#: Модули инструментов стандартов (импортируются по имени из папки db).
STANDARD_MODULES = ("apply_changes.py", "changes_editor.py", "changes_gui.py",
                    "json_to_docx.py", "make_standard.py", "node_table.py",
                    "standard_to_docx.py")

#: Сборщик и проверка структуры: вызываются из окна «Структура».
TOOLS = ("build_structure.py", "check_structure.py")

README = """Папка данных «Редактора схем»
==============================

Здесь лежат все файлы, которые программа читает и пишет. Их можно
редактировать вручную, копировать на другой компьютер и хранить в системе
контроля версий — программа при запуске ищет их именно здесь.

  cabinets.json        каталог шкафов: правки и пользовательские шкафы
  cabs_signals.json    сигналы и испытательные блоки из СТО
  cabs_analog.json     входные аналоговые измерения из СТО
  containers.json      контейнеры КЭТ
  komplekts.json       комплекты (появляется после первой правки каталога)
  structure.json       структура v3: КЭТ → шкафы → комплекты → ИЭУ
  standards_base/      стандарты СТО в JSON (сверка и сборка структуры)
  EA/                  стандарты СТО в структуре EA (таблицы из шкафов)
  standard_editor/     редактор изменений стандартов и его базы
  tools/               сборщик и проверка structure.json

Порядок поиска: папка из переменной EDITOR_DB → db рядом с exe → файл рядом
с exe → данные внутри сборки (только чтение).

Если папку db удалить, программа запустится с встроенными каталогами и
создаст файлы заново при первом сохранении.
"""


# ---------------------------------------------------------------------------
# Что копировать
# ---------------------------------------------------------------------------
def plan():
    """Список ``(источник, путь внутри db, обязателен)``."""
    items = []
    for name, required in DATA_FILES:
        items.append((os.path.join(ROOT, name), name, required))

    base = os.path.join(ROOT, "standards_base")
    for path in sorted(glob.glob(os.path.join(base, "*.json"))):
        items.append((path, os.path.join("standards_base",
                                         os.path.basename(path)), False))

    ea = os.path.join(ROOT, "EA")
    for path in sorted(glob.glob(os.path.join(ea, "*.json"))):
        items.append((path, os.path.join("EA", os.path.basename(path)), False))

    editor = os.path.join(ROOT, "standard_editor")
    for name in STANDARD_MODULES:
        items.append((os.path.join(editor, name),
                      os.path.join("standard_editor", name), False))
    for path in sorted(glob.glob(os.path.join(editor, "*.json"))):
        items.append((path, os.path.join("standard_editor",
                                         os.path.basename(path)), False))
    for pattern, inner in (("changes_text/*.изм.txt", "changes_text"),
                           ("changes/*.json", "changes")):
        for path in sorted(glob.glob(os.path.join(editor, *pattern.split("/")))):
            items.append((path, os.path.join("standard_editor", inner,
                                             os.path.basename(path)), False))

    for name in TOOLS:
        items.append((os.path.join(ROOT, "tools", name),
                      os.path.join("tools", name), False))
    return items


def check():
    """Проверка файлов сборки. Возвращает ``(ошибки, предупреждения, план)``."""
    errors, warnings, items = [], [], []
    for source, target, required in plan():
        exists = os.path.exists(source)
        size = os.path.getsize(source) if exists else 0
        items.append({"источник": source, "цель": target, "есть": exists,
                      "байт": size, "обязателен": required})
        if not exists:
            message = "%s — файла нет: %s" % (target, source)
            (errors if required else warnings).append(message)
    return errors, warnings, items


def report(items):
    """Таблица плана для консоли."""
    print("%-38s %-10s %s" % ("файл в db", "размер", "источник"))
    for item in items:
        mark = "обязателен" if item["обязателен"] else ""
        state = "%.1f КБ" % (item["байт"] / 1024.0) if item["есть"] else "НЕТ"
        print("%-38s %-10s %s %s" % (item["цель"], state,
                                     item["источник"], mark))


# ---------------------------------------------------------------------------
# Папка db и иконка
# ---------------------------------------------------------------------------
def stage(target=None, with_schemes=False, quiet=False):
    """Собрать папку данных. Возвращает ``(путь, скопировано, пропущено)``."""
    target = os.path.abspath(target or os.path.join(DIST_DIR, "db"))
    os.makedirs(target, exist_ok=True)
    copied = skipped = 0
    for source, relative, required in plan():
        destination = os.path.join(target, relative)
        if not os.path.exists(source):
            skipped += 1
            continue
        if os.path.normcase(os.path.abspath(source)) == \
                os.path.normcase(os.path.abspath(destination)):
            skipped += 1
            continue
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    if with_schemes:
        schemes = os.path.join(ROOT, "schemes")
        examples = os.path.join(target, "schemes")
        os.makedirs(examples, exist_ok=True)
        for path in sorted(glob.glob(os.path.join(schemes, "*.json"))):
            shutil.copy2(path, os.path.join(examples, os.path.basename(path)))
            copied += 1
    with open(os.path.join(target, "README.txt"), "w", encoding="utf-8") as handle:
        handle.write(README)
    if not quiet:
        print("Папка данных: %s" % target)
        print("  скопировано файлов: %d, пропущено: %d" % (copied, skipped))
    return target, copied, skipped


def make_icon(force=False, quiet=False):
    """Иконка exe: PNG-размеры из ``appicon`` складываются в ``assets/editor.ico``."""
    if os.path.exists(ICON) and not force:
        return ICON
    os.makedirs(os.path.dirname(ICON), exist_ok=True)
    try:
        import appicon
        image = appicon._render(256)
        if image is None:
            raise RuntimeError("Pillow недоступен")
        image.save(ICON, format="ICO",
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                          (64, 64), (128, 128), (256, 256)])
    except Exception as exc:                       # noqa: BLE001
        if not quiet:
            print("Иконка не сделана (%s): exe будет со стандартной." % exc)
        return None
    if not quiet:
        print("Иконка: %s" % ICON)
    return ICON


# ---------------------------------------------------------------------------
# PyInstaller
# ---------------------------------------------------------------------------
def pyinstaller_args(onefile=False):
    """Аргументы PyInstaller — те же поля вводятся в auto-py-to-exe."""
    os.makedirs(WORK_DIR, exist_ok=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--windowed", "--name", NAME,
            "--distpath", DIST_ROOT, "--workpath", WORK_DIR,
            "--specpath", WORK_DIR]
    if onefile:
        args.append("--onefile")
    if os.path.exists(ICON):
        args += ["--icon", ICON]
    args.append(os.path.join(ROOT, "main.py"))
    return args


def pyinstaller_installed():
    """PyInstaller доступен текущему интерпретатору."""
    try:
        code = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=120).returncode
    except Exception:                              # noqa: BLE001
        return False
    return code == 0


def auto_py_to_exe_text():
    """Что вписать в поля auto-py-to-exe (он делает то же самое)."""
    return "\n".join((
        "auto-py-to-exe — значения полей:",
        "",
        "  Script Location      : %s" % os.path.join(ROOT, "main.py"),
        "  Onefile              : One Directory",
        "  Console Window       : Window Based (hide the console)",
        "  Icon                 : %s" % (ICON if os.path.exists(ICON)
                                          else "сначала: python build_exe.py --icon"),
        "  Name                 : %s" % NAME,
        "  Additional Files     : — (папка db копируется рядом с exe)",
        "  Advanced → --paths   : %s" % ROOT,
        "",
        "После сборки положите db рядом с exe:",
        "  python build_exe.py --stage --stage-dir \"%s\"" % os.path.join(DIST_DIR, "db"),
        "",
        "Готовый exe: %s" % os.path.join(DIST_DIR, NAME + ".exe"),
    ))


def build(onefile=False, with_schemes=False, skip_check=False):
    """Собрать exe и папку db. Возвращает код возврата."""
    errors, warnings, items = check()
    if errors and not skip_check:
        print("Сборка невозможна: нет обязательных файлов.")
        for message in errors:
            print("  ошибка: %s" % message)
        return 2
    for message in warnings:
        print("  пропущено: %s" % message)
    if not pyinstaller_installed():
        print("PyInstaller не установлен для %s." % sys.executable)
        print("  py -3.13 -m pip install pyinstaller      # затем повторить")
        print("  или соберите в auto-py-to-exe — см. --auto-py-to-exe")
        print("Папка данных при этом собирается: --stage")
        return 3

    make_icon()
    print("PyInstaller: %s" % " ".join(pyinstaller_args(onefile)))
    code = subprocess.call(pyinstaller_args(onefile))
    if code != 0:
        print("PyInstaller завершился с кодом %s" % code)
        return code

    folder = DIST_ROOT if onefile else DIST_DIR
    exe = os.path.join(folder, NAME + ".exe")
    if not os.path.exists(exe):
        print("exe не найден: %s" % exe)
        return 4
    stage(os.path.join(folder, "db"), with_schemes=with_schemes)
    verify(exe)
    print("Готово: %s" % exe)
    return 0


def verify(exe):
    """Проверка собранного приложения без окна (``--selftest``)."""
    report = os.path.join(os.path.dirname(exe), "selftest.json")
    if os.path.exists(report):
        os.remove(report)
    try:
        code = subprocess.run([exe, "--selftest", report], timeout=180).returncode
    except Exception as exc:                       # noqa: BLE001
        print("Проверка не запустилась: %s" % exc)
        return False
    if not os.path.exists(report):
        print("Проверка не записала отчёт: %s (код %s)" % (report, code))
        return False
    try:
        with open(report, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:                       # noqa: BLE001
        print("Отчёт проверки не прочитан: %s" % exc)
        return False
    print("Проверка сборки: %s" % data.get("итог"))
    for name, info in data.get("файлы", {}).items():
        print("  %-20s %-5s %s" % (name, "есть" if info.get("есть") else "нет",
                                   info.get("путь")))
    for problem in data.get("ошибки", []):
        print("  ошибка: %s" % problem)
    return data.get("итог") == "ok" and code == 0


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Сборка «Редактора схем» с папкой данных db.")
    parser.add_argument("--check", action="store_true",
                        help="проверить файлы данных и инструментов")
    parser.add_argument("--stage", action="store_true",
                        help="только собрать папку db (без exe)")
    parser.add_argument("--stage-dir", default=None,
                        help="куда собрать db (по умолчанию dist/<имя>/db)")
    parser.add_argument("--onefile", action="store_true",
                        help="собрать один exe (db всё равно рядом)")
    parser.add_argument("--with-schemes", action="store_true",
                        help="положить в db примеры схем")
    parser.add_argument("--icon", action="store_true",
                        help="только собрать assets/editor.ico")
    parser.add_argument("--force-icon", action="store_true",
                        help="перерисовать иконку заново")
    parser.add_argument("--auto-py-to-exe", action="store_true",
                        help="напечатать значения полей auto-py-to-exe")
    parser.add_argument("--skip-check", action="store_true",
                        help="собирать даже при нехватке обязательных файлов")
    args = parser.parse_args(argv)

    if args.icon:
        make_icon(force=args.force_icon)
        return 0
    if args.auto_py_to_exe:
        print(auto_py_to_exe_text())
        return 0
    if args.check:
        errors, warnings, items = check()
        report(items)
        print("\nошибок: %d, предупреждений: %d" % (len(errors), len(warnings)))
        for message in errors:
            print("  ошибка: %s" % message)
        for message in warnings:
            print("  пропущено: %s" % message)
        return 0 if not errors else 2
    if args.stage:
        errors, warnings, items = check()
        stage(args.stage_dir, with_schemes=args.with_schemes)
        for message in warnings:
            print("  пропущено: %s" % message)
        return 0
    return build(onefile=args.onefile, with_schemes=args.with_schemes,
                 skip_check=args.skip_check)


if __name__ == "__main__":
    raise SystemExit(main())
