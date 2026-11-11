import hashlib

import numpy as np
import pytest

from sfx_forge.core import generate_pack
from sfx_forge.presets import PRESETS, preset_names
from sfx_forge.synth import SR, cue_rng, render


def test_same_seed_same_bytes(tmp_path):
    a = generate_pack(presets=["hit", "coin"], seed=7, folder="a", root=tmp_path)
    b = generate_pack(presets=["hit", "coin"], seed=7, folder="b", root=tmp_path)
    assert [c["sha256"] for c in a["cues"]] == [c["sha256"] for c in b["cues"]]


def test_hash_independent_of_render_order(tmp_path):
    one = generate_pack(presets=["crit"], seed=11, folder="one", root=tmp_path)
    both = generate_pack(presets=["hit", "crit"], seed=11, folder="both", root=tmp_path)
    assert one["cues"][0]["sha256"] == both["cues"][1]["sha256"]


def test_different_seed_changes_output(tmp_path):
    a = generate_pack(presets=["hurt"], seed=1, folder="a", root=tmp_path)
    b = generate_pack(presets=["hurt"], seed=2, folder="b", root=tmp_path)
    assert a["cues"][0]["sha256"] != b["cues"][0]["sha256"]


def test_every_preset_renders_exact_length():
    for name in preset_names():
        preset = PRESETS[name]
        x = render(name, preset, 3)
        assert x.dtype == np.float32
        assert len(x) == int(round(preset["duration_ms"] / 1000.0 * SR))


def test_cue_rng_rejects_bad_seeds():
    with pytest.raises(TypeError):
        cue_rng("hit", True)
    with pytest.raises(ValueError):
        cue_rng("hit", -1)
