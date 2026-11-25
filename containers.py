# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.containers``."""

import sys

from core import containers as _module

sys.modules[__name__] = _module
