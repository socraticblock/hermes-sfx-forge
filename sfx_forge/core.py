"""Pack generation and verification: the only implementation both interfaces call.

The CLI and the Hermes tools are thin adapters over these functions. Every
enforcement decision (path policy, resource caps, QA gates) lives here, so an
adapter cannot bypass it and drift between interfaces is a test failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import wave
from pathlib import Path

import numpy as np

from . import paths as P
from .presets import PRESET_SCHEMA_VERSION, PRESETS, preset_names, validate_preset
from .qa import QA_POLICY_VERSION, evaluate
from .synth import SR, render

MAX_CUES_PER_CALL = 16
MAX_SEED = 2 ** 63 - 1


class RequestRejected(ValueError):
    """Raised when tool/CLI arguments violate the documented contract."""


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
    unknown = [n for n in names if n not in PRESETS]
    if unknown:
        raise RequestRejected(f"unknown preset(s): {', '.join(sorted(unknown))}")
    if len(set(names)) != len(names):
        raise RequestRejected("presets must not repeat")
    return names


def expected_samples(preset: dict) -> int:
    return int(round(preset["duration_ms"] / 1000.0 * SR))


def _write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 0.999969)
    data = (pcm * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(SR))
        w.writeframes(data)


def _read_wav(path: Path) -> tuple[np.ndarray, int, int]:
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate, width


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_pack(presets=None, seed: int = 0, folder: str = "pack",
                  root: str | os.PathLike | None = None, overwrite: bool = False) -> dict:
    """Render presets into <root>/<folder>/<preset>.wav and return the manifest."""
    seed = _check_seed(seed)
    overwrite = _check_bool(overwrite, "overwrite")
    names = _check_presets(presets)
    root_path = P.workspace_root(root)
    folder_path = P.resolve_dir(root_path, folder)
    folder_path.mkdir(exist_ok=True)
    if not folder_path.is_dir():
        raise P.PathRejected("folder target is not a directory")

    cues = []
    for name in names:
        preset = PRESETS[name]
        validate_preset(name, preset)
        samples = render(name, preset, seed)
        verdict = evaluate(samples, int(SR), expected_samples(preset))
        if not verdict["passed"]:
            raise RuntimeError(f"preset {name} failed its own gate: {verdict['failed_gates']}")

        target = P.resolve_file(folder_path, name, ".wav")
        P.ensure_free(target, overwrite=overwrite)
        P.atomic_write(target, lambda tmp, s=samples: _write_wav(tmp, s))

        data, rate, width = _read_wav(target)
        file_verdict = evaluate(data, rate, expected_samples(preset))
        cues.append({
            "preset": name,
            "file": f"{folder}/{name}.wav",
            "duration_ms": preset["duration_ms"],
            "sample_count": file_verdict["measurements"]["sample_count"],
            "sha256": sha256_file(target),
            "passed": file_verdict["passed"],
            "failed_gates": file_verdict["failed_gates"],
            "measurements": file_verdict["measurements"],
        })

    manifest = {
        "policy_version": QA_POLICY_VERSION,
        "preset_schema_version": PRESET_SCHEMA_VERSION,
        "seed": seed,
        "sample_rate": int(SR),
        "folder": folder,
        "cue_count": len(cues),
        "passed": all(c["passed"] for c in cues),
        "cues": cues,
    }
    manifest_path = P.resolve_file(folder_path, "manifest", ".json")
    P.atomic_write(manifest_path,
                   lambda tmp: Path(tmp).write_text(json.dumps(manifest, indent=2, sort_keys=True)))
    return manifest


def verify_file(path: str | os.PathLike, expected_samples_: int | None = None) -> dict:
    p = Path(path)
    if not p.is_file():
        raise RequestRejected(f"not a file: {p}")
    if p.suffix.lower() != ".wav":
        raise RequestRejected("verify accepts .wav only")
    data, rate, width = _read_wav(p)
    if width != 2:
        return {"path": str(p), "passed": False, "failed_gates": ["bits_per_sample"],
                "gates": {"bits_per_sample": False}, "measurements": {}, "warnings": []}
    verdict = evaluate(data, rate, expected_samples_)
    verdict["path"] = str(p)
    verdict["sha256"] = sha256_file(p)
    verdict["bytes"] = p.stat().st_size
    return verdict


def verify_pack(folder: str, root: str | os.PathLike | None = None,
                presets=None) -> dict:
    root_path = P.workspace_root(root)
    folder_path = P.resolve_dir(root_path, folder)
    if not folder_path.is_dir():
        raise RequestRejected(f"no such folder: {folder}")
    names = _check_presets(presets)
    results = []
    for name in names:
        target = P.resolve_file(folder_path, name, ".wav")
        if not target.is_file():
            results.append({"preset": name, "passed": False,
                            "failed_gates": ["missing"], "gates": {"missing": False}})
            continue
        v = verify_file(target, expected_samples(PRESETS[name]))
        results.append({"preset": name, **v})
    return {
        "folder": folder,
        "policy_version": QA_POLICY_VERSION,
        "cue_count": len(results),
        "passed": all(r.get("passed") for r in results),
        "results": results,
    }
