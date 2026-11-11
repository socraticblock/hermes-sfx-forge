import os

import pytest

from sfx_forge.core import generate_pack
from sfx_forge.paths import PathRejected, atomic_write, resolve_dir, resolve_file, validate_name, workspace_root

BAD = ["../x", "/etc/passwd", "C:\\x", "a/b", "..", ".", "A B", "-lead", "x" * 41,
       ".hidden", "name.wav", "", " name"]


@pytest.mark.parametrize("name", BAD)
def test_bad_names_rejected(name):
    with pytest.raises(PathRejected):
        validate_name(name)


@pytest.mark.parametrize("name", ["hit", "pack_1", "a-b-c", "0x"])
def test_good_names_accepted(name):
    assert validate_name(name) == name


def test_traversal_resolves_outside_root(tmp_path):
    root = workspace_root(tmp_path)
    with pytest.raises(PathRejected):
        resolve_dir(root, "..")


def test_symlink_target_rejected(tmp_path):
    root = workspace_root(tmp_path / "root")
    target = root / "link"
    os.symlink(tmp_path / "elsewhere", target)
    with pytest.raises(PathRejected):
        resolve_dir(root, "link")


def test_collision_refused_without_overwrite(tmp_path):
    generate_pack(presets=["hit"], seed=0, folder="p", root=tmp_path)
    with pytest.raises(PathRejected):
        generate_pack(presets=["hit"], seed=0, folder="p", root=tmp_path)


def test_overwrite_allowed(tmp_path):
    generate_pack(presets=["hit"], seed=0, folder="p", root=tmp_path)
    m = generate_pack(presets=["hit"], seed=0, folder="p", root=tmp_path, overwrite=True)
    assert m["passed"]


def test_folder_name_is_validated(tmp_path):
    with pytest.raises(PathRejected):
        generate_pack(presets=["hit"], seed=0, folder="../escape", root=tmp_path)


def test_atomic_write_leaves_no_partial_file(tmp_path):
    target = tmp_path / "x.wav"

    def boom(_tmp):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        atomic_write(target, boom)
    assert not target.exists()
    assert [p.name for p in tmp_path.iterdir()] == []
