"""Preset schema v1 and the shipped set.

Presets are data, not code: a preset is a duration plus a list of layers plus an
optional room. Adding a sound means adding a dict, not a function, which is what
keeps this an extensible capability rather than a ten-sound demo.
"""

from __future__ import annotations

PRESET_SCHEMA_VERSION = 1

MAX_LAYERS = 8
MAX_DURATION_MS = 2000
MIN_DURATION_MS = 40

PRESETS: dict[str, dict] = {
    "hit": {
        "duration_ms": 110,
        "layers": [
            {"kind": "tone", "wave": "tri", "freq": 180, "glide_to": 90, "gain": 0.7, "decay": 34},
            {"kind": "tone", "wave": "tri", "freq": 430, "glide_to": 300, "gain": 0.8, "decay": 40},
            {"kind": "noise", "band": [1200, 5000], "gain": 1.0, "decay": 70},
        ],
        "room": {"wet": 0.10, "decay": 0.06},
    },
    "crit": {
        "duration_ms": 220,
        "layers": [
            {"kind": "tone", "wave": "tri", "freq": 240, "glide_to": 120, "gain": 0.8, "decay": 20},
            {"kind": "fm", "carrier": 1180, "ratio": 1.41, "index": 2.2, "gain": 0.35, "decay": 15},
            {"kind": "noise", "band": [1500, 6000], "gain": 0.6, "decay": 55},
        ],
        "room": {"wet": 0.22, "decay": 0.09},
    },
    "hurt": {
        "duration_ms": 260,
        "layers": [
            {"kind": "tone", "wave": "saw", "freq": 110, "glide_to": 62, "gain": 0.55, "decay": 13},
            {"kind": "tone", "wave": "tri", "freq": 330, "glide_to": 210, "gain": 0.8, "decay": 18},
            {"kind": "noise", "band": [400, 2500], "gain": 0.8, "decay": 26},
        ],
        "room": {"wet": 0.12, "decay": 0.08},
    },
    "kill": {
        "duration_ms": 420,
        "layers": [
            {"kind": "tone", "wave": "sine", "freq": 80, "glide_to": 38, "gain": 0.5, "decay": 9},
            {"kind": "tone", "wave": "tri", "freq": 260, "glide_to": 150, "gain": 0.9, "decay": 11},
            {"kind": "noise", "band": [700, 4000], "gain": 0.9, "decay": 16},
        ],
        "room": {"wet": 0.20, "decay": 0.12},
    },
    "pick": {
        "duration_ms": 90,
        "layers": [
            {"kind": "tone", "wave": "tri", "freq": 880, "glide_to": 1320, "gain": 1.0, "decay": 40},
            {"kind": "noise", "band": [2000, 7000], "gain": 0.25, "decay": 90},
        ],
        "room": {"wet": 0.10, "decay": 0.04},
    },
    "coin": {
        "duration_ms": 260,
        "layers": [
            {"kind": "fm", "carrier": 1320, "ratio": 2.02, "index": 1.4, "gain": 0.7, "decay": 18},
            {"kind": "fm", "carrier": 1980, "ratio": 2.02, "index": 1.4, "gain": 0.55, "decay": 18},
        ],
        "room": {"wet": 0.14, "decay": 0.06},
    },
    "ward": {
        "duration_ms": 400,
        "layers": [
            {"kind": "sweep", "wave": "sine", "freq": 300, "freq_to": 520, "gain": 1.0, "decay": 2.2, "swell": 2.0},
            {"kind": "noise", "band": [1200, 5000], "gain": 0.18, "decay": 3.0, "swell": 3.0},
        ],
        "room": {"wet": 0.25, "decay": 0.10},
    },
    "deny": {
        "duration_ms": 180,
        "layers": [
            {"kind": "tone", "wave": "saw", "freq": 150, "gain": 0.7, "decay": 22},
            {"kind": "tone", "wave": "square", "freq": 470, "glide_to": 420, "gain": 0.5, "decay": 28},
        ],
        "room": {"wet": 0.08, "decay": 0.05},
    },
    "level": {
        "duration_ms": 620,
        "layers": [
            {"kind": "tone", "wave": "tri", "freq": 523.25, "gain": 0.55, "decay": 9},
            {"kind": "tone", "wave": "tri", "freq": 783.99, "gain": 0.45, "decay": 9},
            {"kind": "tone", "wave": "tri", "freq": 1046.5, "gain": 0.35, "decay": 9},
        ],
        "room": {"wet": 0.22, "decay": 0.10},
    },
    "death": {
        "duration_ms": 600,
        "layers": [
            {"kind": "tone", "wave": "saw", "freq": 220, "glide_to": 55, "gain": 1.0, "decay": 6},
            {"kind": "noise", "band": [400, 3000], "gain": 0.3, "decay": 12},
        ],
        "room": {"wet": 0.28, "decay": 0.14},
    },
}


def preset_names() -> list[str]:
    return sorted(PRESETS)


def validate_preset(name: str, preset: dict) -> None:
    """Raise ValueError unless a preset satisfies schema v1."""
    if not isinstance(preset, dict):
        raise ValueError(f"preset {name}: not a mapping")
    dur = preset.get("duration_ms")
    if not isinstance(dur, int) or isinstance(dur, bool):
        raise ValueError(f"preset {name}: duration_ms must be an int")
    if not MIN_DURATION_MS <= dur <= MAX_DURATION_MS:
        raise ValueError(f"preset {name}: duration_ms out of range")
    layers = preset.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= MAX_LAYERS:
        raise ValueError(f"preset {name}: layers must be 1..{MAX_LAYERS}")
    for i, layer in enumerate(layers):
        if not isinstance(layer, dict) or layer.get("kind") not in {"tone", "fm", "noise", "sweep"}:
            raise ValueError(f"preset {name}: layer {i} has an unknown kind")
        for key in ("freq", "carrier", "ratio", "index", "gain", "decay", "swell"):
            if key in layer:
                v = layer[key]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise ValueError(f"preset {name}: layer {i}.{key} must be numeric")
                if v != v or v in (float("inf"), float("-inf")):
                    raise ValueError(f"preset {name}: layer {i}.{key} must be finite")
        band = layer.get("band")
        if band is not None:
            if (not isinstance(band, (list, tuple)) or len(band) != 2
                    or not all(isinstance(b, (int, float)) for b in band) or band[0] >= band[1]):
                raise ValueError(f"preset {name}: layer {i}.band must be [lo, hi]")


for _name in PRESETS:
    validate_preset(_name, PRESETS[_name])
