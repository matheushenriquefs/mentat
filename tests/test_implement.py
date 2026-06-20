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


def _write_plan(tmp_path: Path, slug: str, class_: str = "AFK", extra: str = "") -> Path:
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(exist_ok=True)
    plan_file = plan_dir / f"{slug}.md"
    plan_file.write_text(f"---\nid: {slug}\nclass: {class_}\n---\n# Plan\n{extra}\n")
    return plan_file


# ── frontmatter parsing ──────────────────────────────────────────────────────


def test_parse_frontmatter_extracts_class(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "test-plan", class_="AFK")
    fm = impl.parse_frontmatter(plan)
    assert fm["class"] == "AFK"


def test_parse_frontmatter_extracts_id(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "test-plan", class_="HITL")
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
    (plans_dir / "bare-plan.md").write_text("---\nid: bare-plan\nclass: AFK\n---\n")
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
    (tmp_path / "myplan.md").write_text("---\nid: x\nclass: AFK\n---\n")
    path = impl.resolve_plan_path("~/myplan.md")
    assert path.is_absolute()


# ── AFK / HITL harness selection ─────────────────────────────────────────────


def test_implement_single_afk_plan_succeeds(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "afk-plan", class_="AFK")

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
    implement.py emits chunk.spawned{harness:"hitl-in-session"} and returns 0,
    handing control back to the calling Claude session which drives the TDD
    loop in-session.
    """
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "hitl-plan", class_="HITL")

    fake_result = MagicMock()
    fake_result.returncode = 0

    with patch.object(impl, "_invoke_harness", return_value=fake_result) as mock_invoke:
        with patch.object(impl, "_emit_event") as mock_emit:
            rc = impl.run_plan(plan, harness="fake")

    assert rc == 0
    mock_invoke.assert_not_called()
    events = [c.args[0] for c in mock_emit.call_args_list]
    assert "chunk.spawned" in events
    spawned_payload = next(c.args[1] for c in mock_emit.call_args_list if c.args[0] == "chunk.spawned")
    assert spawned_payload.get("harness") == "hitl-in-session"


def test_implement_harness_flag_overrides_config(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "plan", class_="AFK")

    fake_result = MagicMock(returncode=0)
    with patch.object(impl, "_invoke_harness", return_value=fake_result) as mock_invoke:
        impl.run_plan(plan, harness="cursor")

    call_kwargs = mock_invoke.call_args
    harness_arg = call_kwargs.kwargs.get("harness") or call_kwargs.args[0]
    assert harness_arg == "cursor"


# ── AFK ambiguity detection ───────────────────────────────────────────────────


def test_implement_afk_plan_self_answer_detected_exits_42(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "afk-ambi", class_="AFK")

    session_log = tmp_path / "session.jsonl"
    session_log.write_text(
        json.dumps({"role": "assistant", "content": "Q: Should I proceed? A: Yes, I'll proceed."}) + "\n"
    )

    fake_result = MagicMock(returncode=0)
    fake_result.session_log = session_log

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=True):
            with patch.object(impl, "_emit_event") as mock_emit:
                rc = impl.run_plan(plan, harness="fake")

    assert rc == 42
    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk.ejected" in e for e in emitted)


def test_implement_emits_chunk_ejected_with_hitl_reason(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "afk-hitl", class_="AFK")

    fake_result = MagicMock(returncode=0)

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=True):
            with patch.object(impl, "_emit_event") as mock_emit:
                impl.run_plan(plan, harness="fake")

    payloads = [c.args[1] for c in mock_emit.call_args_list if "ejected" in c.args[0]]
    assert payloads
    ejected_payload = payloads[0]
    assert "hitl-required" in str(ejected_payload)


# ── gate failure ──────────────────────────────────────────────────────────────


def test_implement_gate_fail_exits_1(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "gate-fail-plan", class_="AFK")

    fake_result = MagicMock(returncode=0)

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_run_gates", return_value=("block", "gate failed")):
                with patch.object(impl, "_emit_event"):
                    rc = impl.run_plan(plan, harness="fake")

    assert rc == 1


def test_implement_emits_chunk_ejected_with_gate_failed_reason(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "gate-fail-emit", class_="AFK")

    fake_result = MagicMock(returncode=0)

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_run_gates", return_value=("block", "smells bad")):
                with patch.object(impl, "_emit_event") as mock_emit:
                    impl.run_plan(plan, harness="fake")

    payloads = [c.args[1] for c in mock_emit.call_args_list if "ejected" in c.args[0]]
    assert payloads
    assert "gate-failed" in str(payloads[0])


def test_implement_tdd_red_then_green(tmp_path):
    """After harness runs, gate passes → exit 0."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "tdd-plan", class_="AFK")

    fake_result = MagicMock(returncode=0)

    with patch.object(impl, "_invoke_harness", return_value=fake_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_run_gates", return_value=("pass", "")):
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
    plan = _write_plan(tmp_path, "run-plan", class_="AFK")
    with patch.object(impl, "ensure_session"):
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


# ── D11: doctor auto-trigger + logs_path on chunk.ejected ────────────────────


def test_implement_auto_doctors_on_nonzero_exit(tmp_path):
    """rc in {1, 42, 64, 65, 66, 69, 70, 78} → doctor fires."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "fail-plan", class_="AFK")

    with patch.object(impl, "run_plan", return_value=1):
        with patch.object(impl, "_auto_doctor") as mock_doc:
            rc = impl._run_and_doctor(plan, harness="fake")

    assert rc == 1
    mock_doc.assert_called_once()


def test_implement_no_doctor_on_zero_exit(tmp_path):
    """rc == 0 → doctor does NOT fire."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "ok-plan", class_="AFK")

    with patch.object(impl, "run_plan", return_value=0):
        with patch.object(impl, "_auto_doctor") as mock_doc:
            rc = impl._run_and_doctor(plan, harness="fake")

    assert rc == 0
    mock_doc.assert_not_called()


def test_implement_no_doctor_on_signal_exit(tmp_path):
    """SIGINT (130) / SIGTERM (143) skip doctor — signal exits aren't TDD failures."""
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "sig-plan", class_="AFK")

    for sig_rc in (130, 143):
        with patch.object(impl, "run_plan", return_value=sig_rc):
            with patch.object(impl, "_auto_doctor") as mock_doc:
                rc = impl._run_and_doctor(plan, harness="fake")
        assert rc == sig_rc
        mock_doc.assert_not_called()


def test_auto_doctor_fires_when_session_unset(tmp_path, monkeypatch):
    """S2: the MENTAT_SESSION-unset early-return is gone — doctor always fires on
    death. Previously an unset session silently skipped doctor, the root cause of
    silently-killed standalone AFK sessions going undiagnosed."""
    impl = load_module("implement")
    fake_script = tmp_path / "session.py"
    fake_script.write_text("")
    monkeypatch.setattr(impl, "_SESSION_SCRIPT", fake_script)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
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
    monkeypatch.setattr(impl, "_SESSION_SCRIPT", fake_script)
    monkeypatch.setenv("MENTAT_SESSION", "implement-foo-99")
    monkeypatch.delenv("EDITOR", raising=False)

    with patch.object(impl.subprocess, "run") as mock_run:
        impl._auto_doctor()

    cmd = mock_run.call_args.args[0]
    assert cmd == ["python3", str(fake_script), "doctor", "implement-foo-99"]


def test_implement_chunk_ejected_includes_logs_path(tmp_path, monkeypatch):
    """Every chunk.ejected emit carries a logs_path field per ADR-0007 payload-extension rule."""
    impl = load_module("implement")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-001")
    plan = _write_plan(tmp_path, "ej-plan", class_="AFK")

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
    """logs_path points to the dir containing the session JSONL + diagnosis.md bundle."""
    impl = load_module("implement")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-002")

    session_dir = tmp_path / "logs" / "myrepo" / "sess-002"
    session_dir.mkdir(parents=True)
    (session_dir / "mentat-implement-impl.jsonl").write_text('{"event": "plan.started"}\n')
    (session_dir / "diagnosis.md").write_text("## Verdict\n- Reason: test\n")

    logs_dir = Path(impl._logs_path())
    assert logs_dir == session_dir
    assert any(logs_dir.glob("*.jsonl"))
    assert (logs_dir / "diagnosis.md").exists()
