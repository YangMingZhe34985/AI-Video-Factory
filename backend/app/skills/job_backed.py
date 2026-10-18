"""Compatibility alias; implementation lives in app.tools.job_backed."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("app.tools.job_backed")
