# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_ui``."""

import sys

from core import ea_ui as _module

sys.modules[__name__] = _module
