"""Output-path policy: the security boundary shared by the CLI and the tools.

Rules: the caller supplies a *name*, never a path. Names are a small character
class, resolved against a workspace root, refused if they escape it, refused if a
symlink sits at the target, refused on collision, and published atomically so a
half-written WAV never appears at the final name.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class PathRejected(ValueError):
    """Raised when a requested output name is not acceptable."""


def validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise PathRejected("name must be a string")
    if name != name.strip():
        raise PathRejected("name must not have surrounding whitespace")
    if "\\" in name or "/" in name or ":" in name:
        raise PathRejected("name must be a bare name, not a path")
    if name in {".", ".."} or ".." in name:
        raise PathRejected("name must not contain traversal")
    if not SAFE_NAME_RE.match(name):
        raise PathRejected("name must match ^[a-z0-9][a-z0-9_-]{0,39}$")
    return name


def workspace_root(root: str | os.PathLike | None = None) -> Path:
    if root is None:
        root = os.environ.get("SFX_FORGE_ROOT") or (Path.home() / ".hermes" / "sfx-forge")
    p = Path(root).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def resolve_dir(root: Path, name: str) -> Path:
    """Resolve a folder name inside the root; existing folders are allowed."""
    validate_name(name)
    root = Path(root).resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise PathRejected("name resolves outside the workspace root")
    if target.is_symlink():
        raise PathRejected("target is a symlink")
    return target


def resolve_file(directory: Path, stem: str, suffix: str = ".wav") -> Path:
    """Resolve a file name inside a folder; the stem is validated, never a path."""
    validate_name(stem)
    directory = Path(directory).resolve()
    target = (directory / f"{stem}{suffix}").resolve()
    if target.parent != directory:
        raise PathRejected("name resolves outside the folder")
    if target.exists() and target.is_symlink():
        raise PathRejected("target is a symlink")
    if target.is_dir():
        raise PathRejected("target is a directory")
    return target


def ensure_free(target: Path, overwrite: bool = False) -> None:
    if target.exists() and not overwrite:
        raise PathRejected(f"refusing to overwrite existing file: {target.name}")


def atomic_write(target: Path, write_fn) -> Path:
    """Write via a private temp file in the same directory, then rename."""
    fd, tmp = tempfile.mkstemp(prefix=".sfx-", suffix=".part", dir=str(target.parent))
    os.close(fd)
    try:
        write_fn(Path(tmp))
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target
