"""End-to-end HITL pipeline lands a chunk without `claude --headless`.

Flow:
1. orchestrate.run_orchestrate on a HITL plan → emits
   chunk_started{harness:"hitl-in-agent"}; returns without invoking
   the harness.
2. Caller (this test stands in for the calling Claude agent) commits
   work on the slug worktree (simulating the in-agent /mentat-implement
   drive) then invokes land_queue.drain.
3. land_queue rebases + gates + FF-merges, emitting chunk_landed;
   holding FF-advances to the chunk tip.

At no point is `claude --headless` invoked.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README").write_text("seed\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_pipeline_hitl_lands_chunk_without_claude_headless(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    land_queue = _load("landing")

    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "checkout", "-b", "holding")
    slug = "fix-hitl-pipe"
    wt = tmp_path / "wt-fix-hitl-pipe"
    _git(repo, "worktree", "add", "-b", slug, str(wt), "holding")
    (wt / "a.txt").write_text("hi\n")
    _git(wt, "add", ".")
    _git(wt, "commit", "-m", "slice impl")
    chunk_tip = _git(wt, "rev-parse", "HEAD").stdout.strip()

    plan = tmp_path / f"{slug}.md"
    plan.write_text(f"---\nid: {slug}\nstatus: ready\nkind: HITL\nblocked_by: []\n---\n# {slug}\n")

    emitted: list[tuple[str, dict]] = []

    def record(event: str, payload: dict) -> None:
        emitted.append((event, payload))

    monkeypatch.setattr(orchestrate._utils, "emit_event", record)
    monkeypatch.setattr(land_queue, "_emit_event", record)
    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", lambda plans, **kw: [])

    # --- Phase 1: orchestrate emits chunk_started{hitl-in-agent}, no land ---
    rc = orchestrate.run_orchestrate("holding", [plan], harness=None, model=None, dry_run=False)
    assert rc == 0
    spawned = [(e, p) for e, p in emitted if e == "chunk_started"]
    assert spawned, f"chunk_started not emitted; got: {emitted}"
    assert spawned[0][1]["harness"] == "hitl-in-agent"
    assert spawned[0][1]["slug"] == slug
    landed_phase1 = [e for e, _ in emitted if e == "chunk_landed"]
    assert landed_phase1 == [], "chunk_landed must NOT fire in phase 1"

    # --- Phase 2: caller drives land-queue with the HITL slug ---
    chunk = land_queue.Chunk(slug=slug, worktree=wt)
    results = land_queue.drain([chunk], holding="holding")

    assert results and results[0]["status"] == "success", f"chunk did not land: {results}"
    landed = [(e, p) for e, p in emitted if e == "chunk_landed"]
    assert landed, f"chunk_landed not emitted; got: {emitted}"
    assert landed[0][1]["slug"] == slug
    assert landed[0][1]["holding"] == "holding"

    holding_sha = _git(repo, "rev-parse", "holding").stdout.strip()
    assert holding_sha == chunk_tip, f"holding {holding_sha} did not FF to chunk tip {chunk_tip}"
