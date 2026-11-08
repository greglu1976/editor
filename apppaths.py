# -*- coding: utf-8 -*-
"""Папка приложения, папка данных ``db`` и встроенные ресурсы сборки.

Раскладка собранного приложения (режим «One Directory»)::

    Редактор схем.exe
    _internal/…              служебные файлы PyInstaller
    db/
        cabinets.json        каталог шкафов (правки пользователя)
        cabs_signals.json    сигналы и испытательные блоки из СТО
        cabs_analog.json     аналоговые измерения из СТО
        containers.json      контейнеры КЭТ
        komplekts.json       комплекты (появляется после первой правки)
        structure.json       структура v3
        standards_base/      стандарты СТО в JSON
        standard_editor/     инструменты стандартов: модули, базы, изменения
        tools/               build_structure.py, check_structure.py
        schemes/             примеры схем (необязательно)

Файл данных ``X`` ищется по порядку:

1. ``$EDITOR_DB/X`` — если задана переменная окружения (портативная папка);
2. ``<папка exe>/db/X`` — обычная раскладка собранного приложения;
3. ``<папка exe>/X`` — плоская раскладка (совместимость и запуск из исходников);
4. ``<_MEIPASS>/db/X`` и ``<_MEIPASS>/X`` — данные, упакованные внутрь сборки
   (только чтение: временная папка распаковки существует до закрытия).

Если файла нет нигде, ``data_path`` возвращает путь в ``db`` — там его создаст
первое сохранение (``ensure_db``). Поэтому и из исходников, и из exe данные
лежат в одном месте и переживают перезапуск.
"""

import os
import sys

#: Имя папки данных рядом с программой.
DB_FOLDER = "db"

#: Переменная окружения для отдельной (переносимой) папки данных.
DB_ENV = "EDITOR_DB"


def is_frozen():
    """Программа собрана PyInstaller / auto-py-to-exe."""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Папка с exe в сборке, папка с модулями при обычном запуске."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundled_dir():
    """Временная папка распаковки onefile (``sys._MEIPASS``) или None."""
    return getattr(sys, "_MEIPASS", None)


def db_dir():
    """Папка данных: ``$EDITOR_DB`` или ``db`` рядом с программой."""
    override = os.environ.get(DB_ENV)
    if override:
        return os.path.abspath(override)
    return os.path.join(app_dir(), DB_FOLDER)


def ensure_db():
    """Создать папку данных, если её ещё нет. Возвращает её путь."""
    path = db_dir()
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path


def _candidates(name):
    """Возможные места файла данных в порядке приоритета."""
    places = [os.path.join(db_dir(), name),
              os.path.join(app_dir(), name)]
    bundled = bundled_dir()
    if bundled:
        places.append(os.path.join(bundled, DB_FOLDER, name))
        places.append(os.path.join(bundled, name))
    return places


def data_path(name):
    """Путь к файлу данных: первый существующий, иначе место для записи."""
    places = _candidates(name)
    for path in places:
        if os.path.exists(path):
            return path
    return places[0]


def data_dir(name):
    """Путь к папке данных (``standards_base``, ``tools``…).

    Существующая папка возвращается как есть (``db`` → рядом с exe →
    внутри сборки), отсутствующая — как ``db/name``: её создаст тот, кто
    пишет, если это вообще нужно.
    """
    return data_path(name)


def is_writable(path):
    """Папка (или файл) доступна для записи — грубая, но быстрая проверка."""
    target = path if os.path.isdir(path) else os.path.dirname(path) or "."
    return os.access(target, os.W_OK)


def exists(name):
    """Файл данных найден в одном из мест поиска."""
    return any(os.path.exists(path) for path in _candidates(name))


def describe():
    """Короткая сводка путей — для окна «О программе» и тестов."""
    return {
        "папка": app_dir(),
        "данные": db_dir(),
        "сборка": is_frozen(),
        "распаковка": bundled_dir(),
    }
