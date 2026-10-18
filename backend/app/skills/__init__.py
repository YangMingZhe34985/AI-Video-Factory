"""Compatibility exports for the pre-v3 tool namespace."""

import sys
from types import ModuleType
from app import tools as _canonical

__all__ = ["build_default_registry", "get_registry", "build_v3_registry"]


class _CompatibilityModule(ModuleType):
    def __getattr__(self, name):
        return getattr(_canonical, name)

    def __setattr__(self, name, value):
        # Existing integrations may replace the shared registry for a test/run.
        if name in {"_registry", "get_registry", "build_default_registry", "build_v3_registry"}:
            setattr(_canonical, name, value)
        else:
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _CompatibilityModule
