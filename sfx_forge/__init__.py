"""Deterministic, sample-free game SFX synthesis with a delivery gate."""

from .core import generate_pack, verify_file, QA_POLICY_VERSION  # noqa: F401
from .presets import PRESET_SCHEMA_VERSION, preset_names  # noqa: F401

__version__ = "1.0.0"
__all__ = [
    "generate_pack",
    "verify_file",
    "QA_POLICY_VERSION",
    "PRESET_SCHEMA_VERSION",
    "preset_names",
]
