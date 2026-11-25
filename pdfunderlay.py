# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.pdfunderlay``."""

import sys

from core import pdfunderlay as _module

sys.modules[__name__] = _module
