"""S3 — shared worktree lifecycle lib: identity-by-path prune + teardown.

A mentat worktree is one living under ``<repo>/.mentat/worktrees/`` — identity
is PATH, never a session-id name prefix. The S1 rename obsoletes every
``startswith("mentat-"/"auto-"/"mentat-manual-")`` heuristic; preserve-vs-remove
is dirty-vs-clean (git status), not a name guess.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time as _time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import worktrees  # noqa: E402


def _cp(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    r: subprocess.CompletedProcess = subprocess.CompletedProcess.__new__(subprocess.CompletedProcess)
    r.returncode, r.stdout, r.stderr, r.args = returncode, stdout, "", []
    return r


def _make_wt(wt_root: Path, name: str, *, age_secs: int = 7200) -> Path:
    wt = wt_root / name
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: /fake/.git/worktrees/{name}\n")
    mtime = _time.time() - age_secs
    os.utime(wt, (mtime, mtime))
    return wt


def _clean_git(monkeypatch) -> None:
    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp(0, "")
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp(0)
        return _cp(0)

    monkeypatch.setattr(subprocess, "run", fake_run)


# ── identity is path, not name ───────────────────────────────────────────────


def test_is_managed_by_path(tmp_path) -> None:
    repo = tmp_path
    inside = worktrees.worktrees_root(repo) / "anything"
    inside.mkdir(parents=True)
    assert worktrees.is_managed(inside, repo)
    outside = tmp_path / "sibling-strays"
    outside.mkdir()
    assert not worktrees.is_managed(outside, repo)


def test_prune_is_path_based_not_name_based(tmp_path, monkeypatch) -> None:
    """A clean stale worktree is pruned regardless of its name — including one
    a legacy name-exemption (mentat-manual-*) would have spared."""
    wt_root = tmp_path / ".mentat" / "worktrees"
    formerly_exempt = _make_wt(wt_root, "mentat-manual-my-task", age_secs=7200)
    new_style = _make_wt(wt_root, "implement-some-plan-4242", age_secs=7200)
    _clean_git(monkeypatch)

    removed = worktrees.prune_stale(wt_root, active_slugs=set())

    assert not formerly_exempt.exists(), "name-exemption is gone — clean stale pruned by path"
    assert not new_style.exists()
    assert removed == 2


def test_prune_preserves_dirty(tmp_path, monkeypatch) -> None:
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "implement-p-1", age_secs=7200)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0, "?? x\n") if "status" in cmd else _cp(0))
    assert worktrees.prune_stale(wt_root, active_slugs=set()) == 0
    assert wt.exists()


def test_prune_preserves_recent(tmp_path, monkeypatch) -> None:
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "implement-p-2", age_secs=300)
    _clean_git(monkeypatch)
    assert worktrees.prune_stale(wt_root, active_slugs=set()) == 0
    assert wt.exists()


def test_prune_preserves_active(tmp_path, monkeypatch) -> None:
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "implement-p-3", age_secs=7200)
    _clean_git(monkeypatch)
    assert worktrees.prune_stale(wt_root, active_slugs={"implement-p-3"}) == 0
    assert wt.exists()


def test_prune_missing_root(tmp_path) -> None:
    assert worktrees.prune_stale(tmp_path / "nope", active_slugs=set()) == 0


def test_prune_rmtree_fallback(tmp_path, monkeypatch) -> None:
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "implement-p-4", age_secs=7200)

    def fake_run(cmd, **kw):
        if "status" in cmd:
            return _cp(0, "")
        if "worktree" in cmd and "remove" in cmd:
            return _cp(1)  # git remove fails → rmtree fallback
        return _cp(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert worktrees.prune_stale(wt_root, active_slugs=set()) == 1
    assert not wt.exists()


# ── single-worktree teardown (implement's own-failure path) ──────────────────


def test_teardown_removes_clean(tmp_path, monkeypatch) -> None:
    wt = _make_wt(tmp_path / ".mentat" / "worktrees", "implement-p-5", age_secs=10)
    _clean_git(monkeypatch)
    assert worktrees.teardown(wt) is True
    assert not wt.exists()


def test_teardown_preserves_dirty(tmp_path, monkeypatch) -> None:
    wt = _make_wt(tmp_path / ".mentat" / "worktrees", "implement-p-6", age_secs=10)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0, "?? x\n") if "status" in cmd else _cp(0))
    assert worktrees.teardown(wt) is False
    assert wt.exists()


def test_is_dirty(tmp_path, monkeypatch) -> None:
    wt = _make_wt(tmp_path / ".mentat" / "worktrees", "implement-p-7", age_secs=10)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0, " M f\n"))
    assert worktrees.is_dirty(wt) is True
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(0, ""))
    assert worktrees.is_dirty(wt) is False


def test_is_dirty_fails_safe_on_git_error(tmp_path, monkeypatch) -> None:
    """A git error must not green-light removal — treat as dirty (preserve)."""
    wt = _make_wt(tmp_path / ".mentat" / "worktrees", "implement-p-8", age_secs=10)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(128, ""))
    assert worktrees.is_dirty(wt) is True


def test_prune_preserves_on_git_error(tmp_path, monkeypatch) -> None:
    """A stale worktree whose git status errors is preserved, not pruned."""
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "implement-p-9", age_secs=7200)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _cp(128, "fatal: bad index"))
    assert worktrees.prune_stale(wt_root, active_slugs=set()) == 0
    assert wt.exists()
