"""implement.py must not spawn a sub-claude for HITL plans.

Mirrors the slice-1 orchestrate doctrine one layer down: when class==HITL,
emit chunk.spawned{harness:"hitl-in-session"} and return control to the
calling Claude session — never invoke the harness adapter, which would
shell `claude --headless` and lose AskUserQuestion.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import load_script

IMPL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def _load(name: str):
    return load_script(IMPL_SCRIPTS / f"{name}.py", key=f"impl_{name}")


def _write_plan(tmp_path: Path, slug: str, class_: str) -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nstatus: ready\nclass: {class_}\nblocked_by: []\n---\n# {slug}\n")
    return p


def test_hitl_does_not_invoke_harness(tmp_path, monkeypatch):
    impl = _load("implement")
    plan = _write_plan(tmp_path, "fix-hitl", "HITL")

    invoke_calls: list[tuple] = []

    def fake_invoke_harness(harness, prompt, *, afk, model=None):
        invoke_calls.append((harness, afk))
        raise AssertionError("HITL path must not invoke harness")

    monkeypatch.setattr(impl, "_invoke_harness", fake_invoke_harness)

    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(impl, "_emit_event", lambda e, p: emitted.append((e, p)))

    rc = impl.run_plan(plan, harness=None, model=None)

    assert rc == 0, f"HITL run_plan should exit 0, got {rc}"
    assert invoke_calls == [], f"harness invoked for HITL: {invoke_calls}"
    spawned = [p for e, p in emitted if e == "chunk.spawned"]
    assert spawned, f"chunk.spawned not emitted; got: {emitted}"
    assert spawned[0].get("harness") == "hitl-in-session"
    assert spawned[0].get("slug") == "fix-hitl"


def test_afk_still_invokes_harness(tmp_path, monkeypatch):
    impl = _load("implement")
    plan = _write_plan(tmp_path, "fix-afk", "AFK")

    invoke_calls: list[tuple] = []

    class _R:
        returncode = 0
        session_log = None

    def fake_invoke_harness(harness, prompt, *, afk, model=None):
        invoke_calls.append((harness, afk))
        return _R()

    monkeypatch.setattr(impl, "_invoke_harness", fake_invoke_harness)
    monkeypatch.setattr(impl, "_detect_self_answer", lambda r: False)
    monkeypatch.setattr(impl, "_emit_event", lambda *a, **kw: None)

    rc = impl.run_plan(plan, harness=None, model=None)
    assert rc == 0
    assert invoke_calls, "harness must be invoked for AFK plans"
    assert invoke_calls[0][1] is True, "AFK afk-flag must be True"
