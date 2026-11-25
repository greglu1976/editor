# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_exchange``."""

import sys

from core import ea_exchange as _module

sys.modules[__name__] = _module
