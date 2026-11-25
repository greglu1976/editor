# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.pdfexport``."""

import sys

from core import pdfexport as _module

sys.modules[__name__] = _module
