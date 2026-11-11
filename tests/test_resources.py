import pytest

from sfx_forge.core import MAX_CUES_PER_CALL, RequestRejected, generate_pack
from sfx_forge.presets import MAX_DURATION_MS, PRESETS, preset_names, validate_preset


@pytest.mark.parametrize("seed", [True, -1, 1.5, "5", None, 2 ** 63])
def test_bad_seeds_rejected(seed, tmp_path):
    with pytest.raises(RequestRejected):
        generate_pack(presets=["hit"], seed=seed, root=tmp_path)


def test_unknown_preset_rejected(tmp_path):
    with pytest.raises(RequestRejected):
        generate_pack(presets=["nope"], seed=0, root=tmp_path)


def test_empty_and_duplicate_presets_rejected(tmp_path):
    with pytest.raises(RequestRejected):
        generate_pack(presets=[], seed=0, root=tmp_path)
    with pytest.raises(RequestRejected):
        generate_pack(presets=["hit", "hit"], seed=0, root=tmp_path)


def test_too_many_cues_rejected(tmp_path):
    with pytest.raises(RequestRejected):
        generate_pack(presets=preset_names() * 2, seed=0, root=tmp_path)


def test_preset_duration_cap():
    bad = {"duration_ms": MAX_DURATION_MS + 1, "layers": [{"kind": "tone", "wave": "sine", "freq": 100}]}
    with pytest.raises(ValueError):
        validate_preset("bad", bad)


def test_unknown_layer_kind():
    bad = {"duration_ms": 100, "layers": [{"kind": "laser", "freq": 100}]}
    with pytest.raises(ValueError):
        validate_preset("bad", bad)
