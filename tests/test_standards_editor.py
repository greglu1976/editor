# -*- coding: utf-8 -*-
"""Проверка интеграции папки ``standard_editor`` в редактор схем.

Запуск:
    python tests/test_standards_editor.py           # с окнами (нужен tkinter)
    python tests/test_standards_editor.py --no-gui  # только данные и файлы

Проверяет:

1. связку: папка ``standard_editor`` найдена, стандартов три, у каждого
   шифр, шкафы и таблицы;
2. изменения: четыре файла ``*.изм.txt``, шапки читаются, разбор без ошибок,
   старая версия ИЗМ-1 вытесняется новой;
3. сборку редакции: ``assembly`` применяет изменения, пишет журнал, редакция
   сохраняется и повторно читается как JSON;
4. новый стандарт: ``build_standard`` без записи, ``new_standard`` с записью,
   отказ перезаписывать файл, подмножество шкафов с перенумерацией разделов;
5. отчёт DOCX: строится (в текущем или внешнем Python с python-docx);
6. окна: список стандартов, редактор изменений внутри окна редактора,
   диалоги нового стандарта и сборки, окно DOCX;
7. проводку в ленте: вкладка «Стандарты» и её методы у ``main``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import standards_editor as se   # noqa: E402

try:                            # GUI-часть необязательна
    import tkinter as tk
except ImportError:             # pragma: no cover - зависит от сборки Python
    tk = None

FAILURES = []
WORK = os.path.join(ROOT, "output", "_std_test")


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def prepare_work():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        for item in _walk(child):
            yield item


# ---------------------------------------------------------------------------
def test_available():
    print("1. связка с папкой standard_editor")
    check(se.available(), "папка инструментов найдена")
    check(os.path.isdir(se.folder()), "папка: %s" % se.folder())
    rows = se.standards()
    check(len(rows) >= 3, "стандартов в списке: %d" % len(rows))
    check(all(row["шифр"].startswith("СТО") for row in rows),
          "у каждого стандарта есть шифр СТО")
    check(all(row["шкафов"] > 0 for row in rows),
          "у каждого стандарта есть шкафы")
    base = se.default_base()
    check(bool(base) and os.path.isfile(base),
          "база по умолчанию: %s" % os.path.basename(base))
    info = se.standard_info(se.load(base), base)
    check(info["шкафов"] == 6 and info["таблиц"] == 101,
          "карточка 279-2019: шкафов %d, таблиц %d"
          % (info["шкафов"], info["таблиц"]))
    check(len(se.cabinets_of(se.load(base))) == 6,
          "список шкафов строится для диалога")


def test_changes():
    print("2. изменения стандарта")
    files = se.change_files()
    check(len(files) == 4, "файлов *.изм.txt: %d" % len(files))
    summary = se.changes_summary()
    check(all(row["идентификатор"] for row in summary),
          "у каждого файла читается идентификатор")
    first = summary[0]
    check(first["база"].startswith("СТО 56947007-33.040.20"),
          "в шапке указана база: %s" % first["база"])
    check(se.changes_for("СТО 56947007-33.040.20.279-2019") == 4,
          "к 279-2019 относятся все четыре изменения")
    check(se.changes_for("СТО 56947007-33.040.20.280-2019") == 0,
          "к 280-2019 изменений нет")
    compiled, errors = se.compile_changes()
    check(not errors, "разбор без ошибок %s" % ("; ".join(errors[:1])))
    check(len(compiled) == 4, "разобрано наборов: %d" % len(compiled))
    active = [cs for _path, cs, _warns in compiled if cs.get("Изменения")]
    skipped = [cs for _path, cs, _warns in compiled if not cs.get("Изменения")]
    check(len(active) == 3, "наборов с операциями: %d" % len(active))
    check([cs["Идентификатор"] for cs in skipped] == ["ИЗМ-3"],
          "файл с неактивным статусом пуст: %s"
          % ", ".join(cs["Идентификатор"] for cs in skipped))


def test_assembly():
    print("3. сборка редакции")
    result = se.assembly(se.default_base())
    check(result["ok"], "сборка прошла: %s"
          % (result["ошибка"] or "ошибок нет"))
    check(result["изменений"] == 2,
          "применено изменений: %d (ИЗМ-1 ред. 2 и ИЗМ-2)"
          % result["изменений"])
    check("ИЗМ-3" in result["отчёт"],
          "отменённое ИЗМ-3 попало в журнал как пропущенное")
    check("ИЗМ-2" in result["отчёт"] and "ПРОВЕРКА" in result["отчёт"],
          "журнал сборки содержит операции и проверку")
    check(isinstance(result["data"], dict)
          and "Редакция" in result["data"],
          "в редакции есть блок «Редакция»")
    out = os.path.join(WORK, "edition.json")
    size = se.write_json(result["data"], out)
    check(size > 0 and os.path.isfile(out),
          "редакция записана: %.0f КБ" % (size / 1024.0))
    again = se.load(out)
    check(len(again.get("Редакция") or []) == len(result["data"]["Редакция"]),
          "редакция читается обратно (%d изменений)"
          % len(again.get("Редакция") or []))

    bad = se.assembly(os.path.join(WORK, "нет-такого.json"))
    check(not bad["ok"] and "нет файла" in (bad["ошибка"] or ""),
          "отсутствующая база — понятная ошибка")


def test_new_standard():
    print("4. новый стандарт на основе выбранного")
    source = None
    for row in se.standards():
        if "281" in row["имя"]:
            source = row["путь"]
            break
    check(source is not None, "исходный стандарт 281-2019 найден")

    built = se.build_standard(
        source,
        meta={"Шифр стандарта": "СТО 56947007-33.040.20.999-2026",
              "Обозначение стандарта": "Тестовые шкафы ШЭТ",
              "Дата введения": "01.02.2026",
              "Принадлежность стандарта": "ООО «Тест»",
              "Область применения стандарта": "Проверка интеграции"},
        replacements=["431.03-2 => 431.09-2"])
    check(built["ok"], "проверка пройдена: %s"
          % (built["ошибка"] or "ошибок нет"))
    check(built["статистика"]["cabinets"] == 3,
          "шкафов в новом стандарте: %d" % built["статистика"]["cabinets"])
    data = built["data"]
    check(data["Шифр стандарта"] == "СТО 56947007-33.040.20.999-2026",
          "шифр заменён")
    check(not [problem for problem in built["проблемы"]],
          "проблем проверки нет")

    subset = se.build_standard(source, keep=["ШЭТ 431.02-2", "ШЭТ 431.03-2"],
                               renumber=True)
    check(subset["ok"] and subset["статистика"]["cabinets"] == 2,
          "подмножество из двух шкафов: %d"
          % subset["статистика"]["cabinets"])
    sections = [cab.get("Раздел стандарта")
                for _name, cab in se.module("make_standard").cabinets(
                    subset["data"])]
    check(sections == ["5.2", "5.3"],
          "разделы перенумерованы: %s" % ", ".join(sections))

    out = os.path.join(WORK, "новый_стандарт.json")
    saved = se.new_standard(source, out,
                            meta={"Шифр стандарта": "СТО 56947007-33.040.20.998-2026",
                                  "Обозначение стандарта": "Шкафы ШЭТ (тест)",
                                  "Дата введения": "01.02.2026",
                                  "Принадлежность стандарта": "ООО «Тест»",
                                  "Область применения стандарта": "Проверка"})
    check(saved["ok"] and os.path.isfile(out),
          "стандарт записан: %.0f КБ" % (saved.get("размер", 0) / 1024.0))
    problems, _warnings = se.validate_standard(se.load(out))
    check(not problems, "записанный стандарт проходит проверку")
    again = se.new_standard(source, out,
                            meta={"Шифр стандарта": "СТО 56947007-33.040.20.997-2026"})
    check(not again["ok"] and "уже существует" in (again["ошибка"] or ""),
          "без разрешения файл не перезаписывается")


def test_docx():
    print("5. отчёт DOCX")
    interpreter = se.docx_interpreter()
    if not interpreter:
        print("  --   python-docx не найден: отчёт не проверяется")
        return
    check(True, "интерпретатор с python-docx: %s" % interpreter)
    source = None
    for row in se.standards():
        if "281" in row["имя"]:
            source = row["путь"]
            break
    out = os.path.join(WORK, "отчёт.docx")
    result = se.build_docx(se.load(source), out)
    check(result["ok"], "отчёт построен: %s"
          % (result["ошибка"] or result["интерпретатор"]))
    check(os.path.isfile(out) and os.path.getsize(out) > 10000,
          "файл DOCX: %.0f КБ" % (os.path.getsize(out) / 1024.0))
    stats = result["статистика"]
    check(stats.get("cabinets") == 3 and stats.get("tables") == 50,
          "в отчёте шкафов %s, таблиц %s"
          % (stats.get("cabinets"), stats.get("tables")))


def test_gui():
    print("6. окна стандартов")
    import standards_ui as su

    root = tk.Tk()
    root.withdraw()

    class App:
        def __init__(self, root):
            self.root = root

    app = App(root)
    windows = []
    try:
        listing = su.show_standards(app)
        windows.append(listing)
        root.update()
        check(len(listing.paths()) == len(se.standards()),
              "в списке стандартов: %d" % len(listing.paths()))
        check(listing.selected() is not None, "стандарт выбирается")
        check("Стандартов:" in listing.log.get("1.0", "end"),
              "в окне показана сводка")

        dialog = su.show_new_standard(app)
        windows.append(dialog)
        root.update()
        check(len(dialog.tree.get_children()) == 6,
              "шкафы исходного стандарта: %d"
              % len(dialog.tree.get_children()))
        check(dialog.var_meta["Шифр стандарта"].get().startswith("СТО"),
              "реквизиты заполнены из источника")
        items = dialog.tree.get_children()
        dialog.tree.selection_set(items[0])
        dialog._toggle()
        root.update()
        check(dialog.tree.item(items[0], "values")[0] == "·",
              "галочка шкафа снимается")
        check(dialog.checked_cabinets() == [
            dialog.tree.item(iid, "values")[1] for iid in items[1:]],
            "снятый шкаф не попадает в набор")
        dialog._select_all()
        check(dialog.collect()["keep"] is None,
              "когда отмечены все шкафы, набор не ограничивается")
        check(dialog.preview()["ok"], "предпросмотр нового стандарта проходит")

        assembly = su.show_assembly(app)
        windows.append(assembly)
        root.update()
        check("Файлов изменений: 4" in assembly.lbl_changes.cget("text"),
              "окно сборки видит четыре изменения")
        compiled, errors = assembly.check_changes()
        check(len(compiled) == 4 and not errors,
              "проверка файлов из окна сборки: %d" % len(compiled))

        editor = su.open_editor(app, se.default_base())
        windows.append(editor)
        root.update()
        check(editor is not None and getattr(editor, "_std_editor", None),
              "редактор изменений открылся в окне редактора")
        check(os.path.normcase(editor._std_editor.base_path)
              == os.path.normcase(se.default_base()),
              "в редактор загружена выбранная база")

        # Сборка внутри окна: системный %TEMP% закрыт политикой, поэтому
        # проверяем, что подмена временного каталога работает.
        inner = editor._std_editor
        change = os.path.join(se.CHANGES_FOLDER, "ИЗМ-1_ред2.изм.txt")
        inner.set_document(open(change, encoding="utf-8").read())
        root.update()
        inner.action_check()
        check("ИТОГ: OK" in inner.log.get("1.0", "end"),
              "проверка изменений в окне редактора")
        inner.action_assemble()
        root.update()
        check(inner.edition is not None
              and "OK" in inner.status.cget("text"),
              "сборка редакции в окне: %s" % inner.status.cget("text")[:40])

        docx_window = su.show_docx(app)
        windows.append(docx_window)
        root.update()
        hint = docx_window.lbl_python.cget("text")
        check("DOCX" in hint or "python-docx" in hint,
              "окно DOCX показывает интерпретатор: %s" % hint[:48])
    finally:
        for window in windows:
            try:
                if window.winfo_exists():
                    window.destroy()
            except tk.TclError:
                pass
        root.update()
        root.destroy()


def test_wiring():
    print("7. проводка в ленте редактора")
    source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    check('("Стандарты", self._build_ribbon_standards)' in source,
          "вкладка «Стандарты» зарегистрирована")
    for name in ("show_standards_window", "open_standards_editor",
                 "show_new_standard_dialog", "show_assembly_window",
                 "show_docx_window", "_build_ribbon_standards"):
        check("def %s" % name in source, "метод %s объявлен" % name)
    import standards_ui
    for function in ("show_standards", "open_editor", "show_new_standard",
                     "show_assembly", "show_docx"):
        check(hasattr(standards_ui, function), "standards_ui.%s" % function)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-gui", action="store_true",
                        help="не открывать окна")
    args = parser.parse_args(argv)

    print("Проверка интеграции standard_editor\n")
    prepare_work()
    test_available()
    test_changes()
    test_assembly()
    test_new_standard()
    test_docx()
    if not args.no_gui and tk is not None:
        test_gui()
    test_wiring()
    shutil.rmtree(WORK, ignore_errors=True)
    print()
    if FAILURES:
        print("ПРОВАЛЕНО: %d" % len(FAILURES))
        for message in FAILURES:
            print("  - %s" % message)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
