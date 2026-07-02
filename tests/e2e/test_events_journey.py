"""E2E: the ADR-0007 envelope emitter — spawn, bind, and payload builders.

Drives ``lib.events`` without touching the real log subprocess: ``_spawn`` is
exercised over a monkeypatched ``subprocess.run`` for success / failure / empty-
stderr, ``bind`` is driven over a monkeypatched ``_spawn`` to prove the terminal-
event RuntimeError contract vs. the swallow-on-non-terminal path, and the two
payload builders (``spawned_payload`` / ``ejected_payload``) are asserted shape-
exact including every optional-field branch.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from lib import events

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── _spawn ───────────────────────────────────────────────────────────────────


def test_spawn_success_returns_true_and_is_quiet(monkeypatch, capsys):
    monkeypatch.setattr(events.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr=""))
    assert events._spawn("mentat-x", "chunk.started", {"slug": "a"}) is True
    assert capsys.readouterr().err == ""


def test_spawn_failure_returns_false_and_prints_stderr_tail(monkeypatch, capsys):
    monkeypatch.setattr(events.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="boom\ndetail"))
    assert events._spawn("mentat-x", "chunk.started", {"slug": "a"}) is False
    err = capsys.readouterr().err
    assert "emit 'chunk.started' failed rc=1" in err
    assert "detail" in err


def test_spawn_failure_with_empty_stderr_uses_no_stderr_placeholder(monkeypatch, capsys):
    monkeypatch.setattr(events.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2, stderr=""))
    assert events._spawn("mentat-x", "chunk.started", {"slug": "a"}) is False
    assert "(no stderr)" in capsys.readouterr().err


# ── bind ─────────────────────────────────────────────────────────────────────


def test_bind_non_terminal_event_swallows_failed_spawn(monkeypatch):
    monkeypatch.setattr(events, "_spawn", lambda *a, **k: False)
    emit = events.bind("mentat-x")
    # Non-terminal event with a failing spawn must NOT raise.
    emit("chunk.started", {"slug": "a"})


def test_bind_terminal_event_raises_on_failed_spawn(monkeypatch):
    monkeypatch.setattr(events, "_spawn", lambda *a, **k: False)
    emit = events.bind("mentat-x")
    with pytest.raises(RuntimeError):
        emit("chunk.landed", {"slug": "a"})


def test_bind_terminal_event_succeeds_when_spawn_ok(monkeypatch):
    monkeypatch.setattr(events, "_spawn", lambda *a, **k: True)
    emit = events.bind("mentat-x")
    # Successful spawn on a terminal event → no raise.
    emit("chunk.landed", {"slug": "a"})


# ── spawned_payload ──────────────────────────────────────────────────────────


def test_spawned_payload_is_exact_shape():
    assert events.spawned_payload("slug-a", "plan-a", harness="claude_code", worktree="/wt") == {
        "slug": "slug-a",
        "plan": "plan-a",
        "harness": "claude_code",
        "worktree": "/wt",
    }


# ── ejected_payload ──────────────────────────────────────────────────────────


def test_ejected_payload_base_shape_omits_all_optionals():
    assert events.ejected_payload("slug-a", "gate-failed", "land") == {
        "slug": "slug-a",
        "reason": "gate-failed",
        "where": "land",
    }


def test_ejected_payload_includes_every_optional_when_set():
    payload = events.ejected_payload(
        "slug-a",
        "gate-failed",
        "land",
        logs_path="/logs",
        preflight_exit=69,
        upstream="up-slug",
        summary="blocker text",
    )
    assert payload == {
        "slug": "slug-a",
        "reason": "gate-failed",
        "where": "land",
        "logs_path": "/logs",
        "preflight_exit": 69,
        "upstream": "up-slug",
        "summary": "blocker text",
    }
