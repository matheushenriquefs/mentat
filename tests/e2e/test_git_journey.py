"""E2E: drive ``lib.git`` end to end against REAL git repositories on tmp_path.

Every helper in ``.agents/lib/git.py`` is a thin porcelain seam over ``git``
(ADR-0002). These journeys build genuine repos, worktrees, and branches with the
shared ``init_git_repo`` helper plus raw ``subprocess`` setup calls, then assert
the parsed return shapes. No monkeypatching of ``subprocess`` — the whole point
is real journeys. The only env fiddling is ``GIT_CEILING_DIRECTORIES`` to force
a directory to be *outside* any repo, so the ``returncode != 0`` error branches
(which are otherwise unreachable because the pytest tmp tree may sit inside a
repo) are deterministically hit.

Imports go through the package (``from lib import git``): the repo's root
``conftest.py`` puts ``.agents`` on ``sys.path``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from lib import git

from tests.conftest import init_git_repo

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


# ── helpers ──────────────────────────────────────────────────────────────────


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(cwd: Path, name: str, content: str, msg: str) -> str:
    (cwd / name).write_text(content)
    _git("add", name, cwd=cwd)
    _git("commit", "-m", msg, cwd=cwd)
    return _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


def _head(cwd: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


# ── repo_root ────────────────────────────────────────────────────────────────


def test_repo_root_inside_repo_returns_toplevel(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    root = git.repo_root(repo)
    assert root is not None
    # macOS /var vs /private/var: compare resolved paths and the leaf name.
    assert root.resolve() == repo.resolve()
    assert root.name == repo.name


def test_repo_root_outside_any_repo_returns_none(tmp_path: Path, monkeypatch):
    # tmp_path may itself sit under a repo, so pin the ceiling to tmp_path: git
    # refuses to walk above it and rev-parse exits non-zero → returncode branch.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()

    assert git.repo_root(norepo) is None


# ── worktree_list ────────────────────────────────────────────────────────────


def test_worktree_list_parses_main_and_linked_worktree(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "feature-wt"
    _git("worktree", "add", str(linked), "-b", "feature", cwd=repo)

    entries = git.worktree_list(cwd=repo)

    # entries[0] is main per git docs; a linked feature worktree follows.
    assert len(entries) >= 2
    for e in entries:
        assert "worktree" in e
        assert "HEAD" in e
        assert SHA_RE.match(e["HEAD"])
    branches = {e.get("branch") for e in entries}
    assert "main" in branches
    assert "feature" in branches
    feat = next(e for e in entries if e.get("branch") == "feature")
    assert Path(feat["worktree"]).resolve() == linked.resolve()


def test_worktree_list_non_repo_returns_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()

    assert git.worktree_list(cwd=norepo) == []


def test_worktree_list_reports_prunable_after_dir_removed(tmp_path: Path):
    # Removing a linked worktree's directory from disk (without `git worktree
    # remove`) makes `git worktree list --porcelain` annotate it prunable,
    # exercising the `prunable` parse line. Best-effort: assert only if git
    # actually emits the annotation for this git version.
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "gone-wt"
    _git("worktree", "add", str(linked), "-b", "doomed", cwd=repo)

    # Nuke the working directory on disk; the admin record under .git survives.
    for child in sorted(linked.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        else:
            child.rmdir()
    linked.rmdir()

    entries = git.worktree_list(cwd=repo)
    prunables = [e for e in entries if "prunable" in e]
    if prunables:  # git version-dependent; only assert when emitted
        assert all(isinstance(e["prunable"], str) for e in prunables)


# ── worktree_for_slug ────────────────────────────────────────────────────────


def test_worktree_for_chunk_matches_branch(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "feature-wt"
    _git("worktree", "add", str(linked), "-b", "mentat/deadbeef/my-plan", cwd=repo)

    found = git.worktree_for_chunk("deadbeef", "my-plan", cwd=repo)
    assert found.resolve() == linked.resolve()


def test_worktree_for_chunk_unknown_raises(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    with pytest.raises(git.GitError):
        git.worktree_for_chunk("missing", "slug", cwd=repo)


# ── is_dirty ─────────────────────────────────────────────────────────────────


def test_is_dirty_false_on_clean_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    assert git.is_dirty(repo) is False


def test_is_dirty_true_on_uncommitted_change(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README").write_text("changed\n")  # README is tracked by init_git_repo
    assert git.is_dirty(repo) is True


def test_is_dirty_true_on_broken_repo(tmp_path: Path):
    # A plain non-repo dir → `git status` exits non-zero → error branch → True.
    norepo = tmp_path / "norepo"
    norepo.mkdir()
    assert git.is_dirty(norepo) is True


# ── remove_worktree ──────────────────────────────────────────────────────────


def test_remove_worktree_removes_linked_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    linked = tmp_path / "temp-wt"
    _git("worktree", "add", str(linked), "-b", "temp", cwd=repo)
    assert linked.exists()

    # remove_worktree has no cwd param — it runs `git worktree remove` in the
    # process cwd, so the caller must be inside the owning repo.
    monkeypatch.chdir(repo)
    assert git.remove_worktree(linked) is True
    assert not linked.exists()


# ── discard_path ─────────────────────────────────────────────────────────────


def test_discard_path_restores_tracked_file(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    original = (repo / "README").read_text()

    (repo / "README").write_text("scribbled over\n")
    assert git.is_dirty(repo) is True

    git.discard_path(repo, "README")

    assert (repo / "README").read_text() == original
    assert git.is_dirty(repo) is False


def test_discard_path_ignores_bogus_path_silently(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    # Nonexistent path → git checkout errors, but discard_path swallows it.
    git.discard_path(repo, "no/such/file.txt")  # must not raise


# ── rebase_ff_only ───────────────────────────────────────────────────────────


def test_rebase_ff_only_success_returns_sha(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)

    # New commit on main that the feature branch does not yet have.
    _commit(repo, "on_main.txt", "main work\n", "main advances")

    # Feature branch worktree, branched from the *original* main tip.
    feat = tmp_path / "feat-wt"
    _git("worktree", "add", str(feat), "-b", "feature", "HEAD~1", cwd=repo)
    _commit(feat, "on_feat.txt", "feature work\n", "feature advances")

    sha, err = git.rebase_ff_only(feat, "main")

    assert err is None
    assert sha is not None
    assert SHA_RE.match(sha)
    # After rebasing onto main, the feature HEAD carries both files.
    assert (feat / "on_main.txt").exists()
    assert (feat / "on_feat.txt").exists()


def test_rebase_ff_only_conflict_returns_err_and_aborts(tmp_path: Path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    # Shared file both sides will edit differently on the same line.
    _commit(repo, "shared.txt", "base\n", "add shared")

    feat = tmp_path / "feat-wt"
    _git("worktree", "add", str(feat), "-b", "feature", cwd=repo)

    # Divergent edits to the same line → rebase conflict.
    _commit(repo, "shared.txt", "main-side\n", "main edits shared")
    _commit(feat, "shared.txt", "feat-side\n", "feature edits shared")

    sha, err = git.rebase_ff_only(feat, "main")

    assert sha is None
    assert err  # non-empty stderr message

    # `git rebase --abort` must have run: no rebase in progress remains.
    status = subprocess.run(
        ["git", "status"],
        cwd=str(feat),
        capture_output=True,
        text=True,
    )
    assert status.returncode == 0
    git_dir = _git("rev-parse", "--git-path", "rebase-merge", cwd=feat).stdout.strip()
    assert not (feat / git_dir).exists()
    apply_dir = _git("rev-parse", "--git-path", "rebase-apply", cwd=feat).stdout.strip()
    assert not (feat / apply_dir).exists()


# ── ff_merge ─────────────────────────────────────────────────────────────────


def test_ff_merge_fetch_path_when_holding_not_checked_out(tmp_path: Path):
    # holding exists as a ref but is NOT checked out anywhere → fetch path.
    repo = tmp_path / "repo"
    init_git_repo(repo)
    base = _head(repo)
    # Create holding at the base tip, but leave main checked out in repo.
    _git("branch", "holding", base, cwd=repo)

    # Feature worktree descends from holding (base), then advances.
    feat = tmp_path / "feat-wt"
    _git("worktree", "add", str(feat), "-b", "feature", "holding", cwd=repo)
    feat_head = _commit(feat, "f.txt", "feature\n", "feature commit")

    assert git.ff_merge(feat, "holding") is None

    holding_tip = _git("rev-parse", "refs/heads/holding", cwd=repo).stdout.strip()
    assert holding_tip == feat_head


def test_ff_merge_update_ref_path_when_holding_checked_out(tmp_path: Path):
    # holding IS checked out in a linked worktree → update-ref path.
    repo = tmp_path / "repo"
    init_git_repo(repo)
    base = _head(repo)
    _git("branch", "holding", base, cwd=repo)

    # A worktree that has holding checked out.
    hold_wt = tmp_path / "hold-wt"
    _git("worktree", "add", str(hold_wt), "holding", cwd=repo)

    # Feature worktree descends from holding, then advances.
    feat = tmp_path / "feat-wt"
    _git("worktree", "add", str(feat), "-b", "feature", "holding", cwd=repo)
    feat_head = _commit(feat, "f.txt", "feature\n", "feature commit")

    assert git.ff_merge(feat, "holding") is None

    holding_tip = _git("rev-parse", "refs/heads/holding", cwd=repo).stdout.strip()
    assert holding_tip == feat_head


def test_ff_merge_not_ff_when_holding_diverged_checked_out(tmp_path: Path):
    # holding checked out AND has a commit not in feature HEAD → not-ff (the
    # update-ref branch's merge-base --is-ancestor rejection).
    repo = tmp_path / "repo"
    init_git_repo(repo)
    base = _head(repo)
    _git("branch", "holding", base, cwd=repo)

    hold_wt = tmp_path / "hold-wt"
    _git("worktree", "add", str(hold_wt), "holding", cwd=repo)

    feat = tmp_path / "feat-wt"
    _git("worktree", "add", str(feat), "-b", "feature", "holding", cwd=repo)
    _commit(feat, "f.txt", "feature\n", "feature commit")

    # Advance holding independently → its tip is no longer an ancestor of feat.
    _commit(hold_wt, "h.txt", "holding\n", "holding diverges")

    assert git.ff_merge(feat, "holding") == "not-ff"


def test_ff_merge_not_ff_when_holding_diverged_not_checked_out(tmp_path: Path):
    # holding NOT checked out but diverged → not-ff via the fetch-branch's
    # merge-base --is-ancestor rejection.
    repo = tmp_path / "repo"
    init_git_repo(repo)
    base = _head(repo)
    _git("branch", "holding", base, cwd=repo)

    feat = tmp_path / "feat-wt"
    _git("worktree", "add", str(feat), "-b", "feature", "holding", cwd=repo)
    _commit(feat, "f.txt", "feature\n", "feature commit")

    # Advance holding directly on the ref (not checked out anywhere) so its tip
    # is not an ancestor of feat HEAD.
    diverge = _commit(repo, "d.txt", "diverge\n", "main+holding diverge base")
    _git("update-ref", "refs/heads/holding", diverge, cwd=repo)

    assert git.ff_merge(feat, "holding") == "not-ff"


def test_ff_merge_git_error_when_head_unresolvable(tmp_path: Path, monkeypatch):
    # A dir outside any repo → the initial rev-parse HEAD fails → git-error.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    norepo = tmp_path / "norepo"
    norepo.mkdir()

    assert git.ff_merge(norepo, "holding") == "git-error"


def test_ff_merge_git_error_on_repo_without_commits(tmp_path: Path):
    # A freshly init'd repo with NO commits: rev-parse HEAD fails → git-error,
    # covering the empty/unborn-HEAD failure path distinctly from the ceiling one.
    repo = tmp_path / "empty"
    repo.mkdir()
    _git("init", "-b", "main", ".", cwd=repo)

    assert git.ff_merge(repo, "holding") == "git-error"
