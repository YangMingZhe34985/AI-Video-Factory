"""Compatibility alias; implementation lives in app.tools.spec."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("app.tools.spec")
