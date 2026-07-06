"""E2E gap-closer: mentat-log validate/list/prune/emit arms the main test skips."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tests.conftest import agent_events, load_script, seed_agent_events

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PY = REPO_ROOT / ".agents/skills/mentat-log/scripts/log.py"


def _log():
    return load_script(LOG_PY, "e2e_log_gaps")


def _log_env(monkeypatch, log_root: Path, repo: str, agent: str) -> None:
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)
    monkeypatch.setenv("MENTAT_AGENT", agent)
    monkeypatch.setenv("MENTAT_AGENT", agent)


def test_validate_row_flags_missing_top_level_fields():
    log = _log()
    errs = log._validate_row({})
    assert any("missing field: event" in e for e in errs)
    assert all(e.startswith("missing field:") for e in errs)


def test_validate_row_flags_non_object_payload():
    log = _log()
    row = {"ts": "t", "agent": "a", "agent_id": "s", "event": "chunk_started", "payload": ["not", "an", "object"]}
    errs = log._validate_row(row)
    assert errs == ["payload must be object"]


def test_emit_valid_eject_reason_is_written(tmp_path, monkeypatch):
    log = _log()
    log_root = tmp_path / "logs"
    repo, agent = "logrepo", "orchestrate-eject-ok"
    _log_env(monkeypatch, log_root, repo, agent)

    args = argparse.Namespace(
        agent="mentat-orchestrate",
        event="chunk_ejected",
        payload=json.dumps({"slug": "s", "reason": "gate_failed", "where": "land"}),
    )
    assert log.cmd_emit(args) == 0

    rows = agent_events(agent)
    assert rows[0]["event"] == "chunk_ejected"
    assert rows[0]["payload"]["reason"] == "gate_failed"


def test_validate_skips_blank_lines(tmp_path, monkeypatch):
    log = _log()
    _log_env(monkeypatch, tmp_path / "logs", "r", "s")
    good = tmp_path / "good.jsonl"
    row = {
        "ts": "t",
        "agent": "a",
        "agent_id": "s",
        "event": "chunk_started",
        "payload": {"slug": "x", "plan": "p.md", "harness": "default", "worktree": "/wt"},
    }
    good.write_text("\n" + json.dumps(row) + "\n\n")
    assert log.cmd_validate(argparse.Namespace(file=str(good))) == 0


def test_query_skips_blanks_garbage_and_filters_by_agent(tmp_path, monkeypatch, capsys):
    log = _log()
    log_root = tmp_path / "logs"
    repo, agent = "qrepo", "orchestrate-query-gaps"
    _log_env(monkeypatch, log_root, repo, agent)
    (log_root / repo / agent).mkdir(parents=True)

    seed_agent_events(
        tmp_path,
        repo,
        agent,
        [
            {
                "ts": "t1",
                "event": "chunk_started",
                "payload": {"slug": "a", "plan": "a.md", "harness": "default", "worktree": "/wt"},
            }
        ],
        harness="keep",
    )
    seed_agent_events(
        tmp_path,
        repo,
        "other-agent",
        [
            {
                "ts": "t2",
                "event": "chunk_started",
                "payload": {"slug": "b", "plan": "b.md", "harness": "default", "worktree": "/wt"},
            }
        ],
        harness="other",
    )
    (log_root / repo / "other-agent").mkdir(parents=True, exist_ok=True)

    capsys.readouterr()
    rc = log.cmd_list(argparse.Namespace(agent_id=agent, event=None, agent="keep", format="jsonl"))
    assert rc == 0
    out_rows = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert [r["agent"] for r in out_rows] == ["keep"]


def test_prune_skips_non_dirs_and_keeps_recent_sessions(tmp_path, monkeypatch, capsys):
    log = _log()
    log_root = tmp_path / "logs"
    repo = "prunerepo"
    _log_env(monkeypatch, log_root, repo, "unused")

    repo_dir = log_root / repo
    repo_dir.mkdir(parents=True)
    (repo_dir / "stray.txt").write_text("junk\n")
    fresh = repo_dir / "orchestrate-fresh-1"
    fresh.mkdir()

    capsys.readouterr()
    rc = log.cmd_prune(argparse.Namespace(before="2000-01-01"))
    assert rc == 0
    assert "pruned 0 agent" in capsys.readouterr().out
    assert fresh.exists(), "a agent newer than the cutoff is retained"


def test_main_dispatches_prune_over_argv(tmp_path, monkeypatch, capsys):
    log = _log()
    log_root = tmp_path / "logs"
    _log_env(monkeypatch, log_root, "mainrepo", "unused")
    monkeypatch.setattr("sys.argv", ["mentat-log", "prune", "--before", "2020-01-01"])
    with pytest.raises(SystemExit) as exc:
        log.main()
    assert exc.value.code == 0
