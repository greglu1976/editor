# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.pngexport``."""

import sys

from core import pngexport as _module

sys.modules[__name__] = _module
