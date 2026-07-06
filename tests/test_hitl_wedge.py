"""S5 — AFK ambiguity wedge → exit 42 → hitl-required, end to end.

An AFK agent has no human to ask (AskUserQuestion stays disallowed so it cannot
hang on a prompt). When it hits a decision the plan does not resolve it writes
the blocker to `<worktree>/summary.md` with frontmatter `status: blocked` and
stops, rather than guessing. implement reads it, ejects `hitl-required`,
promotes the body to the agent log dir, preserves the worktree, and exits 42.
Orchestrate maps a child exit 42 the same way: not landed, worktree preserved,
visible, downstream cascaded. doctor/report surface the blocker.

Gate-run home (testpaths = ["tests"]). Pure surfaces only — the live harness
subprocess is not exercised here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import bind_plan, load_script, seed_agent_events

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-implement/scripts"
ORCH_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts"
SESSION_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-track/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))


def _impl():
    return load_script(IMPL_SCRIPTS / "implement.py", "impl_wedge")


def _orch():
    return load_script(ORCH_SCRIPTS / "orchestrate.py", "orch_wedge")


def _scheduler():
    return load_script(ORCH_SCRIPTS / "scheduler.py", "sched_wedge")


def _diagnose():
    return load_script(SESSION_SCRIPTS / "diagnose.py", "diagnose_wedge")


def _write_plan(tmp_path: Path, slug: str, kind: str = "AFK") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nkind: {kind}\nblocked_by: []\n---\n# {slug}\nbody\n")
    return p


def _write_blocked_summary(worktree: Path, body: str = "Which auth flow — OAuth or SAML?") -> None:
    (worktree / "summary.md").write_text(f"---\nstatus: blocked\n---\n{body}\n")


# ── _read_blocked_summary — the wedge marker reader ───────────────────────────


def test_read_blocked_summary_returns_body_when_status_blocked(tmp_path):
    impl = _impl()
    _write_blocked_summary(tmp_path, "Need a design call: A or B?")
    assert impl._read_blocked_summary(tmp_path) == "Need a design call: A or B?"


def test_read_blocked_summary_none_when_absent(tmp_path):
    impl = _impl()
    assert impl._read_blocked_summary(tmp_path) is None


def test_read_blocked_summary_none_when_status_not_blocked(tmp_path):
    impl = _impl()
    (tmp_path / "summary.md").write_text("---\nstatus: done\n---\nfinished cleanly\n")
    assert impl._read_blocked_summary(tmp_path) is None


def test_read_blocked_summary_none_when_no_frontmatter(tmp_path):
    impl = _impl()
    (tmp_path / "summary.md").write_text("just a plain summary, no frontmatter\n")
    assert impl._read_blocked_summary(tmp_path) is None


# ── run_plan AFK wedge → exit 42 + hitl-required ──────────────────────────────


def test_run_plan_wedge_via_marker_exits_42_with_summary(tmp_path):
    impl = _impl()
    plan = _write_plan(tmp_path, "afk-wedge")
    promoted: list[str] = []

    with patch.object(impl, "_invoke_harness", return_value=MagicMock(returncode=0)):
        with patch.object(impl, "_read_blocked_summary", return_value="blocked: pick a DB"):
            with patch.object(impl, "_detect_self_answer", return_value=False):
                with patch.object(impl, "_promote_blocked_summary", side_effect=promoted.append):
                    with patch.object(impl, "_emit_event") as emit:
                        rc = impl.run_plan(plan, harness="fake")

    assert rc == impl.EX_HITL_REQUIRED
    ejected = [c.args[1] for c in emit.call_args_list if c.args[0] == "chunk_ejected"]
    assert ejected, "no chunk_ejected emitted"
    assert ejected[0]["reason"] == "hitl_required"
    assert ejected[0]["summary"] == "blocked: pick a DB"
    assert promoted == ["blocked: pick a DB"], "blocker not promoted to the log dir"


def test_run_plan_wedge_precedes_nonzero_exit(tmp_path):
    """A wedge with a nonzero harness exit is still hitl-required, never implement-failed."""
    impl = _impl()
    plan = _write_plan(tmp_path, "afk-wedge-nz")

    with patch.object(impl, "_invoke_harness", return_value=MagicMock(returncode=1)):
        with patch.object(impl, "_read_blocked_summary", return_value="stuck"):
            with patch.object(impl, "_detect_self_answer", return_value=False):
                with patch.object(impl, "_promote_blocked_summary"):
                    with patch.object(impl, "_emit_event") as emit:
                        rc = impl.run_plan(plan, harness="fake")

    assert rc == impl.EX_HITL_REQUIRED
    reasons = [c.args[1].get("reason") for c in emit.call_args_list if c.args[0] == "chunk_ejected"]
    assert "hitl_required" in reasons
    assert "implement_failed" not in reasons


def test_run_plan_self_answer_still_wedges_when_no_marker(tmp_path):
    """The defensive secondary net: AskUserQuestion in the stream still ejects 42."""
    impl = _impl()
    plan = _write_plan(tmp_path, "afk-self")

    with patch.object(impl, "_invoke_harness", return_value=MagicMock(returncode=0)):
        with patch.object(impl, "_read_blocked_summary", return_value=None):
            with patch.object(impl, "_detect_self_answer", return_value=True):
                with patch.object(impl, "_promote_blocked_summary"):
                    with patch.object(impl, "_emit_event") as emit:
                        rc = impl.run_plan(plan, harness="fake")

    assert rc == impl.EX_HITL_REQUIRED
    reasons = [c.args[1].get("reason") for c in emit.call_args_list if c.args[0] == "chunk_ejected"]
    assert "hitl_required" in reasons


def test_run_plan_no_wedge_returns_zero(tmp_path):
    impl = _impl()
    plan = _write_plan(tmp_path, "afk-clean")

    with patch.object(impl, "_invoke_harness", return_value=MagicMock(returncode=0)):
        with patch.object(impl, "_read_blocked_summary", return_value=None):
            with patch.object(impl, "_detect_self_answer", return_value=False):
                with patch.object(impl, "_emit_event"):
                    rc = impl.run_plan(plan, harness="fake")

    assert rc == 0


# ── AFK ambiguity contract injected into the prompt ───────────────────────────


def test_afk_prompt_instructs_blocked_summary_channel(tmp_path):
    impl = _impl()
    plan = _write_plan(tmp_path, "afk-prompt")

    with patch.object(impl, "_invoke_harness", return_value=MagicMock(returncode=0)) as invoke:
        with patch.object(impl, "_read_blocked_summary", return_value=None):
            with patch.object(impl, "_detect_self_answer", return_value=False):
                with patch.object(impl, "_emit_event"):
                    impl.run_plan(plan, harness="fake")

    prompt = invoke.call_args.args[1]
    assert "summary.md" in prompt
    assert "status: blocked" in prompt
    # tells the agent NOT to guess
    assert "guess" in prompt.lower()


# ── worktree preserved on a wedge (exit 42 excluded from teardown) ────────────


def test_hitl_exit_excluded_from_worktree_teardown():
    impl = _impl()
    assert impl.EX_HITL_REQUIRED in impl._PRESERVE_WORKTREE_EXITS
    # the signal exits stay preserved too
    assert 130 in impl._PRESERVE_WORKTREE_EXITS
    assert 143 in impl._PRESERVE_WORKTREE_EXITS


# ── orchestrate: child exit 42 → not landed, preserved, cascaded ──────────────


def testpartition_by_outcome_excludes_hitl_children_from_landing():
    orch = _orch()
    sched = _scheduler()
    bind_plan("a")
    bind_plan("b")
    plan_a = sched.Plan(slug="a", kind="AFK", blocked_by=[], path=Path("/p/a.md"))
    plan_b = sched.Plan(slug="b", kind="AFK", blocked_by=[], path=Path("/p/b.md"))

    emitted: list[tuple[str, dict]] = []
    ejected_slugs: list[str] = []

    with patch.object(orch, "_emit_event", side_effect=lambda e, p: emitted.append((e, p))):
        with patch.object(orch._batch, "_worktree_for_slug", side_effect=lambda s: Path(f"/wt/{s}")):
            chunks, hitl, _transient = orch._batch.partition_by_outcome(
                [(plan_a, 0), (plan_b, orch.EX_HITL_REQUIRED)],
                mark_ejected=ejected_slugs.append,
            )

    landed_slugs = [c.slug for c in chunks]
    assert landed_slugs == ["a"], "hitl child must not be enqueued for landing"
    assert hitl == {"b"}
    assert ejected_slugs == ["b"], "hitl child must cascade via scheduler.mark_ejected"
    hitl_ejects = [p for e, p in emitted if e == "chunk_ejected" and p.get("reason") == "hitl_required"]
    assert hitl_ejects and hitl_ejects[0]["slug"] == "b"


def testpartition_by_outcome_all_clean_lands_all():
    orch = _orch()
    sched = _scheduler()
    bind_plan("x")
    bind_plan("y")
    plans = [sched.Plan(slug=s, kind="AFK", blocked_by=[], path=Path(f"/p/{s}.md")) for s in ("x", "y")]
    with patch.object(orch, "_emit_event", lambda e, p: None):
        with patch.object(orch._batch, "_worktree_for_slug", side_effect=lambda s: Path(f"/wt/{s}")):
            chunks, hitl, _transient = orch._batch.partition_by_outcome(
                [(plans[0], 0), (plans[1], 0)],
                mark_ejected=lambda s: None,
            )
    assert [c.slug for c in chunks] == ["x", "y"]
    assert hitl == set()


# ── MENTAT_REPO frozen pre-chdir so the log dir doesn't split (bug-review fix) ─


def test_ensure_agent_freezes_mentat_repo(tmp_path, monkeypatch):
    """ensure_agent exports MENTAT_REPO from the pre-chdir cwd, so a later
    os.chdir into the worktree can't make _logs_path / doctor / emit resolve to
    the slug dir while transcript.jsonl sits under the repo dir."""
    from lib import agent as agent_mod

    from tests.conftest import init_git_repo

    repo = tmp_path / "myrepo"
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))

    agent_mod.ensure_agent("implement", "my-slug")
    assert os.environ["MENTAT_REPO"] == "myrepo"

    # simulate implement's chdir into its worktree — the frozen value must hold
    wt = repo / ".mentat" / "worktrees" / "my-slug"
    wt.mkdir(parents=True)
    monkeypatch.chdir(wt)
    assert os.environ["MENTAT_REPO"] == "myrepo", "MENTAT_REPO must not drift to the slug dir after chdir"


# ── doctor / report surface the blocker ───────────────────────────────────────


def _write_audit(tmp_path: Path, agent_id: str, rows: list[dict]) -> Path:
    return seed_agent_events(tmp_path, "testrepo", agent_id, rows, harness="mentat-implement")


def test_doctor_verdict_names_hitl_blocker(tmp_path):
    diagnose = _diagnose()
    sd = _write_audit(
        tmp_path,
        "s-hitl",
        [
            {"event": "chunk_started", "ts": "t0", "payload": {"slug": "p", "plan": "/p/p.md"}},
            {
                "event": "chunk_ejected",
                "ts": "t1",
                "payload": {"slug": "p", "reason": "hitl_required", "where": "/wt/p", "summary": "OAuth or SAML?"},
            },
        ],
    )
    verdict = diagnose.build_verdict(sd)
    assert "hitl_required" in verdict
    assert "OAuth or SAML?" in verdict, "doctor must surface the blocker summary"


def test_report_summary_names_hitl_blocker(tmp_path):
    diagnose = _diagnose()
    sd = _write_audit(
        tmp_path,
        "s-rep",
        [
            {"event": "chunk_started", "ts": "t0", "payload": {"slug": "p", "plan": "/p/p.md"}},
            {
                "event": "chunk_ejected",
                "ts": "t1",
                "payload": {"slug": "p", "reason": "hitl_required", "where": "/wt/p", "summary": "pick a queue"},
            },
        ],
    )
    summary = diagnose.build_summary(sd)
    assert "hitl_required" in summary
    assert "pick a queue" in summary


# ── F1: marker lives in agent log dir, not worktree ─────────────────────────


def test_read_blocked_summary_reads_from_session_log_dir(tmp_path, monkeypatch):
    """F1 tracer: _read_blocked_summary must find the marker at
    ~/.mentat/logs/<repo>/<agent>/summary.md (the seam), not in the worktree."""
    impl = _impl()
    sid = "implement-f1test-9999"
    repo = "myrepo"
    monkeypatch.setenv("MENTAT_AGENT", sid)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", repo)

    seam_dir = tmp_path / repo / sid
    seam_dir.mkdir(parents=True)
    (seam_dir / "summary.md").write_text("---\nstatus: blocked\n---\nWhich auth? OAuth or SAML?\n")

    # Pass an EMPTY worktree (no summary.md there) — must still find it via seam
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    assert impl._read_blocked_summary(worktree) == "Which auth? OAuth or SAML?"


def test_afk_ambiguity_prompt_directs_to_session_log_dir(tmp_path):
    """F1 tracer: the AFK prompt must direct the agent to write summary.md in
    the agent log dir (via MENTAT_AGENT_LOG), not the worktree root."""
    impl = _impl()
    contract = impl._AFK_AMBIGUITY_CONTRACT
    # Must mention the agent env var so the agent can resolve the log dir
    assert "MENTAT_AGENT_LOG" in contract or "agent log" in contract.lower(), (
        "_AFK_AMBIGUITY_CONTRACT must direct to agent log dir, not worktree"
    )
