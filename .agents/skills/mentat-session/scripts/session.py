#!/usr/bin/env python3
"""mentat-session — track / doctor / diagnose."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402
from lib.session import log_root as _log_root  # noqa: E402
from lib.session import repo_name as _repo
from lib.session import session_dir as _session_dir_fn

_sessions = load_sibling(__file__, "sessions")
_doctor = load_sibling(__file__, "doctor")
_track = load_sibling(__file__, "track")
_diagnose = load_sibling(__file__, "diagnose")


def _session_dir(repo: str, session_id: str) -> Path:
    """Preserved for test assertions; delegates to the seam."""
    return _log_root() / repo / session_id


def cmd_track(session_id: str | None) -> int:
    repo = _repo()
    repo_dir = _log_root() / repo
    # No session id → live multi-AFK navigator over the whole repo registry.
    if session_id is None:
        return _track.navigate(repo_dir, repo=repo)
    sd = _session_dir_fn(session_id)
    if not sd.exists():
        print(f"mentat-session: session dir not found: {sd}", file=sys.stderr)
        return 1
    _track.view_session(sd)
    return 0


def _resolve_session(session_id: str | None) -> Path | int:
    """Resolve session_id to an existing session dir, or return an exit code."""
    repo = _repo()
    repo_dir = _log_root() / repo
    if session_id is None:
        session_id = _sessions.latest_session(repo_dir)
    if session_id is None:
        print("mentat-session: no sessions found", file=sys.stderr)
        return 1
    sd = _session_dir_fn(session_id)
    if not sd.exists():
        print(f"mentat-session: session dir not found: {sd}", file=sys.stderr)
        return 1
    return sd


def cmd_doctor(session_id: str | None) -> int:
    sd = _resolve_session(session_id)
    if isinstance(sd, int):
        return sd
    diag = _doctor.write_diagnosis(sd)
    print(diag.read_text())
    return 0


def cmd_report(session_id: str | None) -> int:
    """Render the success-side report-back summary (twin of doctor). Operator
    sees what an AFK session implemented without asking the main harness."""
    sd = _resolve_session(session_id)
    if isinstance(sd, int):
        return sd
    summary = _doctor.write_summary(sd)
    print(summary.read_text())
    return 0


def _humanize_age(age_secs: float) -> str:
    secs = int(age_secs)
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


# ASCII status markers (no emoji — shares the tui.py vocabulary).
_STATUS_MARK = {"waiting": "◆", "idle": "✓", "?": "?", "working": "•"}


def cmd_list() -> int:
    """Repo-wide session registry: scan ~/.mentat/logs/<repo>/*, status pulled from
    each session's newest jsonl tail, attention-needing sessions on top."""
    repo = _repo()
    repo_dir = _log_root() / repo
    rows = _sessions.list_sessions(repo_dir)  # returns [] when the dir is absent
    if not rows:
        print(f"mentat-session: no sessions for {repo}")
        return 0
    width = max(len(r["session"]) for r in rows)
    for r in rows:
        mark = _STATUS_MARK.get(r["status"], "?")
        last = r["last_event"] or "-"
        print(f"{mark} {r['status']:<8} {r['session']:<{width}}  {_humanize_age(r['age']):>9}  {last}")
    return 0


def cmd_diagnose(session_id: str | None) -> int:
    sd = _resolve_session(session_id)
    if isinstance(sd, int):
        return sd
    _diagnose.run_diagnose(sd)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-session")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Repo-wide session registry (attention-ordered)")

    track_p = sub.add_parser("track", help="Stream live events")
    track_p.add_argument("session", nargs="?", default=None)

    doctor_p = sub.add_parser("doctor", help="Build verdict markdown")
    doctor_p.add_argument("session", nargs="?", default=None)

    report_p = sub.add_parser("report", help="Render the success-side report-back summary")
    report_p.add_argument("session", nargs="?", default=None)

    diag_p = sub.add_parser("diagnose", help="Doctor-first diagnose loop")
    diag_p.add_argument("session", nargs="?", default=None)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    session = getattr(args, "session", None)
    dispatch = {
        "list": lambda: cmd_list(),
        "track": lambda: cmd_track(session),
        "doctor": lambda: cmd_doctor(session),
        "report": lambda: cmd_report(session),
        "diagnose": lambda: cmd_diagnose(session),
    }
    sys.exit(dispatch[args.cmd]())


if __name__ == "__main__":
    main()
