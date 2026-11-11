import numpy as np

from sfx_forge.core import expected_samples, verify_file
from sfx_forge.presets import PRESETS
from sfx_forge.qa import POLICY, evaluate
from sfx_forge.synth import SR, render


def _good(name="hit"):
    return render(name, PRESETS[name], 0)


def test_shipped_presets_pass_their_gate():
    for name, preset in PRESETS.items():
        v = evaluate(render(name, preset, 5), int(SR), expected_samples(preset))
        assert v["passed"], (name, v["failed_gates"])


def test_clipping_is_named():
    x = _good().copy()
    x[:64] = 1.0
    v = evaluate(x, int(SR))
    assert "no_clipping" in v["failed_gates"]
    assert "sample_peak_below_ceiling" in v["failed_gates"]


def test_dc_offset_is_named():
    x = _good() + 0.05
    v = evaluate(x, int(SR))
    assert "dc_offset_clean" in v["failed_gates"]


def test_wrong_length_is_named():
    x = _good()
    v = evaluate(x, int(SR), expected_samples=len(x) + 10)
    assert "sample_count_exact" in v["failed_gates"]


def test_non_finite_is_named():
    x = _good().copy()
    x[10] = np.nan
    v = evaluate(x, int(SR))
    assert "pcm_finite" in v["failed_gates"]


def test_loud_edges_are_named():
    x = _good().copy()
    x[0] = 0.5
    x[-1] = 0.5
    v = evaluate(x, int(SR))
    assert "edge_silence" in v["failed_gates"]


def test_verify_file_reports_hash_and_policy(tmp_path):
    from sfx_forge.core import generate_pack

    generate_pack(presets=["hit"], seed=0, folder="p", root=tmp_path)
    v = verify_file(tmp_path / "p" / "hit.wav", expected_samples(PRESETS["hit"]))
    assert v["passed"], v["failed_gates"]
    assert len(v["sha256"]) == 64
    assert v["policy_version"] == "1.0.0"
    assert v["measurements"]["sample_count"] == expected_samples(PRESETS["hit"])
