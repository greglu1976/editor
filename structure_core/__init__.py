"""Слой расширяемых структур редактора.

Пакет не импортирует ``main.py``, ``library.py``, каталоги шкафов или
другие модули графического/устаревшего предметного слоя. Он описывает
интерфейс плагина, реестр и визуальный менеджер структур.
"""

from .base import PlaceholderPlugin, StructurePlugin, UnavailablePlugin
from .manager import StructureManagerWindow
from .registry import StructureRegistry

__all__ = [
    "StructurePlugin",
    "PlaceholderPlugin",
    "UnavailablePlugin",
    "StructureRegistry",
    "StructureManagerWindow",
]
