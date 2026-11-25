# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ssdexport``."""

import sys

from core import ssdexport as _module

sys.modules[__name__] = _module
