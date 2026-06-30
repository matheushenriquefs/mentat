"""E2E: the track journey over a real ~/.mentat/logs tree (guards the motivating bug).

The "couldn't track sessions" regression was a reader invoked outside the writer's
cwd scanning an empty log dir and showing nothing. This is its real-subprocess twin:
seed a live + an idle + a stale session under a temp log root, run the actual
``mentat-session`` CLI non-interactively (``track --all`` one-shot path and ``list``),
and assert every seeded session surfaces with the status its tail rows imply. If the
tracker ever stops finding seeded sessions again, this test goes red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SESSION_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-session/scripts/session.py"

# Statuses are pulled from each session's newest jsonl tail (sessions.derive_status):
# a terminal audit event → idle, a non-terminal tail that is fresh → working, the
# same tail gone stale (no activity past STALE_SECS=300) → "?".
_STALE_AGE = 600  # seconds older than STALE_SECS so the live tail reads as crashed


def _write_jsonl(path: Path, rows: list[dict], *, age: float = 0.0) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    if age:
        old = time.time() - age
        os.utime(path, (old, old))


def _seed_tree(log_root: Path, repo: str) -> Path:
    """A repo log dir holding one working, one idle, and one stale session."""
    repo_dir = log_root / repo
    repo_dir.mkdir(parents=True)

    # working: a fresh harness stream row (no `event` key), non-terminal tail.
    (repo_dir / "live-sess").mkdir()
    _write_jsonl(
        repo_dir / "live-sess" / "session.jsonl",
        [{"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking"}]}}],
    )

    # idle: a terminal audit event wins regardless of freshness.
    (repo_dir / "idle-sess").mkdir()
    _write_jsonl(
        repo_dir / "idle-sess" / "events.jsonl",
        [{"ts": "2026-06-30T00:00:00Z", "event": "plan.succeeded", "payload": {}}],
    )

    # stale: a non-terminal tail backdated past STALE_SECS reads as crashed ("?").
    (repo_dir / "stale-sess").mkdir()
    _write_jsonl(
        repo_dir / "stale-sess" / "session.jsonl",
        [{"type": "assistant", "message": {"content": [{"type": "text", "text": "mid-flight"}]}}],
        age=_STALE_AGE,
    )
    return repo_dir


def _run(args: list[str], log_root: Path, repo: str) -> str:
    """Run the mentat-session CLI non-interactively (stdin not a tty → one-shot path)."""
    env = {**os.environ, "MENTAT_LOG_PATH": str(log_root), "MENTAT_REPO": repo}
    proc = subprocess.run(
        [sys.executable, str(SESSION_PY), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def test_track_all_lists_every_seeded_session(tmp_path):
    repo = "trackrepo"
    log_root = tmp_path / "logs"
    _seed_tree(log_root, repo)

    out = _run(["track", "--all"], log_root, repo)

    # Every seeded session surfaces with the status its tail implies.
    for session, status in (("live-sess", "working"), ("idle-sess", "idle"), ("stale-sess", "?")):
        line = next((ln for ln in out.splitlines() if session in ln), None)
        assert line is not None, f"{session} missing from track --all output:\n{out}"
        assert status in line, f"{session} wrong status (want {status!r}):\n{line!r}"


def test_list_lists_every_seeded_session(tmp_path):
    repo = "trackrepo"
    log_root = tmp_path / "logs"
    _seed_tree(log_root, repo)

    out = _run(["list"], log_root, repo)

    for session, status in (("live-sess", "working"), ("idle-sess", "idle"), ("stale-sess", "?")):
        line = next((ln for ln in out.splitlines() if session in ln), None)
        assert line is not None, f"{session} missing from list output:\n{out}"
        assert status in line, f"{session} wrong status (want {status!r}):\n{line!r}"
