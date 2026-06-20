"""S12 — `mentat-git worktree sweep`: list (default) / remove stray + prunable worktrees.

A *stray* is a registered worktree living outside `<repo>/.mentat/worktrees/`
(the parent-folder leftovers mentat must clear). A *prunable* entry is one whose
working dir is gone but whose admin record lingers. Sweep lists both by default
and only removes them when explicitly confirmed (`--force`). The main worktree
and live managed worktrees are never swept.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import init_git_repo, load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def _load_worktree():
    return load_script(_SCRIPTS / "worktree.py", "wt_sweep_mod")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    init_git_repo(r)
    monkeypatch.chdir(r)
    return r


def _porcelain(repo: Path) -> str:
    return subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def messy_repo(repo, tmp_path):
    """Repo with a parent-folder stray, a prunable nested worktree, and a live nested one."""
    wt = _load_worktree()
    # Parent-folder stray: lives in tmp_path (sibling of repo), outside .mentat/worktrees/.
    wt.cmd_worktree_create("stray-one", parent=tmp_path / "strays")
    stray = (tmp_path / "strays" / "stray-one").resolve()
    # Prunable nested worktree: created under .mentat/worktrees/, then its dir deleted.
    wt.cmd_worktree_create("ghost")
    ghost = (repo / ".mentat" / "worktrees" / "ghost").resolve()
    shutil.rmtree(ghost)
    # Live nested worktree: stays — never swept.
    wt.cmd_worktree_create("live")
    live = (repo / ".mentat" / "worktrees" / "live").resolve()
    return {"wt": wt, "stray": stray, "ghost": ghost, "live": live}


# ── sweep_targets: the set selection ───────────────────────────────────────────


def test_sweep_targets_selects_stray_and_prunable_only(repo, messy_repo):
    wt = messy_repo["wt"]
    targets = {p.resolve() for p in wt.sweep_targets(repo)}
    assert targets == {messy_repo["stray"], messy_repo["ghost"]}
    # main worktree and the live managed worktree are never targets
    assert repo.resolve() not in targets
    assert messy_repo["live"] not in targets


def test_sweep_targets_empty_when_clean(repo):
    wt = _load_worktree()
    assert wt.sweep_targets(repo) == []


# ── dry-run (default): lists, never removes ────────────────────────────────────


def test_sweep_dry_run_lists_targets_without_removing(repo, messy_repo, capsys):
    wt = messy_repo["wt"]
    rc = wt.cmd_worktree_sweep(dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert str(messy_repo["stray"]) in out
    assert str(messy_repo["ghost"]) in out
    assert str(messy_repo["live"]) not in out
    # Nothing removed: stray dir still on disk, ghost still registered (prunable).
    assert messy_repo["stray"].is_dir()
    assert str(messy_repo["ghost"]) in _porcelain(repo)


def test_sweep_default_is_dry_run(repo, messy_repo):
    wt = messy_repo["wt"]
    wt.cmd_worktree_sweep()  # no args → dry-run, must not remove
    assert messy_repo["stray"].is_dir()


# ── confirmed run: removes, leaves a clean list ────────────────────────────────


def test_sweep_force_removes_and_leaves_clean(repo, messy_repo):
    wt = messy_repo["wt"]
    rc = wt.cmd_worktree_sweep(dry_run=False)
    assert rc == 0
    porcelain = _porcelain(repo)
    assert str(messy_repo["stray"]) not in porcelain
    assert str(messy_repo["ghost"]) not in porcelain
    # main + live survive
    assert str(repo.resolve()) in porcelain
    assert str(messy_repo["live"]) in porcelain
    assert not messy_repo["stray"].exists()


# ── dirty-preserve: never force-remove un-landed work ──────────────────────────


def test_sweep_force_preserves_dirty_stray(repo, tmp_path):
    """A stray holding uncommitted work is preserved, not force-removed; a clean
    stray beside it is still swept. Mirrors the codebase's locked dirty-preserve
    contract (lib.worktrees.is_dirty / teardown)."""
    wt = _load_worktree()
    wt.cmd_worktree_create("dirty-stray", parent=tmp_path / "strays")
    dirty = (tmp_path / "strays" / "dirty-stray").resolve()
    (dirty / "uncommitted.txt").write_text("un-landed work\n")
    wt.cmd_worktree_create("clean-stray", parent=tmp_path / "strays")
    clean = (tmp_path / "strays" / "clean-stray").resolve()

    rc = wt.cmd_worktree_sweep(dry_run=False)
    assert rc == 0
    assert dirty.is_dir(), "dirty stray with un-landed work must be preserved"
    assert not clean.exists(), "clean stray must be swept"
    assert str(dirty) in _porcelain(repo)


def test_sweep_dry_run_marks_dirty_stray(repo, tmp_path, capsys):
    wt = _load_worktree()
    wt.cmd_worktree_create("dirty-stray", parent=tmp_path / "strays")
    dirty = (tmp_path / "strays" / "dirty-stray").resolve()
    (dirty / "uncommitted.txt").write_text("un-landed work\n")
    wt.cmd_worktree_sweep(dry_run=True)
    out = capsys.readouterr().out
    assert str(dirty) in out
    assert "dirty" in out.lower() or "uncommitted" in out.lower() or "preserve" in out.lower()


# ── edges ──────────────────────────────────────────────────────────────────────


def test_sweep_no_targets_returns_zero(repo, capsys):
    wt = _load_worktree()
    rc = wt.cmd_worktree_sweep(dry_run=True)
    assert rc == 0
    assert "no stray" in capsys.readouterr().out.lower()


def test_sweep_not_in_git_repo(tmp_path, monkeypatch):
    wt = _load_worktree()
    monkeypatch.chdir(tmp_path)
    rc = wt.cmd_worktree_sweep(dry_run=True)
    assert rc == 70


# ── CLI wiring ─────────────────────────────────────────────────────────────────


def test_sweep_cli_dry_run_default(repo, messy_repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "sweep"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    assert str(messy_repo["stray"]) in result.stdout
    # default dry-run: stray not removed
    assert messy_repo["stray"].is_dir()


def test_sweep_cli_force_removes(repo, messy_repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "sweep", "--force"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    assert not messy_repo["stray"].exists()
    assert str(messy_repo["ghost"]) not in _porcelain(repo)


def test_sweep_cli_help(repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "sweep", "--help"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    assert "force" in result.stdout.lower()
