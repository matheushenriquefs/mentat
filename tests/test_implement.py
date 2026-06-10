"""Tests for mentat-implement skill."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def load_module(name: str, package_path: Path | None = None):
    path = (package_path or SCRIPTS) / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _write_plan(tmp_path: Path, slug: str, class_: str = "AFK", extra: str = "") -> Path:
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir(exist_ok=True)
    plan_file = plan_dir / f"{slug}.md"
    plan_file.write_text(
        f"---\nid: {slug}\nclass: {class_}\n---\n# Plan\n{extra}\n"
    )
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
        capture_output=True, text=True,
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
    assert call_kwargs.kwargs.get("afk") is True or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else False
    )


def test_implement_single_hitl_plan_allows_questions(tmp_path):
    impl = load_module("implement")
    plan = _write_plan(tmp_path, "hitl-plan", class_="HITL")

    fake_result = MagicMock()
    fake_result.returncode = 0

    with patch.object(impl, "_invoke_harness", return_value=fake_result) as mock_invoke:
        rc = impl.run_plan(plan, harness="fake")

    assert rc == 0
    call_kwargs = mock_invoke.call_args
    afk_val = call_kwargs.kwargs.get("afk", True)
    assert afk_val is False


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
