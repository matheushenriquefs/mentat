"""E2E: two non-conflicting one-slice plans through a full ``orchestrate run``.

Real git throughout: two sibling worktrees branched off a holding branch, each given
one real commit (touching a distinct file, so they never conflict), then driven
through ``run_orchestrate`` — fan-out, partition, and the serial land queue. The two
seams that can't run hermetically are stubbed: the harness spawn boundary (replaced by
a fake that does the agent's real commit work in the worktree, then a trivial child the
supervisor reaps) and the docker-touching prune/teardown calls. The land queue's rebase
and fast-forward merge are real. Asserts both chunks ff-merge serially onto the holding
tip (init → a → b-rebased-on-a) and that two ``chunk_landed`` events are recorded.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

import pytest

from tests.conftest import TEST_CHUNK_ID, bind_plan, events_by_kind, load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@contextmanager
def _patch_attr(obj, name, value):
    saved = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, saved)


def _setup_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A holding branch + two sibling worktrees (branches `a`, `b`) off its init commit."""
    main_repo = tmp_path / "repo"
    main_repo.mkdir()
    _git(["init", "-b", "holding", "."], cwd=main_repo)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _git(["config", k, v], cwd=main_repo)
    (main_repo / "base.txt").write_text("base\n")
    _git(["add", "."], cwd=main_repo)
    _git(["commit", "-m", "init"], cwd=main_repo)

    wt_root = main_repo / ".mentat" / "worktrees"
    wt_root.mkdir(parents=True)
    wt_a = wt_root / TEST_CHUNK_ID / "a"
    wt_b = wt_root / TEST_CHUNK_ID / "b"
    bind_plan("a", TEST_CHUNK_ID)
    bind_plan("b", TEST_CHUNK_ID)
    _git(["worktree", "add", "-b", f"mentat/{TEST_CHUNK_ID}/a", str(wt_a), "holding"], cwd=main_repo)
    _git(["worktree", "add", "-b", f"mentat/{TEST_CHUNK_ID}/b", str(wt_b), "holding"], cwd=main_repo)
    return main_repo, wt_a, wt_b


def _write_plan(plans_dir: Path, slug: str) -> Path:
    plan = plans_dir / f"{slug}.md"
    plan.write_text(f"---\nid: {slug}\nkind: AFK\n---\n# {slug}\nAdd {slug}.txt and commit.\n")
    return plan


def _fake_spawn(worktrees: dict[str, Path]):
    """Harness stand-in: commit the slice's distinct file on its branch, then a no-op child."""

    async def spawn_async(plan, *, harness=None, model=None, seed_summary=None):
        wt = worktrees[plan.slug]
        (wt / f"{plan.slug}.txt").write_text(f"{plan.slug}\n")
        _git(["add", f"{plan.slug}.txt"], cwd=wt)
        _git(["commit", "-m", f"feat: {plan.slug}"], cwd=wt)
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "")
        return f"orchestrate-{plan.slug}", proc, wt

    return spawn_async


def _landed_events() -> list[dict]:
    from lib import store

    conn = store.connect()
    try:
        agent_ids = [row[0] for row in conn.execute("SELECT id FROM agent").fetchall()]
    finally:
        conn.close()
    out: list[dict] = []
    for agent_id in agent_ids:
        out.extend(events_by_kind(agent_id, "chunk_landed"))
    return out


def test_orchestrate_run_lands_both_chunks_onto_holding(tmp_path, monkeypatch):
    orch = load_script(SCRIPTS / "orchestrate.py", "orchestrate")

    main_repo, wt_a, wt_b = _setup_repo(tmp_path)
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    plan_a = _write_plan(plans_dir, "a")
    plan_b = _write_plan(plans_dir, "b")

    log_root = tmp_path / "logs"
    monkeypatch.setenv("HOME", str(tmp_path))  # no real ~/.mentat/config.toml
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)
    monkeypatch.chdir(main_repo)

    before = int(_git(["rev-list", "--count", "refs/heads/holding"], cwd=main_repo))

    with ExitStack() as stack:
        # Docker-touching seams: stubbed (hermetic, no devcontainer).
        stack.enter_context(_patch_attr(orch._batch, "_prune_stale_containers", lambda: None))
        stack.enter_context(_patch_attr(orch._batch, "_prune_stale_worktrees", lambda preserve=None: None))
        # Harness spawn boundary: the fake agent does the real per-slice commit.
        stack.enter_context(_patch_attr(orch._supervise._spawn, "spawn_async", _fake_spawn({"a": wt_a, "b": wt_b})))
        # Land-queue gate passes; container teardown is a no-op (no docker).
        stack.enter_context(_patch_attr(orch._batch._land_queue, "_run_gates", lambda chunk: ("pass", "")))
        stack.enter_context(_patch_attr(orch._batch._land_queue, "_teardown_container", lambda chunk: None))

        rc = orch.run_orchestrate("holding", [plan_a, plan_b], harness=None, model=None, dry_run=False)

    assert rc == 0, "a clean two-chunk batch must return 0"

    # Both chunks ff-merged serially onto holding: init → a → b (rebased on a).
    after = int(_git(["rev-list", "--count", "refs/heads/holding"], cwd=main_repo))
    assert after == before + 2, f"holding must advance by both commits (was {before}, now {after})"
    subjects = _git(["log", "--format=%s", "refs/heads/holding"], cwd=main_repo).splitlines()
    assert subjects[:3] == ["feat: b", "feat: a", "init"], f"holding history wrong: {subjects}"
    # Both slices' files are present at the holding tip.
    tree = _git(["ls-tree", "-r", "--name-only", "refs/heads/holding"], cwd=main_repo).splitlines()
    assert {"a.txt", "b.txt", "base.txt"} <= set(tree), f"holding tip missing slice files: {tree}"

    # Two chunk_landed events recorded — one per ff-merge onto the tip.
    landed = _landed_events()
    assert {e["payload"]["slug"] for e in landed} == {"a", "b"}, f"expected both landed: {landed}"
    assert all(e["payload"]["holding"] == "holding" for e in landed)
