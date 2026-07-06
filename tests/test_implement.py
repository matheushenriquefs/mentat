"""Tests for mentat-implement skill."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def load_module(name: str, package_path: Path | None = None):
    return load_script((package_path or SCRIPTS) / f"{name}.py", name)


def _write_plan(tmp_path: Path, slug: str, kind: str = "AFK", extra: str = "") -> Path:
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(exist_ok=True)
    plan_file = plan_dir / f"{slug}.md"
    plan_file.write_text(f"---\nid: {slug}\nkind: {kind}\n---\n# Plan\n{extra}\n")
    return plan_file


# ── frontmatter parsing ──────────────────────────────────────────────────────


def test_parse_frontmatter_extracts_class(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "test-plan", kind="AFK")
    fm = impl.parse_frontmatter(plan)
    assert fm["kind"] == "AFK"


def test_parse_frontmatter_extracts_id(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "test-plan", kind="HITL")
    fm = impl.parse_frontmatter(plan)
    assert fm["id"] == "test-plan"


# ── multi-slug refusal ───────────────────────────────────────────────────────


def test_implement_refuses_multi_slug(tmp_path):
    result = subprocess.run(
        ["python3", str(SCRIPTS / "implement.py"), "plan-a", "plan-b"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "mentat-orchestrate" in result.stderr


# ── plan-ref forms ───────────────────────────────────────────────────────────


def test_implement_accepts_bare_slug(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setenv("HOME", str(tmp_path))
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "bare-plan.md").write_text("---\nid: bare-plan\nkind: AFK\n---\n")
    path = impl.resolve_plan_path("bare-plan")
    assert path == plans_dir / "bare-plan.md"


def test_implement_accepts_full_path(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "full-path-plan")
    path = impl.resolve_plan_path(str(plan))
    assert path == plan


def test_implement_accepts_tilde_path(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "myplan.md").write_text("---\nid: x\nkind: AFK\n---\n")
    path = impl.resolve_plan_path("~/myplan.md")
    assert path.is_absolute()


# ── AFK / HITL harness selection ─────────────────────────────────────────────


def test_implement_single_afk_plan_succeeds(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "afk-plan", kind="AFK")

    fake_result = MagicMock()
    fake_result.returncode = 0

    with patch.object(impl, "_invoke_harness", return_value=fake_result) as mock_invoke:
        rc = impl.run_plan(plan, harness="fake")

    assert rc == 0
    call_kwargs = mock_invoke.call_args
    assert call_kwargs.kwargs.get("afk") is True or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else False)


def test_implement_single_hitl_plan_hands_off_to_caller(tmp_path):
    """HITL plans must NOT spawn a sub-claude via the harness adapter.

    The harness shells `claude --headless` which loses AskUserQuestion.
    implement.py emits chunk_started{harness:"hitl-in-agent"} and returns 0,
    handing control back to the calling Claude session which drives the TDD
    loop in-session.
    """
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "hitl-plan", kind="HITL")

    fake_result = MagicMock()
    fake_result.returncode = 0

    with patch.object(impl, "_invoke_harness", return_value=fake_result) as mock_invoke:
        with patch.object(impl, "_emit_event") as mock_emit:
            rc = impl.run_plan(plan, harness="fake")

    assert rc == 0
    mock_invoke.assert_not_called()
    events = [c.args[0] for c in mock_emit.call_args_list]
    assert "chunk_started" in events
    spawned_payload = next(c.args[1] for c in mock_emit.call_args_list if c.args[0] == "chunk_started")
    assert spawned_payload.get("harness") == "hitl-in-agent"


def test_implement_harness_flag_overrides_config(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "plan", kind="AFK")

    fake_result = MagicMock(returncode=0)
    with patch.object(impl, "_invoke_harness", return_value=fake_result) as mock_invoke:
        impl.run_plan(plan, harness="cursor")

    call_kwargs = mock_invoke.call_args
    harness_arg = call_kwargs.kwargs.get("harness") or call_kwargs.args[0]
    assert harness_arg == "cursor"


# ── AFK ambiguity detection ───────────────────────────────────────────────────


def test_implement_afk_plan_self_answer_detected_exits_42(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "afk-ambi", kind="AFK")

    session_log = tmp_path / "session.jsonl"
    session_log.write_text(
        json.dumps({"role": "assistant", "content": "Q: Should I proceed? A: Yes, I'll proceed."}) + "\n"
    )

    fake_result = MagicMock(returncode=0)
    fake_result.session_log = session_log

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=True):
            with patch.object(impl, "_promote_blocked_summary"):
                with patch.object(impl, "_emit_event") as mock_emit:
                    rc = impl.run_plan(plan, harness="fake")

    assert rc == 42
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk_ejected" in e for e in emitted)


def test_implement_emits_chunk_ejected_with_hitl_reason(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "afk-hitl", kind="AFK")

    fake_result = MagicMock(returncode=0)

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=True):
            with patch.object(impl, "_promote_blocked_summary"):
                with patch.object(impl, "_emit_event") as mock_emit:
                    impl.run_plan(plan, harness="fake")

    payloads = [c.args[1] for c in mock_emit.call_args_list if "ejected" in c.args[0]]
    assert payloads
    ejected_payload = payloads[0]
    assert "hitl_required" in str(ejected_payload)


# ── AFK success (in-session gates deferred to land per ADR-0004) ───────────────


def test_implement_afk_harness_success_exits_0(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "tdd-plan", kind="AFK")

    fake_result = MagicMock(returncode=0)

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_emit_event"):
                rc = impl.run_plan(plan, harness="fake")

    assert rc == 0


# ── S26: tests manifest + read-only mounts ───────────────────────────────────


def test_read_tests_manifest_absent(tmp_path, monkeypatch):
    """Returns ([], []) when no manifest file exists."""
    impl = load_module("implement")
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".agents" / "plans").mkdir(parents=True)
    closed, open_ = impl.read_tests_manifest("no-such-slug")
    assert closed == []
    assert open_ == []


def test_read_tests_manifest_reads_file(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setenv("HOME", str(tmp_path))
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "my-plan.tests.json").write_text(
        json.dumps({"closed": ["tests/test_foo.py"], "open": ["tests/test_new.py"]})
    )
    closed, open_ = impl.read_tests_manifest("my-plan")
    assert "tests/test_foo.py" in closed
    assert "tests/test_new.py" in open_


def test_compute_ro_mounts_closed_minus_open():
    impl = load_module("implement")
    ro = impl.compute_ro_mounts(
        closed=["tests/test_a.py", "tests/test_b.py"],
        open_=["tests/test_b.py"],
    )
    assert ro == ["tests/test_a.py"]


def test_compute_ro_mounts_all_open_returns_empty():
    impl = load_module("implement")
    ro = impl.compute_ro_mounts(
        closed=["tests/test_a.py"],
        open_=["tests/test_a.py"],
    )
    assert ro == []


def test_mark_test_writable_moves_to_open(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setenv("HOME", str(tmp_path))
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    manifest = plans_dir / "my-plan.tests.json"
    manifest.write_text(json.dumps({"closed": ["tests/test_foo.py"], "open": []}))

    with patch.object(impl, "_emit_event"):
        impl.mark_test_writable("my-plan", "tests/test_foo.py")

    data = json.loads(manifest.read_text())
    assert "tests/test_foo.py" in data["open"]


def test_mark_test_writable_missing_path_warns(tmp_path, monkeypatch, capsys):
    impl = load_module("implement")
    monkeypatch.setenv("HOME", str(tmp_path))
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "my-plan.tests.json").write_text(json.dumps({"closed": [], "open": []}))

    with patch.object(impl, "_emit_event"):
        impl.mark_test_writable("my-plan", "tests/not_there.py")

    captured = capsys.readouterr()
    assert "not in closed" in captured.err


# ── S10: argparse subcommand uniformity ──────────────────────────────────────


def test_main_mark_test_writable_via_subparser():
    """mark-test-writable dispatches through an argparse subparser, not a raw
    sys.argv pre-parse — slug/path arrive as parsed args."""
    impl = load_module("implement")
    with patch.object(impl, "mark_test_writable") as mock_mark:
        with patch.object(impl.sys, "argv", ["implement.py", "mark-test-writable", "my-plan", "tests/test_foo.py"]):
            with pytest.raises(SystemExit) as exc:
                impl.main()
    assert exc.value.code == impl.EX_OK
    mock_mark.assert_called_once_with(slug="my-plan", path="tests/test_foo.py")


def test_main_mark_test_writable_missing_path_argparse_errors():
    """Missing positional is caught by argparse (exit 2), not a manual len() check."""
    impl = load_module("implement")
    with patch.object(impl.sys, "argv", ["implement.py", "mark-test-writable", "my-plan"]):
        with pytest.raises(SystemExit) as exc:
            impl.main()
    assert exc.value.code == 2


def test_main_run_subcommand_explicit(tmp_path, monkeypatch):
    """`implement run <plan>` is accepted as an explicit subcommand and reaches
    plan execution (parity with the bare `implement <plan>` form)."""
    impl = load_module("implement")
    monkeypatch.setenv("MENTAT_SKIP_PREFLIGHT", "1")
    plan = _write_plan(tmp_path, "run-plan", kind="AFK")
    with patch.object(impl, "ensure_agent"):
        with patch.object(impl, "_prune_worktrees_preflight"):
            with patch.object(impl, "preflight_worktree", return_value=(0, None)):
                with patch.object(impl, "_in_shared_main_tree", return_value=False):
                    with patch.object(impl, "_run_and_doctor", return_value=0) as mock_run:
                        with patch.object(impl, "resolve_plan_path", return_value=plan):
                            with patch.object(impl.sys, "argv", ["implement.py", "run", "run-plan"]):
                                with pytest.raises(SystemExit) as exc:
                                    impl.main()
    assert exc.value.code == 0
    mock_run.assert_called_once()


# ── D11: doctor auto-trigger + logs_path on chunk_ejected ────────────────────


def test_implement_auto_doctors_on_nonzero_exit(tmp_path):
    """rc in {1, 42, 64, 65, 66, 69, 70, 78} → doctor fires."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "fail-plan", kind="AFK")

    with patch.object(impl, "run_plan", return_value=1):
        with patch.object(impl, "_auto_doctor") as mock_doc:
            rc = impl._run_and_doctor(plan, harness="fake")

    assert rc == 1
    mock_doc.assert_called_once()


def test_implement_no_doctor_on_zero_exit(tmp_path):
    """rc == 0 → doctor does NOT fire."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "ok-plan", kind="AFK")

    with patch.object(impl, "run_plan", return_value=0):
        with patch.object(impl, "_auto_doctor") as mock_doc:
            with patch.object(impl, "_auto_summary"):
                rc = impl._run_and_doctor(plan, harness="fake")

    assert rc == 0
    mock_doc.assert_not_called()


def test_implement_auto_summary_on_success(tmp_path):
    """S8: rc == 0 → success summary is written (the success-side twin of doctor)."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "ok-plan", kind="AFK")

    with patch.object(impl, "run_plan", return_value=0):
        with patch.object(impl, "_auto_summary") as mock_sum:
            with patch.object(impl, "_auto_doctor") as mock_doc:
                rc = impl._run_and_doctor(plan, harness="fake")

    assert rc == 0
    mock_sum.assert_called_once()
    mock_doc.assert_not_called()


def test_implement_no_summary_on_failure(tmp_path):
    """S8: a failing run gets a diagnosis, not a success summary."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "fail-plan", kind="AFK")

    with patch.object(impl, "run_plan", return_value=1):
        with patch.object(impl, "_auto_summary") as mock_sum:
            with patch.object(impl, "_auto_doctor"):
                impl._run_and_doctor(plan, harness="fake")

    mock_sum.assert_not_called()


def test_implement_no_summary_on_hitl_handoff(tmp_path):
    """S8 drift fix: a HITL plan returns 0 by handing off to the calling session
    (nothing implemented yet) — no premature 'completed' success summary. Summary
    is for AFK runs that actually executed the plan to completion."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "hitl-handoff", kind="HITL")

    with patch.object(impl, "run_plan", return_value=0):
        with patch.object(impl, "_auto_summary") as mock_sum:
            with patch.object(impl, "_auto_doctor"):
                rc = impl._run_and_doctor(plan, harness="fake")

    assert rc == 0
    mock_sum.assert_not_called()


def test_auto_summary_invokes_session_report(tmp_path, monkeypatch):
    """S8: _auto_summary shells `session.py report [<id>]` to write summary.md
    (mirrors _auto_doctor's session.py doctor call)."""
    impl = load_module("implement")
    fake_script = tmp_path / "session.py"
    fake_script.write_text("")
    monkeypatch.setattr(impl, "_AGENT_SCRIPT", fake_script)
    monkeypatch.setenv("MENTAT_AGENT", "implement-foo-99")

    with patch.object(impl.subprocess, "run") as mock_run:
        impl._auto_summary()

    cmd = mock_run.call_args.args[0]
    assert cmd == ["python3", str(fake_script), "report", "implement-foo-99"]


def test_implement_no_doctor_on_signal_exit(tmp_path):
    """SIGINT (130) / SIGTERM (143) skip doctor — signal exits aren't TDD failures."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "sig-plan", kind="AFK")

    for sig_rc in (130, 143):
        with patch.object(impl, "run_plan", return_value=sig_rc):
            with patch.object(impl, "_auto_doctor") as mock_doc:
                rc = impl._run_and_doctor(plan, harness="fake")
        assert rc == sig_rc
        mock_doc.assert_not_called()


# ── H1: promote_blocked_summary must carry status: blocked frontmatter ──────────


def test_promote_blocked_summary_readable_as_blocked(tmp_path):
    """_promote_blocked_summary must write status:blocked frontmatter so that
    _read_summary_at recognizes the file on re-read (self-answer path: the agent
    never wrote summary.md, executor promotes the fallback body)."""
    impl = load_module("implement")
    summary_path = tmp_path / "session" / "summary.md"
    summary_path.parent.mkdir()

    with patch.object(impl, "_blocked_summary_path", return_value=summary_path):
        impl._promote_blocked_summary("Cannot resolve the design call — two options remain.")

    result = impl._read_summary_at(summary_path)
    assert result is not None, "_read_summary_at must recognize status:blocked after promote"
    assert "Cannot resolve" in result


def test_auto_doctor_fires_when_session_unset(tmp_path, monkeypatch):
    """S2: the MENTAT_AGENT-unset early-return is gone — doctor always fires on
    death. Previously an unset session silently skipped doctor, the root cause of
    silently-killed standalone AFK sessions going undiagnosed."""
    impl = load_module("implement")
    fake_script = tmp_path / "session.py"
    fake_script.write_text("")
    monkeypatch.setattr(impl, "_AGENT_SCRIPT", fake_script)
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)

    with patch.object(impl.subprocess, "run") as mock_run:
        impl._auto_doctor()

    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    # session.py's cmd_doctor falls back to latest_session when no arg is given.
    assert cmd[:3] == ["python3", str(fake_script), "doctor"]


def test_auto_doctor_passes_session_id_when_set(tmp_path, monkeypatch):
    """When the session id is set, it is passed through to the doctor."""
    impl = load_module("implement")
    fake_script = tmp_path / "session.py"
    fake_script.write_text("")
    monkeypatch.setattr(impl, "_AGENT_SCRIPT", fake_script)
    monkeypatch.setenv("MENTAT_AGENT", "implement-foo-99")
    monkeypatch.delenv("EDITOR", raising=False)

    with patch.object(impl.subprocess, "run") as mock_run:
        impl._auto_doctor()

    cmd = mock_run.call_args.args[0]
    assert cmd == ["python3", str(fake_script), "doctor", "implement-foo-99"]


def test_implement_chunk_ejected_includes_logs_path(tmp_path, monkeypatch):
    """Every chunk_ejected emit carries a logs_path field per ADR-0007 payload-extension rule."""
    impl = load_module("implement")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    monkeypatch.setenv("MENTAT_AGENT", "sess-001")
    plan = _write_plan(tmp_path, "ej-plan", kind="AFK")

    fake_result = MagicMock(returncode=1)
    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_emit_event") as mock_emit:
            impl.run_plan(plan, harness="fake")

    payloads = [c.args[1] for c in mock_emit.call_args_list if "ejected" in c.args[0]]
    assert payloads
    assert "logs_path" in payloads[0]
    assert "sess-001" in payloads[0]["logs_path"]
    assert "myrepo" in payloads[0]["logs_path"]


def test_implement_logs_path_dir_holds_jsonl_and_diagnosis(tmp_path, monkeypatch):
    """logs_path in chunk_ejected payloads points to the session dir (JSONL + diagnosis.md)."""
    impl = load_module("implement")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    monkeypatch.setenv("MENTAT_AGENT", "sess-002")

    session_dir = tmp_path / "logs" / "myrepo" / "sess-002"
    session_dir.mkdir(parents=True)
    (session_dir / "mentat-implement-impl.jsonl").write_text('{"event": "chunk_started"}\n')
    (session_dir / "diagnosis.md").write_text("## Verdict\n- Reason: test\n")

    logs_dir = impl._agent_dir_fn(impl.os.environ.get("MENTAT_AGENT", "manual"))
    assert logs_dir == session_dir
    assert any(logs_dir.glob("*.jsonl"))
    assert (logs_dir / "diagnosis.md").exists()


# ── AFK commit contract + HITL prompt ────────────────────────────────────────


def _make_plan_for_contract(tmp_path: Path, plan_kind: str, body: str = "## Slice 1\nDo the thing.") -> Path:
    plan = tmp_path / "fake-plan.md"
    plan.write_text(f"---\nkind: {plan_kind}\nslug: fake-plan\n---\n{body}")
    return plan


def _fake_utils_obj():
    return type(
        "U",
        (),
        {
            "default_harness": staticmethod(lambda: "claude_code"),
            "detect_self_answer": staticmethod(lambda p: False),
        },
    )()


def _patch_impl_common(monkeypatch, impl):
    monkeypatch.setattr(impl, "_utils", _fake_utils_obj())
    monkeypatch.setattr(impl, "read_tests_manifest", lambda slug: ([], []))
    monkeypatch.setattr(impl, "compute_ro_mounts", lambda c, o: [])
    monkeypatch.setattr(impl, "_emit_event", lambda *a, **kw: None)


def test_afk_prompt_contains_commit_contract(tmp_path, monkeypatch):
    impl = load_module("implement")

    captured: dict = {}

    class FakeResult:
        returncode = 0
        session_log = None

    def fake_invoke_harness(harness, prompt, *, afk, model=None):
        captured["prompt"] = prompt
        return FakeResult()

    monkeypatch.setattr(impl, "_invoke_harness", fake_invoke_harness)
    monkeypatch.setattr(impl, "parse_frontmatter", lambda p: {"kind": "AFK"})
    _patch_impl_common(monkeypatch, impl)

    plan = _make_plan_for_contract(tmp_path, "AFK")
    impl.run_plan(plan)

    prompt = captured.get("prompt", "")
    assert "git commit" in prompt, f"Expected 'git commit' in prompt, got: {prompt[:200]}"
    assert "one commit per slice" in prompt.lower(), f"Expected 'one commit per slice' in prompt, got: {prompt[:200]}"


def test_hitl_prompt_unchanged(tmp_path, monkeypatch):
    impl = load_module("implement")

    captured: dict = {"invoke_called": False}

    def fake_invoke_harness(harness, prompt, *, afk, model=None):
        captured["invoke_called"] = True

    monkeypatch.setattr(impl, "_invoke_harness", fake_invoke_harness)
    monkeypatch.setattr(impl, "parse_frontmatter", lambda p: {"kind": "HITL"})
    _patch_impl_common(monkeypatch, impl)

    plan = _make_plan_for_contract(tmp_path, "HITL")
    rc = impl.run_plan(plan)

    assert rc == 0, f"HITL run_plan should return 0, got {rc}"
    assert not captured["invoke_called"], "_invoke_harness must NOT be called for HITL plans"


# ── B5: diff suggestion is raw git diff main..HEAD ────────────────────────────


def test_implement_diff_suggestion_is_raw_git_diff(tmp_path, monkeypatch, capsys):
    """On rc=0, implement must print `git diff main..HEAD`, never `diff_tool`."""
    import sys

    impl = load_script(SCRIPTS / "implement.py", "impl_b5")

    # Minimal monkeypatches to make main() reach the diff suggestion print
    plan_file = tmp_path / "b5-plan.md"
    plan_file.write_text("---\nid: b5-plan\nkind: AFK\n---\nbody\n")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(impl, "resolve_plan_path", lambda _: plan_file)
    monkeypatch.setattr(impl, "ensure_agent", lambda *a, **k: "sess-b5")
    monkeypatch.setattr(impl, "_prune_worktrees_preflight", lambda: None)
    monkeypatch.setattr(impl._utils, "default_harness", lambda: "default")
    monkeypatch.setattr(impl, "preflight_veto_reviewers", lambda _h, reuse_worktree=False: (0, []))
    monkeypatch.setattr(impl, "preflight_worktree", lambda _, reuse_worktree=False: (0, None))
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda reuse_worktree=False: False)
    monkeypatch.setattr(impl, "_run_and_doctor", lambda *a, **k: 0)
    monkeypatch.setattr(impl, "_teardown_worktree", lambda _: None)
    monkeypatch.setattr(sys, "exit", lambda c: None)

    impl.main.__globals__["sys"] = sys  # ensure patched sys
    # Call main with run subcommand
    monkeypatch.setattr(sys, "argv", ["mentat-implement", "run", str(plan_file)])
    impl.main()

    captured = capsys.readouterr()
    assert "git diff main..HEAD" in captured.err, f"raw git diff not in stderr: {captured.err!r}"
    assert "diff_tool" not in captured.err, "diff_tool must not appear in suggestion"


# ── coverage backfill: bin-layer bootstrap ───────────────────────────────────


def test_scripts_dir_bootstrap_inserts_when_absent(monkeypatch):
    """When the scripts dir is not on sys.path, importing implement.py inserts it."""
    import sys as _sys

    filtered = [p for p in _sys.path if "mentat-implement/scripts" not in p]
    monkeypatch.setattr(_sys, "path", filtered)
    load_script(SCRIPTS / "implement.py", "impl_bootstrap")
    assert any("mentat-implement/scripts" in p for p in _sys.path)


# ── mark_test_writable guards ────────────────────────────────────────────────


def test_mark_test_writable_no_manifest_warns(tmp_path, monkeypatch, capsys):
    impl = load_module("implement")
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)  # empty — no manifest
    impl.mark_test_writable("slug-x", "tests/a.py")
    assert "no manifest" in capsys.readouterr().err


# ── _compaction_threshold ────────────────────────────────────────────────────


def test_compaction_threshold_bad_value_raises(tmp_path, monkeypatch):
    impl = load_module("implement")
    cfg = tmp_path / "config.toml"
    cfg.write_text('compaction_threshold_tokens = "not-an-int"\n')
    monkeypatch.setenv("MENTAT_CONFIG", str(cfg))
    with pytest.raises(ValueError, match="invalid compaction_threshold_tokens"):
        impl._compaction_threshold()


# ── _repo_root_from_worktree fallback ────────────────────────────────────────


def test_repo_root_from_worktree_falls_back_on_git_error(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setattr(impl.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    wt = tmp_path / "a" / "b" / "c" / "d"
    wt.mkdir(parents=True)
    assert impl._repo_root_from_worktree(wt) == wt.parents[2]


# ── _run_agent_cmd + _auto_doctor ──────────────────────────────────────────


def test_run_agent_cmd_noop_when_script_missing(monkeypatch):
    impl = load_module("implement")
    monkeypatch.setattr(impl, "_AGENT_SCRIPT", Path("/nonexistent/session.py"))
    called: list = []
    monkeypatch.setattr(impl.subprocess, "run", lambda *a, **k: called.append(a))
    impl._run_agent_cmd("doctor")
    assert not called


class _FakeStdout:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_auto_doctor_opens_editor_when_set(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setattr(impl, "_run_agent_cmd", lambda _sub: None)
    monkeypatch.setenv("EDITOR", "my-editor")
    monkeypatch.setenv("MENTAT_AGENT", "sess-1")
    monkeypatch.setattr(impl, "_agent_dir_fn", lambda _sid: tmp_path)
    monkeypatch.setattr(impl.sys, "stdout", _FakeStdout(True))
    (tmp_path / "diagnosis.md").write_text("diag")
    runs: list = []
    monkeypatch.setattr(impl.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    impl._auto_doctor()
    assert runs and runs[0][0] == "my-editor"


def test_auto_doctor_skips_editor_when_not_a_tty(tmp_path, monkeypatch):
    """Headless/AFK: $EDITOR inherited but stdout is a pipe → the terminal editor
    must NOT be launched (it would block the child on a non-TTY until its wall kill);
    the doctor diagnosis is still written."""
    impl = load_module("implement")
    doctored: list = []
    monkeypatch.setattr(impl, "_run_agent_cmd", lambda sub: doctored.append(sub))
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setenv("MENTAT_AGENT", "sess-1")
    monkeypatch.setattr(impl, "_agent_dir_fn", lambda _sid: tmp_path)
    monkeypatch.setattr(impl.sys, "stdout", _FakeStdout(False))
    (tmp_path / "diagnosis.md").write_text("diag")
    runs: list = []
    monkeypatch.setattr(impl.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    impl._auto_doctor()
    assert runs == [], f"editor must not launch without a TTY: {runs}"
    assert doctored == ["doctor"], "doctor diagnosis must still run"


# ── _is_main_worktree failure modes ──────────────────────────────────────────


def test_is_main_worktree_false_when_spec_none(monkeypatch):
    impl = load_module("implement")
    monkeypatch.setattr(impl.importlib.util, "spec_from_file_location", lambda *a, **k: None)
    assert impl._is_main_worktree(Path.cwd()) is False


def test_is_main_worktree_false_on_load_error(tmp_path, monkeypatch, capsys):
    impl = load_module("implement")
    bad = tmp_path / "worktree.py"
    bad.write_text("def broken(:\n")  # syntax error → exec_module raises
    monkeypatch.setattr(impl, "_GIT_WORKTREE_PY", bad)
    assert impl._is_main_worktree(tmp_path) is False
    assert "worktree.py load failed" in capsys.readouterr().err


# ── preflight_worktree skip when git.py missing ──────────────────────────────


def test_preflight_worktree_skips_when_git_script_missing(monkeypatch):
    impl = load_module("implement")
    monkeypatch.delenv("MENTAT_SKIP_PREFLIGHT", raising=False)
    monkeypatch.setattr(impl, "_GIT_SCRIPT", Path("/nonexistent/git.py"))
    assert impl.preflight_worktree("slug") == (0, None)


# ── _load_mod ────────────────────────────────────────────────────────────────


def test_load_mod_loads_real_module():
    impl = load_module("implement")
    mod = impl._load_mod("hu_probe", SCRIPTS / "harness_utils.py")
    assert hasattr(mod, "default_harness")


def test_load_mod_raises_when_no_loader(tmp_path):
    impl = load_module("implement")
    bad = tmp_path / "x.txt"
    bad.write_text("not python")
    with pytest.raises(ImportError):
        impl._load_mod("x", bad)


# ── blocked-summary seam helpers ─────────────────────────────────────────────


def test_blocked_summary_path_none_without_session(monkeypatch):
    impl = load_module("implement")
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    assert impl._blocked_summary_path() is None


def test_read_summary_at_returns_none_on_oserror(tmp_path, monkeypatch):
    impl = load_module("implement")
    p = tmp_path / "summary.md"
    p.write_text("---\nstatus: blocked\n---\nbody")

    def boom(*a, **k):
        raise OSError("read failed")

    monkeypatch.setattr(Path, "read_text", boom)
    assert impl._read_summary_at(p) is None


def test_read_blocked_summary_falls_back_to_worktree(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.delenv("MENTAT_AGENT", raising=False)  # seam is None → worktree fallback
    (tmp_path / impl.SUMMARY_FILE).write_text("---\nstatus: blocked\n---\nthe blocker text")
    assert impl._read_blocked_summary(tmp_path) == "the blocker text"


def test_promote_blocked_summary_surfaces_oserror(monkeypatch):
    impl = load_module("implement")
    monkeypatch.setenv("MENTAT_AGENT", "sess-x")

    def boom(*a, **k):
        raise OSError("mkdir failed")

    monkeypatch.setattr(Path, "mkdir", boom)
    with pytest.raises(OSError, match="mkdir failed"):
        impl._promote_blocked_summary("body")


# ── _veto_agents_dir mapping ─────────────────────────────────────────────────


def test_veto_agents_dir_maps_known_and_default_harness():
    impl = load_module("implement")
    assert impl._veto_agents_dir("cursor").parts[-2:] == (".cursor", "agents")
    assert impl._veto_agents_dir("unknown-harness").parts[-2:] == (".claude", "agents")


# ── _strip_frontmatter edge cases ────────────────────────────────────────────


def test_strip_frontmatter_no_frontmatter_returned_verbatim():
    impl = load_module("implement")
    assert impl._strip_frontmatter("plain body, no fm") == "plain body, no fm"


def test_strip_frontmatter_unterminated_returned_verbatim():
    impl = load_module("implement")
    text = "---\nid: x\nno closing fence"
    assert impl._strip_frontmatter(text) == text


# ── _do_land wrapper ─────────────────────────────────────────────────────────


def test_do_land_delegates_to_land_queue():
    impl = load_module("implement")

    class _FakeLQ:
        def land(self, chunk, *, holding):
            return {"status": "success", "tip": "sha1", "holding": holding}

    result = impl._do_land("CHUNK", holding="main", land_queue=_FakeLQ())
    assert result["status"] == "success"
    assert result["holding"] == "main"


# ── main() early-exit branches ───────────────────────────────────────────────


def test_main_multi_plan_refs_exits_1(monkeypatch, capsys):
    impl = load_module("implement")
    monkeypatch.setattr(impl.sys, "argv", ["implement.py", "run", "p1", "p2"])
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    assert "one plan at a time" in capsys.readouterr().err


def test_main_plan_not_found_exits_1(monkeypatch, capsys):
    impl = load_module("implement")
    monkeypatch.setattr(impl.sys, "argv", ["implement.py", "run", "ghost"])
    monkeypatch.setattr(impl, "resolve_plan_path", lambda _ref: Path("/nonexistent/ghost.md"))
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    assert "plan not found" in capsys.readouterr().err


def test_main_preflight_veto_failure_names_missing_and_exits(tmp_path, monkeypatch, capsys):
    impl = load_module("implement")
    plan = tmp_path / "p.md"
    plan.write_text("---\nid: p\nkind: AFK\n---\n")
    monkeypatch.setattr(impl.sys, "argv", ["implement.py", "run", str(plan)])
    monkeypatch.setattr(impl, "resolve_plan_path", lambda _ref: plan)
    monkeypatch.setattr(impl, "ensure_agent", lambda *a, **k: "sess")
    monkeypatch.setattr(impl, "_prune_worktrees_preflight", lambda: None)
    monkeypatch.setattr(impl._utils, "default_harness", lambda: "claude-code")
    monkeypatch.setattr(impl, "preflight_veto_reviewers", lambda _h, reuse_worktree=False: (1, ["mentat-bug-reviewer"]))
    with pytest.raises(SystemExit) as exc:
        impl.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "PREFLIGHT FAILED" in err
    assert "mentat-bug-reviewer" in err


def test_mark_test_writable_idempotent_when_already_open(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setattr(impl, "_plans_dir", lambda: tmp_path)
    monkeypatch.setattr(impl, "_emit_event", lambda *a, **k: None)
    manifest = tmp_path / "slug-y.tests.json"
    manifest.write_text(json.dumps({"closed": ["t/a.py"], "open": ["t/a.py"]}))
    impl.mark_test_writable("slug-y", "t/a.py")  # already open → no duplicate append
    assert json.loads(manifest.read_text())["open"] == ["t/a.py"]


def test_auto_doctor_editor_set_but_no_diagnosis_file(tmp_path, monkeypatch):
    impl = load_module("implement")
    monkeypatch.setattr(impl, "_run_agent_cmd", lambda _sub: None)
    monkeypatch.setenv("EDITOR", "my-editor")
    monkeypatch.setenv("MENTAT_AGENT", "sess-1")
    monkeypatch.setattr(impl, "_agent_dir_fn", lambda _sid: tmp_path)  # no diagnosis.md written
    monkeypatch.setattr(impl.sys, "stdout", _FakeStdout(True))  # TTY, so only absence gates
    runs: list = []
    monkeypatch.setattr(impl.subprocess, "run", lambda *a, **k: runs.append(a))
    impl._auto_doctor()
    assert not runs, "editor must not open when diagnosis.md is absent"
