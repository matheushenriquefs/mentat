"""Tests for implement.py run_plan AFK commit contract injection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load_implement():
    key = "mentat_implement"
    if key in sys.modules:
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, SCRIPTS_DIR / "implement.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_plan(tmp_path: Path, plan_class: str, body: str = "## Slice 1\nDo the thing.") -> Path:
    plan = tmp_path / "fake-plan.md"
    plan.write_text(f"---\nclass: {plan_class}\nslug: fake-plan\n---\n{body}")
    return plan


def _fake_utils():
    return type(
        "U",
        (),
        {
            "default_harness": staticmethod(lambda: "claude_code"),
            "detect_self_answer": staticmethod(lambda p: False),
        },
    )()


def _patch_common(monkeypatch, impl):
    monkeypatch.setattr(impl, "_utils", _fake_utils())
    monkeypatch.setattr(impl, "read_tests_manifest", lambda slug: ([], []))
    monkeypatch.setattr(impl, "compute_ro_mounts", lambda c, o: [])
    monkeypatch.setattr(impl, "_emit_event", lambda *a, **kw: None)
    monkeypatch.setattr(impl, "_run_gates", lambda p: ("pass", ""))


def test_afk_prompt_contains_commit_contract(tmp_path, monkeypatch):
    impl = _load_implement()

    captured: dict = {}

    class FakeResult:
        returncode = 0
        session_log = None

    def fake_invoke_harness(harness, prompt, *, afk, model=None):
        captured["prompt"] = prompt
        return FakeResult()

    monkeypatch.setattr(impl, "_invoke_harness", fake_invoke_harness)
    monkeypatch.setattr(impl, "parse_frontmatter", lambda p: {"class": "AFK"})
    _patch_common(monkeypatch, impl)

    plan = _make_plan(tmp_path, "AFK")
    impl.run_plan(plan)

    prompt = captured.get("prompt", "")
    assert "git commit" in prompt, f"Expected 'git commit' in prompt, got: {prompt[:200]}"
    assert "one commit per slice" in prompt.lower(), f"Expected 'one commit per slice' in prompt, got: {prompt[:200]}"


def test_hitl_prompt_unchanged(tmp_path, monkeypatch):
    impl = _load_implement()

    captured: dict = {"invoke_called": False}

    def fake_invoke_harness(harness, prompt, *, afk, model=None):
        captured["invoke_called"] = True

    monkeypatch.setattr(impl, "_invoke_harness", fake_invoke_harness)
    monkeypatch.setattr(impl, "parse_frontmatter", lambda p: {"class": "HITL"})
    _patch_common(monkeypatch, impl)

    plan = _make_plan(tmp_path, "HITL")
    rc = impl.run_plan(plan)

    assert rc == 0, f"HITL run_plan should return 0, got {rc}"
    assert not captured["invoke_called"], "_invoke_harness must NOT be called for HITL plans"
