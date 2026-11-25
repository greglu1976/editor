# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ribbon_icons``."""

import sys

from core import ribbon_icons as _module

sys.modules[__name__] = _module
