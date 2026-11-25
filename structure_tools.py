# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``structure.structure_tools``."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("structure.structure_tools")
