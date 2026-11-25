# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_structure``."""

import sys

from core import ea_structure as _module

sys.modules[__name__] = _module
