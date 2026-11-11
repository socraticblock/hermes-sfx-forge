"""Independent audit regressions: assert externally observable failures."""
import json
import os
import wave

import pytest

from sfx_forge import core
from sfx_forge.core import generate_pack, verify_file, verify_pack
from sfx_forge.paths import PathRejected
from sfx_forge.tools import handle_generate, handle_verify


def test_stereo_input_fails_mono_gate(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    path = tmp_path / "p" / "hit.wav"
    with wave.open(str(path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    stereo = b"".join(frames[i:i+2] * 2 for i in range(0, len(frames), 2))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(stereo)
    result = verify_file(path, 4851)
    assert not result["passed"]
    assert "mono" in result["failed_gates"]


def test_internal_file_symlink_cannot_modify_protected_file(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    protected = folder / "protected.wav"
    protected.write_bytes(b"important protected data")
    (folder / "hit.wav").symlink_to(protected)
    with pytest.raises(PathRejected):
        generate_pack(["hit"], root=tmp_path, folder="p", overwrite=True)
    assert protected.read_bytes() == b"important protected data"
    assert (folder / "hit.wav").is_symlink()


def test_internal_folder_symlink_refused(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "p").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PathRejected):
        generate_pack(["hit"], root=tmp_path, folder="p")
    assert list((tmp_path / "real").iterdir()) == []


def test_race_cannot_overwrite_without_permission(tmp_path, monkeypatch):
    # Inject a competing writer after the preflight check, before publication.
    original = core._write_wav
    victim = tmp_path / "p" / "hit.wav"
    def interleave(*args, **kwargs):
        victim.write_bytes(b"other writer")
        return original(*args, **kwargs)
    monkeypatch.setattr(core, "_write_wav", interleave)
    with pytest.raises(PathRejected):
        generate_pack(["hit"], root=tmp_path, folder="p", overwrite=False)
    assert victim.read_bytes() == b"other writer"


def test_verify_pack_detects_swapped_valid_cue(tmp_path):
    generate_pack(["hit"], seed=1, root=tmp_path, folder="p")
    generate_pack(["hit"], seed=2, root=tmp_path, folder="other")
    (tmp_path / "p" / "hit.wav").write_bytes((tmp_path / "other" / "hit.wav").read_bytes())
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert not result["passed"]
    assert "manifest_sha256" in result["results"][0]["failed_gates"]


def test_malformed_wav_is_structured_failure(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    (tmp_path / "p" / "hit.wav").write_bytes(b"not a RIFF file")
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert result["passed"] is False
    assert result["results"][0]["failed_gates"]
    assert verify_file(tmp_path / "p" / "hit.wav")["passed"] is False


def test_verification_bounded_for_huge_file(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    with open(tmp_path / "p" / "hit.wav", "r+b") as f:
        f.truncate(2_000_000)
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert result["passed"] is False
    assert "max_file_bytes" in result["results"][0]["failed_gates"]


@pytest.mark.parametrize("args", [[1, 2], "hello", {"presets": [["hit"]]}, {"presets": [{"x": 1}]}])
def test_tool_rejects_invalid_json_shapes(args):
    reply = json.loads(handle_generate(args))
    assert reply["kind"] == "rejected"


def test_plugin_loader_does_not_pollute_import_path():
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    # A path-based plugin load is how Hermes imports the adapter.
    previous = sys.path[:]
    spec = importlib.util.spec_from_file_location("sfx_external_plugin_audit", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert sys.path == previous


def test_path_loaded_plugin_without_pythonpath_in_fresh_interpreter(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    plugin = Path(__file__).resolve().parents[1] / "__init__.py"
    code = f'''import importlib.util, sys, json
before = list(sys.path)
spec = importlib.util.spec_from_file_location('agent_plugin', {str(plugin)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Ctx:
    def __init__(self): self.names=[]
    def register_tool(self, **kwargs): self.names.append(kwargs['name'])
ctx=Ctx()
module.register(ctx)
assert ctx.names == ['sfx_generate', 'sfx_verify'], ctx.names
assert sys.path == before
'''
    run = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                         env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_verify_symlinked_file_fails_without_reading_target(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    protected = tmp_path / "protected.wav"
    protected.write_bytes(b"not WAV and should not be read")
    target = tmp_path / "p" / "hit.wav"
    target.unlink()
    target.symlink_to(protected)
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert not result["passed"]
    assert "file_regular" in result["results"][0]["failed_gates"]


def test_manifest_duplicate_field_fails_closed(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    manifest = tmp_path / "p" / "manifest.json"
    content = manifest.read_text()
    manifest.write_text('{"folder":"p","folder":"other","cues":[]}')
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert not result["passed"]
    assert "manifest_valid" in result["results"][0]["failed_gates"]


def test_verify_default_uses_manifest_cue_list(tmp_path):
    generate_pack(["hit", "coin"], root=tmp_path, folder="p")
    result = verify_pack("p", root=tmp_path)
    assert result["passed"]
    assert [r["preset"] for r in result["results"]] == ["hit", "coin"]


def test_oversized_manifest_fails_closed(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    with open(tmp_path / "p" / "manifest.json", "ab") as f:
        f.write(b" " * 270000)
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert not result["passed"]
    assert "manifest_valid" in result["results"][0]["failed_gates"]


def test_verification_of_truncated_payload_fails(tmp_path):
    generate_pack(["hit"], root=tmp_path, folder="p")
    file = tmp_path / "p" / "hit.wav"
    with file.open("r+b") as out:
        out.truncate(100)
    result = verify_file(file, 4851)
    assert not result["passed"]
    assert "wav_valid" in result["failed_gates"]


def test_dc_gate_uses_unrounded_measurement():
    import numpy as np
    from sfx_forge.qa import evaluate
    x = np.full(4410, 0.0020002)
    result = evaluate(x, 44100)
    assert "dc_offset_clean" in result["failed_gates"]


def test_edge_gate_uses_unrounded_measurement():
    import numpy as np
    from sfx_forge.qa import evaluate
    x = np.zeros(4410)
    x[0] = 10 ** (-59.999 / 20)
    result = evaluate(x, 44100)
    assert "edge_silence" in result["failed_gates"]


def test_empty_wav_fails_named_has_audio_gate(tmp_path):
    target = tmp_path / "empty.wav"
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(44100)
        out.writeframes(b"")
    result = verify_file(target)
    assert not result["passed"]
    assert "has_audio" in result["failed_gates"]
