"""Hermes plugin entry point: registration only, with isolated vendored imports.

Hermes loads this file by path; ordinary package imports instead use the normal
relative module. Neither mode changes the host's global sys.path.
"""
from __future__ import annotations

import sys

if __package__ and hasattr(sys.modules.get(__package__), "__path__"):
    from .sfx_forge.tools import register_tools
else:
    import hashlib
    import importlib
    import importlib.util
    from pathlib import Path

    _package_dir = Path(__file__).resolve().parent / "sfx_forge"
    _module_name = "_hermes_sfx_forge_" + hashlib.sha256(
        str(_package_dir).encode("utf-8")
    ).hexdigest()[:16]
    if _module_name not in sys.modules:
        _spec = importlib.util.spec_from_file_location(
            _module_name, _package_dir / "__init__.py",
            submodule_search_locations=[str(_package_dir)],
        )
        if _spec is None or _spec.loader is None:
            raise ImportError("cannot import packaged SFX Forge")
        _module = importlib.util.module_from_spec(_spec)
        sys.modules[_module_name] = _module
        try:
            _spec.loader.exec_module(_module)
        except BaseException:
            sys.modules.pop(_module_name, None)
            raise
    register_tools = importlib.import_module(f"{_module_name}.tools").register_tools

__all__ = ["register"]


def register(ctx) -> None:
    register_tools(ctx)
