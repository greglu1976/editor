# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.report_selection``."""

import sys

from core import report_selection as _module

sys.modules[__name__] = _module
