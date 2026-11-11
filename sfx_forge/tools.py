"""Hermes tool schemas and handlers: thin adapters over sfx_forge.core."""

from __future__ import annotations

import json

from .core import MAX_CUES_PER_CALL, RequestRejected, generate_pack, verify_pack
from .paths import PathRejected
from .presets import preset_names

TOOLSET = "sfx_forge"


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


SFX_GENERATE_SCHEMA = {
    "name": "sfx_generate",
    "description": (
        "Render deterministic, sample-free game sound effects as 16-bit mono 44.1 kHz WAV files "
        "into a pack folder inside the configured workspace, then verify each file against the "
        "delivery gate and return a manifest with per-cue measurements and sha256 hashes. "
        "Output location is a workspace name, never an absolute path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "presets": {
                "type": "array",
                "items": {"type": "string", "enum": preset_names()},
                "description": f"Preset names to render (1-{MAX_CUES_PER_CALL}). Omit to render all.",
            },
            "seed": {
                "type": "integer",
                "minimum": 0,
                "description": "Master seed. Each cue derives its own generator from preset name + seed.",
            },
            "folder": {
                "type": "string",
                "description": "Pack folder name inside the workspace, matching ^[a-z0-9][a-z0-9_-]{0,39}$.",
            },
            "overwrite": {"type": "boolean", "description": "Replace existing files (default false)."},
        },
        "required": [],
    },
}

SFX_VERIFY_SCHEMA = {
    "name": "sfx_verify",
    "description": (
        "Verify WAV files in a pack folder against the delivery gate: exact sample count, sample and "
        "inter-sample peak ceilings, DC offset, clipping and edge silence. Returns a machine-readable "
        "pass/fail verdict per cue with the failing gate named."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "folder": {
                "type": "string",
                "description": "Existing pack folder name inside the workspace.",
            },
            "presets": {
                "type": "array",
                "items": {"type": "string", "enum": preset_names()},
                "description": "Subset to check. Omit to check the standard preset set.",
            },
        },
        "required": ["folder"],
    },
}


def _guard(fn):
    def wrapper(args, **kwargs):
        try:
            return _dumps(fn(args or {}))
        except (RequestRejected, PathRejected) as exc:
            return _dumps({"error": str(exc), "kind": "rejected"})
        except (OSError, ValueError, RuntimeError) as exc:
            return _dumps({"error": str(exc), "kind": "failed"})
    return wrapper


@_guard
def handle_generate(args: dict) -> dict:
    return generate_pack(
        presets=args.get("presets"),
        seed=args.get("seed", 0),
        folder=args.get("folder", "pack"),
        overwrite=args.get("overwrite", False),
    )


@_guard
def handle_verify(args: dict) -> dict:
    folder = args.get("folder")
    if not folder:
        raise RequestRejected("folder is required")
    return verify_pack(folder, presets=args.get("presets"))


TOOLS = (
    (SFX_GENERATE_SCHEMA, handle_generate),
    (SFX_VERIFY_SCHEMA, handle_verify),
)


def register_tools(ctx) -> None:
    for schema, handler in TOOLS:
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler)
