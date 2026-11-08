# -*- coding: utf-8 -*-
"""Интеграция папки ``standard_editor`` в редактор схем.

``standard_editor/`` — отдельный набор инструментов для работы со стандартами
СТО в JSON: текстовый формат изменений ``*.изм.txt``, движок их применения
(``apply_changes.py``), редактор изменений с окном (``changes_gui.py``),
создание нового стандарта на основе выбранного (``make_standard.py``) и
отчёт Word (``json_to_docx.py``).

Этот модуль — единственная точка входа для редактора схем:

* ничего не читает и не импортирует при загрузке (``import`` дешёвый);
* tkinter не тянет — окна живут в :mod:`standards_ui`;
* не меняет ``sys.path`` без вызова :func:`module` (папка добавляется лениво,
  только когда реально нужен модуль стандарта).

    python standards_editor.py --list
    python standards_editor.py --check
    python standards_editor.py --assemble --out редакция.json
    python standards_editor.py --docx редакция.json --docx-out отчёт.docx
"""

from __future__ import annotations

import glob
import importlib
import json
import os
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))

#: Папка с инструментами стандартов (лежит рядом с редактором).
FOLDER = os.path.join(ROOT, "standard_editor")

#: Каталог примеров изменений внутри неё.
CHANGES_FOLDER = os.path.join(FOLDER, "changes_text")

#: Модули стандартов, к которым обращается интеграция.
MODULE_NAMES = ("apply_changes", "changes_editor", "changes_gui",
                "make_standard", "json_to_docx", "node_table")

_LAST_ERROR = None
_CACHE = {}


# ---------------------------------------------------------------------------
# Временные каталоги
# ---------------------------------------------------------------------------
def workdir(prefix="std-"):
    """Временный каталог внутри рабочей папки.

    ``tempfile.mkdtemp`` на Windows ставит на каталог DACL 0700 — под
    политикой редактора в него нельзя ни писать, ни заглянуть. Поэтому
    каталог создаётся обычным ``makedirs`` с уникальным именем, а системный
    ``%TEMP%`` не используется вовсе.
    """
    base = os.path.join(ROOT, "output", ".tmp")
    os.makedirs(base, exist_ok=True)
    for _attempt in range(200):
        path = os.path.join(base, prefix + uuid.uuid4().hex[:12])
        try:
            os.makedirs(path)
        except FileExistsError:
            continue
        except OSError:
            continue
        return path
    raise OSError("не удалось создать временный каталог в %s" % base)


def cleanup(path):
    """Удалить временный каталог, созданный :func:`workdir`."""
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return
    for name in names:
        target = os.path.join(path, name)
        try:
            if os.path.isdir(target):
                os.rmdir(target)
            else:
                os.unlink(target)
        except OSError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Доступ к папке и модулям
# ---------------------------------------------------------------------------
def folder():
    """Путь к папке ``standard_editor``."""
    return FOLDER


def available():
    """Инструменты стандартов на месте (папка и движок на месте)."""
    return os.path.isdir(FOLDER) and os.path.isfile(
        os.path.join(FOLDER, "apply_changes.py"))


def error():
    """Последняя ошибка загрузки модулей стандартов (или None)."""
    return _LAST_ERROR


class _TempDir:
    """Замена ``tempfile.TemporaryDirectory`` из стандартных инструментов.

    Их окна и консольные команды держат промежуточные файлы в системном
    ``%TEMP%``: под политикой редактора такой каталог нельзя ни заполнить,
    ни удалить (DACL 0700). Здесь тот же контракт, но каталог создаётся в
    ``output/.tmp`` рабочей папки и удаляется вручную.
    """

    def __init__(self, suffix=None, prefix=None, dir=None,
                 ignore_cleanup_errors=False, delete=True, **kwargs):
        self.prefix = prefix or "tmp-"
        self.path = None
        self._delete = delete

    def __enter__(self):
        self.path = workdir(self.prefix)
        return self.path

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()
        return False

    def cleanup(self):
        if self.path and self._delete:
            cleanup(self.path)


class _TempModule:
    """Модуль-обманка: подменяет ``tempfile`` только в чужом модуле."""

    TemporaryDirectory = _TempDir

    def __getattr__(self, name):
        import tempfile as real
        return getattr(real, name)


def _patch_tempdir():
    """Направить временные каталоги стандартных модулей в рабочую папку."""
    for name in MODULE_NAMES:
        loaded = sys.modules.get(name)
        if loaded is None or getattr(loaded, "_std_tempdir_patched", False):
            continue
        if getattr(loaded, "tempfile", None) is None:
            continue
        loaded.tempfile = _TempModule()
        loaded._std_tempdir_patched = True


def module(name):
    """Ленивый импорт модуля из ``standard_editor``.

    Папка добавляется в ``sys.path`` только здесь, чтобы импорт редактора
    схем не зависел от инструментов стандартов.
    """
    global _LAST_ERROR
    if name in _CACHE:
        return _CACHE[name]
    if not available():
        _LAST_ERROR = "папка standard_editor не найдена: %s" % FOLDER
        raise ImportError(_LAST_ERROR)
    if FOLDER not in sys.path:
        sys.path.insert(0, FOLDER)
    try:
        loaded = importlib.import_module(name)
    except Exception as exc:                       # noqa: BLE001
        _LAST_ERROR = "модуль %s не загрузился: %s" % (name, exc)
        raise
    _CACHE[name] = loaded
    _patch_tempdir()
    _LAST_ERROR = None
    return loaded


def reset_cache():
    """Забыть загруженные модули (для тестов)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Стандарты: список и сведения
# ---------------------------------------------------------------------------
def standard_folders():
    """Папки, в которых ищутся JSON стандартов."""
    return (("standard_editor", FOLDER),
            ("standards_base", os.path.join(ROOT, "standards_base")))


def load(path):
    """Прочитать JSON стандарта."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path):
    """SHA-256 файла — так же, как в ``apply_changes``."""
    try:
        return module("apply_changes").sha256_file(path)
    except Exception:                              # noqa: BLE001
        return ""


def standard_info(data, path=None):
    """Сведения о стандарте для списков и окон."""
    data = data if isinstance(data, dict) else {}
    info = {
        "путь": path,
        "имя": os.path.basename(path) if path else "",
        "шифр": str(data.get("Шифр стандарта") or ""),
        "обозначение": str(data.get("Обозначение стандарта") or ""),
        "дата": str(data.get("Дата введения") or ""),
        "принадлежность": str(data.get("Принадлежность стандарта") or ""),
        "шкафов": 0, "таблиц": 0, "строк": 0,
        "редакция": len(data.get("Редакция") or []),
        "размер": os.path.getsize(path) if path and os.path.isfile(path) else 0,
    }
    try:
        stats = module("make_standard").stats_of(data)
    except Exception:                              # noqa: BLE001
        stats = {}
    info["шкафов"] = stats.get("cabinets", 0)
    info["таблиц"] = stats.get("tables", 0)
    info["строк"] = stats.get("rows", 0)
    return info


def standards(with_changes=True):
    """Список стандартов: ``standard_editor`` и ``standards_base``.

    Одинаковые файлы (по имени) не дублируются: приоритет у
    ``standard_editor`` — именно его базами правит редактор изменений.
    """
    result, seen = [], set()
    for label, path in standard_folders():
        for candidate in sorted(glob.glob(os.path.join(path, "*.json"))):
            name = os.path.basename(candidate)
            key = name.lower()
            if key in seen:
                continue
            try:
                data = load(candidate)
            except Exception:                      # noqa: BLE001
                continue
            if not isinstance(data, dict) or not isinstance(
                    data.get("Содержимое стандарта"), dict):
                continue
            seen.add(key)
            info = standard_info(data, candidate)
            info["папка"] = label
            info["изменений"] = (changes_for(info["шифр"])
                                 if with_changes else 0)
            result.append(info)
    result.sort(key=lambda item: (item["папка"] != "standard_editor",
                                  item["имя"]))
    return result


def default_base():
    """Путь к базовому стандарту по умолчанию (база редактора изменений)."""
    preferred = os.path.join(FOLDER, "СТО 56947007-33.040.20.279-2019.json")
    if os.path.isfile(preferred):
        return preferred
    for item in standards():
        return item["путь"]
    return ""


# ---------------------------------------------------------------------------
# Изменения
# ---------------------------------------------------------------------------
def change_files(folder_path=None):
    """Файлы ``*.изм.txt`` в каталоге изменений."""
    folder_path = folder_path or CHANGES_FOLDER
    if not os.path.isdir(folder_path):
        return []
    try:
        suffix = module("changes_editor").TEXT_EXT
    except Exception:                              # noqa: BLE001
        suffix = ".изм.txt"
    return sorted(glob.glob(os.path.join(folder_path, "*" + suffix)))


def change_header(path):
    """Шапка изменения: ``{поле: значение}`` без загрузки движка."""
    header = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                if ":" not in text:
                    break
                key, _, value = text.partition(":")
                header[key.strip().upper()] = value.strip()
    except OSError:
        return header
    return header


def changes_for(code, folder_path=None):
    """Сколько изменений относится к стандарту с таким шифром."""
    if not code:
        return 0
    count = 0
    for path in change_files(folder_path):
        header = change_header(path)
        if header.get("БАЗА") == code:
            count += 1
    return count


def changes_summary(folder_path=None):
    """Краткая сводка по каталогу изменений для окон и консоли."""
    rows = []
    for path in change_files(folder_path):
        header = change_header(path)
        rows.append({
            "путь": path,
            "имя": os.path.basename(path),
            "идентификатор": header.get("ИЗМЕНЕНИЕ", ""),
            "версия": header.get("ВЕРСИЯ", ""),
            "дата": header.get("ДАТА", ""),
            "статус": header.get("СТАТУС", ""),
            "название": header.get("НАЗВАНИЕ", ""),
            "база": header.get("БАЗА", ""),
        })
    return rows


# ---------------------------------------------------------------------------
# Сборка редакции
# ---------------------------------------------------------------------------
def compile_changes(folder_path=None):
    """Скомпилировать ``*.изм.txt`` в JSON-наборы изменений.

    Возвращает ``(compiled, errors)``: ``compiled`` — список
    ``(путь, изменение, предупреждения)`` в порядке применения.
    """
    ce = module("changes_editor")
    compiled, errors = [], []
    for path in change_files(folder_path):
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            change_set, warnings = ce.compile_text(text)
        except Exception as exc:                   # noqa: BLE001
            errors.append("%s: %s" % (os.path.basename(path), exc))
            continue
        compiled.append((path, change_set, warnings))
    compiled.sort(key=ce.sort_key)
    return compiled, errors


def assembly(base_path, folder_path=None, strict=False, ignore_hash=False):
    """Собрать редакцию: база + все изменения каталога.

    Возвращает словарь: ``ok``, ``data`` (готовая редакция), ``отчёт``
    (журнал сборки текстом), ``проблемы``, ``предупреждения``,
    ``изменений``, ``операций``, ``ошибка``.
    """
    ac = module("apply_changes")
    folder_path = folder_path or CHANGES_FOLDER
    empty = {"ok": False, "data": None, "отчёт": "", "проблемы": [],
             "предупреждения": [], "изменений": 0, "операций": 0}
    if not os.path.isfile(base_path):
        return dict(empty, ошибка="нет файла базового стандарта: %s" % base_path)
    if not os.path.isdir(folder_path):
        return dict(empty, ошибка="нет папки изменений: %s" % folder_path)
    compiled, errors = compile_changes(folder_path)
    if errors:
        return dict(empty, ошибка="\n".join(errors))
    if not compiled and not glob.glob(os.path.join(folder_path, "*.json")):
        return dict(empty, ошибка="в папке нет ни одного изменения: %s"
                                  % folder_path)
    tmp = workdir("sync-")
    try:
        mapping = {}
        for index, (source, change_set, _warnings) in enumerate(compiled):
            target = os.path.join(tmp, "%03d.json" % index)
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(change_set, handle, ensure_ascii=False, indent=2)
            mapping[os.path.abspath(target)] = source
        patterns = [tmp]
        if glob.glob(os.path.join(folder_path, "*.json")):
            patterns.append(folder_path)
        try:
            (data, context, registry, skipped, base_sha,
             problems, warnings) = ac.assemble(
                base_path, patterns, strict=strict, ignore_hash=ignore_hash)
        except ac.ChangeError as exc:
            message = str(exc)
            for temporary, source in mapping.items():
                message = message.replace(temporary, source)
            return dict(empty, ошибка=message)
        # В журнале движок называет временные файлы 000.json, 001.json…
        # Возвращаем настоящие имена исходных *.изм.txt.
        def real_name(text):
            for temporary, source in mapping.items():
                text = (text.replace(temporary, source)
                        .replace(os.path.basename(temporary),
                                 os.path.basename(source)))
            return text

        skipped = [real_name(item) for item in skipped]
        warnings = [real_name(item) for item in warnings]
        problems = [real_name(item) for item in problems]
        report = real_name(ac.build_report(context, registry, skipped, base_sha,
                                           problems, warnings))
    finally:
        cleanup(tmp)
    return {
        "ok": not problems,
        "data": data,
        "отчёт": report,
        "проблемы": list(problems),
        "предупреждения": list(warnings),
        "изменений": len(registry),
        "операций": sum(row.get("Операций", 0) for row in registry),
        "база": os.path.basename(base_path),
        "sha": base_sha,
        "ошибка": None,
    }


def write_json(data, path, indent=2):
    """Записать редакцию в файл, вернуть размер."""
    folder_path = os.path.dirname(os.path.abspath(path))
    if folder_path and not os.path.isdir(folder_path):
        os.makedirs(folder_path, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent)
        handle.write("\n")
    return os.path.getsize(path)


# ---------------------------------------------------------------------------
# Новый стандарт на основе выбранного
# ---------------------------------------------------------------------------
def build_standard(source_path, meta=None, replacements=None, keep=None,
                   renumber=True):
    """Собрать новый стандарт на основе выбранного, ничего не записывая.

    ``meta`` — реквизиты (``Обозначение стандарта``, ``Шифр стандарта``,
    ``Дата введения``, ``Принадлежность стандарта``, ``Область применения``);
    ``replacements`` — список строк «старое => новое»; ``keep`` — шифры
    шкафов, которые остаются.
    """
    ms = module("make_standard")
    try:
        source = load(source_path)
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "ошибка": "не прочитан исходный стандарт: %s" % exc,
                "проблемы": [], "предупреждения": [], "отчёт": "",
                "статистика": {}, "было": {}, "data": None}
    try:
        result = ms.build(source, meta=meta or {}, replacements=replacements,
                          keep=keep, renumber=renumber,
                          source_label=os.path.basename(source_path))
    except ms.StandardError as exc:
        return {"ok": False, "ошибка": str(exc), "проблемы": [str(exc)],
                "предупреждения": [], "отчёт": "", "статистика": {},
                "было": {}, "data": None}
    report = ms.report(result)
    return {
        "ok": not result["problems"],
        "data": result["data"],
        "проблемы": list(result["problems"]),
        "предупреждения": list(result["warnings"]),
        "отчёт": report,
        "статистика": result["stats"],
        "было": result.get("source_stats") or {},
        "ошибка": (None if not result["problems"] else
                   "проверка не пройдена: %d проблем" % len(result["problems"])),
        "путь": "",
        "размер": 0,
    }


def new_standard(source_path, out_path, meta=None, replacements=None,
                 keep=None, renumber=True, overwrite=False):
    """Собрать и записать новый стандарт на основе выбранного.

    Параметры — как у :func:`build_standard`.
    """
    ms = module("make_standard")
    payload = build_standard(source_path, meta=meta, replacements=replacements,
                             keep=keep, renumber=renumber)
    payload["путь"] = out_path
    if not payload["ok"]:
        return payload
    try:
        payload["размер"] = ms.write_standard(payload["data"], out_path,
                                              overwrite=overwrite)
    except ms.StandardError as exc:
        payload["ok"] = False
        payload["ошибка"] = str(exc)
    except OSError as exc:
        payload["ok"] = False
        payload["ошибка"] = "не удалось записать файл: %s" % exc
    return payload


def validate_standard(data):
    """Проверить стандарт: ``(проблемы, предупреждения)``."""
    try:
        return module("make_standard").validate_standard(data)
    except Exception as exc:                       # noqa: BLE001
        return (["проверка не выполнена: %s" % exc], [])


def cabinets_of(data):
    """Список шкафов стандарта для окон: ``[{шифр, раздел, таблиц, строк}]``."""
    try:
        pairs = module("make_standard").cabinets(data)
    except Exception:                              # noqa: BLE001
        return []
    rows = []
    for _name, cabinet in pairs:
        tables = cabinet.get("Таблицы") or {}
        rows.append({
            "шифр": cabinet.get("Шифр шкафа") or "",
            "раздел": cabinet.get("Раздел стандарта") or "",
            "таблиц": len(tables),
            "строк": sum(len(table.get("Строки") or [])
                         for table in tables.values()
                         if isinstance(table, dict)),
        })
    return rows


# ---------------------------------------------------------------------------
# Отчёт DOCX
# ---------------------------------------------------------------------------
def docx_available():
    """В текущем Python есть python-docx."""
    try:
        import docx                              # noqa: F401
        return True
    except Exception:                              # noqa: BLE001
        return False


def docx_interpreters():
    """Интерпретаторы, в которых есть python-docx (текущий — первым)."""
    found = []
    if docx_available():
        found.append(sys.executable)
    candidates = []
    try:
        output = subprocess.check_output(["py", "-0p"], text=True,
                                         stderr=subprocess.DEVNULL, timeout=10)
        for line in output.splitlines():
            marker = line.rfind("\\")
            if marker > 0 and line.rstrip().endswith("python.exe"):
                candidates.append(line[line.rfind(":") - 1:].strip())
    except Exception:                              # noqa: BLE001
        pass
    for version in ("313", "312", "311", "310"):
        candidates.append(r"C:\Python%s\python.exe" % version)
    seen = set()
    for path in candidates:
        path = os.path.normpath(path)
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        if key == os.path.normcase(os.path.abspath(sys.executable)):
            continue
        try:
            code = subprocess.run(
                [path, "-c", "import docx"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=20).returncode
        except Exception:                          # noqa: BLE001
            continue
        if code == 0:
            found.append(path)
    return found


def docx_interpreter():
    """Первый интерпретатор с python-docx (или None)."""
    found = docx_interpreters()
    return found[0] if found else None


def build_docx(data, out_path, toc=True):
    """Построить отчёт DOCX по стандарту или собранной редакции.

    Если в текущем Python нет ``python-docx``, отчёт строится во внешнем
    интерпретаторе, где пакет есть (результат тот же).
    """
    empty = {"ok": False, "статистика": {}, "ошибка": "", "путь": out_path,
             "интерпретатор": sys.executable}
    if isinstance(data, str):
        try:
            data = load(data)
        except Exception as exc:                   # noqa: BLE001
            return dict(empty, ошибка="не прочитан JSON: %s" % exc)
    folder_path = os.path.dirname(os.path.abspath(out_path))
    if folder_path and not os.path.isdir(folder_path):
        os.makedirs(folder_path, exist_ok=True)
    if docx_available():
        return _docx_here(data, out_path, toc, empty)
    interpreter = docx_interpreter()
    if not interpreter:
        return dict(empty, ошибка=(
            "python-docx не установлен ни в одном найденном Python.\n"
            "Установите: \"%s\" -m pip install python-docx" % sys.executable))
    return _docx_elsewhere(interpreter, data, out_path, toc, empty)


def _docx_here(data, out_path, toc, empty):
    global _LAST_ERROR
    try:
        builder = module("json_to_docx")
    except SystemExit as exc:
        return dict(empty, ошибка=str(exc) or "нет python-docx")
    except Exception as exc:                       # noqa: BLE001
        return dict(empty, ошибка="json_to_docx не загрузился: %s" % exc)
    try:
        stats = builder.build_report(data, out_path, toc=toc)
    except SystemExit as exc:
        return dict(empty, ошибка=str(exc) or "нет python-docx")
    except Exception as exc:                       # noqa: BLE001
        _LAST_ERROR = str(exc)
        return dict(empty, ошибка="отчёт не построен: %s" % exc)
    return {"ok": True, "статистика": dict(stats or {}), "ошибка": None,
            "путь": out_path, "интерпретатор": sys.executable}


_RUNNER = '''# -*- coding: utf-8 -*-
import json, sys, traceback
sys.path.insert(0, {folder!r})
data_path, out_path, toc_flag, result_path = sys.argv[1:5]
payload = {{"ok": False, "error": "не выполнилось"}}
try:
    import json_to_docx
    with open(data_path, encoding="utf-8") as handle:
        data = json.load(handle)
    stats = json_to_docx.build_report(data, out_path, toc=(toc_flag == "1"))
    payload = {{"ok": True, "stats": stats}}
except SystemExit as exc:
    payload = {{"ok": False, "error": str(exc) or "нет python-docx"}}
except BaseException as exc:
    payload = {{"ok": False,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc()}}
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False)
'''


def _docx_elsewhere(interpreter, data, out_path, toc, empty):
    """Отчёт DOCX во внешнем интерпретаторе (там есть python-docx)."""
    tmp = workdir("docx-")
    try:
        data_path = os.path.join(tmp, "edition.json")
        with open(data_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        runner_path = os.path.join(tmp, "runner.py")
        with open(runner_path, "w", encoding="utf-8") as handle:
            handle.write(_RUNNER.format(folder=FOLDER))
        result_path = os.path.join(tmp, "result.json")
        log_path = os.path.join(tmp, "stderr.txt")
        with open(log_path, "w", encoding="utf-8") as log:
            try:
                code = subprocess.run(
                    [interpreter, runner_path, data_path, out_path,
                     "1" if toc else "0", result_path],
                    stdout=subprocess.DEVNULL, stderr=log, timeout=600
                ).returncode
            except Exception as exc:               # noqa: BLE001
                return dict(empty, ошибка="внешний интерпретатор не запустился: %s"
                                          % exc, интерпретатор=interpreter)
        payload = {}
        if os.path.isfile(result_path):
            try:
                with open(result_path, encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception:                      # noqa: BLE001
                payload = {}
        if not payload.get("ok"):
            detail = payload.get("error") or "код %s" % code
            if not payload.get("error"):
                try:
                    with open(log_path, encoding="utf-8") as handle:
                        tail = handle.read()[-800:]
                    detail = "%s\n%s" % (detail, tail.strip())
                except OSError:
                    pass
            return dict(empty, ошибка="отчёт не построен: %s" % detail,
                        интерпретатор=interpreter)
    finally:
        cleanup(tmp)
    return {"ok": True, "статистика": dict(payload.get("stats") or {}),
            "ошибка": None, "путь": out_path, "интерпретатор": interpreter}


# ---------------------------------------------------------------------------
# Консоль
# ---------------------------------------------------------------------------
def _print_standards():
    rows = standards()
    if not rows:
        print("Стандартов не найдено в %s и standards_base"
              % os.path.basename(FOLDER))
        return 1
    print("%-28s %-34s %6s %6s %6s  %s"
          % ("Файл", "Шифр", "Шкафы", "Табл.", "Изм.", "Папка"))
    for item in rows:
        print("%-28s %-34s %6d %6d %6d  %s"
              % (item["имя"][:28], item["шифр"][:34], item["шкафов"],
                 item["таблиц"], item["изменений"], item["папка"]))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    base = argv[argv.index("--base") + 1] if "--base" in argv \
        else default_base()
    changes = argv[argv.index("--changes") + 1] if "--changes" in argv \
        else CHANGES_FOLDER
    if "--list" in argv or not argv:
        return _print_standards()
    if "--check" in argv:
        compiled, errors = compile_changes(changes)
        print("Изменений в %s: %d, файлов: %d"
              % (os.path.basename(changes), len(compiled),
                 len(change_files(changes))))
        for path, change_set, warnings in compiled:
            print("  %-24s %s v%s, операций %d"
                  % (os.path.basename(path), change_set["Идентификатор"],
                     change_set.get("Версия", 1),
                     len(change_set.get("Изменения") or [])))
            for warning in warnings:
                print("      ! %s" % warning)
        for problem in errors:
            print("  ОШИБКА %s" % problem)
        return 1 if errors else 0
    if "--assemble" in argv:
        result = assembly(base, changes, strict="--strict" in argv,
                          ignore_hash="--ignore-hash" in argv)
        print(result["отчёт"] or result["ошибка"])
        if not result["ok"]:
            return 1
        out = argv[argv.index("--out") + 1] if "--out" in argv else ""
        if out:
            size = write_json(result["data"], out)
            print("\nРедакция записана: %s (%.1f КБ)" % (out, size / 1024.0))
        return 0
    if "--docx" in argv:
        index = argv.index("--docx")
        source = argv[index + 1] if len(argv) > index + 1 else ""
        if not source:
            print("Укажите JSON: python standards_editor.py --docx файл.json",
                  file=sys.stderr)
            return 2
        out = argv[argv.index("--docx-out") + 1] if "--docx-out" in argv \
            else os.path.splitext(source)[0] + ".docx"
        result = build_docx(source, out, toc="--no-toc" not in argv)
        if not result["ok"]:
            print("ОШИБКА DOCX: %s" % result["ошибка"], file=sys.stderr)
            return 1
        print("Отчёт DOCX: %s" % out)
        print("  шкафов %(cabinets)s, комплектов %(complects)s, "
              "таблиц %(tables)s, строк %(rows)s" % result["статистика"])
        print("  интерпретатор: %s" % result["интерпретатор"])
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
