"""E2E gap-closer: mentat-log validate/query/prune/emit arms the main test skips.

Companion to ``test_log_journey.py``. Drives ``_validate_row`` directly for the
missing-field and non-object-payload rejections, a valid chunk.ejected emit
(the reason-accepted arm), blank/garbage-line skips in validate and query, the
query --agent mismatch filter, prune's non-dir skip and its keep-recent arm,
and ``main()`` over a patched argv. In-process — the emit's own log subprocess
writes real artifacts but the module-under-test is driven in this process.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PY = REPO_ROOT / ".agents/skills/mentat-log/scripts/log.py"


def _log():
    return load_script(LOG_PY, "e2e_log_gaps")


def _log_env(monkeypatch, log_root: Path, repo: str, session: str) -> None:
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)
    monkeypatch.setenv("MENTAT_SESSION", session)


# ── _validate_row: missing top-level fields (90, 92) ──────────────────────────


def test_validate_row_flags_missing_top_level_fields():
    log = _log()
    errs = log._validate_row({})
    assert any("missing field: event" in e for e in errs)
    # Returns early on missing fields — no payload-level errors mixed in.
    assert all(e.startswith("missing field:") for e in errs)


# ── _validate_row: payload present but not an object (100-101) ─────────────────


def test_validate_row_flags_non_object_payload():
    log = _log()
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": ["not", "an", "object"]}
    errs = log._validate_row(row)
    assert errs == ["payload must be object"]


# ── cmd_emit: chunk.ejected with a VALID reason writes the row (148->152) ──────


def test_emit_valid_eject_reason_is_written(tmp_path, monkeypatch):
    log = _log()
    log_root = tmp_path / "logs"
    repo, session = "logrepo", "orchestrate-eject-ok"
    _log_env(monkeypatch, log_root, repo, session)

    args = argparse.Namespace(
        agent="mentat-orchestrate",
        event="chunk.ejected",
        payload=json.dumps({"slug": "s", "reason": "gate-failed", "where": "land"}),
    )
    assert log.cmd_emit(args) == 0

    jsonls = list((log_root / repo / session).glob("*.jsonl"))
    assert jsonls, "a valid-reason eject must be written"
    rows = [json.loads(ln) for ln in jsonls[0].read_text().splitlines() if ln.strip()]
    assert rows[0]["event"] == "chunk.ejected"
    assert rows[0]["payload"]["reason"] == "gate-failed"


# ── cmd_validate: blank lines are skipped (174) ───────────────────────────────


def test_validate_skips_blank_lines(tmp_path, monkeypatch):
    log = _log()
    _log_env(monkeypatch, tmp_path / "logs", "r", "s")
    good = tmp_path / "good.jsonl"
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {"path": "p.md"}}
    # Interior + trailing blank lines around one valid row.
    good.write_text("\n" + json.dumps(row) + "\n\n")
    assert log.cmd_validate(argparse.Namespace(file=str(good))) == 0


# ── cmd_query: blank-line skip, garbage-line skip, --agent mismatch (201,204-205,209) ─


def test_query_skips_blanks_garbage_and_filters_by_agent(tmp_path, monkeypatch, capsys):
    log = _log()
    log_root = tmp_path / "logs"
    repo, session = "qrepo", "orchestrate-query-gaps"
    _log_env(monkeypatch, log_root, repo, session)

    sd = log_root / repo / session
    sd.mkdir(parents=True)
    want = {"ts": "t1", "agent": "keep", "session": session, "event": "plan.started", "payload": {"path": "a"}}
    drop = {"ts": "t2", "agent": "other", "session": session, "event": "plan.started", "payload": {"path": "b"}}
    # Blank line (201), then a garbage non-JSON line (204-205), then two valid
    # rows by different agents so the --agent filter drops one (209).
    (sd / "log.jsonl").write_text("\n" + "this is not json\n" + json.dumps(want) + "\n" + json.dumps(drop) + "\n")

    capsys.readouterr()
    rc = log.cmd_query(argparse.Namespace(session=session, event=None, agent="keep"))
    assert rc == 0
    out_rows = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert [r["agent"] for r in out_rows] == ["keep"], "only the matching-agent row prints"


# ── cmd_prune: non-dir entry skipped; a recent dir is kept (232, 234->230) ─────


def test_prune_skips_non_dirs_and_keeps_recent_sessions(tmp_path, monkeypatch, capsys):
    log = _log()
    log_root = tmp_path / "logs"
    repo = "prunerepo"
    _log_env(monkeypatch, log_root, repo, "unused")

    repo_dir = log_root / repo
    repo_dir.mkdir(parents=True)
    # A stray file (not a session dir) → the is_dir() guard skips it (232).
    (repo_dir / "stray.txt").write_text("junk\n")
    # A fresh session dir whose mtime is well after the cutoff → kept (234->230).
    fresh = repo_dir / "orchestrate-fresh-1"
    fresh.mkdir()
    (fresh / "log.jsonl").write_text("{}\n")

    capsys.readouterr()
    rc = log.cmd_prune(argparse.Namespace(before="2000-01-01"))
    assert rc == 0
    assert "pruned 0 session" in capsys.readouterr().out
    assert fresh.exists(), "a session newer than the cutoff is retained"


# ── main(): the real entrypoint over a patched argv (266-269) ─────────────────


def test_main_dispatches_prune_over_argv(tmp_path, monkeypatch, capsys):
    log = _log()
    log_root = tmp_path / "logs"
    _log_env(monkeypatch, log_root, "mainrepo", "unused")
    # No repo dir yet → prune is a clean no-op, but it exercises main()'s
    # build_parser → parse_args → dispatch → sys.exit(rc) wiring.
    monkeypatch.setattr("sys.argv", ["mentat-log", "prune", "--before", "2020-01-01"])
    with pytest.raises(SystemExit) as exc:
        log.main()
    assert exc.value.code == 0
