"""Hostile inputs: the attacks a reviewer will try before trusting the gate."""

import json
import threading

import numpy as np
import pytest

from sfx_forge.core import RequestRejected, generate_pack, verify_file, verify_pack
from sfx_forge.paths import PathRejected, workspace_root
from sfx_forge.presets import PRESETS
from sfx_forge.qa import evaluate
from sfx_forge.synth import SR, render
from sfx_forge.tools import handle_generate, handle_verify


@pytest.mark.parametrize("folder", ["../escape", "/abs/path", "C:\\windows", "a/b", "..", "X" * 41, "", "name.wav"])
def test_tool_generate_rejects_hostile_folders(folder, tmp_path, monkeypatch):
    monkeypatch.setenv("SFX_FORGE_ROOT", str(tmp_path))
    reply = json.loads(handle_generate({"presets": ["hit"], "folder": folder}))
    assert reply["kind"] == "rejected", reply
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("folder", ["../escape", "/etc", "C:\\x", "a/b"])
def test_tool_verify_rejects_hostile_folders(folder, tmp_path, monkeypatch):
    monkeypatch.setenv("SFX_FORGE_ROOT", str(tmp_path))
    reply = json.loads(handle_verify({"folder": folder}))
    assert reply["kind"] == "rejected"


def test_tool_argument_types_are_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("SFX_FORGE_ROOT", str(tmp_path))
    for args in ({"presets": "hit", "seed": -1},
                 {"presets": {"a": 1}},
                 {"presets": ["hit"], "overwrite": "yes"},
                 {"presets": ["hit"], "seed": float("nan")}):
        reply = json.loads(handle_generate(args))
        assert "error" in reply, (args, reply)


def test_symlinked_folder_rejected(tmp_path):
    root = workspace_root(tmp_path / "root")
    import os

    os.symlink(tmp_path, root / "evil")
    with pytest.raises(PathRejected):
        generate_pack(presets=["hit"], seed=0, folder="evil", root=root)


def test_verify_refuses_missing_and_non_wav(tmp_path):
    with pytest.raises(RequestRejected):
        verify_file(tmp_path / "nope.wav")
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(RequestRejected):
        verify_file(bad)


def test_verify_reports_missing_cue_instead_of_crashing(tmp_path):
    generate_pack(presets=["hit"], seed=0, folder="p", root=tmp_path)
    result = verify_pack("p", root=tmp_path, presets=["hit", "coin"])
    assert result["passed"] is False
    assert result["results"][1]["failed_gates"] == ["missing"]


def test_concurrent_writers_never_leave_a_partial_file(tmp_path):
    errors = []

    def run():
        try:
            generate_pack(presets=["kill", "ward"], seed=9, folder="race", root=tmp_path)
        except PathRejected:
            pass
        except Exception as exc:  # noqa: BLE001 - recorded, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    for name in ("kill", "ward"):
        path = tmp_path / "race" / f"{name}.wav"
        v = verify_file(path, int(round(PRESETS[name]["duration_ms"] / 1000.0 * SR)))
        assert v["passed"], (name, v["failed_gates"])


def test_quantization_cannot_push_a_cue_over_the_ceiling(tmp_path):
    # every shipped cue must survive the int16 round trip, which is where a
    # rounding boundary would show up
    manifest = generate_pack(seed=3, folder="q", root=tmp_path)
    assert manifest["passed"]
    for cue in manifest["cues"]:
        assert cue["measurements"]["intersample_peak_dbtp"] <= -1.0
        assert cue["measurements"]["sample_peak_dbfs"] <= -1.0


def test_gate_cannot_be_fooled_by_a_silent_file(tmp_path):
    (tmp_path / "p").mkdir()
    import wave

    with wave.open(str(tmp_path / "p" / "hit.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(np.zeros(4851, dtype="<i2").tobytes())
    v = verify_file(tmp_path / "p" / "hit.wav", 4851)
    assert v["passed"], v["failed_gates"]
    assert "rms_below_diagnostic_threshold" in v["warnings"]
