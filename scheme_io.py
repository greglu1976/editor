# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.scheme_io``."""

import sys

from core import scheme_io as _module

sys.modules[__name__] = _module
