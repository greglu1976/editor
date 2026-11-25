# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_edit``."""

import sys

from core import ea_edit as _module

sys.modules[__name__] = _module
