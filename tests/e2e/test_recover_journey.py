"""E2E journey: the model-driven JIT recovery pass (ADR-0015), end to end.

``recover`` is pure orchestration logic — every side-effecting primitive
(respawn / reslice / dead-letter / teardown / decide / backoff) is injected, so
the whole pass runs in-process against real ``Plan`` graphs and a real on-disk
audit log. This journey drives the config resolvers, the storm/budget guardrails,
the decision parser, and the ``recover`` loop across all of its rungs: retry,
reslice, abandon, per-slug cap, batch-wide storm/budget breach, unknown-slug and
HITL skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script, seed_agent_events

pytestmark = pytest.mark.e2e

RECOVER_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts/recover.py"


def _recover():
    return load_script(RECOVER_PY, "e2e_recover")


class _Plan:
    def __init__(self, slug: str, kind: str = "AFK") -> None:
        self.slug = slug
        self.kind = kind
        self.path = Path(f"/plans/{slug}.md")


def _ctx_builder(plan, attempt, cap):
    return {"slug": plan.slug, "reason": "worker_died", "worktree": "/wt", "attempt": attempt, "cap": cap}


def _wire(mod, *, calls: dict):
    """No-op recovery primitives that record their calls, plus a stubbed emit."""
    calls.setdefault("respawn", [])
    calls.setdefault("reslice", [])
    calls.setdefault("dead", [])
    calls.setdefault("teardown", [])

    def respawn(plan, attempt, context):
        calls["respawn"].append((plan.slug, attempt))
        return [{"slug": plan.slug, "status": "success"}]

    def reslice(plan, attempt):
        calls["reslice"].append((plan.slug, attempt))
        return [{"slug": f"{plan.slug}-a", "status": "success"}]

    def dead_letter(plan, reason):
        calls["dead"].append((plan.slug, reason))

    def teardown(slug):
        calls["teardown"].append(slug)

    mod._emit_event = lambda *a, **k: None
    return {
        "respawn": respawn,
        "reslice": reslice,
        "dead_letter": dead_letter,
        "teardown": teardown,
        "context_builder": _ctx_builder,
    }


# ── config resolvers: happy + malformed-value fallbacks ───────────────────────


def test_config_resolvers_read_values_and_fall_back(monkeypatch):
    m = _recover()
    cfg: dict = {}
    monkeypatch.setattr(m._config, "read_config", lambda: cfg)

    cfg.clear()
    assert m.recovery_attempts() == m.DEFAULT_ATTEMPTS
    assert m.recovery_max_restarts() == m.DEFAULT_MAX_RESTARTS
    assert m.recovery_restart_window() == m.DEFAULT_RESTART_WINDOW
    assert m.recovery_budget() is None

    cfg.update(
        {"recovery_attempts": 5, "recovery_max_restarts": 9, "recovery_restart_window": 30, "recovery_budget": 4}
    )
    assert m.recovery_attempts() == 5
    assert m.recovery_max_restarts() == 9
    assert m.recovery_restart_window() == 30.0
    assert m.recovery_budget() == 4.0

    # Malformed values degrade to the documented defaults, never raise.
    cfg.update(
        {
            "recovery_attempts": "lots",
            "recovery_max_restarts": None,
            "recovery_restart_window": "soon",
            "recovery_budget": "much",
        }
    )
    assert m.recovery_attempts() == m.DEFAULT_ATTEMPTS
    assert m.recovery_max_restarts() == m.DEFAULT_MAX_RESTARTS
    assert m.recovery_restart_window() == m.DEFAULT_RESTART_WINDOW
    assert m.recovery_budget() is None


# ── StormGuard + Budget guardrails ────────────────────────────────────────────


def test_storm_guard_slides_window_and_caps():
    m = _recover()
    clock = {"t": 0.0}
    storm = m.StormGuard(2, 10.0, clock=lambda: clock["t"])
    assert storm.allow() is True
    storm.record()
    storm.record()
    assert storm.allow() is False, "two respawns fill a max=2 window"
    clock["t"] = 20.0  # both stamps age out of the 10s window
    assert storm.allow() is True


def test_budget_gates_and_accrues():
    m = _recover()
    unlimited = m.Budget(None)
    assert unlimited.allow(100.0) is True

    bud = m.Budget(2.0)
    assert bud.allow(1.0) is True
    bud.spend()
    bud.spend()
    assert bud.spent == 2.0
    assert bud.allow(1.0) is False, "a third unit exceeds the total"


# ── attempt_count: replay recovery respawns from the durable log ──────────────


def test_attempt_count_replays_recovery_spawns(monkeypatch, tmp_path):
    m = _recover()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")

    assert m.attempt_count("no-session", "core") == 0

    seed_agent_events(
        tmp_path,
        "repo",
        "s1",
        [
            {"event": "chunk_started", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "core"}},
            {"event": "chunk_landed", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "other", "trigger": "recovery"}},
        ],
    )

    assert m.attempt_count("s1", "core") == 2


# ── decision parsing: extract, degrade, and the injected decider ──────────────


def test_decision_parsing_and_decide_seam():
    m = _recover()
    assert m._extract_json('noise {"action": "retry"} tail') == '{"action": "retry"}'
    assert m._parse_decision('{"action": "retry", "rationale": "env"}') == {"action": "retry", "rationale": "env"}
    assert m._parse_decision("reslice it {")["action"] == "abandon"  # no closing brace → unparseable
    assert m._parse_decision('{"action": "explode"}')["action"] == "abandon"  # unrecognized
    assert m._parse_decision("[1, 2, 3]")["action"] == "abandon"  # no object → unparseable

    # decide() renders the prompt and routes the injected invoke's reply.
    seen: dict = {}

    def fake_invoke(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"action": "reslice", "rationale": "too big"}'

    out = m.decide({"slug": "core", "reason": "timeout"}, invoke=fake_invoke)
    assert out == {"action": "reslice", "rationale": "too big"}
    assert "core" in seen["prompt"] and "timeout" in seen["prompt"]


def test_make_recovery_prompt_fills_all_fields():
    m = _recover()
    prompt = m.make_recovery_prompt(
        {
            "slug": "c",
            "reason": "r",
            "worktree": "/w",
            "holding": "h",
            "attempt": 1,
            "cap": 2,
            "progress_note": "## Done\n- step",
        }
    )
    for token in ("c", "/w", "attempt 1 of 2", "## Done"):
        assert token in prompt


# ── recover(): every rung of the loop ─────────────────────────────────────────


def _run(m, transient, plans, *, monkeypatch, tmp_path, is_afk=None, decide=None, **over):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    calls: dict = {}
    prim = _wire(m, calls=calls)
    kwargs = dict(
        plans_by_slug=plans,
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=is_afk or (lambda s: True),
        decide=decide or (lambda ctx: {"action": "retry", "rationale": "env"}),
        notify=lambda msg: None,
        cap=2,
        **prim,
    )
    kwargs.update(over)
    return m.recover(set(transient), **kwargs), calls


def test_recover_retry_reslice_and_abandon(monkeypatch, tmp_path):
    m = _recover()
    plans = {s: _Plan(s) for s in ("aa", "bb", "cc")}

    def decide(ctx):
        return {
            "aa": {"action": "retry", "rationale": "env"},
            "bb": {"action": "reslice", "rationale": "too big"},
            "cc": {"action": "abandon", "rationale": "hopeless"},
        }[ctx["slug"]]

    out, calls = _run(m, {"aa", "bb", "cc"}, plans, monkeypatch=monkeypatch, tmp_path=tmp_path, decide=decide)
    by = {o["slug"]: o for o in out}
    assert by["aa"]["recovery"] == "retry" and calls["respawn"] == [("aa", 1)]
    assert by["bb"]["recovery"] == "reslice" and calls["reslice"] == [("bb", 1)]
    assert by["cc"]["recovery"] == "abandon" and ("cc", "hopeless") in calls["dead"]
    assert set(calls["teardown"]) == {"aa", "bb", "cc"}


def test_recover_skips_unknown_and_hitl(monkeypatch, tmp_path):
    m = _recover()
    plans = {"real": _Plan("real")}  # "ghost" has no plan
    out, _ = _run(
        m,
        {"real", "ghost", "ui"},
        {**plans, "ui": _Plan("ui", kind="HITL")},
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        is_afk=lambda s: s != "ui",
    )
    by = {o["slug"]: o for o in out}
    assert by["ghost"]["recovery"] == "unrecoverable"
    assert by["ui"]["recovery"] == "skipped-hitl"
    assert by["real"]["recovery"] == "retry"


def test_recover_attempt_cap_dead_letters(monkeypatch, tmp_path):
    m = _recover()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    seed_agent_events(
        tmp_path,
        "repo",
        "s1",
        [
            {"event": "chunk_started", "payload": {"slug": "core", "trigger": "recovery"}},
            {"event": "chunk_started", "payload": {"slug": "core", "trigger": "recovery"}},
        ],
    )
    out, calls = _run(m, {"core"}, {"core": _Plan("core")}, monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert out[0]["recovery"] == "dead-lettered" and out[0]["reason"] == "attempt-cap"
    assert calls["respawn"] == []


def test_recover_storm_breach_escalates_remaining(monkeypatch, tmp_path):
    m = _recover()
    plans = {s: _Plan(s) for s in ("a", "b", "c")}
    storm = m.StormGuard(1, 60.0, clock=lambda: 0.0)  # one respawn, then breach
    out, calls = _run(
        m, {"a", "b", "c"}, plans, monkeypatch=monkeypatch, tmp_path=tmp_path, storm_guard=storm, backoff=lambda i: None
    )
    assert calls["respawn"] == [("a", 1)]
    assert {o["slug"] for o in out if o["recovery"] == "dead-lettered"} == {"b", "c"}


def test_recover_budget_breach_escalates_remaining(monkeypatch, tmp_path):
    m = _recover()
    plans = {s: _Plan(s) for s in ("a", "b")}
    out, calls = _run(m, {"a", "b"}, plans, monkeypatch=monkeypatch, tmp_path=tmp_path, budget=m.Budget(1.0))
    assert calls["respawn"] == [("a", 1)]
    assert {o["slug"] for o in out if o["recovery"] == "dead-lettered"} == {"b"}


@pytest.mark.parametrize("reason", ["preflight_worktree_failed", "container_oom"])
def test_recover_retries_er3_transient_reasons(monkeypatch, tmp_path, reason):
    m = _recover()

    def ctx(plan, attempt, cap):
        return {"slug": plan.slug, "reason": reason, "worktree": "/wt", "attempt": attempt, "cap": cap}

    out, calls = _run(
        m,
        {"core"},
        {"core": _Plan("core")},
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        context_builder=ctx,
    )
    assert out[0]["recovery"] == "retry"
    assert calls["respawn"] == [("core", 1)]


def test_git_error_is_not_transient():
    from lib import events

    assert not events.is_transient_eject(events.GIT_ERROR)
