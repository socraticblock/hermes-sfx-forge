"""Delivery gate for short one-shot assets.

No integrated loudness: BS.1770 gates in 400 ms blocks and most one-shots are
shorter than one block, so the measurement is undefined for them. One-shots are
gated on peak, inter-sample peak, DC, edges and clipping; RMS and crest factor are
reported for comparison, not gated.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly

QA_POLICY_VERSION = "1.0.0"

POLICY: dict = {
    "sample_rate": 44100,
    "channels": 1,
    "bits_per_sample": 16,
    "sample_peak_ceiling_dbfs": -1.0,
    "intersample_peak_ceiling_dbtp": -1.0,
    "dc_max_abs": 0.002,
    "edge_silence_dbfs": -60.0,
    "rms_diagnostic_dbfs": -45.0,
    "oversample": 4,
}


def _db(value: float) -> float:
    v = 20.0 * float(np.log10(max(abs(float(value)), 1e-12)))
    return max(v, -120.0)


def spectral_centroid(x: np.ndarray, sr: int) -> float:
    if not x.size:
        return 0.0
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    total = float(spec.sum())
    return float((freqs * spec).sum() / total) if total > 0 else 0.0


def band_ratio(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    if not x.size:
        return 0.0
    spec = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    sel = (freqs >= lo) & (freqs < hi)
    total = float(spec.sum())
    return float(spec[sel].sum() / total) if total > 0 else 0.0


def measure(x: np.ndarray, sr: int, policy: dict = POLICY) -> dict:
    x = np.asarray(x)
    mono = x if x.ndim == 1 else x.mean(axis=1)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    up = resample_poly(mono, int(policy["oversample"]), 1)
    isp = float(np.max(np.abs(up))) if up.size else 0.0
    rms = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
    dc = float(np.mean(mono)) if mono.size else 0.0
    return {
        "sample_count": int(mono.size),
        "duration_s": round(mono.size / float(sr), 4),
        "sample_peak_dbfs": round(_db(peak), 2),
        "intersample_peak_dbtp": round(_db(isp), 2),
        "rms_dbfs": round(_db(rms), 2),
        "crest_db": round(_db(peak) - _db(rms), 2),
        "dc_offset": round(dc, 6),
        "clipped_samples": int(np.sum(np.abs(mono) >= 0.999)),
        "first_sample_dbfs": round(_db(float(mono[0])), 2) if mono.size else -120.0,
        "last_sample_dbfs": round(_db(float(mono[-1])), 2) if mono.size else -120.0,
        "spectral_centroid_hz": round(spectral_centroid(mono, sr), 1),
        "low_band_60_200": round(band_ratio(mono, sr, 60, 200), 3),
    }


def evaluate(x: np.ndarray, sr: int, expected_samples: int | None = None,
             policy: dict = POLICY) -> dict:
    """Return a machine-readable verdict; never raises on bad audio."""
    try:
        x = np.asarray(x, dtype=np.float64)
        if x.ndim not in (1, 2):
            raise ValueError("audio must have one or two dimensions")
        finite = bool(np.isfinite(x).all())
        # Measurements must never crash on NaN/Inf. The finite gate still fails.
        clean = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)
        m = measure(clean, max(int(sr), 1), policy)
        mono = clean if clean.ndim == 1 else clean.mean(axis=1)
        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        isp = float(np.max(np.abs(resample_poly(mono, int(policy["oversample"]), 1)))) if mono.size else 0.0
    except (TypeError, ValueError, OverflowError, MemoryError):
        return {"policy_version": QA_POLICY_VERSION, "expected_samples": expected_samples,
                "gates": {"pcm_finite": False}, "failed_gates": ["pcm_finite"],
                "passed": False, "measurements": {}, "warnings": []}
    dc_abs = abs(float(np.mean(mono))) if mono.size else 0.0
    edge_limit = 10 ** (policy["edge_silence_dbfs"] / 20.0)
    edge_ok = bool(mono.size) and abs(float(mono[0])) <= edge_limit and abs(float(mono[-1])) <= edge_limit
    gates = {
        "has_audio": bool(mono.size),
        "pcm_finite": finite,
        "sample_rate": int(sr) == int(policy["sample_rate"]),
        "mono": x.ndim == 1,
        "sample_count_exact": (expected_samples is None or m["sample_count"] == int(expected_samples)),
        "no_clipping": m["clipped_samples"] == 0,
        "sample_peak_below_ceiling": peak <= 10 ** (policy["sample_peak_ceiling_dbfs"] / 20.0),
        "intersample_peak_below_ceiling": isp <= 10 ** (policy["intersample_peak_ceiling_dbtp"] / 20.0),
        "dc_offset_clean": dc_abs <= policy["dc_max_abs"],
        "edge_silence": edge_ok,
    }
    failed = [k for k, v in gates.items() if not v]
    return {
        "policy_version": QA_POLICY_VERSION,
        "expected_samples": expected_samples,
        "gates": gates,
        "failed_gates": failed,
        "passed": not failed,
        "measurements": m,
        "warnings": (["rms_below_diagnostic_threshold"]
                     if m["rms_dbfs"] < policy["rms_diagnostic_dbfs"] else []),
    }
