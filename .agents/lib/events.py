"""ADR-0007 envelope emitter. Stdlib only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from typing import Literal

from lib import paths
from lib.session import agent_id_from_env, make_agent_id

# Events where a failed emit must not be silently swallowed — the orchestration
# state machine cannot proceed correctly without a confirmed log write.
_TERMINAL_EVENTS: frozenset[str] = frozenset({"chunk_landed", "chunk_ejected"})
_EMIT_TIMEOUT_S = 30.0

IMPLEMENT_FAILED = "implement_failed"
GATE_FAILED = "gate_failed"
REBASE_CONFLICTED = "rebase_conflicted"
NOT_FF = "not_ff"
GIT_ERROR = "git_error"
HITL_REQUIRED = "hitl_required"
PREFLIGHT_WORKTREE_FAILED = "preflight_worktree_failed"
MAIN_TREE_REFUSED = "main_tree_refused"
UPSTREAM_EJECTED = "upstream_ejected"
WORKER_DIED = "worker_died"
CONTAINER_OOM = "container_oom"

OK = "ok"
NONZERO = "nonzero"
SIGNAL = "signal"
DEAD_PID = "dead_pid"

StatusReason = Literal[
    "implement_failed",
    "gate_failed",
    "rebase_conflicted",
    "not_ff",
    "git_error",
    "hitl_required",
    "preflight_worktree_failed",
    "main_tree_refused",
    "upstream_ejected",
    "worker_died",
    "container_oom",
    "ok",
    "nonzero",
    "signal",
    "dead_pid",
]

CHUNK_EJECT_REASONS: frozenset[str] = frozenset(
    {
        IMPLEMENT_FAILED,
        GATE_FAILED,
        REBASE_CONFLICTED,
        NOT_FF,
        GIT_ERROR,
        HITL_REQUIRED,
        PREFLIGHT_WORKTREE_FAILED,
        MAIN_TREE_REFUSED,
        UPSTREAM_EJECTED,
        WORKER_DIED,
        CONTAINER_OOM,
    }
)

AGENT_STATUS_REASONS: frozenset[str] = frozenset({OK, NONZERO, SIGNAL, DEAD_PID})

STATUS_REASONS: frozenset[str] = CHUNK_EJECT_REASONS | AGENT_STATUS_REASONS

EJECT_REASONS = CHUNK_EJECT_REASONS

TRANSIENT_EJECT_REASONS: frozenset[str] = frozenset({WORKER_DIED, NOT_FF, PREFLIGHT_WORKTREE_FAILED, CONTAINER_OOM})


def is_transient_eject(reason: str) -> bool:
    """True iff `reason` is worth re-attempting (environment failed, not the code)."""
    return reason in TRANSIENT_EJECT_REASONS


def _spawn(skill: str, event: str, payload: dict[str, object]) -> bool:
    env = dict(os.environ)
    if not agent_id_from_env(env):
        env["MENTAT_AGENT"] = make_agent_id(skill, "adhoc")
        env.setdefault("MENTAT_SESSION", env["MENTAT_AGENT"])
    r = subprocess.run(
        ["python3", str(paths.LOG_SCRIPT), "emit", skill, event, json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=_EMIT_TIMEOUT_S,
    )
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        print(f"{skill}: emit {event!r} failed rc={r.returncode}: {tail[0]}", file=sys.stderr)
        return False
    return True


def bind(skill: str) -> Callable[[str, dict[str, object]], None]:
    def emit(event: str, payload: dict[str, object]) -> None:
        ok = _spawn(skill, event, payload)
        if not ok and event in _TERMINAL_EVENTS:
            raise RuntimeError(f"{skill}: terminal emit {event!r} rejected; orchestration halted")

    return emit


SUMMARY_FILE = "summary.md"

HITL_IN_SESSION = "hitl-in-session"


def spawned_payload(
    slug: str,
    plan: str,
    *,
    harness: str,
    worktree: str,
    trigger: str | None = None,
    attempt: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"slug": slug, "plan": plan, "harness": harness, "worktree": worktree}
    if trigger is not None:
        payload["trigger"] = trigger
    if attempt is not None:
        payload["attempt"] = attempt
    return payload


def ejected_payload(
    slug: str,
    reason: str,
    where: str,
    *,
    logs_path: str | None = None,
    preflight_exit: int | None = None,
    upstream: str | None = None,
    summary: str | None = None,
    killed_by: str | None = None,
    timed_out: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"slug": slug, "reason": reason, "where": where}
    if logs_path is not None:
        payload["logs_path"] = logs_path
    if preflight_exit is not None:
        payload["preflight_exit"] = preflight_exit
    if upstream is not None:
        payload["upstream"] = upstream
    if summary is not None:
        payload["summary"] = summary
    if killed_by is not None:
        payload["killed_by"] = killed_by
    if timed_out is not None:
        payload["timed_out"] = timed_out
    return payload
