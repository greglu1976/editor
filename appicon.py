# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.appicon``."""

import sys

from core import appicon as _module

sys.modules[__name__] = _module
