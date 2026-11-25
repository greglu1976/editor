# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.pdf2json``."""

import sys

from core import pdf2json as _module

sys.modules[__name__] = _module
