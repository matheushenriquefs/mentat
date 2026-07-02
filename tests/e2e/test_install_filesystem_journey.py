"""E2E: the install filesystem helpers over a REAL tmp filesystem.

Drives ``.agents/skills/mentat-install/scripts/filesystem.py`` end to end: real
symlinks, real ``shutil.copytree`` trees, real ``mkdir(parents=True)``, and a
real default-config write — no mocking of the module under test. Loaded via
``load_script`` since it is a free-standing skill script.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
FILESYSTEM_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/filesystem.py"


@pytest.fixture
def fs():
    return load_script(FILESYSTEM_PY, "install_fs")


# ── safe_symlink ─────────────────────────────────────────────────────────────


def test_safe_symlink_dry_run_is_noop(fs, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("payload\n")
    target = tmp_path / "sub" / "link"
    fs.safe_symlink(source, target, dry_run=True)
    assert not target.exists()
    assert not target.parent.exists()


def test_safe_symlink_creates_link_to_source(fs, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("payload\n")
    target = tmp_path / "newparent" / "link"
    fs.safe_symlink(source, target)
    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_safe_symlink_clears_broken_parent_symlink(fs, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("payload\n")
    # target.parent is itself a symlink pointing at a missing dir → is_symlink()
    # True while exists() False. safe_symlink must unlink it then proceed.
    missing = tmp_path / "gone"
    broken_parent = tmp_path / "broken_parent"
    broken_parent.symlink_to(missing)
    target = broken_parent / "link"
    fs.safe_symlink(source, target)
    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_safe_symlink_replaces_existing_symlink(fs, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("payload\n")
    other = tmp_path / "other.txt"
    other.write_text("stale\n")
    target = tmp_path / "link"
    target.symlink_to(other)
    fs.safe_symlink(source, target)
    assert target.resolve() == source.resolve()


def test_safe_symlink_raises_on_real_file_at_target(fs, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("payload\n")
    target = tmp_path / "real.txt"
    target.write_text("do not clobber\n")
    with pytest.raises(fs.InstallConflict):
        fs.safe_symlink(source, target)


# ── safe_copy ────────────────────────────────────────────────────────────────


def test_safe_copy_dry_run_is_noop(fs, tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "file.txt").write_text("x\n")
    target = tmp_path / "dst"
    fs.safe_copy(source, target, dry_run=True)
    assert not target.exists()


def test_safe_copy_copies_tree(fs, tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "file.txt").write_text("payload\n")
    target = tmp_path / "nested" / "dst"
    fs.safe_copy(source, target)
    assert (target / "file.txt").read_text() == "payload\n"


def test_safe_copy_raises_on_missing_source(fs, tmp_path: Path):
    missing = tmp_path / "no-such-src"
    target = tmp_path / "dst"
    with pytest.raises(FileNotFoundError):
        fs.safe_copy(missing, target)


def test_safe_copy_is_idempotent_via_dirs_exist_ok(fs, tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "file.txt").write_text("payload\n")
    target = tmp_path / "dst"
    fs.safe_copy(source, target)
    fs.safe_copy(source, target)  # second call must not raise
    assert (target / "file.txt").read_text() == "payload\n"


# ── safe_mkdir ───────────────────────────────────────────────────────────────


def test_safe_mkdir_dry_run_is_noop(fs, tmp_path: Path):
    path = tmp_path / "a" / "b" / "c"
    fs.safe_mkdir(path, dry_run=True)
    assert not path.exists()


def test_safe_mkdir_creates_dir_with_parents(fs, tmp_path: Path):
    path = tmp_path / "a" / "b" / "c"
    fs.safe_mkdir(path)
    assert path.is_dir()


# ── write_default_config ─────────────────────────────────────────────────────


def test_write_default_config_dry_run_is_noop(fs, tmp_path: Path):
    path = tmp_path / "cfg" / "config.toml"
    fs.write_default_config(path, dry_run=True)
    assert not path.exists()


def test_write_default_config_writes_template(fs, tmp_path: Path):
    path = tmp_path / "cfg" / "config.toml"
    fs.write_default_config(path)
    assert "harness" in path.read_text()


def test_write_default_config_never_overwrites_existing(fs, tmp_path: Path):
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('harness = "cursor"  # pre-existing\n')
    fs.write_default_config(path)  # must NOT overwrite
    assert path.read_text() == 'harness = "cursor"  # pre-existing\n'
