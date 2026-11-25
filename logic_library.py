# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.logic_library``."""

import sys

from core import logic_library as _module

sys.modules[__name__] = _module
