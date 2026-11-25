# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.library``."""

import sys

from core import library as _module

sys.modules[__name__] = _module
