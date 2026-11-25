# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_merge``."""

import sys

from core import ea_merge as _module

sys.modules[__name__] = _module
