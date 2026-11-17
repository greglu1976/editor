# Архив старой ветки стандартов

Сюда перенесено то, что относилось к прежней (доструктурной) работе со
стандартами и больше нигде не используется. Новый формат — JSON по модели
`EA/structure.eapx`, его читают `ea_standard.py`, `ea_ui.py`,
`ea_catalog.py`, `ea_new_standard.py` и `ea_docx.py`.

Перенос сделан по проверке ссылок: ни один модуль редактора эти файлы не
импортирует и не читает.

| Что | Откуда | Чем было |
|-----|--------|----------|
| `_parse/` | `standard_editor/_parse/` | Скрипты разбора PDF (`build_json*.py`, `build_complects.py`), их отчёты, тестовые DOCX. Черновики сборки старого JSON. |
| `example.json` | `standard_editor/example.json` | Ручной образец старого формата (`Содержимое стандарта`, `Таблицы`, `Комплект`). |
| `run_changes_gui.bat` | `standard_editor/run_changes_gui.bat` | Запуск `changes_gui.py` двойным щелчком. |
| `cat/` | `cat/` | Два JSON по КЭТ-6-2/6-3; ни один модуль их не читает. |
| `rza_catalog/` | `rza_catalog/` | Остались только `.pyc` удалённого пакета (`models`, `store`, `export`…), исходников нет. |

## Что осталось на месте

Старая ветка ещё работает и удаляется отдельным шагом:

* `standards_base/` + `standards_base.py` — база старых стандартов;
* `standards_editor.py`, `standards_sync.py`, `standards_ui.py` — окна и
  синхронизация старой ветки;
* `standard_editor/` без `_parse`, `example.json` и `.bat` — редактор
  изменений (`apply_changes.py`, `changes_gui.py`, `json_to_docx.py`,
  `make_standard.py`);
* `tools/build_structure.py` — ещё импортирует `standards_base`.

## Как вернуть

```bash
git mv archive/legacy_standards/_parse standard_editor/_parse
git mv archive/legacy_standards/example.json standard_editor/example.json
git mv archive/legacy_standards/run_changes_gui.bat standard_editor/run_changes_gui.bat
git mv archive/legacy_standards/cat cat
```

`rza_catalog/` в git не хранился (только `__pycache__`), поэтому
восстанавливать нечего: пакет удалён вместе с исходниками.
