"""S2: model-driven JIT recovery pass for transient-ejected AFK chunks (ADR-0015).

The recovery engine, unit-tested with its side-effecting primitives injected. A
transient AFK slug within cap → the agent is consulted and its decision applied; a
HITL slug is never respawned; the per-slug attempt count is replayed from the durable
audit log so it survives a resume.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Plan:
    def __init__(self, slug: str, class_: str = "AFK") -> None:
        self.slug = slug
        self.class_ = class_
        self.path = Path(f"/tmp/{slug}.md")


@pytest.fixture
def recover(monkeypatch):
    mod = _load("recover")
    monkeypatch.setattr(mod, "_emit_event", lambda *a, **k: None)
    return mod


def _ctx_builder(plan, attempt, cap):
    return {"slug": plan.slug, "attempt": attempt, "cap": cap, "worktree": f"/wt/{plan.slug}"}


def _wire(recover, monkeypatch, *, calls):
    """Record every primitive invocation into `calls`."""

    def teardown(slug):
        calls.setdefault("teardown", []).append(slug)

    def respawn(plan, attempt):
        calls.setdefault("respawn", []).append((plan.slug, attempt))
        return [{"slug": plan.slug, "status": "success"}]

    def reslice(plan, attempt):
        calls.setdefault("reslice", []).append((plan.slug, attempt))
        return [{"slug": f"{plan.slug}-1", "status": "success"}]

    def dead_letter(plan, rationale):
        calls.setdefault("dead_letter", []).append((plan.slug, rationale))

    return dict(teardown=teardown, respawn=respawn, reslice=reslice, dead_letter=dead_letter)


# ── attempt_count: log-replayed, resume-safe ──────────────────────────────────


def _write_recovery_spawn(log_dir: Path, slug: str) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": "2026-07-02T00:00:00+00:00",
        "agent": "mentat-orchestrate",
        "session": "s1",
        "event": "chunk.spawned",
        "payload": {"slug": slug, "plan": "p", "harness": "d", "worktree": "w", "trigger": "recovery", "attempt": 1},
    }
    with (log_dir / "a-x.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


def test_attempt_count_zero_when_no_log(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    assert recover.attempt_count("s1", "a") == 0


def test_attempt_count_replays_recovery_spawns_across_resume(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    log_dir = tmp_path / "repo" / "s1"
    _write_recovery_spawn(log_dir, "a")
    _write_recovery_spawn(log_dir, "a")
    _write_recovery_spawn(log_dir, "b")  # different slug — not counted
    # A "resume" is just a fresh read of the durable log.
    assert recover.attempt_count("s1", "a") == 2
    assert recover.attempt_count("s1", "b") == 1


def test_attempt_count_ignores_non_recovery_spawns(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    log_dir = tmp_path / "repo" / "s1"
    log_dir.mkdir(parents=True)
    plain = {"event": "chunk.spawned", "payload": {"slug": "a", "plan": "p", "harness": "d", "worktree": "w"}}
    other = {"event": "chunk.landed", "payload": {"slug": "a", "sha": "x", "holding": "h"}}
    (log_dir / "a.jsonl").write_text(json.dumps(plain) + "\n" + json.dumps(other) + "\n\nnot-json\n")
    assert recover.attempt_count("s1", "a") == 0


def test_attempt_count_skips_unreadable_log_file(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    log_dir = tmp_path / "repo" / "s1"
    log_dir.mkdir(parents=True)
    # A directory named like a log file → read_text raises OSError, must be skipped.
    (log_dir / "d.jsonl").mkdir()
    assert recover.attempt_count("s1", "a") == 0


# ── decision parsing ──────────────────────────────────────────────────────────


def test_parse_decision_valid_retry(recover):
    assert recover._parse_decision('{"action": "retry", "rationale": "env blip"}') == {
        "action": "retry",
        "rationale": "env blip",
    }


def test_parse_decision_chatty_reply_extracted(recover):
    raw = 'Here is my decision:\n{"action": "reslice", "rationale": "too big"}\nThanks!'
    assert recover._parse_decision(raw)["action"] == "reslice"


def test_parse_decision_unparseable_degrades_to_abandon(recover):
    assert recover._parse_decision("not json at all")["action"] == "abandon"


def test_parse_decision_unrecognized_action_degrades_to_abandon(recover):
    assert recover._parse_decision('{"action": "explode"}')["action"] == "abandon"


def test_parse_decision_non_object_degrades_to_abandon(recover):
    assert recover._parse_decision("[1, 2, 3]")["action"] == "abandon"


def test_build_prompt_includes_context(recover):
    prompt = recover.build_prompt({"slug": "core", "reason": "worker-died", "attempt": 1, "cap": 2})
    assert "core" in prompt and "worker-died" in prompt


def test_decide_uses_injected_invoke(recover):
    decision = recover.decide({"slug": "a"}, invoke=lambda _p: '{"action": "retry", "rationale": "x"}')
    assert decision == {"action": "retry", "rationale": "x"}


# ── _invoke_claude subprocess seam ────────────────────────────────────────────


def test_invoke_claude_returns_stdout_on_success(recover, monkeypatch):
    class _R:
        returncode = 0
        stdout = '{"action": "retry"}'

    monkeypatch.setattr(recover.subprocess, "run", lambda *a, **k: _R())
    assert recover._invoke_claude("p") == '{"action": "retry"}'


def test_invoke_claude_empty_on_nonzero(recover, monkeypatch):
    class _R:
        returncode = 1
        stdout = "boom"

    monkeypatch.setattr(recover.subprocess, "run", lambda *a, **k: _R())
    assert recover._invoke_claude("p") == ""


def test_invoke_claude_empty_on_oserror(recover, monkeypatch):
    def _boom(*a, **k):
        raise OSError("no claude")

    monkeypatch.setattr(recover.subprocess, "run", _boom)
    assert recover._invoke_claude("p") == ""


# ── recovery_attempts config ──────────────────────────────────────────────────


def test_recovery_attempts_default(recover, monkeypatch):
    monkeypatch.setattr(recover._config, "read_config", lambda: {})
    assert recover.recovery_attempts() == 2


def test_recovery_attempts_reads_config(recover, monkeypatch):
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_attempts": 5})
    assert recover.recovery_attempts() == 5


def test_recovery_attempts_bad_value_falls_back(recover, monkeypatch):
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_attempts": "nope"})
    assert recover.recovery_attempts() == 2


# ── recover() orchestration ───────────────────────────────────────────────────


def test_recover_retry_invokes_agent_and_respawns(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    plan = _Plan("core")
    seen_ctx: dict = {}

    def fake_decide(ctx):
        seen_ctx.update(ctx)
        return {"action": "retry", "rationale": "env"}

    out = recover.recover(
        {"core"},
        plans_by_slug={"core": plan},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=fake_decide,
        backoff=lambda i: calls.setdefault("backoff", []).append(i),
        cap=2,
        **prim,
    )

    assert seen_ctx["slug"] == "core"  # agent was consulted with the failure context
    assert calls["teardown"] == ["core"]
    assert calls["respawn"] == [("core", 1)]
    assert "reslice" not in calls
    assert calls["backoff"] == [0]
    assert out[0]["recovery"] == "retry" and out[0]["attempt"] == 1


def test_recover_reslice_calls_reslice(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"core"},
        plans_by_slug={"core": _Plan("core")},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "reslice", "rationale": "big"},
        **prim,
    )
    assert calls["reslice"] == [("core", 1)]
    assert "respawn" not in calls
    assert out[0]["recovery"] == "reslice"


def test_recover_abandon_dead_letters_without_respawn(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"core"},
        plans_by_slug={"core": _Plan("core")},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "abandon", "rationale": "hopeless"},
        **prim,
    )
    assert calls["dead_letter"] == [("core", "hopeless")]
    assert "respawn" not in calls and "reslice" not in calls
    assert out[0]["recovery"] == "abandon"


def test_recover_never_respawns_hitl(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"ui"},
        plans_by_slug={"ui": _Plan("ui", class_="HITL")},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: False,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        **prim,
    )
    assert calls == {}  # no teardown, no respawn, no decision applied
    assert out[0]["recovery"] == "skipped-hitl"


def test_recover_cap_exhausted_dead_letters(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    _write_recovery_spawn(tmp_path / "repo" / "s1", "core")
    _write_recovery_spawn(tmp_path / "repo" / "s1", "core")  # already 2 prior attempts
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"core"},
        plans_by_slug={"core": _Plan("core")},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        cap=2,
        **prim,
    )
    assert calls.get("dead_letter") == [("core", "recovery attempt cap (2) exhausted")]
    assert "respawn" not in calls
    assert out[0]["recovery"] == "dead-lettered"


def test_recover_unknown_slug_is_unrecoverable(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"ghost"},
        plans_by_slug={},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        **prim,
    )
    assert calls == {}
    assert out[0]["recovery"] == "unrecoverable"


def test_recover_default_cap_from_config(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setattr(recover, "recovery_attempts", lambda: 1)
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"core"},
        plans_by_slug={"core": _Plan("core")},
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        **prim,
    )
    assert out[0]["recovery"] == "retry"  # cap defaulted to 1, attempt 1 within cap
