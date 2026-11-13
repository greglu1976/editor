# -*- coding: utf-8 -*-
"""Тесты создания стандарта на основе выбранного (make_standard.py).

Запуск:  python -B _parse\\test_new_standard.py
Тесты не пишут в рабочую папку: временные файлы создаются в %TEMP%.
"""
from __future__ import annotations

import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

import make_standard as ms          # noqa: E402

BASE_279 = os.path.join(ROOT, "СТО 56947007-33.040.20.279-2019.json")
BASE_280 = os.path.join(ROOT, "СТО 56947007-33.040.20.280-2019.json")
TMP = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
_created = []


def tmp_file(name):
    path = os.path.join(TMP, "sto-new-%d-%s" % (os.getpid(), name))
    _created.append(path)
    return path


def cleanup():
    for path in _created:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_from(path, **kwargs):
    return ms.build(load(path), **kwargs)


def assert_raises(fn, needle=""):
    try:
        fn()
    except ms.StandardError as exc:
        assert needle in str(exc), "ожидали %r, получили: %s" % (needle, exc)
        return
    raise AssertionError("ожидали ошибку %r" % needle)


# ---------------------------------------------------------------------------
# 1. Только реквизиты
# ---------------------------------------------------------------------------
def test_meta_only():
    source = load(BASE_279)
    original = json.dumps(source, ensure_ascii=False, sort_keys=True)
    res = build_from(BASE_279, meta={
        "Шифр стандарта": "СТО 56947007-33.040.20.290-2019",
        "Обозначение стандарта": "Типовые шкафы ШЭТ РЗА. Проверка",
        "Дата введения": "01.02.2026",
        "Принадлежность стандарта": "ПАО «Россети»",
    })
    assert not res["problems"], res["problems"]
    assert not res["warnings"], res["warnings"]
    data = res["data"]
    assert data["Шифр стандарта"] == "СТО 56947007-33.040.20.290-2019"
    assert data["Обозначение стандарта"] == "Типовые шкафы ШЭТ РЗА. Проверка"
    assert data["Дата введения"] == "01.02.2026"
    assert data["Принадлежность стандарта"] == "ПАО «Россети»"
    assert res["stats"] == res["source_stats"]
    # область применения унаследована
    assert data["Область применения стандарта"] == \
        source["Область применения стандарта"]
    # исходник не изменился
    assert json.dumps(source, ensure_ascii=False, sort_keys=True) == original
    # повторная проверка того же объекта
    assert not ms.validate_standard(data)[0]
    print("  PASS meta")


# ---------------------------------------------------------------------------
# 2. Замены кодов ШЭТ
# ---------------------------------------------------------------------------
def test_replacements():
    res = build_from(BASE_280, replacements=["430.03-1 => 430.09-1"])
    assert not res["problems"], res["problems"]
    text = json.dumps(res["data"], ensure_ascii=False)
    assert "430.03-1" not in text
    assert text.count("430.09-1") > 0
    assert res["replacements"]["keys"] >= 1
    assert res["replacements"]["values"] >= 1
    codes = [row["Код ШЭТ"] for row in
             res["data"]["Содержимое стандарта"][ms.LIST_KEY]]
    assert "430.09-1" in codes and "430.03-1" not in codes
    cabs = ms.cabinets(res["data"])
    target = [cab for _, cab in cabs if cab["Шифр шкафа"] == "ШЭТ 430.09-1"]
    assert target, [cab["Шифр шкафа"] for _, cab in cabs]
    assert target[0]["Описание шкафа"]["Шифр шкафа"] == "ШЭТ 430.09-1"

    # замены не наслаиваются друг на друга
    sample = {"Поле": "I типа", "I типа": {"Глубоко": "I типа"}}
    ms.apply_replacements(sample, [
        {"Старое": "I типа", "Новое": "II типа"},
        {"Старое": "II типа", "Новое": "III типа"},
    ])
    assert sample == {"Поле": "II типа",
                      "II типа": {"Глубоко": "II типа"}}, sample
    print("  PASS replacements")


# ---------------------------------------------------------------------------
# 3–4. Подмножество шкафов и перенумерация
# ---------------------------------------------------------------------------
def test_keep_and_renumber():
    res = build_from(BASE_279, keep=["ШЭТ 430.01-0", "ШЭТ 431.06-0"])
    assert not res["problems"], res["problems"]
    data = res["data"]
    content = data["Содержимое стандарта"]
    cabs = ms.cabinets(data)
    assert [cab["Шифр шкафа"] for _, cab in cabs] == \
        ["ШЭТ 430.01-0", "ШЭТ 431.06-0"]
    assert [cab["Раздел стандарта"] for _, cab in cabs] == ["5.2", "5.3"]
    dropped = "Шкаф защит и автоматики батареи статических конденсаторов " \
              "типа ШЭТ 431.02-0 для архитектуры I типа"
    assert dropped not in content
    codes = [row["Код ШЭТ"] for row in content[ms.LIST_KEY]]
    assert codes == ["430.01-0", "431.06-0"]

    second = cabs[1][1]
    assert all(name.startswith("Таблица 5.3.")
               for name in second["Таблицы"])
    desc = second["Описание шкафа"]
    assert desc["Поясняющая схема подключения"] == "Рисунок 5.3.1"
    assert desc["Отчеты в АСУ ТП"] == "Таблица 5.3.11"
    assert any("снятых шкафов" in item for item in res["warnings"]), \
        res["warnings"]
    print("  PASS keep + renumber")


def test_keep_middle():
    res = build_from(BASE_279, keep=["ШЭТ 431.02-0", "ШЭТ 431.06-0"])
    assert not res["problems"], res["problems"]
    cabs = ms.cabinets(res["data"])
    first, second = cabs[0][1], cabs[1][1]
    assert (first["Шифр шкафа"], first["Раздел стандарта"]) == \
        ("ШЭТ 431.02-0", "5.2")
    assert (second["Шифр шкафа"], second["Раздел стандарта"]) == \
        ("ШЭТ 431.06-0", "5.3")
    assert first["Описание шкафа"]["Поясняющие схемы подключения"] == \
        "Рисунок 5.2.1"
    assert first["Описание шкафа"]["Отчеты в АСУ ТП"] == "Таблица 5.2.20"
    assert second["Описание шкафа"]["Поясняющая схема подключения"] == \
        "Рисунок 5.3.1"
    assert all(name.startswith("Таблица 5.2.") for name in first["Таблицы"])
    assert all(name.startswith("Таблица 5.3.") for name in second["Таблицы"])
    print("  PASS keep middle")


# ---------------------------------------------------------------------------
# 5–6. Проверка целостности
# ---------------------------------------------------------------------------
def test_duplicate_cipher():
    res = build_from(BASE_280, replacements=["431.01-1 => 431.02-1"])
    assert res["problems"], "ожидали проблему повторяющегося шифра"
    assert any("повторяется" in item for item in res["problems"]), res["problems"]
    assert any("повторяются" in item for item in res["problems"]), res["problems"]
    print("  PASS duplicate cipher")


def test_keep_without_renumber():
    res = build_from(BASE_279, keep=["ШЭТ 430.01-0", "ШЭТ 431.06-0"],
                     renumber=False)
    assert not res["problems"], res["problems"]
    cabs = ms.cabinets(res["data"])
    assert [cab["Раздел стандарта"] for _, cab in cabs] == ["5.2", "5.7"]
    assert all(name.startswith("Таблица 5.7.") for name in cabs[1][1]["Таблицы"])
    assert any("не подряд" in item for item in res["warnings"]), res["warnings"]
    print("  PASS keep without renumber")


def test_dangling_reference():
    res = build_from(BASE_279, keep=["ШЭТ 430.01-0"])
    assert not res["problems"], res["problems"]
    data = res["data"]
    cab = ms.cabinets(data)[0][1]
    cab["Назначение шкафа"] += " См. Таблица 5.9.9."
    problems, _ = ms.validate_standard(data)
    assert any("отсутствующие таблицы" in item for item in problems), problems
    print("  PASS dangling reference")


def test_table_counts():
    data = load(BASE_279)
    cab = ms.cabinets(data)[0][1]
    name = list(cab["Таблицы"])[0]
    cab["Таблицы"][name]["Количество строк"] += 1
    problems, _ = ms.validate_standard(data)
    assert any("«Количество строк»" in item for item in problems), problems
    print("  PASS table counts")


# ---------------------------------------------------------------------------
# 7. Ошибки
# ---------------------------------------------------------------------------
def test_errors():
    source = load(BASE_279)
    assert_raises(lambda: ms.build({"a": 1}), "не стандарт")
    assert_raises(lambda: ms.build(source, meta={"Нет поля": "x"}),
                  "неизвестные реквизиты")
    assert_raises(lambda: ms.build(source, meta={"Шифр стандарта": "  "}),
                  "не может быть пустым")
    assert_raises(lambda: ms.build(source, replacements=["без стрелки"]),
                  "старое => новое")
    assert_raises(lambda: ms.build(source, replacements=["a => a"]),
                  "совпадают")
    assert_raises(lambda: ms.build(source, keep=["ШЭТ 999.99-9"]),
                  "не найдены шкафы")
    assert_raises(lambda: ms.build(source, keep=[]), "пуст")
    assert_raises(lambda: ms.write_standard(source, BASE_279),
                  "уже существует")
    print("  PASS errors")


def test_code_hint():
    old = "СТО 56947007-33.040.20.279-2019"
    new = "СТО 56947007-33.040.20.282-2019"
    reps = ms.code_replacements(old, new)
    assert reps[0] == {"Старое": old, "Новое": new}, reps
    assert reps[1] == {"Старое": "33.040.20.279",
                       "Новое": "33.040.20.282"}, reps
    assert ms.code_replacements(old, old) == []
    assert ms.code_replacements("X-1", "Y-2") == [{"Старое": "X-1",
                                                   "Новое": "Y-2"}]
    print("  PASS code hint")


# ---------------------------------------------------------------------------
# 8. Командная строка
# ---------------------------------------------------------------------------
def test_cli():
    out = tmp_file("cli.json")
    argv = ["--base", BASE_279, "--out", out,
            "--code", "СТО 56947007-33.040.20.291-2019",
            "--title", "CLI-стандарт", "--dry-run"]
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        code = ms.main(argv)
    finally:
        sys.stdout = old_stdout
    assert code == 0, buf.getvalue()
    assert not os.path.exists(out)
    assert "ПРОВЕРКА: OK" in buf.getvalue()

    argv = ["--base", BASE_279, "--out", out,
            "--code", "СТО 56947007-33.040.20.291-2019",
            "--title", "CLI-стандарт", "--keep", "ШЭТ 431.02-0"]
    buf = io.StringIO()
    sys.stdout = buf
    try:
        code = ms.main(argv)
    finally:
        sys.stdout = old_stdout
    assert code == 0, buf.getvalue()
    assert os.path.isfile(out)
    data = load(out)
    assert data["Шифр стандарта"] == "СТО 56947007-33.040.20.291-2019"
    assert len(ms.cabinets(data)) == 1
    assert not ms.validate_standard(data)[0]

    # проблема проверки -> код 1 и файл не перезаписывается
    bad = tmp_file("cli-bad.json")
    argv = ["--base", BASE_280, "--out", bad,
            "--replace", "431.01-1 => 431.02-1"]
    buf, err = io.StringIO(), io.StringIO()
    sys.stdout, old_stderr = buf, sys.stderr
    sys.stderr = err
    try:
        code = ms.main(argv)
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    assert code == 1, (code, buf.getvalue(), err.getvalue())
    assert not os.path.exists(bad)
    print("  PASS CLI")


# ---------------------------------------------------------------------------
# 9. GUI: диалог и сохранение
# ---------------------------------------------------------------------------
def test_gui():
    import tkinter as tk
    import changes_gui as cg

    root = tk.Tk()
    root.withdraw()
    try:
        app = cg.App(root)
        root.update()
        sources = app.standard_sources()
        assert sources, "нет источников"
        for _label, path in sources:
            assert os.path.isfile(path)
            assert isinstance(cg.ac.load_json(path), dict)
        base_before = app.base_path

        dlg = cg.NewStandardDialog(app, sources)
        root.update()
        dlg._select(0)
        assert dlg.cab_names, "в диалоге нет шкафов"
        dlg.ent_code.delete(0, "end")
        dlg.ent_code.insert(0, "СТО 56947007-33.040.20.292-2019")
        dlg.ent_title.delete(0, "end")
        dlg.ent_title.insert(0, "Стандарт из GUI")
        dlg._suggest_code()
        assert "292-2019" in cg.get_text(dlg.txt_reps)

        # оставить все шкафы, кроме последнего
        total = len(dlg.cab_names)
        dlg.lst_cabs.selection_clear(total - 1)
        opts, res = dlg.build_now()
        assert not res["problems"], res["problems"]
        assert res["stats"]["cabinets"] == total - 1
        assert dlg.txt_report.get("1.0", "end").strip()

        out = tmp_file("gui.json")
        old_save, old_ask = cg.filedialog.asksaveasfilename, cg.messagebox.askyesno
        cg.filedialog.asksaveasfilename = lambda **kwargs: out
        cg.messagebox.askyesno = lambda *args, **kwargs: False
        try:
            dlg.save()
        finally:
            cg.filedialog.asksaveasfilename = old_save
            cg.messagebox.askyesno = old_ask
        assert dlg.result == out, dlg.result
        assert os.path.isfile(out)
        saved = load(out)
        assert saved["Шифр стандарта"] == "СТО 56947007-33.040.20.292-2019"
        assert not ms.validate_standard(saved)[0]
        assert app.base_path == base_before, "база не должна меняться без согласия"

        dlg.destroy()
        print("  PASS GUI")
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# 10. DOCX из созданного стандарта (если есть python-docx)
# ---------------------------------------------------------------------------
def test_docx():
    try:
        import docx  # noqa: F401
    except ImportError:
        print("  SKIP: нет python-docx")
        return
    import json_to_docx

    res = build_from(BASE_279, meta={
        "Шифр стандарта": "СТО 56947007-33.040.20.293-2019",
        "Обозначение стандарта": "Отчёт по новому стандарту"}, keep=["ШЭТ 430.01-0"])
    assert not res["problems"], res["problems"]
    out = tmp_file("docx.docx")
    json_to_docx.build_report(res["data"], out, scope="cabinets", max_rows=3)
    assert os.path.getsize(out) > 20000
    print("  PASS DOCX (%d байт)" % os.path.getsize(out))


def main():
    tests = [
        test_meta_only,
        test_replacements,
        test_keep_and_renumber,
        test_keep_middle,
        test_keep_without_renumber,
        test_duplicate_cipher,
        test_dangling_reference,
        test_table_counts,
        test_errors,
        test_code_hint,
        test_cli,
        test_gui,
        test_docx,
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
