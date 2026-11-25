# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_new_standard``."""

import sys

from core import ea_new_standard as _module

sys.modules[__name__] = _module
