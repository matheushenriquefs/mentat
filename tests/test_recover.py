"""S2: model-driven JIT recovery pass for transient-ejected AFK chunks (ADR-0015).

The recovery engine, unit-tested with its side-effecting primitives injected. A
transient AFK slug within cap → the agent is consulted and its decision applied; a
HITL slug is never respawned; the per-slug attempt count is replayed from the durable
audit log so it survives a resume.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests.conftest import seed_agent_events

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Plan:
    def __init__(self, slug: str, kind: str = "AFK") -> None:
        self.slug = slug
        self.kind = kind
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

    def respawn(plan, attempt, context):
        calls.setdefault("respawn", []).append((plan.slug, attempt))
        return [{"slug": plan.slug, "status": "success"}]

    def reslice(plan, attempt):
        calls.setdefault("reslice", []).append((plan.slug, attempt))
        return [{"slug": f"{plan.slug}-1", "status": "success"}]

    def dead_letter(plan, rationale):
        calls.setdefault("dead_letter", []).append((plan.slug, rationale))

    return dict(teardown=teardown, respawn=respawn, reslice=reslice, dead_letter=dead_letter)


# ── attempt_count: log-replayed, resume-safe ──────────────────────────────────


def _write_recovery_spawn(tmp_path: Path, repo: str, agent_id: str, slug: str) -> None:
    seed_agent_events(
        tmp_path,
        repo,
        agent_id,
        [
            {
                "ts": "2026-07-02T00:00:00+00:00",
                "event": "chunk_started",
                "payload": {
                    "slug": slug,
                    "plan": "p",
                    "harness": "d",
                    "worktree": "w",
                    "trigger": "recovery",
                    "attempt": 1,
                },
            }
        ],
    )


def test_attempt_count_zero_when_no_log(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    assert recover.attempt_count("s1", "a") == 0


def test_attempt_count_replays_recovery_spawns_across_resume(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    _write_recovery_spawn(tmp_path, "repo", "s1", "a")
    _write_recovery_spawn(tmp_path, "repo", "s1", "a")
    _write_recovery_spawn(tmp_path, "repo", "s1", "b")
    assert recover.attempt_count("s1", "a") == 2
    assert recover.attempt_count("s1", "b") == 1


def test_attempt_count_ignores_non_recovery_spawns(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    seed_agent_events(
        tmp_path,
        "repo",
        "s1",
        [
            {
                "event": "chunk_started",
                "payload": {"slug": "a", "plan": "p", "harness": "d", "worktree": "w"},
            },
            {
                "event": "chunk_landed",
                "payload": {"slug": "a", "sha": "x", "holding": "h"},
            },
        ],
    )
    assert recover.attempt_count("s1", "a") == 0


def test_attempt_count_skips_unreadable_log_file(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
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


def test_make_recovery_prompt_includes_context(recover):
    prompt = recover.make_recovery_prompt(
        {"slug": "core", "reason": "worker_died", "attempt": 1, "cap": 2, "progress_note": "## Done\n- x"}
    )
    assert "core" in prompt and "worker_died" in prompt and "## Done" in prompt


def test_build_prompt_alias(recover):
    assert recover.build_prompt({"slug": "a", "progress_note": "note"}) == recover.make_recovery_prompt(
        {"slug": "a", "progress_note": "note"}
    )


def test_distill_falls_back_to_diff_without_transcript(recover, tmp_path):
    note = recover.distill_progress_note(agent_log_dir=tmp_path, diff="the-diff", holding_tip="abc123")
    assert note == "the-diff"


def test_distill_reads_transcript(recover, tmp_path):
    log_dir = tmp_path / "agent"
    log_dir.mkdir()
    (log_dir / "transcript.jsonl").write_text('{"type":"assistant","message":{"content":[{"text":"did X"}]}}\n')
    note = recover.distill_progress_note(
        agent_log_dir=log_dir,
        diff="fallback",
        holding_tip="deadbeef",
        invoke=lambda _p: "## Done\n- implemented X",
    )
    assert "## Done" in note


def test_make_recovery_seed_includes_progress_note(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    seed_agent_events(
        tmp_path,
        "repo",
        "orch-sess",
        [
            {
                "event": "chunk_ejected",
                "payload": {"slug": "core", "reason": "worker_died", "logs_path": str(tmp_path / "agent")},
            }
        ],
    )
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "transcript.jsonl").write_text('{"type":"assistant"}\n')
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(recover, "distill_progress_note", lambda **kw: "## Pending\n- finish tests")
    seed = recover.make_recovery_seed(
        slug="core",
        reason="worker_died",
        worktree=wt,
        holding="main",
        attempt=1,
        cap=2,
        agent_id="orch-sess",
        diff="raw-diff",
    )
    assert seed["progress_note"] == "## Pending\n- finish tests"
    assert seed["seed_summary"] == seed["progress_note"]


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
        agent_id="s1",
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
        agent_id="s1",
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
        agent_id="s1",
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
        plans_by_slug={"ui": _Plan("ui", kind="HITL")},
        holding="hold",
        agent_id="s1",
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
    _write_recovery_spawn(tmp_path, "repo", "s1", "core")
    _write_recovery_spawn(tmp_path, "repo", "s1", "core")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    out = recover.recover(
        {"core"},
        plans_by_slug={"core": _Plan("core")},
        holding="hold",
        agent_id="s1",
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
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        **prim,
    )
    assert calls == {}
    assert out[0]["recovery"] == "unrecoverable"


# ── S3 guardrails: storm cap, budget, escalate rung ───────────────────────────


def test_storm_guard_allows_within_cap(recover):
    clock = [0.0]
    g = recover.StormGuard(2, 60.0, clock=lambda: clock[0])
    assert g.allow()
    g.record()
    assert g.allow()
    g.record()
    assert not g.allow()  # 2 within window → third blocked


def test_storm_guard_window_expiry_reallows(recover):
    clock = [0.0]
    g = recover.StormGuard(1, 10.0, clock=lambda: clock[0])
    g.record()
    assert not g.allow()
    clock[0] = 11.0  # window passed
    assert g.allow()


def test_budget_unlimited_when_none(recover):
    b = recover.Budget(None)
    b.spend(1000)
    assert b.allow(1e9)


def test_budget_blocks_over_total(recover):
    b = recover.Budget(2.0)
    assert b.allow(1.0)
    b.spend(2.0)
    assert not b.allow(1.0)


def test_recovery_max_restarts_config(recover, monkeypatch):
    monkeypatch.setattr(recover._config, "read_config", lambda: {})
    assert recover.recovery_max_restarts() == 3
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_max_restarts": 7})
    assert recover.recovery_max_restarts() == 7


def test_recovery_restart_window_config(recover, monkeypatch):
    monkeypatch.setattr(recover._config, "read_config", lambda: {})
    assert recover.recovery_restart_window() == 60.0
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_restart_window": 30})
    assert recover.recovery_restart_window() == 30.0
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_restart_window": "bad"})
    assert recover.recovery_restart_window() == 60.0


def test_recovery_budget_config(recover, monkeypatch):
    monkeypatch.setattr(recover._config, "read_config", lambda: {})
    assert recover.recovery_budget() is None
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_budget": 100})
    assert recover.recovery_budget() == 100.0
    monkeypatch.setattr(recover._config, "read_config", lambda: {"recovery_budget": "bad"})
    assert recover.recovery_budget() is None


def test_recover_storm_cap_escalates_remaining(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    notes: list = []
    plans = {s: _Plan(s) for s in ("a", "b", "c")}
    # StormGuard that allows exactly one respawn, then blocks → b, c escalated.
    storm = recover.StormGuard(1, 60.0, clock=lambda: 0.0)
    out = recover.recover(
        {"a", "b", "c"},
        plans_by_slug=plans,
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        storm_guard=storm,
        notify=notes.append,
        cap=5,
        **prim,
    )
    assert calls.get("respawn") == [("a", 1)]  # only the first got through
    escalated = {o["slug"] for o in out if o["recovery"] == "dead-lettered"}
    assert escalated == {"b", "c"}
    assert notes  # operator was notified


def test_recover_storm_escalation_skips_non_afk_remaining(recover, monkeypatch, tmp_path):
    """The batch-wide give-up loop dead-letters only AFK remainders — a HITL slug
    in the tail is left for the operator, not dead-lettered (recover.py 338->336)."""
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    notes: list = []
    plans = {s: _Plan(s) for s in ("a", "b", "c")}
    storm = recover.StormGuard(1, 60.0, clock=lambda: 0.0)  # one respawn, then breach
    out = recover.recover(
        {"a", "b", "c"},
        plans_by_slug=plans,
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: s != "c",  # c is HITL — never auto-dead-lettered
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        storm_guard=storm,
        notify=notes.append,
        cap=5,
        **prim,
    )
    assert calls.get("respawn") == [("a", 1)]
    escalated = {o["slug"] for o in out if o["recovery"] == "dead-lettered"}
    assert escalated == {"b"}, "only the AFK remainder is dead-lettered; c is skipped"
    assert not any(o["slug"] == "c" and o["recovery"] == "dead-lettered" for o in out)


def test_recover_budget_exhausted_halts(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    notes: list = []
    plans = {s: _Plan(s) for s in ("a", "b")}
    out = recover.recover(
        {"a", "b"},
        plans_by_slug=plans,
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        budget=recover.Budget(1.0),  # one respawn, then halt
        notify=notes.append,
        cap=5,
        **prim,
    )
    assert calls.get("respawn") == [("a", 1)]
    assert {o["slug"] for o in out if o["recovery"] == "dead-lettered"} == {"b"}
    assert any("budget" in n for n in notes)


def test_recover_abandon_does_not_charge_storm_or_budget(recover, monkeypatch, tmp_path):
    """An abandon (no respawn happens) must not charge the storm counter or budget —
    else it prematurely trips the batch-wide give-up rungs and dead-letters still-
    recoverable siblings."""
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    storm = recover.StormGuard(5, 60.0, clock=lambda: 0.0)
    bud = recover.Budget(10.0)
    recover.recover(
        {"a"},
        plans_by_slug={"a": _Plan("a")},
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "abandon", "rationale": "no"},
        storm_guard=storm,
        budget=bud,
        **prim,
    )
    assert storm._stamps == [], "abandon must not record a storm respawn"
    assert bud.spent == 0.0, "abandon must not spend budget"


def test_recover_retry_charges_storm_and_budget_once(recover, monkeypatch, tmp_path):
    """A retry (an actual respawn) charges the storm counter and budget exactly once."""
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    storm = recover.StormGuard(5, 60.0, clock=lambda: 0.0)
    bud = recover.Budget(10.0)
    recover.recover(
        {"a"},
        plans_by_slug={"a": _Plan("a")},
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        storm_guard=storm,
        budget=bud,
        **prim,
    )
    assert len(storm._stamps) == 1, "one respawn → one storm record"
    assert bud.spent == 1.0, "one respawn → one unit spent"


def test_recover_abandon_notifies(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    notes: list = []
    recover.recover(
        {"a"},
        plans_by_slug={"a": _Plan("a")},
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "abandon", "rationale": "no"},
        notify=notes.append,
        **prim,
    )
    assert any("abandon" in n for n in notes)


def test_recover_attempt_cap_notifies(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    _write_recovery_spawn(tmp_path, "repo", "s1", "a")
    _write_recovery_spawn(tmp_path, "repo", "s1", "a")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    notes: list = []
    recover.recover(
        {"a"},
        plans_by_slug={"a": _Plan("a")},
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        cap=2,
        notify=notes.append,
        **prim,
    )
    assert any("attempt cap" in n for n in notes)


def test_recover_notify_defaults_to_module_notifier(recover, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)
    recover.recover(
        {"a"},
        plans_by_slug={"a": _Plan("a")},
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "abandon", "rationale": "no"},
        **prim,
    )
    assert "ESCALATE" in capsys.readouterr().err


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
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=_ctx_builder,
        decide=lambda ctx: {"action": "retry"},
        **prim,
    )
    assert out[0]["recovery"] == "retry"  # cap defaulted to 1, attempt 1 within cap


@pytest.mark.parametrize("reason", ["preflight_worktree_failed", "container_oom"])
def test_recover_retries_new_transient_reasons(recover, monkeypatch, tmp_path, reason):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(recover, monkeypatch, calls=calls)

    def ctx(plan, attempt, cap):
        return {"slug": plan.slug, "reason": reason, "worktree": f"/wt/{plan.slug}", "attempt": attempt, "cap": cap}

    out = recover.recover(
        {"a"},
        plans_by_slug={"a": _Plan("a")},
        holding="hold",
        agent_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=ctx,
        decide=lambda ctx: {"action": "retry"},
        **prim,
    )
    assert out[0]["recovery"] == "retry"
    assert calls.get("respawn") == [("a", 1)]


def test_eject_reason_for_slug_reads_latest_from_store(recover, monkeypatch, tmp_path):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    seed_agent_events(
        tmp_path,
        "repo",
        "s1",
        [
            {
                "event": "chunk_ejected",
                "payload": {"slug": "a", "reason": "container_oom", "where": "/wt"},
            }
        ],
    )
    assert recover.eject_reason_for_slug("s1", "a") == "container_oom"
    assert recover.eject_reason_for_slug("s1", "missing") == "unknown"
