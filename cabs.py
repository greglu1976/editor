# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.cabs``."""

import sys

from core import cabs as _module

sys.modules[__name__] = _module
