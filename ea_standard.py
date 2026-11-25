# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_standard``."""

import sys

from core import ea_standard as _module

sys.modules[__name__] = _module
