# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ui_theme``."""

import sys

from core import ui_theme as _module

sys.modules[__name__] = _module
