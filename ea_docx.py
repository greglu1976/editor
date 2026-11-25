# -*- coding: utf-8 -*-
"""Совместимость: модуль переехал в ``core.ea_docx``."""

import sys

from core import ea_docx as _module

sys.modules[__name__] = _module
