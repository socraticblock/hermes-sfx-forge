"""Shared SFX generation and verification boundary for CLI and Hermes tools.

Untrusted pack names are resolved through directory descriptors; no adapter may
bypass the same resource caps, validation, and QA verdict implementation.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import wave
from pathlib import Path

import numpy as np

from . import paths as P
from .presets import PRESET_SCHEMA_VERSION, PRESETS, MAX_DURATION_MS, preset_names, validate_preset
from .qa import QA_POLICY_VERSION, evaluate
from .synth import SR, render

MAX_CUES_PER_CALL = 16
MAX_SEED = 2 ** 63 - 1
MAX_AUDIO_FRAMES = int(SR * MAX_DURATION_MS / 1000.0)
MAX_WAV_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 262_144


class RequestRejected(ValueError):
    """An untrusted caller argument was rejected."""


class AudioRejected(ValueError):
    """Malformed or unsupported audio, with a machine-readable QA gate."""

    def __init__(self, gate: str, message: str):
        self.gate = gate
        super().__init__(message)


def _check_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise RequestRejected("seed must be an integer")
    if not 0 <= seed <= MAX_SEED:
        raise RequestRejected(f"seed must be between 0 and {MAX_SEED}")
    return seed


def _check_bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise RequestRejected(f"{name} must be a boolean")
    return value


def _check_presets(presets) -> list[str]:
    if presets is None:
        return preset_names()
    if isinstance(presets, str):
        presets = [presets]
    if not isinstance(presets, (list, tuple)):
        raise RequestRejected("presets must be a list of preset names")
    names = list(presets)
    if not names:
        raise RequestRejected("presets must not be empty")
    if len(names) > MAX_CUES_PER_CALL:
        raise RequestRejected(f"at most {MAX_CUES_PER_CALL} presets per call")
    if any(not isinstance(n, str) for n in names):
        raise RequestRejected("every preset name must be a string")
    unknown = [n for n in names if n not in PRESETS]
    if unknown:
        raise RequestRejected(f"unknown preset(s): {', '.join(sorted(unknown))}")
    if len(set(names)) != len(names):
        raise RequestRejected("presets must not repeat")
    return names


def expected_samples(preset: dict) -> int:
    return int(round(preset["duration_ms"] / 1000.0 * SR))


def _write_wav(out, samples: np.ndarray) -> None:
    pcm = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 0.999969)
    data = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(SR))
        w.writeframes(data)


def _read_wav(stream) -> tuple[np.ndarray, int, int, int]:
    """Read at most 2s of PCM; preserve channels so the mono gate can reject."""
    with wave.open(stream, "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        if width != 2:
            raise AudioRejected("bits_per_sample", "expected 16-bit PCM")
        if channels < 1 or channels > 8:
            raise AudioRejected("channel_count", "unsupported channel count")
        if nframes > MAX_AUDIO_FRAMES:
            raise AudioRejected("max_sample_count", "WAV exceeds the 2-second cue limit")
        raw = w.readframes(nframes)
    if len(raw) != nframes * width * channels:
        raise AudioRejected("wav_valid", "truncated WAV payload")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate, width, channels


def _failed_file(path: Path, gate: str, message: str = "") -> dict:
    return {"path": str(path), "policy_version": QA_POLICY_VERSION,
            "passed": False, "gates": {gate: False}, "failed_gates": [gate],
            "measurements": {}, "warnings": [], "error": message}


def _fail_gate(verdict: dict, gate: str) -> None:
    verdict.setdefault("gates", {})[gate] = False
    if gate not in verdict["failed_gates"]:
        verdict["failed_gates"].append(gate)
    verdict["passed"] = False


def _verify_file(path: Path, expected_samples_: int | None,
                 directory_fd: int | None = None) -> dict:
    path = Path(path)
    if path.suffix.lower() != ".wav":
        raise RequestRejected("verify accepts .wav only")
    if directory_fd is None and not path.is_file():
        raise RequestRejected(f"not a file: {path}")
    own_fd = directory_fd is None
    fd = os.open(path.parent.resolve(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if own_fd else directory_fd
    try:
        try:
            with P.open_regular(fd, path.name, max_bytes=MAX_WAV_BYTES) as stream:
                # Decode and hash the same bounded snapshot, not separate reads
                # that could observe different content during an in-place edit.
                payload = stream.read(MAX_WAV_BYTES + 1)
                if len(payload) > MAX_WAV_BYTES:
                    raise AudioRejected("max_file_bytes", "WAV exceeds file size limit")
                size = len(payload)
                data, rate, _, channels = _read_wav(io.BytesIO(payload))
                digest = hashlib.sha256(payload).hexdigest()
        except P.FileTooLarge as exc:
            return _failed_file(path, "max_file_bytes", str(exc))
        except P.PathRejected as exc:
            return _failed_file(path, "file_regular", str(exc))
        except AudioRejected as exc:
            return _failed_file(path, exc.gate, str(exc))
        except (wave.Error, EOFError, struct.error, ValueError, OSError) as exc:
            return _failed_file(path, "wav_valid", str(exc))
        verdict = evaluate(data, rate, expected_samples_)
        # The original channel count is authoritative, not a downmixed proxy.
        verdict["gates"]["mono"] = channels == 1
        if channels != 1:
            _fail_gate(verdict, "mono")
        verdict["path"] = str(path)
        verdict["sha256"] = digest
        verdict["bytes"] = size
        return verdict
    finally:
        if own_fd:
            os.close(fd)


def verify_file(path: str | os.PathLike, expected_samples_: int | None = None) -> dict:
    """Explicit CLI file verification; pack verification uses descriptor-scoped reads."""
    return _verify_file(Path(path), expected_samples_)


def generate_pack(presets=None, seed: int = 0, folder: str = "pack",
                  root: str | os.PathLike | None = None, overwrite: bool = False) -> dict:
    """Generate and report WAVs under an anchored, explicitly named pack folder."""
    seed = _check_seed(seed)
    overwrite = _check_bool(overwrite, "overwrite")
    names = _check_presets(presets)
    P.validate_name(folder)
    root_path = P.workspace_root(root)
    with P.open_pack(root_path, folder, create=True) as (folder_path, folder_fd):
        with P.pack_write_lock(folder_fd):
            return _generate_locked(names, seed, folder, folder_path, folder_fd, overwrite)


def _generate_locked(names, seed, folder, folder_path, folder_fd, overwrite):
    cues = []
    # The manifest is also subject to the same collision policy as cue files.
    manifest_path = P.resolve_file(folder_path, "manifest", ".json")
    P.ensure_free(manifest_path, overwrite)
    for name in names:
        preset = PRESETS[name]
        validate_preset(name, preset)
        samples = render(name, preset, seed)
        verdict = evaluate(samples, int(SR), expected_samples(preset))
        if not verdict["passed"]:
            raise RuntimeError(f"preset {name} failed its own gate: {verdict['failed_gates']}")
        target = P.resolve_file(folder_path, name, ".wav")
        P.ensure_free(target, overwrite)
        P.atomic_write(target, lambda out, s=samples: _write_wav(out, s),
                       overwrite=overwrite, directory_fd=folder_fd)
        file_verdict = _verify_file(target, expected_samples(preset), folder_fd)
        if not file_verdict["passed"]:
            raise RuntimeError(f"encoded {name} failed its gate: {file_verdict['failed_gates']}")
        cues.append({
            "preset": name, "file": f"{folder}/{name}.wav",
            "duration_ms": preset["duration_ms"],
            "sample_count": file_verdict["measurements"]["sample_count"],
            "sha256": file_verdict["sha256"],
            "passed": file_verdict["passed"],
            "failed_gates": file_verdict["failed_gates"],
            "measurements": file_verdict["measurements"],
        })
    manifest = {
        "policy_version": QA_POLICY_VERSION,
        "preset_schema_version": PRESET_SCHEMA_VERSION,
        "seed": seed, "sample_rate": int(SR), "folder": folder,
        "cue_count": len(cues), "passed": all(c["passed"] for c in cues),
        "cues": cues,
    }
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    P.atomic_write(manifest_path, lambda out: out.write(payload),
                   overwrite=overwrite, directory_fd=folder_fd)
    return manifest


def _unique_json_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate manifest field: {key}")
        obj[key] = value
    return obj


def _load_manifest(folder_fd: int, folder: str) -> tuple[dict, dict[str, dict]]:
    with P.open_regular(folder_fd, "manifest.json", max_bytes=MAX_MANIFEST_BYTES) as f:
        raw = f.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds size limit")
    manifest = json.loads(raw, object_pairs_hook=_unique_json_object)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cues"), list):
        raise ValueError("invalid manifest structure")
    cues = manifest["cues"]
    if (manifest.get("folder") != folder
            or manifest.get("policy_version") != QA_POLICY_VERSION
            or manifest.get("preset_schema_version") != PRESET_SCHEMA_VERSION
            or manifest.get("sample_rate") != int(SR)
            or type(manifest.get("seed")) is not int
            or not 0 <= manifest["seed"] <= MAX_SEED
            or manifest.get("cue_count") != len(cues)
            or manifest.get("passed") is not True
            or not 1 <= len(cues) <= MAX_CUES_PER_CALL):
        raise ValueError("manifest policy, schema, seed, or count mismatch")
    by_name = {}
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("invalid cue entry")
        name = cue.get("preset")
        if not isinstance(name, str) or name not in PRESETS or name in by_name:
            raise ValueError("unknown or duplicate manifest cue")
        if (cue.get("file") != f"{folder}/{name}.wav"
                or cue.get("sample_count") != expected_samples(PRESETS[name])
                or cue.get("duration_ms") != PRESETS[name]["duration_ms"]
                or cue.get("passed") is not True
                or cue.get("failed_gates") != []
                or not isinstance(cue.get("sha256"), str)
                or len(cue["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in cue["sha256"])):
            raise ValueError("invalid manifest cue metadata")
        by_name[name] = cue
    return manifest, by_name


def verify_pack(folder: str, root: str | os.PathLike | None = None,
                presets=None) -> dict:
    P.validate_name(folder)
    root_path = P.workspace_root(root)
    with P.open_pack(root_path, folder) as (folder_path, folder_fd):
        manifest, entries = None, {}
        manifest_error = None
        try:
            manifest, entries = _load_manifest(folder_fd, folder)
        except (P.PathRejected, ValueError, UnicodeError, OSError, RecursionError) as exc:
            manifest_error = str(exc)
        if presets is None:
            names = list(entries) if manifest is not None else preset_names()
        else:
            names = _check_presets(presets)
        results = []
        for name in names:
            # Keep the leaf un-followed here; the fd-based reader reports a
            # symlink as a failed verdict rather than raising during preflight.
            target = folder_path / f"{name}.wav"
            # Report a missing cue independently of manifest validity.
            try:
                os.stat(target.name, dir_fd=folder_fd, follow_symlinks=False)
            except FileNotFoundError:
                results.append({"preset": name, "passed": False,
                                "failed_gates": ["missing"], "gates": {"missing": False}})
                continue
            v = _verify_file(target, expected_samples(PRESETS[name]), folder_fd)
            if manifest_error is not None:
                _fail_gate(v, "manifest_valid")
            elif name not in entries:
                _fail_gate(v, "manifest_entry")
            elif v.get("sha256") != entries[name]["sha256"]:
                _fail_gate(v, "manifest_sha256")
            # Matching a manifest's own checksum proves only that the file and
            # manifest agree. Regenerate from the recorded seed to also check
            # the deterministic synthesis contract for the installed version.
            if manifest is not None and name in entries:
                expected = io.BytesIO()
                _write_wav(expected, render(name, PRESETS[name], manifest["seed"]))
                if hashlib.sha256(expected.getvalue()).hexdigest() != entries[name]["sha256"]:
                    _fail_gate(v, "seed_consistency")
            results.append({"preset": name, **v})
        return {
            "folder": folder, "policy_version": QA_POLICY_VERSION,
            "cue_count": len(results),
            "manifest_valid": manifest_error is None,
            "manifest_error": manifest_error,
            "passed": bool(results) and all(r.get("passed") for r in results),
            "results": results,
        }
