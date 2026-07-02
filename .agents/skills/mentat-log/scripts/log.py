#!/usr/bin/env python3
"""mentat-log — emit / validate / query / prune audit JSONL."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import state as _state  # noqa: E402
from lib.events import EJECT_REASONS as _EJECT_REASONS  # noqa: E402
from lib.session import log_root as _log_root  # noqa: E402
from lib.session import mint_session as _mint_session
from lib.session import repo_name as _repo

EVENT_CATALOG: dict[str, list[str]] = {
    "plan.started": ["path"],
    "plan.succeeded": ["path"],
    "plan.failed": ["path", "reason"],
    "chunk.spawned": ["slug", "plan", "harness", "worktree"],
    "chunk.landed": ["slug", "sha", "holding"],
    "chunk.ejected": ["slug", "reason", "where"],
    "gate.evaluated": ["gate", "verdict", "severity", "message"],
    "review.submitted": ["reviewer", "score", "threshold", "verdict"],
    "batch.reviewed": ["session", "summary"],
    "chunk.teardown": ["slug", "ok"],
    "task.created": ["id", "slug"],
    "task.claimed": ["id", "agent", "expires_at"],
    "task.released": ["id"],
    "task.done": ["id"],
    "task.wontfix": ["id"],
    "session.prune": ["reclaimed_bytes"],
}

# Optional payload fields per event — extensions beyond the required catalog
# above. Declared (documented), not rejected: emitters may add these without a
# new event type. chunk.ejected carries them via lib.events.ejected_payload.
EVENT_OPTIONAL_FIELDS: dict[str, list[str]] = {
    "chunk.ejected": ["logs_path", "preflight_exit", "upstream", "summary"],
}


def _session() -> str | None:
    return os.environ.get("MENTAT_SESSION")


def _agent_slug() -> str:
    return os.environ.get("MENTAT_SLUG", f"agent-{os.getpid()}")


def _session_dir(base: Path, repo: str, session: str) -> Path:
    return base / repo / session


def _log_file(base: Path, repo: str, session: str, agent: str, slug: str) -> Path:
    return _session_dir(base, repo, session) / f"{agent}-{slug}.jsonl"


def _sidecar_file(base: Path, repo: str, session: str, agent: str, slug: str) -> Path:
    return _session_dir(base, repo, session) / ".stderr" / f"{agent}-{slug}.stderr"


def _ensure_log_dir(log_root: Path) -> None:
    log_root.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        log_root.chmod(0o700)


def _reject(base: Path, repo: str, session: str, agent: str, slug: str, event: str, reason: str) -> None:
    sc = _sidecar_file(base, repo, session, agent, slug)
    sc.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    sc.parent.parent.parent.mkdir(parents=True, exist_ok=True)
    with sc.open("a") as f:
        f.write(f"{ts}  reject event={event} reason={reason}\n")
    print(f"mentat-log: reject event={event} reason={reason} (sidecar={sc})", file=sys.stderr)


def _validate_row(row: dict[str, object]) -> list[str]:
    """Return list of validation errors for a single row dict."""
    errors: list[str] = []
    for field in ("ts", "agent", "session", "event", "payload"):
        if field not in row:
            errors.append(f"missing field: {field}")
    if errors:
        return errors
    event = row["event"]
    if event not in EVENT_CATALOG:
        errors.append(f"unknown event: {event!r}")
        return errors
    required = EVENT_CATALOG[event]
    payload = row.get("payload") or {}
    if not isinstance(payload, dict):
        errors.append("payload must be object")
        return errors
    for f in required:
        if f not in payload:
            errors.append(f"missing required payload field: {f!r} for event {event!r}")
    return errors


def cmd_emit(args: argparse.Namespace) -> int:
    agent = args.agent
    event = args.event
    raw = args.payload

    if event not in EVENT_CATALOG:
        print(f"mentat-log: unknown event {event!r}. Valid: {sorted(EVENT_CATALOG)}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"mentat-log: payload not valid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("mentat-log: payload must be a JSON object", file=sys.stderr)
        return 1

    required = EVENT_CATALOG[event]
    missing = [f for f in required if f not in payload]

    base = _log_root()
    repo = _repo()
    # Last-resort guard: ensure_session (entrypoints) and bind() (emit path) both
    # set MENTAT_SESSION before any emit. If a raw `mentat-log emit` still slips
    # through unkeyed, mint an opaque uuid — never an `orphan-`/pid-derived id
    # that could collide or strand the row.
    session = _session() or _mint_session("mentat-log", "adhoc")
    slug = _agent_slug()

    _ensure_log_dir(base)
    session_dir = _session_dir(base, repo, session)
    session_dir.mkdir(parents=True, exist_ok=True)

    if missing:
        _reject(base, repo, session, agent, slug, event, f"missing-required:{','.join(missing)}")
        return 1

    if event == "chunk.ejected":
        reason = payload.get("reason", "")
        if reason not in _EJECT_REASONS:
            _reject(base, repo, session, agent, slug, event, f"invalid-reason:{reason!r}")
            return 1

    row = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "agent": agent,
        "session": session,
        "event": event,
        "payload": payload,
    }
    log_file = _log_file(base, repo, session, agent, slug)
    with log_file.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"mentat-log: file not found: {path}", file=sys.stderr)
        return 1
    errors_found = False
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"line {lineno}: invalid JSON: {exc}", file=sys.stderr)
            errors_found = True
            continue
        errs = _validate_row(row)
        for err in errs:
            print(f"line {lineno}: {err}", file=sys.stderr)
            errors_found = True
    return 1 if errors_found else 0


def cmd_query(args: argparse.Namespace) -> int:
    base = _log_root()
    repo = _repo()
    session = args.session
    session_dir = _session_dir(base, repo, session)
    if not session_dir.exists():
        print(f"mentat-log: session dir not found: {session_dir}", file=sys.stderr)
        return 1

    for log_file in sorted(session_dir.glob("*.jsonl")):
        for line in log_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if args.event and row.get("event") != args.event:
                continue
            if args.agent and row.get("agent") != args.agent:
                continue
            print(json.dumps(row))
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    import shutil

    base = _log_root()
    repo = _repo()
    try:
        cutoff = datetime.date.fromisoformat(args.before)
    except ValueError:
        print(f"mentat-log: invalid date {args.before!r}, expected YYYY-MM-DD", file=sys.stderr)
        return 1

    repo_dir = base / repo
    if not repo_dir.exists():
        return 0

    pruned = 0
    for session_dir in repo_dir.iterdir():
        if not session_dir.is_dir():
            continue
        mtime = datetime.date.fromtimestamp(session_dir.stat().st_mtime)
        if mtime < cutoff:
            shutil.rmtree(session_dir)
            pruned += 1

    print(f"mentat-log: pruned {pruned} session(s) older than {cutoff}")
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    """Regenerate state.db from the NDJSON log; optionally prune stale dirs first.

    The log is durable and authoritative (ADR-0007); state.db is a throwaway read
    model rebuilt from it (Kleppmann). ``--prune-before`` runs the one-shot sweep
    that reclaims orphan session dirs older than the cutoff before projecting."""
    prune_before = None
    if args.prune_before is not None:
        try:
            prune_before = datetime.date.fromisoformat(args.prune_before)
        except ValueError:
            print(f"mentat-log: invalid date {args.prune_before!r}, expected YYYY-MM-DD", file=sys.stderr)
            return 1

    counts = _state.rebuild(_log_root(), prune_before=prune_before)
    print(f"mentat-log: rebuilt projection — {counts['projected']} session(s) projected, {counts['pruned']} pruned")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-log", description="Mentat audit log tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    emit_p = sub.add_parser("emit", help="Append a JSONL audit row")
    emit_p.add_argument("agent", help="Emitting agent name")
    emit_p.add_argument("event", help="Event name (must be in EVENT_CATALOG)")
    emit_p.add_argument("payload", help="JSON payload string")

    val_p = sub.add_parser("validate", help="Validate a JSONL log file")
    val_p.add_argument("file", help="Path to .jsonl file")

    qry_p = sub.add_parser("query", help="Filter and print log rows")
    qry_p.add_argument("session", help="Session ID")
    qry_p.add_argument("--event", default=None, help="Filter by event name")
    qry_p.add_argument("--agent", default=None, help="Filter by agent name")

    prune_p = sub.add_parser("prune", help="Delete old session dirs")
    prune_p.add_argument("--before", required=True, metavar="YYYY-MM-DD", help="Delete dirs older than this date")

    rebuild_p = sub.add_parser("rebuild-projection", help="Regenerate state.db from the NDJSON log")
    rebuild_p.add_argument(
        "--prune-before",
        default=None,
        metavar="YYYY-MM-DD",
        help="One-shot: prune session dirs older than this date before projecting",
    )

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    dispatch = {
        "emit": cmd_emit,
        "validate": cmd_validate,
        "query": cmd_query,
        "prune": cmd_prune,
        "rebuild-projection": cmd_rebuild,
    }
    sys.exit(dispatch[args.cmd](args))


if __name__ == "__main__":
    main()
