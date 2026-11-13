# Стандарты СТО в структуре EA

Новая ветка работы со стандартами: JSON собирается по модели
`EA/structure.eapx` (`EA/docx2json.py`), а редактор схем читает его через
`ea_standard.py`: показывает в окне `ea_ui.py`, ставит шкафы и комплекты на
схему (`ea_catalog.py`), делает новый стандарт на базе выбранного
(`ea_new_standard.py`) и выгружает документ в Word (`ea_docx.py`).

Старая ветка (`standards_base/`, `standards_editor.py`, `standards_ui.py`,
`standard_editor/`) пока работает как раньше и **новой веткой не
используется**. План её удаления — в конце файла.

## Формат

```
Standard
├── Section → Subsection → Clause → Subclause   (текст документа)
│   └── Table / Figure                          (таблица — только форма)
└── Cabinet → Kit → IED                          (данные)
```

Ключевое правило: **данные хранятся один раз — в `cabinets`**. Таблица в
разделе СТО содержит номер, название, ссылку и форму (шапку), а также поле
`cabinet` — шифр шкафа, из которого берутся строки:

```json
{
  "number": "5.3",
  "name": "Входные аналоговые измерения ИЭУ ШЭТ 431.11-1",
  "reference": "Таблица 5.3",
  "cabinet": "ШЭТ 431.11-1",
  "rows": [{"content": ["Аналоговая цепь", "..."], "is_header_first_row": true}]
}
```

У «Описание ШЭТ» форма — ключи первого столбца с пустыми значениями:
значения подставляет шкаф. Таблицы вне шкафов (термины, сокращения,
применимость, библиография) хранят данные сами — им неоткуда их тянуть.

## Модули

| Файл | Роль |
|---|---|
| [`ea_standard.py`](ea_standard.py) | чтение папки, обход дерева, `table_view()` — сборка строк таблицы из шкафа, `cabinet_card()`, `validate()`, CLI |
| [`ea_ui.py`](ea_ui.py) | окно «СТО (EA)…»: дерево документа и шкафов, таблицы, карточки, размещение на схеме, новый стандарт, DOCX |
| [`ea_catalog.py`](ea_catalog.py) | мост «шкаф стандарта → каталог редактора»: `ensure_catalog()`, `kit_entry()` |
| [`ea_new_standard.py`](ea_new_standard.py) | новый стандарт на базе выбранного: реквизиты, отбор шкафов, замены, перенумерация |
| [`ea_docx.py`](ea_docx.py) | выгрузка стандарта в Word: титул, оглавление, таблицы из шкафов, приложение со шкафами |
| [`main.py`](main.py) | кнопка «СТО (EA)…» на вкладке «Стандарты» и метод `show_ea_standards` |
| [`EA/docx2json.py`](EA/docx2json.py) | сборка JSON стандарта из DOCX по модели EA |
| [`tests/test_ea_standard.py`](tests/test_ea_standard.py) | проверка данных, сборки таблиц, CLI и окна |
| [`tests/test_ea_features.py`](tests/test_ea_features.py) | размещение, новый стандарт, DOCX, архив |

Папка стандартов: `EA/` рядом с исходниками, `db/EA/` в собранном
приложении (`apppaths.data_dir("EA")`).

## Запуск

```bash
python ea_standard.py --list                  # стандарты в папке
python ea_standard.py --stats                 # счётчики
python ea_standard.py --check                 # ссылки «таблица → шкаф», полнота сигналов
python ea_standard.py --table 5.3 --limit 10  # таблица, собранная из шкафа
python ea_standard.py --cabinet "ШЭТ 431.11-1"
python ea_catalog.py --check                  # шкафы стандарта в каталоге редактора
python ea_catalog.py --cabinet "ШЭТ 431.11-1"
python ea_new_standard.py --dry-run --code "СТО (проект, ред. 3)" --date 01.01.2027
python ea_new_standard.py --out "EA/new.json" --code "..." --date 01.01.2027 \
    --keep "ШЭТ 431.12-1" --replace "431.12-1 => 431.99-1"
python ea_docx.py --out "Отчет.docx"           # титул, оглавление, все таблицы
python tests/test_ea_standard.py --no-gui     # тесты без окна
```

В редакторе: вкладка **«Стандарты»** → **«СТО (EA)…»**. Слева дерево
разделов, шкафов, комплектов и ИЭУ, справа — таблица с данными из шкафа,
карточка шкафа или список функций ИЭУ.

* **«На схему»** (выбран шкаф) — шкаф заносится в каталог редактора
  (`ea_catalog.ensure_catalog`) и ставится на чертёж. Если запись с таким
  шифром уже есть, она используется как есть.
* **«Комплект → в шкаф»** (выбран комплект) — комплект добавляется в шкаф,
  выделенный на схеме (`add_komplekt_to_cabinet`).
* **«Новый стандарт…»** — диалог: реквизиты, набор шкафов, замены,
  перенумерация. Результат — отдельный JSON в папке стандартов.
* **«DOCX…»** — сборка документа Word в фоне (таблицы берутся из шкафов).
* **«Проверить»** — `ea_standard.validate()`.

## Что не зависит от старой ветки

`ea_standard.py` импортирует только стандартную библиотеку и `apppaths`.
`ea_ui.py` добавляет `ui_theme`, `ea_catalog` (каталог шкафов `cabs` и
`komplekts`), `ea_new_standard` и `ea_docx`. Старой ветки —
`standards_base`, `standards_editor`, `standards_ui`, `standard_editor` — не
использует ни один из них, поэтому новую ветку можно развивать, не
оглядываясь на старую.

## Архив

Неиспользуемые файлы старой ветки перенесены в
[`archive/legacy_standards/`](archive/legacy_standards/README.md):
`standard_editor/_parse/`, `standard_editor/example.json`,
`standard_editor/run_changes_gui.bat`, `cat/`, `rza_catalog/`. В README —
что это было и как вернуть.

## Удаление старой ветки

Старая ветка — это два разных слоя, удалять их нужно по очереди.

**Слой 1. Окна и редактор изменений** (удаляется без влияния на данные):

- `standards_editor.py`, `standards_ui.py`;
- `standard_editor/` целиком (включая `changes_gui.py`, `apply_changes.py`,
  базы `*.json`, `changes_text/`);
- кнопки «Стандарты…», «Редактор изменений…», «Собрать редакцию…»,
  «Новый стандарт…», «DOCX…» и методы `show_standards_window`,
  `open_standards_editor`, `show_new_standard_dialog`,
  `show_assembly_window`, `show_docx_window` в `main.py`;
- `tests/test_standards_editor.py`.

**Слой 2. Данные и сборка структуры** (удалять только после переноса):

- `standards_base.py`, `standards_base/*.json`, `standards_sync.py`,
  окно «Сверка…» и кнопка «Добавить из СТО»;
- `tests/test_standards_base.py`, `tests/test_standards_sync.py`;
- `tools/build_structure.py` сейчас читает `standards_base` — перед удалением
  его нужно переключить на `ea_standard` (поля карточек и таблицы ИЭУ) или
  собирать `structure.json` без стандартов;
- `build_exe.py`: убрать копирование `standards_base/` и `standard_editor/`,
  оставить `EA/`.

Проверка после каждого шага:

```bash
python tests/test_ea_standard.py --no-gui
python tests/test_structure_docking.py --no-gui
python tools/check_structure.py
```

Пока слой 2 не перенесён, `standards_base/` — источник данных для
`structure.json`, поэтому удалять его нельзя, даже если окна стандартов уже
убраны.
