"""E2E: two concurrent chunk-keyed worktrees must not collide or touch main HEAD."""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.chunk as chunk_mod
import lib.git as git_lib
import pytest

from tests.conftest import init_git_repo


def _git(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _main_head(cwd: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.mark.e2e
def test_two_chunk_worktrees_are_isolated(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    main_head_before = _main_head(repo)

    cid_a = chunk_mod.make_chunk_id()
    cid_b = chunk_mod.make_chunk_id()
    slug = "same-plan"

    wt_a = repo / ".mentat" / "worktrees" / cid_a / slug
    wt_b = repo / ".mentat" / "worktrees" / cid_b / slug
    wt_a.parent.mkdir(parents=True, exist_ok=True)
    wt_b.parent.mkdir(parents=True, exist_ok=True)

    branch_a = chunk_mod.holding_branch(chunk_mod.chunk_slug(cid_a, slug))
    branch_b = chunk_mod.holding_branch(chunk_mod.chunk_slug(cid_b, slug))
    _git(["worktree", "add", "-b", branch_a, str(wt_a), "main"], cwd=repo)
    _git(["worktree", "add", "-b", branch_b, str(wt_b), "main"], cwd=repo)

    assert git_lib.worktree_for_chunk(cid_a, slug, cwd=repo).resolve() == wt_a.resolve()
    assert git_lib.worktree_for_chunk(cid_b, slug, cwd=repo).resolve() == wt_b.resolve()
    assert wt_a.resolve() != wt_b.resolve()
    assert _main_head(repo) == main_head_before

    (wt_a / "only-a.txt").write_text("a\n")
    _git(["add", "only-a.txt"], cwd=wt_a)
    _git(["commit", "-m", "a"], cwd=wt_a)

    assert _main_head(repo) == main_head_before
    assert not (wt_b / "only-a.txt").exists()

    with pytest.raises(git_lib.GitError):
        git_lib.worktree_for_chunk("not-bound", slug, cwd=repo)
