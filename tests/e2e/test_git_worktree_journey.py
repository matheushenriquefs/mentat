"""E2E: drive ``.agents/skills/mentat-git/scripts/worktree.py`` against REAL git.

Every function in ``worktree.py`` is a thin porcelain seam over ``git`` — the
journeys here build genuine repos, linked worktrees, and branches with the
shared ``init_git_repo`` helper plus raw ``subprocess`` setup, then assert the
real behaviour and exit codes.

Two seams need forcing rather than staging:

* Directories *outside any repo* are produced with ``GIT_CEILING_DIRECTORIES``
  pinned to ``tmp_path`` so ``git rev-parse`` refuses to walk up and the
  ``returncode != 0`` branches fire deterministically.
* The ``git worktree add`` TOCTOU stderr-mapping branches are otherwise
  unreachable (the pre-checks already caught every real conflict), so those
  tests wrap the module-level ``_git`` with a shim that runs the real command
  for every call *except* ``["worktree", "add", ...]``, which returns a scripted
  ``CompletedProcess``.

``cmd_worktree_sweep`` and ``cmd_worktree_create`` read ``Path.cwd()``, so those
tests ``monkeypatch.chdir`` into the repo (or pass ``parent`` explicitly).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import init_git_repo, load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]

git_worktree = load_script(REPO_ROOT / ".agents/skills/mentat-git/scripts/worktree.py", "git_worktree")

EX_DATAERR = git_worktree.EX_DATAERR
EX_NOINPUT = git_worktree.EX_NOINPUT
EX_SOFTWARE = git_worktree.EX_SOFTWARE


# ── helpers ──────────────────────────────────────────────────────────────────


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path)


def _fake_add_result(returncode: int, stderr: str):
    """Build a shim over the real ``_git`` that only scripts ``worktree add``.

    Every pre-check call (rev-parse / worktree list / branch verify / prune)
    runs the real git; the single ``["worktree", "add", ...]`` invocation
    returns a scripted CompletedProcess so we can drive the TOCTOU branches.
    """
    real = git_worktree._git

    def shim(args, *, cwd=None):
        if args and args[0] == "worktree" and args[1] == "add":
            return subprocess.CompletedProcess(args=["git", *args], returncode=returncode, stdout="", stderr=stderr)
        return real(args, cwd=cwd)

    return shim


# ── _git ─────────────────────────────────────────────────────────────────────


def test_git_rev_parse_smoke_returns_rc_zero(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    r = git_worktree._git(["rev-parse", "HEAD"], cwd=repo)
    assert r.returncode == 0
    assert r.stdout.strip()


# ── _main_repo_root ──────────────────────────────────────────────────────────


def test_main_repo_root_inside_main_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    root = git_worktree._main_repo_root(repo)
    assert root is not None
    assert root.resolve() == repo.resolve()


def test_main_repo_root_from_linked_worktree_returns_main(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "feature-wt"
    _git("worktree", "add", str(linked), "-b", "feature", cwd=repo)

    root = git_worktree._main_repo_root(linked)
    assert root is not None
    assert root.resolve() == repo.resolve()


def test_main_repo_root_outside_any_repo_returns_none(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()

    assert git_worktree._main_repo_root(norepo) is None


# ── is_main_worktree ─────────────────────────────────────────────────────────


def test_is_main_worktree_true_in_main(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    assert git_worktree.is_main_worktree(repo) is True


def test_is_main_worktree_false_in_linked(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "feature-wt"
    _git("worktree", "add", str(linked), "-b", "feature", cwd=repo)

    assert git_worktree.is_main_worktree(linked) is False


def test_is_main_worktree_false_outside_repo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()

    assert git_worktree.is_main_worktree(norepo) is False


# ── _list_worktrees ──────────────────────────────────────────────────────────


def test_list_worktrees_includes_linked(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "feature-wt"
    _git("worktree", "add", str(linked), "-b", "feature", cwd=repo)

    entries = git_worktree._list_worktrees(repo)
    assert len(entries) >= 2
    paths = {Path(e["worktree"]).resolve() for e in entries}
    assert repo.resolve() in paths
    assert linked.resolve() in paths


# ── _existing_worktree ───────────────────────────────────────────────────────


def test_existing_worktree_true_for_registered(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "feature-wt"
    _git("worktree", "add", str(linked), "-b", "feature", cwd=repo)

    assert git_worktree._existing_worktree(repo, linked) is True


def test_existing_worktree_false_for_unregistered(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    assert git_worktree._existing_worktree(repo, tmp_path / "nope") is False


# ── _is_prunable_target ──────────────────────────────────────────────────────


def test_is_prunable_target_true_when_dir_deleted(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "gone-wt"
    _git("worktree", "add", str(linked), "-b", "doomed", cwd=repo)

    # Delete the working dir but leave the admin record → prunable.
    _rmtree(linked)

    assert git_worktree._is_prunable_target(repo, linked) is True


def test_is_prunable_target_false_for_live_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "live-wt"
    _git("worktree", "add", str(linked), "-b", "live", cwd=repo)

    assert git_worktree._is_prunable_target(repo, linked) is False


def test_is_prunable_target_false_for_unregistered(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    assert git_worktree._is_prunable_target(repo, tmp_path / "never") is False


# ── _branch_exists ───────────────────────────────────────────────────────────


def test_branch_exists_true_for_main(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    assert git_worktree._branch_exists(repo, "main") is True


def test_branch_exists_false_for_bogus(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    assert git_worktree._branch_exists(repo, "no-such-branch") is False


# ── _detect_default_branch ───────────────────────────────────────────────────


def test_detect_default_branch_from_origin_head_strips_prefix(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    def fake(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            return subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout="origin/trunk\n", stderr="")
        raise AssertionError("should not reach further git calls")

    monkeypatch.setattr(git_worktree, "_git", fake)
    assert git_worktree._detect_default_branch(repo) == "trunk"


def test_detect_default_branch_origin_head_without_prefix_verbatim(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    def fake(args, *, cwd=None):
        if args[:2] == ["symbolic-ref", "--short"]:
            return subprocess.CompletedProcess(args=["git", *args], returncode=0, stdout="develop\n", stderr="")
        raise AssertionError("should not reach further git calls")

    monkeypatch.setattr(git_worktree, "_git", fake)
    assert git_worktree._detect_default_branch(repo) == "develop"


def test_detect_default_branch_from_init_default_branch_config(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    # No origin HEAD; a real init.defaultBranch config drives detection.
    _git("config", "init.defaultBranch", "foo", cwd=repo)

    assert git_worktree._detect_default_branch(repo) == "foo"


def test_detect_default_branch_falls_back_to_main(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    # No origin HEAD, no init.defaultBranch → literal "main".
    assert git_worktree._detect_default_branch(repo) == "main"


# ── sweep_targets ────────────────────────────────────────────────────────────


def test_sweep_targets_classifies_strays_managed_prunable_main(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    # (a) stray: lives OUTSIDE <repo>/.mentat/worktrees/ → included.
    stray = tmp_path / "stray-wt"
    _git("worktree", "add", str(stray), "-b", "stray", cwd=repo)

    # (b) managed + live: under .mentat/worktrees/ → excluded.
    managed_root = repo / ".mentat" / "worktrees"
    managed_root.mkdir(parents=True)
    managed_live = managed_root / "live"
    _git("worktree", "add", str(managed_live), "-b", "managed-live", cwd=repo)

    # (c) prunable: a managed worktree whose dir is deleted → included.
    managed_gone = managed_root / "gone"
    _git("worktree", "add", str(managed_gone), "-b", "managed-gone", cwd=repo)
    _rmtree(managed_gone)

    targets = {p.resolve() for p in git_worktree.sweep_targets(repo)}

    assert stray.resolve() in targets
    assert managed_gone.resolve() in targets
    assert managed_live.resolve() not in targets
    assert repo.resolve() not in targets  # main is never a target


# ── cmd_worktree_sweep ───────────────────────────────────────────────────────


def test_cmd_worktree_sweep_not_in_repo_returns_software(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()
    monkeypatch.chdir(norepo)

    rc = git_worktree.cmd_worktree_sweep(dry_run=True)
    assert rc == EX_SOFTWARE
    assert "not inside a git repo" in capsys.readouterr().err


def test_cmd_worktree_sweep_nothing_to_do_returns_zero(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    monkeypatch.chdir(repo)

    rc = git_worktree.cmd_worktree_sweep(dry_run=True)
    assert rc == 0
    assert "no stray or prunable worktrees" in capsys.readouterr().out


def test_cmd_worktree_sweep_dry_run_lists_and_marks_dirty(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    clean_stray = tmp_path / "clean-stray"
    _git("worktree", "add", str(clean_stray), "-b", "clean", cwd=repo)

    dirty_stray = tmp_path / "dirty-stray"
    _git("worktree", "add", str(dirty_stray), "-b", "dirty", cwd=repo)
    (dirty_stray / "scratch.txt").write_text("uncommitted\n")

    monkeypatch.chdir(repo)
    rc = git_worktree.cmd_worktree_sweep(dry_run=True)

    out = capsys.readouterr().out
    assert rc == 0
    assert "Would sweep" in out
    assert str(dirty_stray.resolve()) in out
    assert "(dirty — will be preserved)" in out
    # Dry run removes nothing.
    assert clean_stray.exists()
    assert dirty_stray.exists()


def test_cmd_worktree_sweep_force_removes_clean_preserves_dirty(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    clean_stray = tmp_path / "clean-stray"
    _git("worktree", "add", str(clean_stray), "-b", "clean", cwd=repo)

    dirty_stray = tmp_path / "dirty-stray"
    _git("worktree", "add", str(dirty_stray), "-b", "dirty", cwd=repo)
    (dirty_stray / "scratch.txt").write_text("uncommitted\n")

    monkeypatch.chdir(repo)
    rc = git_worktree.cmd_worktree_sweep(dry_run=False)

    captured = capsys.readouterr()
    assert rc == 0
    assert "swept 1 worktree(s)" in captured.out
    assert "preserved" in captured.err
    assert str(dirty_stray.resolve()) in captured.err
    # Clean one gone, dirty one kept.
    assert not clean_stray.exists()
    assert dirty_stray.exists()


# ── cmd_worktree_create ──────────────────────────────────────────────────────


def test_cmd_worktree_create_not_in_repo_returns_software(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()
    monkeypatch.chdir(norepo)

    rc = git_worktree.cmd_worktree_create("slug")
    assert rc == EX_SOFTWARE
    assert "not inside a git repo" in capsys.readouterr().err


def test_cmd_worktree_create_fresh_create(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)

    out = capsys.readouterr().out
    target = parent / "mine"
    assert rc == 0
    assert str(target.resolve()) in out
    assert target.is_dir()
    assert git_worktree._branch_exists(repo, "mine") is True


def test_cmd_worktree_create_idempotent(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    assert git_worktree.cmd_worktree_create("mine", parent=parent) == 0
    capsys.readouterr()  # drain

    # Second call on the existing worktree → no-op, still 0.
    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    out = capsys.readouterr().out
    assert rc == 0
    assert str((parent / "mine").resolve()) in out


def test_cmd_worktree_create_prunes_stale_then_recreates(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    target = parent / "mine"
    assert git_worktree.cmd_worktree_create("mine", parent=parent) == 0
    capsys.readouterr()

    # Delete the dir → stale prunable admin record lingers.
    _rmtree(target)
    assert git_worktree._is_prunable_target(repo, target) is True

    # Branch "mine" still exists, so recreate attaches without -b after pruning.
    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    assert rc == 0
    assert target.is_dir()


def test_cmd_worktree_create_path_exists_not_worktree_returns_dataerr(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    target = parent / "mine"
    target.mkdir(parents=True)
    (target / "junk.txt").write_text("not a worktree\n")
    monkeypatch.chdir(repo)

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    assert rc == EX_DATAERR
    assert "exists but is not a registered worktree" in capsys.readouterr().err


def test_cmd_worktree_create_missing_base_returns_noinput(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    rc = git_worktree.cmd_worktree_create("mine", base="nonexistent-branch", parent=parent)
    assert rc == EX_NOINPUT
    assert "does not exist" in capsys.readouterr().err


def test_cmd_worktree_create_attaches_existing_branch_without_b(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    # Branch exists but has no worktree → attach without -b.
    _git("branch", "mine", cwd=repo)
    monkeypatch.chdir(repo)

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    out = capsys.readouterr().out
    target = parent / "mine"
    assert rc == 0
    assert str(target.resolve()) in out
    assert target.is_dir()


# ── cmd_worktree_create: TOCTOU stderr mapping (scripted worktree add) ────────


def test_cmd_worktree_create_toctou_branch_exists_retries_without_b(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    # Branch already exists (the TOCTOU race): the real retry `worktree add
    # <target> mine` needs it to succeed.
    subprocess.run(["git", "branch", "mine"], cwd=repo, check=True, capture_output=True)

    # First `worktree add` fails with the branch-race stderr; the code retries
    # without -b. Script the FIRST add to fail, then fall through to the real
    # `_git` so the retry actually creates the worktree.
    real = git_worktree._git
    calls = {"add": 0}

    def shim(args, *, cwd=None):
        if args and args[0] == "worktree" and args[1] == "add":
            calls["add"] += 1
            if calls["add"] == 1:
                return subprocess.CompletedProcess(
                    args=["git", *args],
                    returncode=128,
                    stdout="",
                    stderr="fatal: a branch named 'mine' already exists",
                )
        return real(args, cwd=cwd)

    monkeypatch.setattr(git_worktree, "_git", shim)

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    out = capsys.readouterr().out
    target = parent / "mine"
    assert rc == 0
    assert calls["add"] == 2  # -b attempt + retry
    assert str(target.resolve()) in out
    assert target.is_dir()


def test_cmd_worktree_create_toctou_already_exists_returns_dataerr(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    monkeypatch.setattr(
        git_worktree,
        "_git",
        _fake_add_result(128, "fatal: '...' already exists"),
    )

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    assert rc == EX_DATAERR
    assert "exists but is not a registered worktree" in capsys.readouterr().err


def test_cmd_worktree_create_toctou_not_empty_directory_returns_dataerr(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    monkeypatch.setattr(
        git_worktree,
        "_git",
        _fake_add_result(128, "fatal: 'target' is not an empty directory"),
    )

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    assert rc == EX_DATAERR


def test_cmd_worktree_create_toctou_invalid_reference_returns_noinput(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    monkeypatch.setattr(
        git_worktree,
        "_git",
        _fake_add_result(128, "fatal: invalid reference: base"),
    )

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    assert rc == EX_NOINPUT
    assert "does not exist" in capsys.readouterr().err


def test_cmd_worktree_create_toctou_unknown_revision_returns_noinput(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    monkeypatch.setattr(
        git_worktree,
        "_git",
        _fake_add_result(128, "fatal: unknown revision or path not in the working tree"),
    )

    assert git_worktree.cmd_worktree_create("mine", parent=parent) == EX_NOINPUT


def test_cmd_worktree_create_toctou_not_valid_object_returns_noinput(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    monkeypatch.setattr(
        git_worktree,
        "_git",
        _fake_add_result(128, "fatal: not a valid object name: base"),
    )

    assert git_worktree.cmd_worktree_create("mine", parent=parent) == EX_NOINPUT


def test_cmd_worktree_create_toctou_opaque_stderr_returns_returncode(tmp_path: Path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    parent = tmp_path / "parent"
    monkeypatch.chdir(repo)

    monkeypatch.setattr(
        git_worktree,
        "_git",
        _fake_add_result(99, "fatal: something totally unexpected happened"),
    )

    rc = git_worktree.cmd_worktree_create("mine", parent=parent)
    # `return r.returncode or EX_SOFTWARE`: the failure block is entered only
    # when returncode != 0, so returncode is always truthy here and 99 is
    # propagated. The `or EX_SOFTWARE` tail is dead code (see final report).
    assert rc == 99
    assert "worktree add failed" in capsys.readouterr().err
