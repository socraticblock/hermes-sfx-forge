"""Hermes plugin entry point for hermes-sfx-forge.

Registration only: every behaviour lives in sfx_forge.core, which the CLI calls
through the same functions. Two loader styles exist — the plugin host imports this
file by path (so the plugin directory must join sys.path for the vendored package
to resolve), while tests and `python -m` import it as part of a package.
"""

from __future__ import annotations

try:  # imported as a package (tests, `python -m`)
    from .sfx_forge.tools import register_tools
except ImportError:  # imported by path by the plugin host
    import sys
    from pathlib import Path

    _here = str(Path(__file__).resolve().parent)
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from sfx_forge.tools import register_tools

__all__ = ["register"]


def register(ctx) -> None:
    register_tools(ctx)
