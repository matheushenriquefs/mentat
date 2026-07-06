#!/usr/bin/env python3
"""mentat-log — emit / validate / list / prune audit events (SQLite canonical)."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import store as _store  # noqa: E402
from lib.events import EJECT_REASONS as _EJECT_REASONS  # noqa: E402
from lib.session import agent_id_from_env as _agent_id_from_env
from lib.session import log_root as _log_root  # noqa: E402
from lib.session import make_agent_id as _make_agent_id
from lib.session import repo_name as _repo

EVENT_CATALOG: dict[str, list[str]] = {
    "slice_scheduled": ["slug"],
    "slice_blocked": ["slug", "blocked_by"],
    "slice_skipped": ["slug", "reason"],
    "agent_started": ["harness"],
    "agent_stopped": ["reason"],
    "agent_reaped": ["reclaimed_bytes"],
    "chunk_started": ["slug", "plan", "harness", "worktree"],
    "chunk_landed": ["slug", "sha", "holding"],
    "chunk_ejected": ["slug", "reason", "where"],
    "chunk_teardown": ["slug", "ok"],
    "gate_evaluated": ["gate", "verdict", "severity", "message"],
    "review_submitted": ["reviewer", "score", "threshold", "verdict"],
    "batch_reviewed": ["session", "summary"],
    "task_created": ["id", "slug"],
    "task_claimed": ["id", "agent", "expires_at"],
    "task_released": ["id"],
    "task_resolved": ["id"],
    "task_canceled": ["id"],
    "test_writable_requested": ["slug", "path"],
}

EVENT_OPTIONAL_FIELDS: dict[str, list[str]] = {
    "chunk_ejected": ["logs_path", "preflight_exit", "upstream", "summary", "killed_by", "timed_out"],
    "chunk_started": ["trigger", "attempt"],
    "agent_reaped": ["containers_removed", "worktrees_removed", "worktrees_gc"],
}


def _session() -> str | None:
    return _agent_id_from_env()


def _agent_slug() -> str:
    return os.environ.get("MENTAT_SLUG", f"agent-{os.getpid()}")


def _session_dir(base: Path, repo: str, session: str) -> Path:
    return base / repo / session.replace("/", "-")


def _sidecar_file(base: Path, repo: str, session: str, agent: str, slug: str) -> Path:
    return _session_dir(base, repo, session) / ".stderr" / f"{agent}-{slug}.stderr"


def _ensure_log_dir(log_root: Path) -> None:
    log_root.mkdir(parents=True, exist_ok=True)
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
    session = _session() or _make_agent_id("mentat-log", "adhoc")
    slug = _agent_slug()

    _ensure_log_dir(base)
    session_dir = _session_dir(base, repo, session)
    session_dir.mkdir(parents=True, exist_ok=True)

    if missing:
        _reject(base, repo, session, agent, slug, event, f"missing-required:{','.join(missing)}")
        return 1

    if event == "chunk_ejected":
        reason = payload.get("reason", "")
        if reason not in _EJECT_REASONS:
            _reject(base, repo, session, agent, slug, event, f"invalid-reason:{reason!r}")
            return 1

    env = dict(os.environ)
    env["MENTAT_AGENT"] = session
    env.setdefault("MENTAT_SESSION", session)
    if not env.get("MENTAT_HARNESS"):
        env["MENTAT_HARNESS"] = agent
    _store.record_emit(env, event, payload)
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


def cmd_list(args: argparse.Namespace) -> int:
    agent_id = args.agent_id
    if not _store.get_agent(agent_id) and not (_log_root() / _repo() / agent_id.replace("/", "-")).is_dir():
        print(f"mentat-log: agent not found: {agent_id}", file=sys.stderr)
        return 1

    for row in _store.list_events(agent_id):
        if args.event and row.get("event") != args.event:
            continue
        if args.agent and row.get("agent") != args.agent:
            continue
        if args.format == "jsonl":
            print(json.dumps(row))
        else:
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-log", description="Mentat audit log tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    emit_p = sub.add_parser("emit", help="Append a canonical audit event")
    emit_p.add_argument("agent", help="Emitting agent name")
    emit_p.add_argument("event", help="Event name (must be in EVENT_CATALOG)")
    emit_p.add_argument("payload", help="JSON payload string")

    val_p = sub.add_parser("validate", help="Validate a JSONL log file")
    val_p.add_argument("file", help="Path to .jsonl file")

    list_p = sub.add_parser("list", help="List audit events from the canonical store")
    list_p.add_argument("agent_id", help="Agent ID")
    list_p.add_argument("--event", default=None, help="Filter by event name")
    list_p.add_argument("--agent", default=None, help="Filter by emitting skill name")
    list_p.add_argument(
        "--format",
        default="jsonl",
        choices=("jsonl",),
        help="Output format (jsonl reproduces the legacy audit trail on stdout)",
    )

    qry_p = sub.add_parser("query", help="Alias for list (deprecated)")
    qry_p.add_argument("agent_id", help="Agent ID")
    qry_p.add_argument("--event", default=None, help="Filter by event name")
    qry_p.add_argument("--agent", default=None, help="Filter by emitting skill name")
    qry_p.add_argument("--format", default="jsonl", choices=("jsonl",))

    prune_p = sub.add_parser("prune", help="Delete old session dirs")
    prune_p.add_argument("--before", required=True, metavar="YYYY-MM-DD", help="Delete dirs older than this date")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "query":
        args.cmd = "list"
    dispatch = {
        "emit": cmd_emit,
        "validate": cmd_validate,
        "list": cmd_list,
        "prune": cmd_prune,
    }
    sys.exit(dispatch[args.cmd](args))


if __name__ == "__main__":
    main()
