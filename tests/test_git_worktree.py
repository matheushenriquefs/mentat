"""FOLLOW-UP #23 — mentat-git worktree create subcommand."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import init_git_repo, load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def _load_worktree():
    return load_script(_SCRIPTS / "worktree.py", "wt_mod")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    init_git_repo(r)
    monkeypatch.chdir(r)
    return r


def test_creates_sibling_worktree(repo, capsys):
    wt = _load_worktree()
    rc = wt.cmd_worktree_create("feat-x")
    assert rc == 0
    target = repo / ".mentat" / "worktrees" / "feat-x"
    assert target.is_dir()
    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert "feat-x" in branches
    # cmd_worktree_create prints the target path on success — preflight reads this.
    out = capsys.readouterr().out.strip()
    assert out.endswith("feat-x")
    assert Path(out).resolve() == target.resolve()


def test_idempotent_prints_same_path(repo, capsys):
    wt = _load_worktree()
    wt.cmd_worktree_create("feat-x")
    first = capsys.readouterr().out.strip()
    wt.cmd_worktree_create("feat-x")
    second = capsys.readouterr().out.strip()
    assert first == second
    assert first.endswith("feat-x")


def test_idempotent_when_worktree_already_exists(repo):
    wt = _load_worktree()
    assert wt.cmd_worktree_create("feat-x") == 0
    assert wt.cmd_worktree_create("feat-x") == 0


def test_conflict_when_path_exists_unregistered(repo):
    wt = _load_worktree()
    conflict = repo / ".mentat" / "worktrees" / "feat-conflict"
    conflict.mkdir(parents=True)
    rc = wt.cmd_worktree_create("feat-conflict")
    assert rc == 65


def test_missing_base_branch(repo):
    wt = _load_worktree()
    rc = wt.cmd_worktree_create("feat-y", base="nonexistent-branch")
    assert rc == 66


def test_custom_parent(repo, tmp_path):
    wt = _load_worktree()
    custom = tmp_path / "wts"
    rc = wt.cmd_worktree_create("feat-z", parent=custom)
    assert rc == 0
    assert (custom / "feat-z").is_dir()


def test_not_in_git_repo(tmp_path, monkeypatch):
    wt = _load_worktree()
    monkeypatch.chdir(tmp_path)
    rc = wt.cmd_worktree_create("feat-q")
    assert rc == 70


def test_cli_dispatch(repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "create", "feat-cli"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    target = repo / ".mentat" / "worktrees" / "feat-cli"
    assert target.is_dir()
    out_path = Path(result.stdout.strip().splitlines()[-1])
    assert out_path.resolve() == target.resolve()


def test_cli_worktree_help(repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "create", "--help"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    assert "slug" in result.stdout.lower()


# ── TOCTOU race window: stderr mapping kicks in if pre-check is bypassed ───


def test_race_window_path_conflict_maps_to_65(repo, monkeypatch):
    """If another process creates the target between our pre-check and `git worktree add`,
    we should still return 65 (not 70) by reading git's stderr."""
    wt = _load_worktree()
    target_parent = repo / ".mentat" / "worktrees"

    real_existing = wt._existing_worktree
    real_target_exists_check = Path.exists

    # Make pre-checks lie: pretend target does NOT exist, then create it
    # right before `git worktree add` runs (simulating a racing process).
    def fake_exists(self):
        if self == (target_parent / "race-target").resolve():
            return False
        return real_target_exists_check(self)

    monkeypatch.setattr(wt, "_existing_worktree", lambda *a, **kw: False)
    monkeypatch.setattr(Path, "exists", fake_exists)

    real_git = wt._git

    def racing_git(args, *, cwd=None):
        if args[:2] == ["worktree", "add"]:
            # Race: path appears with a sentinel file (git refuses non-empty dirs)
            rc = target_parent / "race-target"
            rc.mkdir(parents=True, exist_ok=True)
            (rc / "stranger.txt").write_text("racer wrote this\n")
        return real_git(args, cwd=cwd)

    monkeypatch.setattr(wt, "_git", racing_git)
    rc = wt.cmd_worktree_create("race-target")
    # Without stderr mapping this would be `r.returncode or 70`; with mapping it's 65.
    assert rc == 65, f"expected 65 (path conflict via stderr map), got {rc}"

    monkeypatch.setattr(wt, "_existing_worktree", real_existing)


def test_race_window_missing_base_maps_to_66(repo, monkeypatch):
    """If base branch disappears between pre-check and `git worktree add`, map to 66."""
    wt = _load_worktree()

    # Bypass the _branch_exists pre-check so the call reaches `git worktree add`
    # with a bogus base; git will refuse and we map its stderr.
    monkeypatch.setattr(wt, "_branch_exists", lambda *a, **kw: True)
    rc = wt.cmd_worktree_create("feat-race-base", base="absolutely-not-a-branch")
    assert rc == 66, f"expected 66 (missing base via stderr map), got {rc}"


# ── BUG3: branch exists but worktree does not ──────────────────────────────


def test_create_worktree_when_branch_already_exists(repo, capsys):
    """cmd_worktree_create must succeed when the branch exists but has no worktree.

    RED: fails before fix because `git worktree add -b <slug>` is called even when
    the branch already exists, and git refuses "A branch named '<slug>' already exists".
    GREEN: passes after fix detects existing branch and uses `git worktree add <path> <branch>`
    (no -b).
    """
    wt = _load_worktree()

    # Create the branch manually (simulates a prior killed/failed implement run)
    subprocess.run(
        ["git", "branch", "feat-existing", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    rc = wt.cmd_worktree_create("feat-existing")

    assert rc == 0, f"must succeed when branch exists but worktree does not, got rc={rc}"
    target = repo / ".mentat" / "worktrees" / "feat-existing"
    assert target.is_dir(), "worktree directory must be created"
    out = capsys.readouterr().out.strip()
    assert out.endswith("feat-existing"), f"must print target path, got: {out!r}"


def test_create_worktree_existing_branch_is_idempotent(repo):
    """Second call with branch+worktree already present must return 0 (existing idempotent path)."""
    wt = _load_worktree()

    # First call creates branch + worktree
    assert wt.cmd_worktree_create("feat-idem") == 0
    # Second call: branch exists AND worktree exists — idempotent
    assert wt.cmd_worktree_create("feat-idem") == 0


def test_create_worktree_branch_exists_toctou(repo, monkeypatch):
    """TOCTOU: branch appears between pre-check and `git worktree add -b` — must not crash."""
    wt = _load_worktree()

    real_branch_exists = wt._branch_exists

    # Return False only for the slug check (to force the -b path), not for the base check.
    def fake_branch_exists(main_root, branch):
        if branch == "feat-toctou-branch":
            return False
        return real_branch_exists(main_root, branch)

    original_git = wt._git

    def patched_git(args, *, cwd=None):
        if args[:3] == ["worktree", "add", "-b"]:
            # Create the branch mid-flight so git complains "branch already exists"
            subprocess.run(
                ["git", "branch", args[3], "main"],
                cwd=repo,
                capture_output=True,
            )
        return original_git(args, cwd=cwd)

    monkeypatch.setattr(wt, "_branch_exists", fake_branch_exists)
    monkeypatch.setattr(wt, "_git", patched_git)

    rc = wt.cmd_worktree_create("feat-toctou-branch")
    assert rc == 0, f"TOCTOU branch-exists must be handled gracefully, got rc={rc}"
