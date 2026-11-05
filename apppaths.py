# -*- coding: utf-8 -*-
"""Папка приложения — единая точка для файлов данных рядом с программой.

В обычном запуске это папка с исходниками, в замороженной сборке
(PyInstaller / auto-py-to-exe) — папка с exe. Файлы каталогов
(``cabinets.json``, ``containers.json``, ``komplekts.json``,
``structure.json``) читаются и пишутся именно там: во временной папке
распаковки onefile правки пользователя пропали бы после закрытия.
"""

import os
import sys


def app_dir():
    """Папка с exe в сборке, папка с модулями при обычном запуске."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_path(name):
    """Путь к файлу данных рядом с приложением."""
    return os.path.join(app_dir(), name)
