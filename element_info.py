# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.element_info``."""

import sys

from core import element_info as _module

sys.modules[__name__] = _module
