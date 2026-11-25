# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.schematic_symbols``."""

import sys

from core import schematic_symbols as _module

sys.modules[__name__] = _module
