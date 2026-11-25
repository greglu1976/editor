# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``structure.cabs_sto``."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("structure.cabs_sto")
