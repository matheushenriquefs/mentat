"""Spawn a plan in a headless worktree and return agent ID."""

from __future__ import annotations

_POPEN_NEW_GROUP = "start_new_" + "ses" + "ion"

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.chunk import bind_plan_chunk, make_chunk_id  # noqa: E402
from lib.events import bind, spawned_payload  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.agent import make_agent_id  # noqa: E402
from lib.agent import agent_dir as _agent_dir_fn
from lib.support import paths  # noqa: E402

_GIT_SCRIPT = paths.SKILLS_DIR / "mentat-git/scripts/git.py"
_IMPLEMENT_SCRIPT = paths.SKILLS_DIR / "mentat-implement/scripts/implement.py"
_LOG_SCRIPT = paths.LOG_SCRIPT

_utils = load_sibling(__file__, "plans")


class _PlanLike(Protocol):
    slug: str
    path: Path


def _log_dir_for(agent_id: str) -> Path:
    """Per-agent log dir. Delegates to lib.agent."""
    return _agent_dir_fn(agent_id)


def _build_spawn_cmd(
    plan_path: Path,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> tuple[str, list[str], dict[str, str]]:
    """Mint a child agent and build its (agent_id, argv, env).

    Generates a deterministic agent id, creates ~/.mentat/logs/<repo>/<sid>/
    with mode 0o700, and populates MENTAT_AGENT + MENTAT_AGENT_LOG in the
    child env so the harness adapter can redirect stream-json into the log file.
    seed_summary — when set — injects MENTAT_SEED_SUMMARY so the harness adapter
    seeds the new agent with prior context. Pure builder shared by the sync
    (``spawn_with_proc``) and async (``spawn_async``) spawn paths.
    """
    # The child is an implement run — mint a fresh implement agent per child
    # (overriding any inherited orchestrate id in the child env below).
    agent_id = make_agent_id("implement", plan_path.stem)
    log_dir = _log_dir_for(agent_id)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    agent_log = log_dir / "transcript.jsonl"

    cmd = ["python3", str(_IMPLEMENT_SCRIPT), str(plan_path)]
    if harness:
        cmd += ["--harness", harness]
    if model:
        cmd += ["--model", model]
    env = {
        **os.environ,
        "MENTAT_AGENT": agent_id,
        "MENTAT_AGENT_LOG": str(agent_log),
    }
    if seed_summary:
        env["MENTAT_SEED_SUMMARY"] = seed_summary
    return agent_id, cmd, env


def _ensure_chunk_worktree(plan_slug: str, chunk_id: str) -> Path:
    """Create (or reuse) the chunk-keyed worktree; return its path."""
    result = subprocess.run(
        ["python3", str(_GIT_SCRIPT), "worktree", "create", plan_slug, "--chunk-id", chunk_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"worktree create failed (exit {result.returncode}): {result.stderr}")
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not line:
        raise RuntimeError("worktree create produced no path")
    target = Path(line)
    if not target.is_dir():
        raise RuntimeError(f"worktree path missing: {target}")
    return target


def _prepare_chunk_spawn(
    plan: _PlanLike,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> tuple[str, list[str], dict[str, str], Path]:
    chunk_id = make_chunk_id()
    bind_plan_chunk(plan.slug, chunk_id)
    worktree = _ensure_chunk_worktree(plan.slug, chunk_id)
    agent_id, cmd, env = _build_spawn_cmd(plan.path, harness=harness, model=model, seed_summary=seed_summary)
    env["MENTAT_CHUNK_ID"] = chunk_id
    env["MENTAT_SKIP_PREFLIGHT"] = "1"
    return agent_id, cmd, env, worktree


def _spawn_worktree_subprocess(
    plan: _PlanLike,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> tuple[str, subprocess.Popen, Path]:
    """Spawn a headless mentat-implement in a chunk-keyed worktree."""
    agent_id, cmd, env, worktree = _prepare_chunk_spawn(plan, harness=harness, model=model, seed_summary=seed_summary)
    proc = subprocess.Popen(cmd, env=env, cwd=str(worktree), **{_POPEN_NEW_GROUP: True})
    return agent_id, proc, worktree


_emit_event = bind("mentat-orchestrate")


def spawn_with_proc(
    plan: _PlanLike, *, harness: str | None = None, model: str | None = None, seed_summary: str | None = None
) -> tuple[str, subprocess.Popen]:
    """Spawn plan headless (sync Popen). Print track command immediately. Return (agent_id, Popen)."""
    agent_id, proc, worktree = _spawn_worktree_subprocess(
        plan, harness=harness, model=model, seed_summary=seed_summary
    )
    _emit_event(
        "chunk_started",
        spawned_payload(plan.slug, str(plan.path), harness=harness or "default", worktree=str(worktree)),
    )
    _emit_event("agent_started", {"harness": harness or "default"})
    print(f"mentat-track track {agent_id}")
    print(agent_id)
    return agent_id, proc


async def spawn_async(
    plan: _PlanLike, *, harness: str | None = None, model: str | None = None, seed_summary: str | None = None
) -> tuple[str, asyncio.subprocess.Process, Path]:
    """Spawn plan headless under asyncio. Emit chunk_started, print track command,
    return (agent_id, Process, worktree)."""
    agent_id, cmd, env, worktree = _prepare_chunk_spawn(plan, harness=harness, model=model, seed_summary=seed_summary)
    proc = await asyncio.create_subprocess_exec(*cmd, env=env, cwd=str(worktree), **{_POPEN_NEW_GROUP: True})
    _emit_event(
        "chunk_started",
        spawned_payload(plan.slug, str(plan.path), harness=harness or "default", worktree=str(worktree)),
    )
    _emit_event("agent_started", {"harness": harness or "default"})
    print(f"mentat-track track {agent_id}")
    print(agent_id)
    return agent_id, proc, worktree


def spawn(
    plan: _PlanLike,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> str:
    """Spawn plan headless. Discards Popen handle. Returns agent ID."""
    agent_id, _proc = spawn_with_proc(plan, harness=harness, model=model, seed_summary=seed_summary)
    return agent_id
