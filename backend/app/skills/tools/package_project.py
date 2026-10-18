"""Compatibility alias; implementation lives in app.tools.specs.package_project."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("app.tools.specs.package_project")
