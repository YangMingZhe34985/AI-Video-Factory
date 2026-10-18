"""Compatibility alias; implementation lives in app.tools.model_guard."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("app.tools.model_guard")
