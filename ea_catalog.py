# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_catalog``."""

import sys

from core import ea_catalog as _module

sys.modules[__name__] = _module
