# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_schema``."""

import sys

from core import ea_schema as _module

sys.modules[__name__] = _module
