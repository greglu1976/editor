# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_model``."""

import sys

from core import ea_model as _module

sys.modules[__name__] = _module
