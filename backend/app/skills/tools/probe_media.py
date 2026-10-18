"""Compatibility alias; implementation lives in app.tools.specs.probe_media."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("app.tools.specs.probe_media")
