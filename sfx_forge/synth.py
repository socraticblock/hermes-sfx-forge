"""Synthesis primitives and the preset renderer.

Pure NumPy. No subprocess, no network, no filesystem access: this module turns a
preset dict plus a seed into a float32 mono array, and nothing else.

Determinism rule: every cue derives its own generator from
sha256(preset_name + seed), so a cue's output never depends on what else was
rendered in the same run or in what order.
"""

from __future__ import annotations

import hashlib

import numpy as np
from scipy.signal import resample_poly

from .qa import POLICY

SR = 44100.0
ENV_ATTACK_S = 0.003
EDGE_FADE_S = 0.002
# Render targets are derived from the gate policy, never restated: change the
# ceiling in one place and the renderer follows, so a file cannot fail its own gate.
HEADROOM_DB = 0.5
PEAK_TARGET = 10 ** ((POLICY["sample_peak_ceiling_dbfs"] - HEADROOM_DB) / 20.0)
ISP_TARGET = 10 ** ((POLICY["intersample_peak_ceiling_dbtp"] - HEADROOM_DB) / 20.0)
OVERSAMPLE = int(POLICY["oversample"])


def cue_rng(preset_name: str, seed: int) -> np.random.Generator:
    """Per-cue generator derived from the preset name and the caller's seed."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    digest = hashlib.sha256(f"{preset_name}:{seed}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _lowpass(x: np.ndarray, cutoff_hz: float) -> np.ndarray:
    a = float(np.exp(-2.0 * np.pi * cutoff_hz / SR))
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1.0 - a) * x[i] + a * acc
        y[i] = acc
    return y


def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return _lowpass(x - _lowpass(x, lo), hi)


def _decay(n: int, rate: float) -> np.ndarray:
    return np.exp(-float(rate) * np.arange(n) / SR)


def _tone(n: int, wave: str, freq: float, glide_to: float | None) -> np.ndarray:
    if glide_to is None:
        f = np.full(n, float(freq))
    else:
        f = np.geomspace(float(freq), float(glide_to), n)
    phase = np.cumsum(2.0 * np.pi * f / SR)
    if wave == "sine":
        return np.sin(phase)
    if wave == "tri":
        return 2.0 * np.abs(2.0 * (phase / (2.0 * np.pi) % 1.0) - 1.0) - 1.0
    if wave == "saw":
        return 2.0 * (phase / (2.0 * np.pi) % 1.0) - 1.0
    if wave == "square":
        return np.sign(np.sin(phase))
    raise ValueError(f"unknown waveform: {wave}")


def _fm(n: int, carrier: float, ratio: float, index: float) -> np.ndarray:
    t = np.arange(n) / SR
    mod = np.sin(2.0 * np.pi * carrier * ratio * t)
    return np.sin(2.0 * np.pi * carrier * t + index * mod)


def _render_layer(layer: dict, n: int, rng: np.random.Generator) -> np.ndarray:
    kind = layer["kind"]
    if kind == "tone":
        x = _tone(n, layer["wave"], layer["freq"], layer.get("glide_to"))
    elif kind == "fm":
        x = _fm(n, layer["carrier"], layer["ratio"], layer["index"])
    elif kind == "noise":
        lo, hi = layer["band"]
        x = _bandpass(rng.standard_normal(n), lo, hi)
    elif kind == "sweep":
        x = _tone(n, layer.get("wave", "sine"), layer["freq"], layer["freq_to"])
    else:
        raise ValueError(f"unknown layer kind: {kind}")

    gain = float(layer.get("gain", 1.0))
    rate = float(layer.get("decay", 20.0))
    env = _decay(n, rate)
    attack = max(1, int(ENV_ATTACK_S * SR))
    if n > attack:
        env[:attack] *= np.linspace(0.0, 1.0, attack)
    swell = layer.get("swell")
    if swell:
        env *= np.linspace(0.0, 1.0, n) ** float(swell)
    return x * env * gain


def _room(x: np.ndarray, wet: float, decay: float) -> np.ndarray:
    if wet <= 0:
        return x
    out = x.copy()
    for delay_ms, gain in ((11, 0.5), (19, 0.34), (31, 0.24), (47, 0.16)):
        d = int(SR * delay_ms / 1000.0)
        if 0 < d < len(x):
            out[d:] += gain * wet * x[:-d] * np.exp(-decay * d / SR * 8.0)
    return out


def render(preset_name: str, preset: dict, seed: int) -> np.ndarray:
    """Render one preset to an exact-length mono float32 array."""
    n = int(round(preset["duration_ms"] / 1000.0 * SR))
    rng = cue_rng(preset_name, seed)
    mix = np.zeros(n, dtype=np.float64)
    for layer in preset["layers"]:
        mix += _render_layer(layer, n, rng)
    room = preset.get("room") or {}
    mix = _room(mix, float(room.get("wet", 0.0)), float(room.get("decay", 0.08)))
    return _finish(mix)[:n].astype(np.float32)


def _finish(x: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(x))) + 1e-12
    x = x / peak * PEAK_TARGET
    # The gate is on inter-sample peak, so the renderer honours it too: hard-edged
    # waveforms (saw, square) overshoot between samples and would otherwise fail
    # their own gate on a value no sample-level normalizer can see.
    isp = float(np.max(np.abs(resample_poly(x, OVERSAMPLE, 1)))) + 1e-12
    if isp > ISP_TARGET:
        x = x * (ISP_TARGET / isp)
    fade = max(1, int(EDGE_FADE_S * SR))
    if len(x) > 2 * fade:
        x[:fade] *= np.linspace(0.0, 1.0, fade)
        x[-fade:] *= np.linspace(1.0, 0.0, fade)
    return x
