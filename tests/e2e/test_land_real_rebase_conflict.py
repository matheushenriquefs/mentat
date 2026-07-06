"""E2E: two real sibling chunks editing the same line — second hits a genuine
rebase conflict and ejects cleanly (gap D).

The eject mechanics are unit-tested with forced/mocked errors; nothing drives two
real sibling branches through ``land_queue.drain`` where the second hits an actual
git rebase conflict after the first lands. This test builds that situation with
real git: chunk A lands (advancing holding onto the contested line), then chunk B
rebases onto the new holding and conflicts. It must eject ``rebase-conflicted``,
leave its worktree clean (``rebase --abort`` ran — no rebase in progress, no
unmerged paths), and keep its branch commit intact so the work is recoverable for
a manual land. Siblings → no cascade (``test_sibling_eject_does_not_cascade``
covers the dependency case).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _setup_conflicting_siblings(tmp_path: Path):
    """Holding + two sibling worktrees whose branches edit the same line of f.txt.

    A and B both branch off holding's init commit and rewrite the same middle
    line differently, so once A lands, B's rebase onto holding conflicts.
    """
    lq = load_module("landing")
    main_repo = tmp_path / "main"
    main_repo.mkdir()

    _git(["init", "-b", "holding", str(main_repo)], cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=main_repo)

    (main_repo / "f.txt").write_text("line1\nTARGET\nline3\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "init"], cwd=main_repo)

    _git(["checkout", "-b", "a"], cwd=main_repo)
    (main_repo / "f.txt").write_text("line1\nAAA\nline3\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "a edits target"], cwd=main_repo)

    _git(["checkout", "holding"], cwd=main_repo)
    _git(["checkout", "-b", "b"], cwd=main_repo)
    (main_repo / "f.txt").write_text("line1\nBBB\nline3\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "b edits target"], cwd=main_repo)
    b_sha = _git(["rev-parse", "HEAD"], cwd=main_repo)

    _git(["checkout", "holding"], cwd=main_repo)

    wt_a = tmp_path / "wt-a"
    wt_b = tmp_path / "wt-b"
    _git(["worktree", "add", str(wt_a), "a"], cwd=main_repo)
    _git(["worktree", "add", str(wt_b), "b"], cwd=main_repo)

    chunk_a = lq.Chunk(slug="a", worktree=wt_a)
    chunk_b = lq.Chunk(slug="b", worktree=wt_b)
    return lq, main_repo, chunk_a, chunk_b, b_sha


def test_second_sibling_rebase_conflict_ejects_clean(tmp_path):
    lq, main_repo, chunk_a, chunk_b, b_sha = _setup_conflicting_siblings(tmp_path)

    with patch.object(lq, "_run_gates", return_value=("pass", "")):
        with patch.object(lq, "_teardown_container", lambda _slug: None):
            with patch.object(lq, "_emit_event", lambda *a, **k: None):
                results = lq.drain([chunk_a, chunk_b], holding="holding")

    by_slug = {r["slug"]: r for r in results}

    # A lands; holding advances to A's contested edit.
    assert by_slug["a"]["status"] == "success", f"A must land: {by_slug['a']}"
    assert _git(["rev-parse", "refs/heads/holding"], cwd=main_repo) == _git(
        ["rev-parse", "refs/heads/a"], cwd=main_repo
    ), "holding must fast-forward to A"

    # B hits a genuine rebase conflict and ejects.
    assert by_slug["b"]["status"] == "eject", f"B must eject: {by_slug['b']}"
    assert by_slug["b"]["reason"] == lq.REBASE_CONFLICTED

    # B's worktree is clean — rebase --abort ran: no rebase in progress, no unmerged paths.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=chunk_b.worktree, capture_output=True, text=True, check=True
    ).stdout
    assert status.strip() == "", f"B worktree must be clean after abort: {status!r}"
    # No rebase state left behind (REBASE_HEAD only resolves mid-rebase).
    rebase_head = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "REBASE_HEAD"], cwd=chunk_b.worktree, capture_output=True
    )
    assert rebase_head.returncode != 0, "no rebase may be left in progress in B's worktree"

    # B's branch commit is intact — work recoverable for a manual land.
    assert _git(["rev-parse", "refs/heads/b"], cwd=main_repo) == b_sha, "B's commit must survive the aborted rebase"
    assert _git(["log", "-1", "--format=%s", "b"], cwd=main_repo) == "b edits target"
