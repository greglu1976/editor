# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.schematic_library``."""

import sys

from core import schematic_library as _module

sys.modules[__name__] = _module
