# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.apppaths``."""

import sys

from core import apppaths as _module

sys.modules[__name__] = _module
