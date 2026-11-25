# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.logic_editor``."""

import sys

from core import logic_editor as _module

sys.modules[__name__] = _module
