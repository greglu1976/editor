# -*- coding: utf-8 -*-
"""Регрессионные тесты дублирования узлов стандарта (операция COPY).

Запуск:  python -B _parse\\test_duplicate.py
Тесты не пишут в рабочую папку: временные файлы создаются в %TEMP%.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

import apply_changes as ac          # noqa: E402
import changes_editor as ce         # noqa: E402

BASE = os.path.join(ROOT, "СТО 56947007-33.040.20.279-2019.json")
TMP = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
_created = []


def tmp_file(name):
    path = os.path.join(TMP, "sto-copy-%d-%s" % (os.getpid(), name))
    _created.append(path)
    return path


def cleanup():
    for path in _created:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def load_base():
    return ac.load_json(BASE)


def make_cs(ident, ops, order=10, supersedes=None):
    return {
        "Формат": ac.FORMAT,
        "Идентификатор": ident,
        "Версия": 1,
        "Наименование": ident,
        "Дата": "2026-01-01",
        "Порядок": order,
        "Статус": "действует",
        "Применимо к": {"Шифр стандарта": "СТО 56947007-33.040.20.279-2019"},
        "Заменяет": list(supersedes or []),
        "Изменения": ops,
    }


def assemble(changes, name="change"):
    paths = []
    try:
        for i, cs in enumerate(changes):
            path = tmp_file("%s-%d.json" % (name, i))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cs, f, ensure_ascii=False, indent=2)
            paths.append(path)
        return ac.assemble(BASE, paths, ignore_hash=True)
    finally:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass


def apply_one(op):
    base = load_base()
    data = json.loads(json.dumps(base, ensure_ascii=False))
    ctx = ac.Context()
    cs = make_cs("T", [op])
    allowed = ac.apply_op(data, cs, 0, op, ctx, False)
    return data, ctx, allowed


def cabinet(data, cipher):
    for key, value in data["Содержимое стандарта"].items():
        if isinstance(value, dict) and value.get("Шифр шкафа") == cipher:
            return key, value
    raise AssertionError("нет шкафа %r" % cipher)


def assert_raises(fn, needle=""):
    try:
        fn()
    except ac.ChangeError as exc:
        assert needle in str(exc), "ожидали %r в ошибке, получили: %s" % (
            needle, exc)
        return
    except ce.TextError as exc:
        assert needle in str(exc), "ожидали %r в ошибке, получили: %s" % (
            needle, exc)
        return
    raise AssertionError("ожидали ошибку %r" % needle)


# ---------------------------------------------------------------------------
# 1. COPY базовых видов узлов
# ---------------------------------------------------------------------------
def test_copy_positions():
    def run(obj, op):
        data = json.loads(json.dumps(obj, ensure_ascii=False))
        ctx = ac.Context()
        ac.apply_op(data, make_cs("P", [op]), 0, op, ctx, False)
        return data, ctx

    data, ctx = run({"a": 1, "b": 2}, {
        "Операция": "COPY", "Путь": ["a"], "Ключ": "a2", "После": "a"})
    assert list(data) == ["a", "a2", "b"], list(data)
    data, ctx = run({"a": 1, "b": 2}, {
        "Операция": "COPY", "Путь": ["b"], "Ключ": "b0", "Перед": "b"})
    assert list(data) == ["a", "b0", "b"], list(data)
    data, ctx = run({"a": 1, "b": 2}, {
        "Операция": "COPY", "Путь": ["b"], "Ключ": "bx", "После": "нет"})
    assert list(data) == ["a", "b", "bx"], list(data)
    assert any("не найден" in s for s in ctx.applied), ctx.applied

    data, ctx = run({"src": {"x": 1}, "dst": {"y": 2}}, {
        "Операция": "COPY", "Путь": ["src"], "Куда": ["dst"], "Ключ": "z"})
    assert data["dst"] == {"y": 2, "z": {"x": 1}}, data["dst"]
    assert data["src"] == {"x": 1}

    data, ctx = run({"arr": [{"n": 1}, {"n": 2}]}, {
        "Операция": "COPY", "Путь": ["arr", {"@index": 0}], "Позиция": 0})
    assert [x["n"] for x in data["arr"]] == [1, 1, 2], data["arr"]

    copy, stats = ac.build_copy("Таблица 5.3.1", {"Замены": ["5.3. => 5.9."]})
    assert copy == "Таблица 5.9.1"
    assert stats == {"keys": 0, "values": 1}, stats

    assert_raises(lambda: ac.build_copy({"obj": {"a": 1, "b": 2}}, {
        "Правки": [{"Путь": ["obj", "a"], "Переименовать": "b"}]}), "уже есть")
    print("  PASS positions / strings")


def test_copy_scalar():
    op = {"Операция": "COPY", "Путь": ["Обозначение стандарта"],
          "Ключ": "Обозначение стандарта (копия)"}
    data, ctx, allowed = apply_one(op)
    assert data["Обозначение стандарта (копия)"] == data["Обозначение стандарта"]
    assert allowed == ["/Обозначение стандарта (копия)", "/"]
    print("  PASS scalar")


def test_copy_row_and_edit():
    base = load_base()
    _, cab = cabinet(base, "ШЭТ 431.02-0")
    table0 = cab["Таблицы"]["Таблица 5.3.8"]["Строки"]
    before = json.loads(json.dumps(table0, ensure_ascii=False))
    path = ["Содержимое стандарта", {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}},
            "Таблицы", "Таблица 5.3.8", "Строки"]
    ops = [
        {"Операция": "COPY", "Путь": path + [{"@index": 1}],
         "Поля": {"Краткое наименование ФК": "Копия ФК"},
         "Перенумеровать": True,
         "Причина": "проверка копии строки"},
        {"Операция": "OVERRIDE", "Путь": path + [{"@index": 2}],
         "Поля": {"Примечание": "копия строки"}},
    ]
    data, ctx, registry, skipped, sha, problems, warnings = assemble(
        [make_cs("C1", ops)], "row")
    assert not problems, problems
    assert not warnings, warnings
    _, cab2 = cabinet(data, "ШЭТ 431.02-0")
    rows = cab2["Таблицы"]["Таблица 5.3.8"]["Строки"]
    assert len(rows) == len(before) + 1, (len(rows), len(before))
    assert rows[0] == before[0]
    assert rows[2]["Краткое наименование ФК"] == "Копия ФК"
    assert rows[2]["Примечание"] == "копия строки"
    assert [r["№"] for r in rows] == [str(i) for i in range(1, len(rows) + 1)]
    assert cab2["Таблицы"]["Таблица 5.3.8"]["Количество строк"] == len(rows)
    print("  PASS row")


def test_copy_cabinet():
    base = load_base()
    _, src_cab = cabinet(base, "ШЭТ 431.02-0")
    src_cipher = src_cab["Шифр шкафа"]
    src_tables = list(src_cab["Таблицы"])
    new_key = "Шкаф защит и автоматики типа ШЭТ 431.09-0 для архитектуры I типа"
    path = ["Содержимое стандарта", {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}]
    op = {
        "Операция": "COPY", "Путь": path, "Ключ": new_key,
        "Замены": [
            {"Старое": "431.02-0", "Новое": "431.09-0"},
            {"Старое": "Таблица 5.3.", "Новое": "Таблица 5.9."},
        ],
        "Правки": [{"Путь": ["Раздел стандарта"], "Значение": "5.9"}],
        "Перенумеровать": True,
        "Причина": "дублирование шкафа для нового присоединения",
    }
    edit = {
        "Операция": "OVERRIDE",
        "Путь": ["Содержимое стандарта",
                 {"@where": {"Шифр шкафа": "ШЭТ 431.09-0"}},
                 "Назначение шкафа"],
        "Значение": "Копия шкафа 431.02-0 для проверки",
    }
    data, ctx, registry, skipped, sha, problems, warnings = assemble(
        [make_cs("C2", [op, edit])], "cabinet")
    assert not problems, problems
    assert not warnings, warnings

    key2, cab2 = cabinet(data, "ШЭТ 431.09-0")
    assert key2 == new_key
    assert cab2["Раздел стандарта"] == "5.9"
    assert cab2["Назначение шкафа"] == "Копия шкафа 431.02-0 для проверки"
    assert len(cab2["Таблицы"]) == len(src_tables)
    assert all(k.startswith("Таблица 5.9.") for k in cab2["Таблицы"])
    assert not any("431.02-0" in k for k in cab2)

    refs = []
    for name, complect in cab2["Описание шкафа"].items():
        if isinstance(complect, dict) and "Таблицы комплекта" in complect:
            refs.extend(complect["Таблицы комплекта"].values())
    assert refs, "в копии не нашлись ссылки на таблицы комплектов"
    missing = [r for r in refs if r not in cab2["Таблицы"]]
    assert not missing, "ссылки на несуществующие таблицы: %r" % missing

    for table in cab2["Таблицы"].values():
        assert table["Количество строк"] == len(table["Строки"])
        if table["Строки"] and "№" in table["Строки"][0]:
            assert [r["№"] for r in table["Строки"]] == [
                str(i) for i in range(1, len(table["Строки"]) + 1)]

    orig_key, orig_cab = cabinet(data, "ШЭТ 431.02-0")
    assert orig_cab["Шифр шкафа"] == src_cipher
    assert list(orig_cab["Таблицы"]) == src_tables
    assert src_cipher in orig_key

    # DOCX собирается с копией шкафа (если установлен python-docx)
    try:
        import docx  # noqa: F401
    except ImportError:
        print("  SKIP DOCX (python-docx не установлен)")
    else:
        import json_to_docx
        out = tmp_file("copy-report.docx")
        json_to_docx.build_report(data, out)
        assert os.path.getsize(out) > 10000, os.path.getsize(out)
    print("  PASS cabinet")


def test_copy_table_to_other_cabinet():
    path_a = ["Содержимое стандарта",
              {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}},
              "Таблицы", "Таблица 5.3.2"]
    path_b = ["Содержимое стандарта",
              {"@where": {"Шифр шкафа": "ШЭТ 430.03-0"}}, "Таблицы"]
    op = {"Операция": "COPY", "Путь": path_a, "Куда": path_b,
          "Ключ": "Таблица 5.4.99"}
    data, ctx, allowed = apply_one(op)
    _, src = cabinet(data, "ШЭТ 431.02-0")
    _, dst = cabinet(data, "ШЭТ 430.03-0")
    assert "Таблица 5.3.2" in src["Таблицы"]
    assert "Таблица 5.4.99" in dst["Таблицы"]
    assert dst["Таблицы"]["Таблица 5.4.99"]["Строки"] == \
        src["Таблицы"]["Таблица 5.3.2"]["Строки"]
    assert dst["Таблицы"]["Таблица 5.4.99"] is not src["Таблицы"]["Таблица 5.3.2"]
    print("  PASS table -> other cabinet")


# ---------------------------------------------------------------------------
# 2. DSL ДУБЛИРОВАТЬ
# ---------------------------------------------------------------------------
TEXT = """ИЗМЕНЕНИЕ: ТЕКСТ-1
ВЕРСИЯ: 1
ДАТА: 2026-01-02
ПОРЯДОК: 10
СТАТУС: действует
НАЗВАНИЕ: Дублирование шкафа текстом
БАЗА: СТО 56947007-33.040.20.279-2019
ЗАМЕНЯЕТ:

ДУБЛИРОВАТЬ шкаф=ШЭТ 431.02-0
  КЛЮЧ: Шкаф защит и автоматики типа ШЭТ 431.10-0 для архитектуры I типа
  ЗАМЕНА: 431.02-0 => 431.10-0
  ЗАМЕНА: Таблица 5.3. => Таблица 5.10.
  ЗАМЕНА.ЗНАЧЕНИЯ: Комплект защит и автоматики => Комплект защит (копия)
  > Раздел стандарта: 5.10
  ПРАВКА: {"Путь": ["Описание шкафа", "Наименование шкафа"], "Значение": "Копия текстом"}
  ПЕРЕНУМЕРОВАТЬ: да

ЗАМЕНИТЬ шкаф=ШЭТ 431.10-0 / Назначение шкафа
  СТАЛО: Назначение копии текстом
"""


def test_text_roundtrip_and_build():
    cs, warnings = ce.compile_text(TEXT)
    assert not warnings, warnings
    assert cs["Изменения"][0]["Операция"] == "COPY"
    assert ce.check_paths(cs, load_base()) == [], ce.check_paths(cs, load_base())
    again, _ = ce.compile_text(ce.decompile(cs))
    assert again == cs, "roundtrip DSL изменил JSON"

    data, ctx, registry, skipped, sha, problems, warnings = assemble(
        [cs], "text")
    assert not problems, problems
    assert not warnings, warnings
    _, cab = cabinet(data, "ШЭТ 431.10-0")
    assert cab["Описание шкафа"]["Наименование шкафа"] == "Копия текстом"
    assert cab["Назначение шкафа"] == "Назначение копии текстом"
    assert all(k.startswith("Таблица 5.10.") for k in cab["Таблицы"])
    print("  PASS DSL text")


def test_check_paths_order():
    base = load_base()
    new_path = ["Содержимое стандарта", "Шкаф-новая-копия",
                "Описание шкафа", "Наименование шкафа"]
    edit = {"Операция": "OVERRIDE", "Путь": new_path, "Значение": "x"}
    copy = {"Операция": "COPY",
            "Путь": ["Содержимое стандарта",
                     {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}],
            "Ключ": "Шкаф-новая-копия"}
    errs = ce.check_paths(make_cs("T", [edit]), base)
    assert errs, "правка до COPY должна не находить путь"
    errs = ce.check_paths(make_cs("T", [copy, edit]), base)
    assert not errs, errs
    print("  PASS check_paths order")


# ---------------------------------------------------------------------------
# 3. Конфликты и «Заменяет»
# ---------------------------------------------------------------------------
def test_conflict_with_source():
    path = ["Содержимое стандарта",
            {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}]
    change_a = make_cs("A", [
        {"Операция": "OVERRIDE",
         "Путь": path + ["Назначение шкафа"], "Значение": "Новое назначение"},
    ], order=10)
    change_b = make_cs("B", [
        {"Операция": "COPY", "Путь": path, "Ключ": "Копия-для-конфликта"},
    ], order=20)
    try:
        assemble([change_a, change_b], "conflict")
    except ac.ChangeError as exc:
        assert "конфликт" in str(exc), exc
    else:
        raise AssertionError("ожидали конфликт COPY с изменением источника")

    change_b["Заменяет"] = ["A"]
    data, ctx, registry, skipped, sha, problems, warnings = assemble(
        [change_a, change_b], "conflict-ok")
    assert not problems, problems
    assert "Копия-для-конфликта" in data["Содержимое стандарта"]
    print("  PASS conflict / Заменяет")


def test_allow_flag():
    path = ["Содержимое стандарта",
            {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}]
    a = make_cs("A", [{"Операция": "OVERRIDE",
                       "Путь": path + ["Назначение шкафа"],
                       "Значение": "A"}], order=10)
    b = make_cs("B", [{"Операция": "COPY", "Путь": path,
                       "Ключ": "Копия-разрешено", "Разрешить": True}], order=20)
    data, ctx, registry, skipped, sha, problems, warnings = assemble(
        [a, b], "allow")
    assert not problems, problems
    print("  PASS Разрешить")


# ---------------------------------------------------------------------------
# 4. Негативные проверки
# ---------------------------------------------------------------------------
def test_negative():
    base = load_base()
    path = ["Содержимое стандарта",
            {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}]

    def run(op):
        data = json.loads(json.dumps(base, ensure_ascii=False))
        ac.apply_op(data, make_cs("N", [op]), 0, op, ac.Context(), False)

    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия",
                               "Замены": [{"Старое": "", "Новое": "x"}]}),
                  "пустое")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия",
                               "Замены": [{"Старое": "a", "Новое": "b",
                                           "Где": "везде"}]}), "«Где»")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": cabinet(base, "ШЭТ 431.02-0")[0]}),
                  "уже существует")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path}),
                  "нужен «Ключ»")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия", "Позиция": 1}),
                  "«Позиция»")
    assert_raises(lambda: run({"Операция": "COPY",
                               "Путь": path + ["Таблицы", "Таблица 5.3.8",
                                               "Строки", {"@index": 1}],
                               "Ключ": "x"}),
                  "только к объекту")
    assert_raises(lambda: run({"Операция": "COPY",
                               "Путь": ["Содержимое стандарта", "нет-такого"],
                               "Ключ": "x"}), "нет ключа")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия",
                               "Куда": ["Содержимое стандарта", "нет-такого"]}),
                  "нет ключа")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия", "Удалить": ["Нет поля"]}),
                  "нет поля")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия",
                               "Правки": [{"Путь": ["Нет поля"],
                                           "Значение": 1}]}), "нет ключа")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": path,
                               "Ключ": "Копия",
                               "Правки": [{"Путь": ["Описание шкафа"]}]}),
                  "нужен")
    assert_raises(lambda: run({"Операция": "COPY",
                               "Путь": path + ["Таблицы", "Таблица 5.3.8",
                                               "Строки", {"@index": 1}],
                               "Позиция": 99999}), "вне массива")
    assert_raises(lambda: run({"Операция": "COPY",
                               "Путь": path + ["Таблицы", "Таблица 5.3.8",
                                               "Строки", {"@index": 1}],
                               "Позиция": "abc"}), "числом")
    assert_raises(lambda: run({"Операция": "COPY", "Путь": [],
                               "Ключ": "x"}), "Путь")

    # коллизия имён полей после замены
    src = {"ab": 1, "cb": 2}
    assert_raises(lambda: ac.build_copy(
        src, {"Замены": [{"Старое": "a", "Новое": "c"}]}), "стали")
    # замена только ключей / только значений
    src = {"Таблица 5.3.1": "Таблица 5.3.1", "x": "Таблица 5.3.1"}
    copy, stats = ac.build_copy(src, {"Замены": [
        {"Старое": "5.3.", "Новое": "5.9.", "Где": "ключи"}]})
    assert list(copy) == ["Таблица 5.9.1", "x"]
    assert copy["x"] == "Таблица 5.3.1"
    copy, stats = ac.build_copy(src, {"Замены": [
        {"Старое": "5.3.", "Новое": "5.9.", "Где": "значения"}]})
    assert list(copy) == ["Таблица 5.3.1", "x"]
    assert copy["x"] == "Таблица 5.9.1"
    assert src == {"Таблица 5.3.1": "Таблица 5.3.1", "x": "Таблица 5.3.1"}

    # Поля / Удалить / Правки на маленьком объекте
    src = {"A": {"B": "x", "C": "y"}, "D": "z", "row": [{"№": "1"}, {"№": "2"}]}
    copy, stats = ac.build_copy(src, {
        "Поля": {"D": "zz"},
        "Правки": [
            {"Путь": ["A", "C"], "Переименовать": "CC"},
            {"Путь": ["row", {"@index": 0}], "Удалить": True},
            {"Путь": ["A", "B"], "Значение": "xx"},
        ],
    })
    assert copy["D"] == "zz"
    assert copy["A"] == {"B": "xx", "CC": "y"}
    assert len(copy["row"]) == 1
    assert src["A"] == {"B": "x", "C": "y"} and src["D"] == "z"

    copy, stats = ac.build_copy({"A": 1, "B": 2}, {"Удалить": ["B"]})
    assert copy == {"A": 1}
    print("  PASS negative")


# ---------------------------------------------------------------------------
# 5. Совместимость с существующими изменениями
# ---------------------------------------------------------------------------
def test_existing_changes():
    changes_dir = os.path.join(ROOT, "changes")
    text_dir = os.path.join(ROOT, "changes_text")
    for name in ("ИЗМ-1", "ИЗМ-1_ред2", "ИЗМ-2", "ИЗМ-3"):
        txt_path = os.path.join(text_dir, name + ".изм.txt")
        json_path = os.path.join(changes_dir, name + ".json")
        with open(txt_path, encoding="utf-8") as f:
            cs_text, warnings = ce.compile_text(f.read())
        cs_json = ac.load_json(json_path)
        assert not warnings, (name, warnings)
        assert json.dumps(cs_text, ensure_ascii=False, sort_keys=True) == \
            json.dumps(cs_json, ensure_ascii=False, sort_keys=True), name
        assert not ce.check_paths(cs_text, load_base()), name

    data, ctx, registry, skipped, sha, problems, warnings = ac.assemble(
        BASE, [changes_dir], ignore_hash=False)
    assert not problems, problems
    print("  PASS existing changes (%d изменений)" % len(registry))


# ---------------------------------------------------------------------------
# 6. GUI: дублирование узла и окно правки копии
# ---------------------------------------------------------------------------
def test_gui():
    import tkinter as tk
    import changes_gui as cg

    root = tk.Tk()
    root.withdraw()
    try:
        app = cg.App(root)
        root.update()
        app.blocks.clear()
        app.rebuild_ops()
        iid = app.expand_to(["Содержимое стандарта",
                             {"@where": {"Шифр шкафа": "ШЭТ 431.02-0"}}])
        assert iid, "шкаф не найден в дереве GUI"
        app.tree.selection_set(iid)
        app._on_tree_select(None)
        assert app.grid_view.model is not None

        opts = {
            "key": "Шкаф-копия-GUI",
            "replacements": [
                {"Старое": "431.02-0", "Новое": "431.11-0"},
                {"Старое": "Таблица 5.3.", "Новое": "Таблица 5.11."},
            ],
            "renumber": False,
            "edit": True,
        }
        app.ask_duplicate_options = lambda *args, **kwargs: opts
        app.duplicate_node()
        root.update()
        assert len(app.blocks) == 1, app.blocks
        assert app.blocks[0].splitlines()[0].startswith("ДУБЛИРОВАТЬ")
        assert "431.11-0" in app.blocks[0]

        editor = app.copy_editor
        assert editor is not None
        assert editor.expand_to(["Таблицы", "Таблица 5.11.2", "Строки"])
        model = editor.grid_view.model
        assert model.kind == "table"
        column = "Аналоговая цепь"
        old = model.rows[0].cells[column]
        model.rows[0].cells[column] = "КОПИЯ " + str(old)
        blocks = editor.grid_view.generate() or []
        assert blocks, "правка копии не дала операций"
        assert "Шкаф-копия-GUI" in blocks[0], blocks[0]

        assert editor.expand_to(["Назначение шкафа"])
        scalar = editor.grid_view.model
        scalar.rows[0].cells["Значение"] = "Назначение копии из GUI"
        assert editor.grid_view.generate()

        text = app.build_text()
        cs, warnings = ce.compile_text(text)
        assert not warnings, warnings
        assert not ce.check_paths(cs, app.base), ce.check_paths(cs, app.base)

        data, ctx, registry, skipped, sha, problems, warnings = assemble(
            [cs], "gui")
        assert not problems, problems
        _, cab = cabinet(data, "ШЭТ 431.11-0")
        assert cab["Назначение шкафа"] == "Назначение копии из GUI"
        assert cab["Таблицы"]["Таблица 5.11.2"]["Строки"][0]["Аналоговая цепь"] \
            .startswith("КОПИЯ ")

        editor.destroy()
        print("  PASS GUI")
    finally:
        root.destroy()


def main():
    tests = [
        test_copy_positions,
        test_copy_scalar,
        test_copy_row_and_edit,
        test_copy_cabinet,
        test_copy_table_to_other_cabinet,
        test_text_roundtrip_and_build,
        test_check_paths_order,
        test_conflict_with_source,
        test_allow_flag,
        test_negative,
        test_existing_changes,
        test_gui,
    ]
    failed = 0
    for test in tests:
        print("%s..." % test.__name__)
        try:
            test()
        except Exception:
            failed += 1
            traceback.print_exc()
    cleanup()
    if failed:
        print("\nПРОВАЛЕНО ТЕСТОВ: %d" % failed)
        return 1
    print("\nВСЕ ТЕСТЫ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
