# hermes-sfx-forge

Deterministic, sample-free game sound effects with a delivery gate.

Two tools, one implementation. `sfx_generate` renders short one-shot WAV cues from
named presets and an explicit seed; `sfx_verify` checks files against a fixed gate
and returns a machine-readable verdict. The command line calls the same functions,
so the two interfaces cannot drift.

## What this is not

- Not a model and not a song generator. There is no ML, no GPU and no network. Synthesis uses NumPy and SciPy for array math, noise filtering and inter-sample peak estimation.
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

`verify --folder` checks the exact sample count and **SHA-256 against the pack
manifest** for every selected cue. It also regenerates the expected WAV SHA-256
from the recorded seed and the installed preset engine. With no explicit
`--preset`, it verifies the cues listed in that manifest. Missing, malformed,
oversized, or inconsistent manifests fail closed. The manifest is an **integrity consistency record**, not a
signature or proof of authenticity: someone able to rewrite both WAVs and the
manifest can forge a new consistent pack. A bare `verify <path>` cannot know
which preset produced a file, so it only reports the sample count; use folder
verification for a complete pack verdict. The bare path form is an explicitly
invoked local CLI operation and may inspect a user-selected path outside the
workspace; Hermes tools accept only validated folder names.

Names must match `^[a-z0-9][a-z0-9_-]{0,39}$`. Untrusted absolute paths,
traversal, Windows drive forms, separators, and symlinked pack folders/files are
refused. Output reads and writes are anchored to open directory descriptors with
`O_NOFOLLOW` on Linux/POSIX, so swapping a folder name for a symlink cannot
redirect the operation. For `overwrite=false`, a hard-link publication prevents
replacement even if another process creates the filename after the preflight
check. Cooperative pack generators use a nonblocking POSIX advisory lock to
reject overlapping writes to the same folder. The stable `.sfx-pack.lock` file
is intentionally retained after generation; this is not a lock against hostile
processes able to alter the directory. Verification does not acquire that lock
and may report an in-progress pack as inconsistent. For `overwrite=true`, a
directory-relative atomic rename replaces only the directory entry and never
writes through an existing symlink.

Verification is limited to **1 MiB per WAV**, at most **2 seconds of PCM** per
file, and **256 KiB per manifest**. Because the integrity check re-renders from
the manifest seed with the *installed* engine, changing a preset or the renderer
deliberately invalidates previously generated packs — regenerate after upgrading
rather than re-verifying old output. Individual files are published atomically,
but a pack of multiple WAVs plus its manifest is **not an all-or-nothing
transaction**: a failed generation can leave finished WAV files without a new
manifest. The verifier detects such incomplete or mismatched packs. These
filesystem protections are designed and tested on Linux; other POSIX systems and
adversarial network filesystem behavior have not been established.

## Where it runs and what it writes

The plugin runs inside the Hermes plugin host process. There is no separate
sandbox and no privilege of its own beyond what that process has; the protections
described above are what keep it inside its workspace. Hermes gets exactly two
entry points: `sfx_generate` and `sfx_verify`.

A generation call writes, inside the resolved workspace root and nowhere else:

- one 16-bit mono WAV per requested cue,
- `manifest.json`, recording each cue's preset, seed, sample count and sha256,
- `.sfx-pack.lock`, intentionally retained after the run.

There are no network calls and no subprocess execution. The CLI accepts an
explicit `--root`, and `verify <path>` can inspect a user-selected file outside
the workspace; the registered tools accept neither.

## Hermes compatibility

`plugin.yaml` declares Hermes `>=0.23.0`, the version previously reported as
validated by the implementation author. Compatibility on earlier versions is
not asserted. Independent Hermes validation must be rerun on the final public
commit before catalog submission.

The filesystem protections are Linux/POSIX-specific (`O_NOFOLLOW`, `dir_fd`
operations, and an `fcntl` advisory lock), so v1 targets Linux and macOS.
Windows is not supported: `fcntl` is unavailable there.

## License

MIT for this code. Dependencies: NumPy and SciPy, both BSD-3-Clause. See
`THIRD_PARTY.md`. No third-party audio, no bundled binaries.
