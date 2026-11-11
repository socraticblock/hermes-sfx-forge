"""Workspace path policy with directory-relative, no-follow filesystem operations.

Folder and file names are untrusted. An opened directory descriptor, not a
resolved pathname, anchors subsequent reads and writes against symlink swaps.
The configured workspace root itself is a trusted operator setting.
"""
from __future__ import annotations

import errno
import fcntl
import os
import re
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path

SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class PathRejected(ValueError):
    """A requested name, destination or filesystem object is not allowed."""


class FileTooLarge(PathRejected):
    """An input exceeds the bounded verification size."""


def validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise PathRejected("name must be a string")
    if name != name.strip():
        raise PathRejected("name must not have surrounding whitespace")
    if "\\" in name or "/" in name or ":" in name:
        raise PathRejected("name must be a bare name, not a path")
    if name in {".", ".."} or ".." in name:
        raise PathRejected("name must not contain traversal")
    if not SAFE_NAME_RE.fullmatch(name):
        raise PathRejected("name must match ^[a-z0-9][a-z0-9_-]{0,39}$")
    return name


def workspace_root(root: str | os.PathLike | None = None) -> Path:
    if root is None:
        root = os.environ.get("SFX_FORGE_ROOT") or (Path.home() / ".hermes" / "sfx-forge")
    # The root is explicitly configured by the operator; pack folder names are not.
    p = Path(root).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve(strict=True)


def resolve_dir(root: Path, name: str) -> Path:
    """Return an un-followed child path; actual operations use open_pack()."""
    validate_name(name)
    root = Path(root).resolve(strict=True)
    target = root / name
    if target.is_symlink():
        raise PathRejected("folder is a symlink")
    if target.exists() and not target.is_dir():
        raise PathRejected("folder target is not a directory")
    return target


def resolve_file(directory: Path, stem: str, suffix: str = ".wav") -> Path:
    validate_name(stem)
    if suffix not in (".wav", ".json"):
        raise PathRejected("unsupported output file type")
    target = Path(directory) / (stem + suffix)
    if target.is_symlink():
        raise PathRejected("target is a symlink")
    if target.is_dir():
        raise PathRejected("target is a directory")
    return target


@contextmanager
def open_pack(root: Path, name: str, *, create: bool = False):
    """Open a real immediate child directory anchored to an opened root fd."""
    validate_name(name)
    root = Path(root).resolve(strict=True)
    root_fd = os.open(root, _DIR_FLAGS)
    try:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        try:
            folder_fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
        except OSError as exc:
            # ELOOP / ENOTDIR cover linked directories with O_NOFOLLOW;
            # preserve genuine I/O / permission failures as system failures.
            if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                raise PathRejected(f"folder must be a real directory: {name}") from exc
            raise
        try:
            yield root / name, folder_fd
        finally:
            os.close(folder_fd)
    finally:
        os.close(root_fd)


@contextmanager
def pack_write_lock(directory_fd: int):
    """Prevent simultaneous cooperating generators from updating the same pack.

    The lock file is retained so that all writers lock the same inode. This is
    an advisory Linux/POSIX lock, not protection against hostile filesystem
    modifications by an actor with write access to the pack directory.
    """
    name = ".sfx-pack.lock"
    try:
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                     mode=0o600, dir_fd=directory_fd)
    except OSError as exc:
        raise PathRejected("cannot open pack lock") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PathRejected("pack lock must be a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PathRejected("pack is already being generated") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def ensure_free(target: Path, overwrite: bool = False) -> None:
    """Preflight diagnostic only; atomic_write enforces the no-replace condition."""
    if target.is_symlink():
        raise PathRejected("target is a symlink")
    if target.exists() and not overwrite:
        raise PathRejected(f"refusing to overwrite existing file: {target.name}")


def _validate_leaf(target: Path) -> None:
    if target.suffix not in (".wav", ".json"):
        raise PathRejected("unsupported output file type")
    validate_name(target.stem)


def open_regular(directory_fd: int, name: str, *, max_bytes: int):
    """Open a bounded, regular file without following a leaf symlink."""
    if ("/" in name or "\\" in name
            or (name != "manifest.json"
                and not (name.endswith(".wav") and SAFE_NAME_RE.fullmatch(name[:-4])))):
        raise PathRejected("invalid file name")
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
    except OSError as exc:
        raise PathRejected(f"cannot open regular file without following links: {name}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PathRejected(f"not a regular file: {name}")
        if info.st_size > max_bytes:
            raise FileTooLarge(f"file too large: {name}")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def atomic_write(target: Path, write_fn, *, overwrite: bool = False,
                 directory_fd: int | None = None) -> Path:
    """Publish a private temp file atomically; no-replace uses hard-link creation.

    An atomic link fails with EEXIST even when another writer creates the target
    after preflight. Overwriting uses a directory-relative rename, never follows
    the existing destination symlink, and never writes through it.
    """
    target = Path(target)
    _validate_leaf(target)
    own_fd = directory_fd is None
    dfd = os.open(target.parent, _DIR_FLAGS) if own_fd else directory_fd
    tmp = ".sfx-" + secrets.token_hex(12) + ".part"
    created = False
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     mode=0o600, dir_fd=dfd)
        created = True
        with os.fdopen(fd, "wb") as out:
            write_fn(out)
            out.flush()
            os.fsync(out.fileno())
        if overwrite:
            try:
                current = os.stat(target.name, dir_fd=dfd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
                    raise PathRejected(f"refusing to replace non-regular file: {target.name}")
            os.replace(tmp, target.name, src_dir_fd=dfd, dst_dir_fd=dfd)
            created = False
        else:
            try:
                os.link(tmp, target.name, src_dir_fd=dfd, dst_dir_fd=dfd,
                        follow_symlinks=False)
            except FileExistsError as exc:
                raise PathRejected(f"refusing to overwrite existing file: {target.name}") from exc
        return target
    finally:
        if created:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except FileNotFoundError:
                pass
        if own_fd:
            os.close(dfd)
