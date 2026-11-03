# -*- coding: utf-8 -*-
"""Точка входа миграции: python3 migrate_catalog.py [исходный.json].

Сам пакет лежит в ``rza_catalog/``; файл нужен, чтобы не переименовывать
существующий ``main.py`` приложения.
"""

from rza_catalog.main import main

if __name__ == "__main__":
    raise SystemExit(main())
