# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.logic_scheme_render``."""

import sys

from core import logic_scheme_render as _module

sys.modules[__name__] = _module
