"""Compatibility aliases preserving module identity and monkeypatch behavior."""

import sys
from importlib import import_module
from types import ModuleType

_canonical = import_module("app.tools.specs")
for _name, _value in vars(_canonical).items():
    if isinstance(_value, ModuleType) and _value.__name__.startswith("app.tools.specs."):
        sys.modules[f"{__name__}.{_name}"] = _value
sys.modules[__name__] = _canonical
