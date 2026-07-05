"""Spawn a plan in a headless worktree and return session ID."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import paths  # noqa: E402
from lib.events import bind, spawned_payload  # noqa: E402
from lib.loader import load_sibling  # noqa: E402
from lib.session import make_agent_id  # noqa: E402
from lib.session import session_dir as _session_dir_fn

_IMPLEMENT_SCRIPT = paths.SKILLS_DIR / "mentat-implement/scripts/implement.py"
_CONTAINER_SCRIPT = paths.CONTAINER_SCRIPT
_LOG_SCRIPT = paths.LOG_SCRIPT

_utils = load_sibling(__file__, "plans")


class _PlanLike(Protocol):
    slug: str
    path: Path


def _log_dir_for(session_id: str) -> Path:
    """Per-session log dir. Delegates to lib.session."""
    return _session_dir_fn(session_id)


def _build_spawn_cmd(
    plan_path: Path,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> tuple[str, list[str], dict[str, str]]:
    """Mint a child session and build its (session_id, argv, env).

    Generates a deterministic session id, creates ~/.mentat/logs/<repo>/<sid>/
    with mode 0o700, and populates MENTAT_SESSION + MENTAT_SESSION_LOG in the
    child env so the harness adapter can redirect stream-json into the log file.
    seed_summary — when set — injects MENTAT_SEED_SUMMARY so the harness adapter
    seeds the new session with prior context. Pure builder shared by the sync
    (``spawn_with_proc``) and async (``spawn_async``) spawn paths.
    """
    # The child is an implement run — mint a fresh implement session per child
    # (overriding any inherited orchestrate id in the child env below).
    session_id = make_agent_id("implement", plan_path.stem)
    log_dir = _log_dir_for(session_id)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    session_log = log_dir / "session.jsonl"

    cmd = ["python3", str(_IMPLEMENT_SCRIPT), str(plan_path)]
    if harness:
        cmd += ["--harness", harness]
    if model:
        cmd += ["--model", model]
    env = {
        **os.environ,
        "MENTAT_SESSION": session_id,
        "MENTAT_SESSION_LOG": str(session_log),
    }
    if seed_summary:
        env["MENTAT_SEED_SUMMARY"] = seed_summary
    return session_id, cmd, env


def _spawn_worktree_subprocess(
    plan_path: Path,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> tuple[str, subprocess.Popen]:
    """Spawn a headless mentat-implement in a new worktree. Returns (session_id, Popen).

    start_new_session=True puts the child in its own process group / session,
    which the harness grandchild (implement.py -> harness) inherits. On a
    timeout, orchestrate group-kills that pgid so the grandchild is reaped too
    instead of orphaning and continuing to mutate the worktree (Bug A).
    """
    session_id, cmd, env = _build_spawn_cmd(plan_path, harness=harness, model=model, seed_summary=seed_summary)
    proc = subprocess.Popen(cmd, env=env, start_new_session=True)
    return session_id, proc


_emit_event = bind("mentat-orchestrate")


def spawn_with_proc(
    plan: _PlanLike, *, harness: str | None = None, model: str | None = None, seed_summary: str | None = None
) -> tuple[str, subprocess.Popen]:
    """Spawn plan headless (sync Popen). Print track command immediately. Return (session_id, Popen)."""
    session_id, proc = _spawn_worktree_subprocess(plan.path, harness=harness, model=model, seed_summary=seed_summary)
    _emit_event(
        "chunk.spawned",
        spawned_payload(plan.slug, str(plan.path), harness=harness or "default", worktree=str(Path.cwd())),
    )
    print(f"mentat-session track {session_id}")
    print(session_id)
    return session_id, proc


async def spawn_async(
    plan: _PlanLike, *, harness: str | None = None, model: str | None = None, seed_summary: str | None = None
) -> tuple[str, asyncio.subprocess.Process]:
    """Spawn plan headless under asyncio. Emit chunk.spawned, print track command,
    return (session_id, Process).

    The asyncio supervisor (orchestrate._fan_out_plans) awaits the returned
    Process via communicate() and enforces the per-chunk deadline. As with the
    sync path, start_new_session=True makes the child a group leader so a timeout
    group-kill reaps the harness grandchild too (Bug A)."""
    session_id, cmd, env = _build_spawn_cmd(plan.path, harness=harness, model=model, seed_summary=seed_summary)
    proc = await asyncio.create_subprocess_exec(*cmd, env=env, start_new_session=True)
    _emit_event(
        "chunk.spawned",
        spawned_payload(plan.slug, str(plan.path), harness=harness or "default", worktree=str(Path.cwd())),
    )
    print(f"mentat-session track {session_id}")
    print(session_id)
    return session_id, proc


def spawn(
    plan: _PlanLike,
    *,
    harness: str | None = None,
    model: str | None = None,
    seed_summary: str | None = None,
) -> str:
    """Spawn plan headless. Discards Popen handle. Returns session ID."""
    session_id, _proc = spawn_with_proc(plan, harness=harness, model=model, seed_summary=seed_summary)
    return session_id
