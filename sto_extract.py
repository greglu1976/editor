# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.sto_extract``."""

import sys

from core import sto_extract as _module

sys.modules[__name__] = _module
