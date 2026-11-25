# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_editor``."""

import sys

from core import ea_editor as _module

sys.modules[__name__] = _module
