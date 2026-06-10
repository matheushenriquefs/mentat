#!/usr/bin/env python3
"""mentat-session — track / doctor / diagnose."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import sessions as _sessions
import doctor as _doctor
import track as _track
import diagnose as _diagnose


def _log_root() -> Path:
    return Path(os.environ.get("MENTAT_LOG_PATH", Path.home() / ".mentat" / "logs"))


def _repo() -> str:
    return os.environ.get("MENTAT_REPO", Path.cwd().name)


def _session_dir(repo: str, session_id: str) -> Path:
    return _log_root() / repo / session_id


def cmd_track(session_id: str | None) -> int:
    repo = _repo()
    repo_dir = _log_root() / repo
    if session_id is None:
        session_id = _sessions.latest_session(repo_dir)
    if session_id is None:
        print("mentat-session: no sessions found", file=sys.stderr)
        return 1
    session_dir = _session_dir(repo, session_id)
    if not session_dir.exists():
        print(f"mentat-session: session dir not found: {session_dir}", file=sys.stderr)
        return 1
    _track.stream(session_dir)
    return 0


def cmd_doctor(session_id: str | None) -> int:
    repo = _repo()
    repo_dir = _log_root() / repo
    if session_id is None:
        session_id = _sessions.latest_session(repo_dir)
    if session_id is None:
        print("mentat-session: no sessions found", file=sys.stderr)
        return 1
    session_dir = _session_dir(repo, session_id)
    if not session_dir.exists():
        print(f"mentat-session: session dir not found: {session_dir}", file=sys.stderr)
        return 1
    diag = _doctor.write_diagnosis(session_dir)
    print(diag.read_text())
    return 0


def cmd_diagnose(session_id: str | None) -> int:
    repo = _repo()
    repo_dir = _log_root() / repo
    if session_id is None:
        session_id = _sessions.latest_session(repo_dir)
    if session_id is None:
        print("mentat-session: no sessions found", file=sys.stderr)
        return 1
    session_dir = _session_dir(repo, session_id)
    _diagnose.run_diagnose(session_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-session")
    sub = p.add_subparsers(dest="cmd", required=True)

    track_p = sub.add_parser("track", help="Stream live events")
    track_p.add_argument("session", nargs="?", default=None)

    doctor_p = sub.add_parser("doctor", help="Build verdict markdown")
    doctor_p.add_argument("session", nargs="?", default=None)

    diag_p = sub.add_parser("diagnose", help="Doctor-first diagnose loop")
    diag_p.add_argument("session", nargs="?", default=None)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "track":
        sys.exit(cmd_track(args.session))
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(args.session))
    elif args.cmd == "diagnose":
        sys.exit(cmd_diagnose(getattr(args, "session", None)))


if __name__ == "__main__":
    main()
