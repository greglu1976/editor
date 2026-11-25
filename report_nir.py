# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.report_nir``."""

import sys

from core import report_nir as _module

sys.modules[__name__] = _module
