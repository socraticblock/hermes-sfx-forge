"""Regression cases for issues found after the first 91-test audit."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from sfx_forge import paths
from sfx_forge.core import generate_pack, verify_pack
from sfx_forge.presets import PRESETS, validate_preset
from sfx_forge.synth import render


@pytest.mark.parametrize("filename", ["hit.wav", "manifest.json"])
def test_fifo_verification_never_blocks(tmp_path, filename):
    """A regression must time out rather than hang pytest on the old implementation."""
    generate_pack(["hit"], folder="p", root=tmp_path)
    target = tmp_path / "p" / filename
    target.unlink()
    os.mkfifo(target)
    script = (
        "import json, sys; from sfx_forge.core import verify_pack; "
        "result=verify_pack('p',root=sys.argv[1],presets=['hit']); "
        "print(json.dumps(result)); assert not result['passed']"
    )
    run = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                         capture_output=True, text=True, timeout=3)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result["passed"] is False
    if filename == "hit.wav":
        assert "file_regular" in result["results"][0]["failed_gates"]
    else:
        assert "manifest_valid" in result["results"][0]["failed_gates"]


def test_simultaneous_generation_same_pack_refused(tmp_path):
    root = paths.workspace_root(tmp_path)
    with paths.open_pack(root, "p", create=True) as (_, directory_fd):
        with paths.pack_write_lock(directory_fd):
            with pytest.raises(paths.PathRejected, match="already being generated"):
                generate_pack(["hit"], seed=2, root=tmp_path, folder="p", overwrite=True)
    # Releasing the cooperative lock permits normal generation.
    assert generate_pack(["hit"], seed=1, root=tmp_path, folder="p")["passed"]


def test_lock_is_stable_file_and_refuses_symlink(tmp_path):
    root = paths.workspace_root(tmp_path)
    with paths.open_pack(root, "p", create=True) as (p, directory_fd):
        with paths.pack_write_lock(directory_fd):
            pass
        inode = (p / ".sfx-pack.lock").stat().st_ino
        with paths.pack_write_lock(directory_fd):
            pass
        assert (p / ".sfx-pack.lock").stat().st_ino == inode
    (p / ".sfx-pack.lock").unlink()
    (p / ".sfx-pack.lock").symlink_to(tmp_path / "other")
    with paths.open_pack(root, "p") as (_, directory_fd):
        with pytest.raises(paths.PathRejected, match="lock"):
            with paths.pack_write_lock(directory_fd):
                pass


def test_manifest_seed_alone_cannot_forge_consistency(tmp_path):
    generate_pack(["hit"], seed=1, folder="p", root=tmp_path)
    manifest_file = tmp_path / "p" / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["seed"] = 2
    manifest_file.write_text(json.dumps(manifest))
    verdict = verify_pack("p", root=tmp_path)
    assert not verdict["passed"]
    assert "seed_consistency" in verdict["results"][0]["failed_gates"]


def test_manifest_seed_and_checksum_must_agree(tmp_path):
    generate_pack(["hit"], seed=1, folder="p", root=tmp_path)
    manifest_file = tmp_path / "p" / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["cues"][0]["sha256"] = "0" * 64
    manifest_file.write_text(json.dumps(manifest))
    verdict = verify_pack("p", root=tmp_path)
    assert not verdict["passed"]
    assert "seed_consistency" in verdict["results"][0]["failed_gates"]
    assert "manifest_sha256" in verdict["results"][0]["failed_gates"]


def test_regenerated_seed_verification_preserves_valid_pack(tmp_path):
    generate_pack(["hit", "coin"], seed=14, folder="p", root=tmp_path)
    verdict = verify_pack("p", root=tmp_path)
    assert verdict["passed"]
    assert all("seed_consistency" not in v["failed_gates"] for v in verdict["results"])


@pytest.mark.parametrize("layer", [
    {"kind": "tone", "freq": 100},
    {"kind": "tone", "wave": "sine"},
    {"kind": "tone", "wave": "unknown", "freq": 100},
    {"kind": "tone", "wave": [], "freq": 100},
    {"kind": "tone", "wave": "tri", "freq": 100, "glide_to": 0},
    {"kind": "tone", "wave": "tri", "freq": 100, "glide_to": float("inf")},
    {"kind": "fm", "carrier": 500, "ratio": 1},
    {"kind": "fm", "carrier": 500, "ratio": 1, "index": -1},
    {"kind": "noise"},
    {"kind": "noise", "band": [400, float("nan")]},
    {"kind": "noise", "band": [500, 500]},
    {"kind": "noise", "band": [100, 50]},
    {"kind": "sweep", "freq": 200},
    {"kind": ["tone"], "freq": 200, "wave": "sine"},
    {"kind": "tone", "wave": "sine", "freq": 100, "gain": -1},
    {"kind": "tone", "wave": "sine", "freq": 100, "swell": -1},
    {"kind": "tone", "wave": "sine", "freq": 100, "gain": 10**1000},
    {"kind": "tone", "wave": "sine", "freq": 100, "unknown": 1},
])
def test_reject_nonrenderable_layers(layer):
    with pytest.raises(ValueError):
        validate_preset("bad", {"duration_ms": 100, "layers": [layer]})


@pytest.mark.parametrize("room", [
    "room", [], {"wet": -0.1}, {"wet": float("inf")},
    {"decay": -1}, {"wet": None}, {"wet": 0.3, "unknown": 1},
])
def test_reject_invalid_room_settings(room):
    with pytest.raises(ValueError):
        validate_preset("bad", {"duration_ms": 100,
                                "layers": [{"kind": "tone", "wave": "sine", "freq": 100}],
                                "room": room})


def test_deeply_nested_manifest_fails_as_structured_verdict(tmp_path):
    generate_pack(["hit"], seed=1, folder="p", root=tmp_path)
    (tmp_path / "p" / "manifest.json").write_text("[" * 5000 + "0" + "]" * 5000)
    result = verify_pack("p", root=tmp_path, presets=["hit"])
    assert not result["passed"]
    assert "manifest_valid" in result["results"][0]["failed_gates"]


def test_valid_schema_is_renderable():
    for name, preset in PRESETS.items():
        validate_preset(name, preset)
        assert render(name, preset, 0).size > 0
