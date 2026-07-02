"""ADR-0007 envelope emitter. Stdlib only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable

from lib import paths, state
from lib.session import mint_session

# Events where a failed emit must not be silently swallowed — the orchestration
# state machine cannot proceed correctly without a confirmed log write.
_TERMINAL_EVENTS: frozenset[str] = frozenset({"chunk.landed", "chunk.ejected"})


def _spawn(skill: str, event: str, payload: dict[str, object]) -> bool:
    # Guarantee a session id reaches log.py: mint an opaque uuid into the child
    # env when none is set (never mutating our own os.environ), so log.py's
    # last-resort fallback is unreachable and no unkeyed `orphan-` dir is born.
    env = dict(os.environ)
    if not env.get("MENTAT_SESSION"):
        env["MENTAT_SESSION"] = mint_session(skill, "adhoc")
    r = subprocess.run(
        ["python3", str(paths.LOG_SCRIPT), "emit", skill, event, json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["(no stderr)"]
        print(f"{skill}: emit {event!r} failed rc={r.returncode}: {tail[0]}", file=sys.stderr)
        return False
    # Log write confirmed → project the derived read model from the same env the
    # child logged under. Best-effort inside project(): never fails an emit.
    state.project(env, event)
    return True


def bind(skill: str) -> Callable[[str, dict[str, object]], None]:
    def emit(event: str, payload: dict[str, object]) -> None:
        ok = _spawn(skill, event, payload)
        if not ok and event in _TERMINAL_EVENTS:
            raise RuntimeError(f"{skill}: terminal emit {event!r} rejected; orchestration halted")

    return emit


class EjectReason:
    """Canonical ``chunk.ejected`` reasons — one definition imported by every
    emitter (implement, orchestrate, land_queue) and reader (doctor, sessions,
    log) so a rename can't desync them. Values are the wire strings."""

    IMPLEMENT_FAILED = "implement-failed"
    GATE_FAILED = "gate-failed"
    REBASE_CONFLICTED = "rebase-conflicted"
    NOT_FF = "not-ff"
    GIT_ERROR = "git-error"
    HITL_REQUIRED = "hitl-required"
    PREFLIGHT_WORKTREE_FAILED = "preflight-worktree-failed"
    MAIN_TREE_REFUSED = "main-tree-refused"
    UPSTREAM_EJECTED = "upstream_ejected"
    WORKER_DIED = "worker-died"


EJECT_REASONS: frozenset[str] = frozenset(
    {
        EjectReason.IMPLEMENT_FAILED,
        EjectReason.GATE_FAILED,
        EjectReason.REBASE_CONFLICTED,
        EjectReason.NOT_FF,
        EjectReason.GIT_ERROR,
        EjectReason.HITL_REQUIRED,
        EjectReason.PREFLIGHT_WORKTREE_FAILED,
        EjectReason.MAIN_TREE_REFUSED,
        EjectReason.UPSTREAM_EJECTED,
        EjectReason.WORKER_DIED,
    }
)

# The one report-back filename: implement reads it as the AFK wedge marker, the
# AFK prompt tells the agent to write it, doctor writes the success summary to
# it. Shared so the cross-skill contract has a single source.
SUMMARY_FILE = "summary.md"

# Harness sentinel for a HITL chunk that runs in the calling session rather than
# a spawned headless sub-claude.
HITL_IN_SESSION = "hitl-in-session"


def spawned_payload(slug: str, plan: str, *, harness: str, worktree: str) -> dict[str, object]:
    """The one canonical ``chunk.spawned`` payload — shared by fan_out (headless
    AFK spawn) and the in-session HITL emitters in implement/orchestrate."""
    return {"slug": slug, "plan": plan, "harness": harness, "worktree": worktree}


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
    """Build the one canonical ``chunk.ejected`` payload.

    Base shape ``{slug, reason, where}`` for every ejection regardless of caller;
    the optional fields (``logs_path``, ``preflight_exit``, ``upstream``,
    ``summary``, ``killed_by``, ``timed_out``) are included only when set.
    ``summary`` carries the operator-facing blocker text on a ``hitl-required``
    ejection; ``timed_out``/``killed_by`` make a ``worker-died`` ejection
    self-describing (a chunk killed at its deadline vs. one lost to a downed
    container). These optionals are declared in mentat-log's
    ``EVENT_OPTIONAL_FIELDS`` — a payload extension, not a new event type (the
    event catalog is unchanged).
    """
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
