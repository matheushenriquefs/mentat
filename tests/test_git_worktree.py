"""FOLLOW-UP #23 — mentat-git worktree create subcommand."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import init_git_repo, load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"

_CID = "a" * 32


@pytest.fixture(autouse=True)
def _fixed_chunk_id(monkeypatch):
    import lib.chunk as chunk_mod

    monkeypatch.setattr(chunk_mod, "make_chunk_id", lambda: _CID)


def _load_worktree():
    return load_script(_SCRIPTS / "worktree.py", "wt_mod")


def _ok(stdout: str = "", returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    init_git_repo(r)
    monkeypatch.chdir(r)
    return r


def test_creates_sibling_worktree(repo, capsys):
    wt = _load_worktree()
    rc = wt.cmd_worktree_create("feat-x", chunk_id=_CID)
    assert rc == 0
    target = repo / ".mentat" / "worktrees" / _CID / "feat-x"
    assert target.is_dir()
    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert f"mentat/{_CID}/feat-x" in branches
    out = capsys.readouterr().out.strip()
    assert out.endswith("feat-x")
    assert Path(out).resolve() == target.resolve()


def test_idempotent_prints_same_path(repo, capsys):
    wt = _load_worktree()
    wt.cmd_worktree_create("feat-x", chunk_id=_CID)
    first = capsys.readouterr().out.strip()
    wt.cmd_worktree_create("feat-x", chunk_id=_CID)
    second = capsys.readouterr().out.strip()
    assert first == second
    assert first.endswith("feat-x")


def test_idempotent_when_worktree_already_exists(repo):
    wt = _load_worktree()
    assert wt.cmd_worktree_create("feat-x", chunk_id=_CID) == 0
    assert wt.cmd_worktree_create("feat-x", chunk_id=_CID) == 0


def test_conflict_when_path_exists_unregistered(repo):
    wt = _load_worktree()
    conflict = repo / ".mentat" / "worktrees" / _CID / "feat-conflict"
    conflict.mkdir(parents=True)
    rc = wt.cmd_worktree_create("feat-conflict", chunk_id=_CID)
    assert rc == 65


def test_missing_base_branch(repo):
    wt = _load_worktree()
    rc = wt.cmd_worktree_create("feat-y", base="nonexistent-branch")
    assert rc == 66


def test_custom_parent(repo, tmp_path):
    wt = _load_worktree()
    custom = tmp_path / "wts"
    rc = wt.cmd_worktree_create("feat-z", parent=custom, chunk_id=_CID)
    assert rc == 0
    assert (custom / _CID / "feat-z").is_dir()


def test_not_in_git_repo(tmp_path, monkeypatch):
    wt = _load_worktree()
    monkeypatch.chdir(tmp_path)
    rc = wt.cmd_worktree_create("feat-q")
    assert rc == 70


def test_cli_dispatch(repo):
    result = subprocess.run(
        [
            "python3",
            str(_SCRIPTS / "git.py"),
            "worktree",
            "create",
            "feat-cli",
            "--chunk-id",
            _CID,
        ],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    target = repo / ".mentat" / "worktrees" / _CID / "feat-cli"
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
        race = (target_parent / _CID / "race-target").resolve()
        if self == race:
            return False
        return real_target_exists_check(self)

    monkeypatch.setattr(wt, "_existing_worktree", lambda *a, **kw: False)
    monkeypatch.setattr(Path, "exists", fake_exists)

    real_git = wt._git

    def racing_git(args, *, cwd=None):
        if args[:2] == ["worktree", "add"]:
            rc = target_parent / _CID / "race-target"
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
        ["git", "branch", f"mentat/{_CID}/feat-existing", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    rc = wt.cmd_worktree_create("feat-existing")

    assert rc == 0, f"must succeed when branch exists but worktree does not, got rc={rc}"
    target = repo / ".mentat" / "worktrees" / _CID / "feat-existing"
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
        if branch == f"mentat/{_CID}/feat-toctou-branch":
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


# ── worktree.py helpers: _main_repo_root / is_main_worktree / _detect_default_branch ──


def test_main_repo_root_rev_parse_fails_returns_none(tmp_path, monkeypatch):
    """_main_repo_root returns None when rev-parse fails (lines 45-49 region)."""
    wt = _load_worktree()
    monkeypatch.setattr(wt, "_git", lambda args, *, cwd=None: _ok(returncode=1))
    assert wt._main_repo_root(tmp_path) is None


def test_main_repo_root_common_dir_without_dot_git(tmp_path, monkeypatch):
    """When --git-common-dir is not named .git, it is returned as-is (line 40)."""
    wt = _load_worktree()
    common = tmp_path / "custom-common"
    monkeypatch.setattr(wt, "_git", lambda args, *, cwd=None: _ok(stdout=f"{common}\n"))
    assert wt._main_repo_root(tmp_path) == common


def test_is_main_worktree_true_when_dirs_match(tmp_path, monkeypatch):
    """is_main_worktree True when git-common-dir == git-dir (lines 45-49)."""
    wt = _load_worktree()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    monkeypatch.setattr(wt, "_git", lambda args, *, cwd=None: _ok(stdout=f"{git_dir}\n"))
    assert wt.is_main_worktree(tmp_path) is True


def test_is_main_worktree_false_on_git_failure(tmp_path, monkeypatch):
    """is_main_worktree returns False when a rev-parse call fails (line 48)."""
    wt = _load_worktree()
    monkeypatch.setattr(wt, "_git", lambda args, *, cwd=None: _ok(returncode=1))
    assert wt.is_main_worktree(tmp_path) is False


def test_detect_default_branch_from_origin_head(tmp_path, monkeypatch):
    """origin/HEAD with origin/ prefix is stripped (lines 80-84)."""
    wt = _load_worktree()

    def fake_git(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            return _ok(stdout="origin/develop\n")
        return _ok(returncode=1)

    monkeypatch.setattr(wt, "_git", fake_git)
    assert wt._detect_default_branch(tmp_path) == "develop"


def test_detect_default_branch_symbolic_ref_no_prefix(tmp_path, monkeypatch):
    """symbolic-ref returning a bare ref (no origin/ prefix) is returned as-is (line 84)."""
    wt = _load_worktree()

    def fake_git(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            return _ok(stdout="trunk\n")
        return _ok(returncode=1)

    monkeypatch.setattr(wt, "_git", fake_git)
    assert wt._detect_default_branch(tmp_path) == "trunk"


def test_detect_default_branch_symbolic_ref_empty_falls_through(tmp_path, monkeypatch):
    """symbolic-ref rc==0 but empty stdout falls through to config (83->86)."""
    wt = _load_worktree()

    def fake_git(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            if len(args) > 2 and args[2] == "refs/remotes/origin/HEAD":
                return _ok(stdout="\n")
            return _ok(returncode=1)
        if args[:2] == ["config", "--get"]:
            return _ok(stdout="cfgbranch\n")
        return _ok(returncode=1)

    monkeypatch.setattr(wt, "_git", fake_git)
    assert wt._detect_default_branch(tmp_path) == "cfgbranch"


def test_detect_default_branch_from_local_head(tmp_path, monkeypatch):
    """Local HEAD symbolic-ref is used when origin/HEAD is absent."""
    wt = _load_worktree()

    def fake_git(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            if len(args) > 2 and args[2] == "refs/remotes/origin/HEAD":
                return _ok(returncode=1)
            return _ok(stdout="trunk\n")
        return _ok(returncode=1)

    monkeypatch.setattr(wt, "_git", fake_git)
    assert wt._detect_default_branch(tmp_path) == "trunk"


def test_detect_default_branch_raises_when_unresolvable(tmp_path, monkeypatch):
    wt = _load_worktree()
    monkeypatch.setattr(wt, "_git", lambda args, *, cwd=None: _ok(returncode=1))
    with pytest.raises(wt._git_lib.GitError, match="cannot detect default branch"):
        wt._detect_default_branch(tmp_path)


def test_detect_default_branch_from_init_default(tmp_path, monkeypatch):
    """Falls back to init.defaultBranch config when origin/HEAD absent (line 88)."""
    wt = _load_worktree()

    def fake_git(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            return _ok(returncode=1)
        if args[:2] == ["config", "--get"]:
            return _ok(stdout="primary\n")
        return _ok(returncode=1)

    monkeypatch.setattr(wt, "_git", fake_git)
    assert wt._detect_default_branch(tmp_path) == "primary"


def test_create_prunes_stale_admin_record(repo, monkeypatch):
    """A prunable target triggers `git worktree prune` before idempotency check (line 193)."""
    wt = _load_worktree()
    prune_calls: list[list[str]] = []

    monkeypatch.setattr(wt, "_main_repo_root", lambda cwd: repo)
    monkeypatch.setattr(wt, "_is_prunable_target", lambda main_root, target: True)
    # After the prune, the target is not registered → falls through to create path.
    monkeypatch.setattr(wt, "_existing_worktree", lambda main_root, target: False)
    monkeypatch.setattr(wt, "_branch_exists", lambda main_root, branch: branch != "fresh-slug")

    real_git = wt._git

    def tracking_git(args, *, cwd=None):
        if args[:2] == ["worktree", "prune"]:
            prune_calls.append(list(args))
            return _ok()
        return real_git(args, cwd=cwd)

    monkeypatch.setattr(wt, "_git", tracking_git)
    monkeypatch.setattr(wt, "_detect_default_branch", lambda root: "main")

    wt.cmd_worktree_create("fresh-slug", base="main", parent=repo / ".mentat" / "worktrees")

    assert prune_calls, "git worktree prune must run for a prunable target"


def test_create_worktree_add_generic_failure_maps_software(repo, monkeypatch):
    """A non-TOCTOU `git worktree add` failure returns the rc / EX_SOFTWARE (246-247)."""
    wt = _load_worktree()

    monkeypatch.setattr(wt, "_main_repo_root", lambda cwd: repo)
    monkeypatch.setattr(wt, "_is_prunable_target", lambda main_root, target: False)
    monkeypatch.setattr(wt, "_existing_worktree", lambda main_root, target: False)
    monkeypatch.setattr(wt, "_branch_exists", lambda main_root, branch: branch == "main")
    monkeypatch.setattr(wt, "_detect_default_branch", lambda root: "main")

    def fake_git(args, *, cwd=None):
        if args[:2] == ["worktree", "add"]:
            r = _ok(returncode=128)
            r.stderr = "fatal: some unexpected git error\n"
            return r
        return _ok()

    monkeypatch.setattr(wt, "_git", fake_git)

    rc = wt.cmd_worktree_create("oops-slug", base="main", parent=repo / ".mentat" / "worktrees")
    assert rc == 128


def test_create_toctou_retry_still_fails_maps_conflict(repo, monkeypatch):
    """TOCTOU retry without -b also fails → fall through to the conflict map (233->236)."""
    wt = _load_worktree()

    monkeypatch.setattr(wt, "_main_repo_root", lambda cwd: repo)
    monkeypatch.setattr(wt, "_is_prunable_target", lambda main_root, target: False)
    monkeypatch.setattr(wt, "_existing_worktree", lambda main_root, target: False)
    monkeypatch.setattr(wt, "_branch_exists", lambda main_root, branch: branch == "main")
    monkeypatch.setattr(wt, "_detect_default_branch", lambda root: "main")

    add_calls = [0]

    def fake_git(args, *, cwd=None):
        if args[:2] == ["worktree", "add"]:
            add_calls[0] += 1
            r = _ok(returncode=128)
            # First add (-b): TOCTOU "a branch named ... already exists" → triggers retry.
            # Retry (no -b) also fails, but now with a path-conflict message.
            if add_calls[0] == 1:
                r.stderr = "fatal: a branch named 'slug' already exists\n"
            else:
                r.stderr = "fatal: 'target' already exists\n"
            return r
        return _ok()

    monkeypatch.setattr(wt, "_git", fake_git)

    rc = wt.cmd_worktree_create("conflict-slug", base="main", parent=repo / ".mentat" / "worktrees")
    assert rc == wt.EX_DATAERR  # 65 path conflict
    assert add_calls[0] == 2, "the -b add and the no-b retry must both run"
