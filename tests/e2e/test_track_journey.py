"""E2E: the track journey over a real ~/.mentat/logs tree (guards the motivating bug).

The "couldn't track sessions" regression was a reader invoked outside the writer's
cwd scanning an empty log dir and showing nothing. ``track`` now reads the fixed-path
sqlite projection instead of a cwd-relative dir scan, so that failure mode can't recur.
This is its real-subprocess twin: project a live + two terminal sessions into the db,
seed the same tree on disk for ``list`` (still a dir scan), run the actual
``mentat-session`` CLI non-interactively (``track --all`` and ``list``), and assert
every seeded session surfaces. If the tracker ever stops finding sessions again, this
test goes red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import seed_agent_events, subprocess_env

pytestmark = pytest.mark.e2e

_AGENTS = Path(__file__).resolve().parents[2] / ".agents"
if str(_AGENTS) not in sys.path:
    sys.path.insert(0, str(_AGENTS))
from lib import store  # noqa: E402

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
        [{"ts": "2026-06-30T00:00:00Z", "event": "agent_stopped", "payload": {}}],
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
    env = subprocess_env(
        MENTAT_LOG_PATH=str(log_root),
        MENTAT_REPO=repo,
        MENTAT_DB=str(log_root.parent / "mentat.db"),
    )
    proc = subprocess.run(
        [sys.executable, str(SESSION_PY), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def test_track_all_lists_every_seeded_session(tmp_path, monkeypatch):
    repo = "trackrepo"
    log_root = tmp_path / "logs"
    db = tmp_path / "mentat.db"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    for uuid, event in (
        ("live-sess", "chunk_started"),
        ("done-sess", "chunk_landed"),
        ("failed-sess", "chunk_ejected"),
    ):
        env = {"MENTAT_AGENT": uuid, "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
        store.record_emit(env, event, {"slug": "x"})
        (log_root / repo / uuid).mkdir(parents=True)

    out = _run(["track", "--all"], log_root, repo)

    for session, status in (("live-sess", "working"), ("done-sess", "idle"), ("failed-sess", "idle")):
        line = next((ln for ln in out.splitlines() if session in ln), None)
        assert line is not None, f"{session} missing from track --all output:\n{out}"
        assert status in line, f"{session} wrong status (want {status!r}):\n{line!r}"


def test_list_lists_every_seeded_session(tmp_path, monkeypatch):
    repo = "trackrepo"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(tmp_path / "mentat.db"))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)

    stale_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - _STALE_AGE))
    for agent_id, event, status, ts in (
        ("live-sess", "chunk_started", "running", None),
        ("idle-sess", "agent_stopped", "stopped", None),
        ("stale-sess", "chunk_started", "running", stale_ts),
    ):
        row = {"event": event, "payload": {"path": "p", "slug": "x"}}
        if ts:
            row["ts"] = ts
        seed_agent_events(
            tmp_path,
            repo,
            agent_id,
            [row],
            status=status,
        )
        sd = log_root / repo / agent_id
        sd.mkdir(parents=True, exist_ok=True)
        if agent_id == "live-sess":
            (sd / "session.jsonl").write_text(
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "thinking"}]}}) + "\n"
            )
        if agent_id == "stale-sess":
            old = time.time() - _STALE_AGE
            os.utime(sd, (old, old))
            (sd / "session.jsonl").write_text(
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "mid-flight"}]}})
                + "\n"
            )
            os.utime(sd / "session.jsonl", (old, old))

    out = _run(["list"], log_root, repo)

    for session, status in (("live-sess", "working"), ("idle-sess", "idle"), ("stale-sess", "?")):
        line = next((ln for ln in out.splitlines() if session in ln), None)
        assert line is not None, f"{session} missing from list output:\n{out}"
        assert status in line, f"{session} wrong status (want {status!r}):\n{line!r}"
