# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_report``."""

import sys

from core import ea_report as _module

sys.modules[__name__] = _module
