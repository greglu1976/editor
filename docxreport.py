# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.docxreport``."""

import sys

from core import docxreport as _module

sys.modules[__name__] = _module
