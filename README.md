# hermes-sfx-forge

Deterministic, sample-free game sound effects with a delivery gate.

Two tools, one implementation. `sfx_generate` renders short one-shot WAV cues from
named presets and an explicit seed; `sfx_verify` checks files against a fixed gate
and returns a machine-readable verdict. The command line calls the same functions,
so the two interfaces cannot drift.

## What this is not

- Not a model and not a song generator. There is no ML, no GPU and no network. Synthesis is NumPy; SciPy is used only for the 4x oversampling that measures inter-sample peak.
- Not a sampler. Every sample is synthesized; no audio assets ship with it.
- Not a loudness meter. Integrated LUFS is deliberately absent: BS.1770 gates in
  400 ms blocks, and most one-shots are shorter than one block, so the measurement
  is undefined for them.

## Install

```bash
pip install .
```

The plugin path is a directory under `~/.hermes/plugins/hermes-sfx-forge/` (or a
catalog install at a pinned commit).

## Use

```bash
sfx-forge presets
sfx-forge generate --preset hit --preset coin --seed 7 --folder demo --root /tmp/sfx --json
sfx-forge verify --folder demo --root /tmp/sfx --json
```

From a Hermes session, the tools are `sfx_generate` and `sfx_verify`. The workspace
root is `SFX_FORGE_ROOT` (default `~/.hermes/sfx-forge`); tool calls name a folder
inside it and cannot supply a path.

## The gate (policy 1.0.0)

Hard fail: non-finite samples · wrong sample rate · not mono · sample count not
exactly the preset's · any sample at or beyond full scale · sample peak above
-1.0 dBFS · 4x-oversampled inter-sample peak above -1.0 dBTP · DC magnitude above
0.002 · non-silent first or last sample (-60 dBFS threshold).

Reported, not gated: RMS, crest factor, spectral centroid, 60-200 Hz energy.

Every cue is normalized to 0.84 (-1.51 dBFS) and then, if 4x oversampling shows a
higher inter-sample peak, scaled down so the inter-sample peak also sits at 0.84
(-1.51 dBTP). Both targets are below the gate ceiling by design, so a rendered
file cannot fail its own gate on a rounding boundary.

## Determinism

Each cue derives its own generator from `sha256(preset_name + ":" + seed)`, so a
cue's bytes never depend on which other cues were rendered or in what order. The
same preset and seed produce byte-identical WAV on the same interpreter and
platform; cross-platform byte-identity is not claimed, because NumPy's
floating-point results and the WAV quantizer are only pinned per environment.

## Output safety

Names must match `^[a-z0-9][a-z0-9_-]{0,39}$`. Absolute paths, traversal, Windows
drive forms, separators, symlinks and collisions are refused in code, and files are
published through a private temporary file and an atomic rename, so a partial WAV
never appears at the final name.

## License

MIT for this code. Dependencies: NumPy and SciPy, both BSD-3-Clause. See
`THIRD_PARTY.md`. No third-party audio, no bundled binaries.
