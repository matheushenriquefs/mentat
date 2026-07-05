"""E2E: the mentat-log emit → validate → query → prune lifecycle, driven in-process.

Drives the actual ``log.py`` CLI over a temp log root by parsing real argv and calling
``main()`` (the same entry the shell hits), so the whole dispatch runs for real: emit a
spawn then a landing, validate the resulting jsonl, query it back (unfiltered and filtered
by event/agent), then prune the whole session dir by date. Every step reads and writes
real audit artifacts. In-process (not a subprocess) so the run is measured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

LOG_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-log/scripts/log.py"


def _log_env(monkeypatch, log_root: Path, repo: str, session: str) -> None:
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)
    monkeypatch.setenv("MENTAT_SESSION", session)


def _dispatch(log, argv: list[str]) -> int:
    """Run one log.py subcommand through its real argparse dispatch, returning rc."""
    args = log.build_parser().parse_args(argv)
    return {"emit": log.cmd_emit, "validate": log.cmd_validate, "query": log.cmd_query, "prune": log.cmd_prune}[
        args.cmd
    ](args)


def test_log_emit_validate_query_prune_lifecycle(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_lifecycle")
    log_root = tmp_path / "logs"
    repo, session = "logrepo", "orchestrate-main-1"
    _log_env(monkeypatch, log_root, repo, session)

    # emit: a spawn then a landing — two real audit rows under one session.
    assert (
        _dispatch(
            log,
            [
                "emit",
                "mentat-orchestrate",
                "chunk.spawned",
                json.dumps({"slug": "s1", "plan": "s1.md", "harness": "claude-code", "worktree": "/tmp/wt"}),
            ],
        )
        == 0
    )
    assert (
        _dispatch(
            log,
            [
                "emit",
                "mentat-orchestrate",
                "chunk.landed",
                json.dumps({"slug": "s1", "sha": "cafe", "holding": "main"}),
            ],
        )
        == 0
    )

    session_dir = log_root / repo / session
    jsonls = list(session_dir.glob("*.jsonl"))
    assert jsonls, "emit must write a jsonl into the session dir"

    # validate: the freshly-written log passes.
    assert _dispatch(log, ["validate", str(jsonls[0])]) == 0

    # query: both events come back unfiltered.
    capsys.readouterr()
    assert _dispatch(log, ["query", session]) == 0
    events = [json.loads(ln)["event"] for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert events == ["chunk.spawned", "chunk.landed"]

    # query --event: filter to just the landing.
    assert _dispatch(log, ["query", session, "--event", "chunk.landed"]) == 0
    rows = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert [r["event"] for r in rows] == ["chunk.landed"]
    assert rows[0]["payload"]["sha"] == "cafe"

    # query --agent: filter by emitting agent.
    assert _dispatch(log, ["query", session, "--agent", "mentat-orchestrate"]) == 0
    assert len([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]) == 2

    # prune: a cutoff after the session's mtime removes it.
    assert _dispatch(log, ["prune", "--before", "2999-01-01"]) == 0
    assert "pruned 1 session" in capsys.readouterr().out
    assert not session_dir.exists(), "prune must remove the aged session dir"


def test_log_emit_unknown_event_is_rejected(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_unknown")
    _log_env(monkeypatch, tmp_path / "logs", "logrepo", "s")
    rc = _dispatch(log, ["emit", "a", "not.an.event", "{}"])
    assert rc == 1
    assert "unknown event" in capsys.readouterr().err


def test_log_emit_rejects_missing_payload_field(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_missing")
    log_root = tmp_path / "logs"
    repo, session = "logrepo", "orchestrate-main-2"
    _log_env(monkeypatch, log_root, repo, session)

    # chunk.landed requires sha + holding; omit them → reject with a sidecar.
    rc = _dispatch(log, ["emit", "mentat-orchestrate", "chunk.landed", json.dumps({"slug": "s1"})])
    assert rc == 1
    assert "reject" in capsys.readouterr().err

    sidecars = list((log_root / repo / session / ".stderr").glob("*.stderr"))
    assert sidecars, "a rejected emit must leave a sidecar"
    assert "missing-required" in sidecars[0].read_text()


def test_log_emit_rejects_invalid_eject_reason(tmp_path, monkeypatch):
    log = load_script(LOG_PY, "e2e_log_reason")
    _log_env(monkeypatch, tmp_path / "logs", "logrepo", "orchestrate-main-3")
    rc = _dispatch(
        log,
        [
            "emit",
            "mentat-orchestrate",
            "chunk.ejected",
            json.dumps({"slug": "s", "reason": "made-up", "where": "land"}),
        ],
    )
    assert rc == 1


def test_log_emit_bad_json_payload(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_badjson")
    _log_env(monkeypatch, tmp_path / "logs", "logrepo", "s")
    rc = _dispatch(log, ["emit", "a", "plan.started", "{not json"])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_log_emit_non_object_payload(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_nonobj")
    _log_env(monkeypatch, tmp_path / "logs", "logrepo", "s")
    rc = _dispatch(log, ["emit", "a", "plan.started", "[1, 2]"])
    assert rc == 1
    assert "must be a JSON object" in capsys.readouterr().err


def test_log_validate_flags_bad_rows(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_validate")
    _log_env(monkeypatch, tmp_path / "logs", "r", "s")
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        json.dumps({"ts": "t", "agent": "a", "session": "s", "event": "chunk.landed", "payload": {"slug": "x"}})
        + "\nnot json\n"
        + json.dumps({"ts": "t", "agent": "a", "session": "s", "event": "made.up", "payload": {}})
        + "\n"
    )
    rc = _dispatch(log, ["validate", str(bad)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "missing required payload field" in err
    assert "invalid JSON" in err
    assert "unknown event" in err


def test_log_validate_missing_file(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_valmissing")
    _log_env(monkeypatch, tmp_path / "logs", "r", "s")
    rc = _dispatch(log, ["validate", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "file not found" in capsys.readouterr().err


def test_log_query_missing_session(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_qmissing")
    _log_env(monkeypatch, tmp_path / "logs", "r", "s")
    rc = _dispatch(log, ["query", "ghost"])
    assert rc == 1
    assert "session dir not found" in capsys.readouterr().err


def test_log_prune_bad_date_and_missing_repo(tmp_path, monkeypatch, capsys):
    log = load_script(LOG_PY, "e2e_log_prune")
    log_root = tmp_path / "logs"
    _log_env(monkeypatch, log_root, "pruner", "s")

    # invalid date → rc 1.
    assert _dispatch(log, ["prune", "--before", "nope"]) == 1
    assert "invalid date" in capsys.readouterr().err

    # valid date but no repo dir yet → clean no-op rc 0.
    assert _dispatch(log, ["prune", "--before", "2020-01-01"]) == 0
