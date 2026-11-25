# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.komplekts``."""

import sys

from core import komplekts as _module

sys.modules[__name__] = _module
