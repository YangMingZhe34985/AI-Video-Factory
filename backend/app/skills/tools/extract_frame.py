"""Compatibility alias; implementation lives in app.tools.specs.extract_frame."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("app.tools.specs.extract_frame")
