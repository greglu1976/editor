# -*- coding: utf-8 -*-
"""Проверка сборки приложения и папки данных ``db``.

Запуск:
    python3 tests/test_packaging.py

Проверяет:

1. ``apppaths`` — папка данных, переменная ``EDITOR_DB``, порядок поиска
   (db → рядом с программой → внутри сборки);
2. план сборки ``build_exe.plan`` — все обязательные файлы на месте;
3. ``build_exe.stage`` — папка db собирается и читается как рабочая;
4. модули в отдельном процессе с ``EDITOR_DB`` берут файлы из db;
5. ``main.py --selftest`` — отчёт о сборке без окна;
6. имитацию замороженной сборки (``sys.frozen``, ``_MEIPASS``);
7. иконку ``assets/editor.ico`` и командную строку ``build_exe.py``.

PyInstaller для этих проверок не нужен: сборка exe проверяется отдельно,
когда пакет установлен (``python build_exe.py``).
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import apppaths               # noqa: E402
import build_exe              # noqa: E402
import structure              # noqa: E402

WORK = os.path.join(ROOT, "output", "_pkg_test_%d" % os.getpid())
FAILURES = []
PYTHON = sys.executable


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def _run_to_files(command, env=None, log="child"):
    """Запуск процесса с выводом в файлы: каналы под политикой ненадёжны."""
    os.makedirs(WORK, exist_ok=True)
    out_path = os.path.join(WORK, log + ".out.txt")
    err_path = os.path.join(WORK, log + ".err.txt")
    environment = dict(os.environ)
    environment.update(env or {})
    environment["PYTHONIOENCODING"] = "utf-8"
    with open(out_path, "w", encoding="utf-8") as out, \
            open(err_path, "w", encoding="utf-8") as err:
        code = subprocess.call(command, cwd=ROOT, env=environment,
                               stdout=out, stderr=err, timeout=300)
    output = open(out_path, encoding="utf-8", errors="replace").read()
    errors = open(err_path, encoding="utf-8", errors="replace").read()
    return subprocess.CompletedProcess(command, code, stdout=output,
                                       stderr=errors)


def child(code, env=None):
    """Запуск кода в отдельном процессе (у модулей пути кэшируются)."""
    return _run_to_files([PYTHON, "-X", "utf8", "-c", code], env, "child")


def test_apppaths():
    print("1. apppaths: папка данных и порядок поиска")
    check(apppaths.app_dir() == ROOT, "папка приложения — папка модулей")
    check(not apppaths.is_frozen(), "обычный запуск не считается сборкой")
    check(apppaths.db_dir() == os.path.join(ROOT, "db"),
          "по умолчанию данные ищутся в db рядом с программой")
    check(apppaths.bundled_dir() is None, "вне сборки _MEIPASS отсутствует")

    probe = os.path.join(WORK, "paths", "db")
    os.makedirs(probe, exist_ok=True)
    with open(os.path.join(probe, "probe.json"), "w", encoding="utf-8") as handle:
        json.dump({"ок": True}, handle)

    known = apppaths.data_path("cabinets.json")
    check(os.path.exists(known), "существующий файл найден: %s" % known)
    check(not apppaths.exists("probe.json"),
          "файл из чужой папки не подхватывается")

    result = child("import apppaths; print(apppaths.db_dir()); "
                   "print(apppaths.data_path('probe.json'))",
                   {"EDITOR_DB": probe})
    lines = result.stdout.strip().splitlines()
    check(result.returncode == 0 and lines
          and os.path.normcase(lines[0]) == os.path.normcase(probe),
          "EDITOR_DB переопределяет папку данных")
    check(len(lines) > 1 and lines[1].endswith("probe.json")
          and os.path.exists(lines[1]),
          "data_path находит файл в папке EDITOR_DB")

    missing = apppaths.data_path("komplekts.json")
    check(os.path.basename(os.path.dirname(missing)) == "db"
          or missing.startswith(apppaths.db_dir()),
          "отсутствующий файл адресуется в db: %s" % missing)

    summary = apppaths.describe()
    check(set(summary) == {"папка", "данные", "сборка", "распаковка"},
          "describe() отдаёт четыре ключа")


def test_plan():
    print("2. план сборки")
    errors, warnings, items = build_exe.check()
    check(not errors, "обязательные файлы на месте (%d ошибок)" % len(errors))
    check(len(items) >= 7, "в плане %d файлов" % len(items))
    targets = {item["цель"] for item in items}
    for name in ("cabinets.json", "structure.json", "cabs_signals.json"):
        check(name in targets, "в db попадёт %s" % name)
    check(any(target.startswith("EA" + os.sep) for target in targets),
          "стандарты EA попадают в db/EA")
    check({os.path.join("tools", "build_structure.py"),
           os.path.join("tools", "check_structure.py")} <= targets,
          "сборщик и проверка структуры попадают в db/tools")
    check(all(item["байт"] >= 0 for item in items), "размеры файлов посчитаны")


def test_stage():
    print("3. сборка папки db")
    target = os.path.join(WORK, "db")
    path, copied, skipped = build_exe.stage(target, quiet=True)
    check(os.path.normcase(path) == os.path.normcase(target),
          "папка собрана по указанному пути")
    check(copied >= 7, "скопировано файлов: %d" % copied)
    for name in ("cabinets.json", "structure.json", "cabs_signals.json",
                 "README.txt"):
        check(os.path.exists(os.path.join(target, name)),
              "в db есть %s" % name)
    check(os.path.isdir(os.path.join(target, "EA")),
          "в db есть папка EA")
    check(os.path.isfile(os.path.join(target, "tools", "build_structure.py")),
          "в db есть сборщик структуры")

    size = sum(os.path.getsize(os.path.join(base, name))
               for base, _, names in os.walk(target) for name in names)
    check(size > 5 * 1024 * 1024, "объём db: %.1f МБ" % (size / 1048576.0))


def test_modules_use_db():
    print("4. модули читают из db (EDITOR_DB)")
    target = os.path.join(WORK, "db")
    code = "\n".join((
        "import os",
        "import apppaths, cabs, komplekts, containers, structure",
        "import ea_standard, structure_tools",
        "print(os.path.normcase(structure.DEFAULT_PATH))",
        "print(os.path.normcase(cabs.USER_CATALOG_PATH))",
        "print(os.path.normcase(komplekts.USER_CATALOG_PATH))",
        "print(os.path.normcase(containers.USER_CATALOG_PATH))",
        "print(os.path.normcase(ea_standard.FOLDER))",
        "print(os.path.normcase(structure_tools.TOOLS_DIR))",
        "print(len(structure.cabinets()))",
    ))
    result = child(code, {"EDITOR_DB": target})
    lines = result.stdout.strip().splitlines()
    check(result.returncode == 0 and len(lines) == 7,
          "модули загрузились с EDITOR_DB: %s"
          % (result.stderr.strip()[:80] or "ok"))
    if len(lines) == 7:
        db = os.path.normcase(os.path.abspath(target))
        for index, name in enumerate(("structure.json", "cabinets.json",
                                      "komplekts.json", "containers.json",
                                      "EA", "tools")):
            check(lines[index].startswith(db),
                  "%s берётся из db" % name)
        check(int(lines[6]) > 300, "шкафов из db: %s" % lines[6])


def test_selftest():
    print("5. проверка сборки без окна (--selftest)")
    target = os.path.join(WORK, "db")
    report = os.path.join(WORK, "selftest.json")
    if os.path.exists(report):
        os.remove(report)
    code = ("import sys; sys.argv = ['main.py', '--selftest', %r]; "
            "import runpy; runpy.run_path('main.py', "
            "run_name='__main__')" % report)
    result = child(code, {"EDITOR_DB": target})
    check(os.path.exists(report), "отчёт записан: %s" % report)
    if not os.path.exists(report):
        print(result.stderr.strip()[-500:])
        return
    with open(report, encoding="utf-8") as handle:
        data = json.load(handle)
    check(data["итог"] == "ok", "итог проверки: %s" % data["итог"])
    check(data["данные"] and os.path.normcase(data["данные"])
          == os.path.normcase(os.path.abspath(target)),
          "проверка увидела папку db")
    check(data["файлы"]["cabinets.json"]["есть"], "каталог шкафов найден")
    check(data["файлы"]["structure.json"]["есть"], "структура найдена")
    check(data.get("структура", {}).get("шкафов", 0) > 300,
          "структура прочитана: %s шкафов"
          % data.get("структура", {}).get("шкафов"))
    check(data.get("стандарты") >= 1,
          "стандарты прочитаны: %s" % data.get("стандарты"))
    check(data["сборка"] is False, "обычный запуск не помечен как сборка")


def test_frozen_imitation():
    print("6. имитация замороженной сборки")
    base = os.path.join(WORK, "frozen")
    exe_dir = os.path.join(base, "dist")
    unpack = os.path.join(base, "_internal")
    os.makedirs(os.path.join(exe_dir, "db"), exist_ok=True)
    os.makedirs(os.path.join(unpack, "db"), exist_ok=True)
    with open(os.path.join(exe_dir, "db", "flat.json"), "w",
              encoding="utf-8") as handle:
        handle.write("{}")
    with open(os.path.join(unpack, "db", "inside.json"), "w",
              encoding="utf-8") as handle:
        handle.write("{}")

    code = "\n".join((
        "import sys, os",
        "sys.frozen = True",
        "sys.executable = os.path.join(%r, 'Редактор схем.exe')" % exe_dir,
        "sys._MEIPASS = %r" % unpack,
        "import apppaths",
        "print(apppaths.is_frozen())",
        "print(os.path.normcase(apppaths.app_dir()))",
        "print(os.path.normcase(apppaths.db_dir()))",
        "print(os.path.normcase(apppaths.data_path('flat.json')))",
        "print(os.path.normcase(apppaths.data_path('inside.json')))",
        "print(os.path.normcase(apppaths.data_path('нет.json')))",
    ))
    result = child(code)
    lines = result.stdout.strip().splitlines()
    check(result.returncode == 0 and len(lines) == 6,
          "apppaths работает в замороженном режиме: %s"
          % (result.stderr.strip()[:120] or "ok"))
    if len(lines) == 6:
        check(lines[0] == "True", "режим сборки определён")
        check(lines[1] == os.path.normcase(os.path.abspath(exe_dir)),
              "папка приложения — папка exe, а не распаковки")
        check(lines[2] == os.path.normcase(os.path.join(exe_dir, "db")),
              "db берётся рядом с exe")
        check(lines[3] == os.path.normcase(os.path.join(exe_dir, "db",
                                                        "flat.json")),
              "файл из db рядом с exe")
        check(lines[4] == os.path.normcase(os.path.join(unpack, "db",
                                                        "inside.json")),
              "файл из упакованных данных (только чтение)")
        check(lines[5] == os.path.normcase(os.path.join(exe_dir, "db",
                                                        "нет.json")),
              "новый файл адресуется в db рядом с exe")


def test_icon():
    print("7. иконка приложения")
    path = build_exe.ICON
    check(os.path.exists(path), "иконка собрана: %s" % path)
    if not os.path.exists(path):
        return
    with open(path, "rb") as handle:
        header = handle.read(6)
    reserved, kind, count = struct.unpack("<HHH", header)
    check(reserved == 0 and kind == 1, "файл — ICO")
    check(count >= 5, "размеров в иконке: %d" % count)


def test_command_line():
    print("8. командная строка build_exe.py")

    def run(*args):
        """Вывод команды: пишем в файлы, каналы под политикой ненадёжны."""
        result = _run_to_files([PYTHON, "-X", "utf8", "build_exe.py"]
                               + list(args), None, "build_exe")
        return result.returncode, result.stdout, result.stderr

    code, stdout, stderr = run("--check")
    check(code == 0, "build_exe.py --check без ошибок")
    text = stdout or stderr
    check("ошибок: 0" in text, "проверка сообщает об отсутствии ошибок")

    code, stdout, stderr = run("--auto-py-to-exe")
    text = stdout or stderr
    check(code == 0, "справка auto-py-to-exe печатается")
    for fragment in ("Script Location", "One Directory", "Window Based",
                     "Name", "Additional Files", "db"):
        check(fragment in text, "в справке есть «%s»" % fragment)


def test_modules_have_no_flat_paths():
    print("9. пути данных заданы через apppaths")
    check(os.path.normcase(structure.DEFAULT_PATH)
          == os.path.normcase(apppaths.data_path("structure.json")),
          "structure.DEFAULT_PATH = apppaths.data_path")
    import ea_standard
    check(os.path.normcase(ea_standard.FOLDER)
          == os.path.normcase(apppaths.data_dir("EA")),
          "ea_standard.FOLDER = apppaths.data_dir")
    places = {
        "structure.py": os.path.join(ROOT, "structure", "structure.py"),
        "ea_standard.py": os.path.join(ROOT, "core", "ea_standard.py"),
        "structure_tools.py": os.path.join(ROOT, "structure",
                                           "structure_tools.py"),
    }
    for name, path in places.items():
        source = open(path, encoding="utf-8").read()
        flat = 'os.path.join(os.path.dirname(os.path.abspath(__file__)), "structure.json")'
        check(flat not in source, "%s не собирает путь к structure.json" % name)


def test_source_layout():
    """Пункт 32: новые пакеты на месте, старые импорты работают."""
    print("10. структура исходников")
    import importlib
    check(os.path.isdir(os.path.join(ROOT, "core"))
          and os.path.isfile(os.path.join(ROOT, "core", "__init__.py")),
          "пакет core/ на месте")
    check(os.path.isfile(os.path.join(ROOT, "structure", "__init__.py"))
          and os.path.isfile(os.path.join(ROOT, "structure", "structure.json")),
          "пакет structure/ со структурой на месте")
    check(os.path.normcase(apppaths.app_dir()) == os.path.normcase(ROOT),
          "apppaths указывает на корень, а не на core/")
    path = apppaths.data_path("structure.json")
    check(os.path.normcase(path)
          == os.path.normcase(os.path.join(ROOT, "structure",
                                           "structure.json")),
          "structure.json находится через apppaths")
    for old, new in (("cabs", "core.cabs"),
                     ("structure_tools", "structure.structure_tools"),
                     ("cabs_data", "structure.cabs_data")):
        check(importlib.import_module(old) is importlib.import_module(new),
              "%s перенаправляет на %s" % (old, new))


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    try:
        test_apppaths()
        test_plan()
        test_stage()
        test_modules_use_db()
        test_selftest()
        test_frozen_imitation()
        test_icon()
        test_command_line()
        test_modules_have_no_flat_paths()
        test_source_layout()
    except Exception:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        try:
            with open(os.path.join(ROOT, "output", "_pkg_traceback.txt"), "w",
                      encoding="utf-8") as handle:
                traceback.print_exc(file=handle)
        except OSError:
            pass
        FAILURES.append("проверка прервана исключением")
    finally:
        shutil.rmtree(WORK, ignore_errors=True)

    if FAILURES:
        print("\nПРОВАЛЫ (%d):" % len(FAILURES))
        for message in FAILURES:
            print("  x", message)
        return 1
    print("\nВсе проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
