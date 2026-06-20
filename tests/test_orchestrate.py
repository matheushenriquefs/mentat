"""Tests for mentat-orchestrate top-level CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan_file(tmp_path: Path, slug: str, class_: str = "AFK") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nclass: {class_}\n---\n")
    return p


def test_orchestrate_full_pipeline_exits_0_on_all_success(tmp_path):
    orch = load_module("orchestrate")
    coord_mod = orch._coordinator
    plan = _make_plan_file(tmp_path, "plan-a", "AFK")

    class _FakeCoord:
        def __init__(self, **kw):
            pass

        def run(self, plans, session_id, **kw):
            return coord_mod.BatchResult(session_id=session_id, landed=("plan-a",), ejected=())

    with patch.object(coord_mod, "BatchCoordinator", _FakeCoord):
        with patch.object(orch, "_prune_stale_containers", lambda: None):
            with patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None):
                with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                    rc = orch.run_orchestrate(
                        holding="main",
                        plan_paths=[plan],
                        harness=None,
                        model=None,
                        dry_run=False,
                    )
    assert rc == 0


def test_orchestrate_exits_1_on_any_ejection(tmp_path):
    orch = load_module("orchestrate")
    coord_mod = orch._coordinator
    plan = _make_plan_file(tmp_path, "plan-b", "AFK")

    class _EjectCoord:
        def __init__(self, **kw):
            pass

        def run(self, plans, session_id, **kw):
            return coord_mod.BatchResult(session_id=session_id, landed=(), ejected=("plan-b",))

    with patch.object(coord_mod, "BatchCoordinator", _EjectCoord):
        with patch.object(orch, "_prune_stale_containers", lambda: None):
            with patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None):
                with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                    rc = orch.run_orchestrate(
                        holding="main",
                        plan_paths=[plan],
                        harness=None,
                        model=None,
                        dry_run=False,
                    )
    assert rc == 1


def test_orchestrate_holding_positional_required():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "orchestrate.py"), "run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_orchestrate_accepts_plan_slug_and_path_intermixed(tmp_path, monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setenv("HOME", str(tmp_path))
    plans_dir = tmp_path / ".agents" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "bare-slug.md").write_text("---\nid: bare-slug\nclass: AFK\n---\n")
    abs_plan = tmp_path / "abs-plan.md"
    abs_plan.write_text("---\nid: abs-plan\nclass: AFK\n---\n")

    paths = orch._resolve_plan_refs(["bare-slug", str(abs_plan)])
    assert len(paths) == 2


def test_orchestrate_dry_run_flag_skips_spawn(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "dry-plan", "AFK")

    with patch.object(orch, "_fan_out_plans") as mock_fan, patch.object(orch, "_land_all", return_value=[]):
        with patch.object(orch, "_batch_review"):
            orch.run_orchestrate(
                holding="main",
                plan_paths=[plan],
                harness=None,
                model=None,
                dry_run=True,
            )
    mock_fan.assert_not_called()


def test_orchestrate_anchored_runs_in_current_session(tmp_path):
    orch = load_module("orchestrate")
    hitl = _make_plan_file(tmp_path, "hitl-plan", "HITL")

    anchored_calls: list[str] = []

    def fake_run_anchored(plans, *, harness, model):
        for p in plans:
            anchored_calls.append(p.slug)
        return ["chunk-hitl"]

    with patch.object(orch, "_emit_anchored_chunks", side_effect=fake_run_anchored):
        with patch.object(orch, "_land_all", return_value=[{"status": "success", "slug": "chunk-hitl", "tip": "abc"}]):
            with patch.object(orch, "_batch_review"):
                orch.run_orchestrate(
                    holding="main",
                    plan_paths=[hitl],
                    harness=None,
                    model=None,
                    dry_run=False,
                )

    assert anchored_calls


def test_orchestrate_auto_spawn_runs_headless(tmp_path):
    orch = load_module("orchestrate")
    afk = _make_plan_file(tmp_path, "afk-plan", "AFK")

    with (
        patch.object(orch, "_fan_out_plans", return_value=[]) as mock_fan,
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch, "_land_all", return_value=[{"status": "success", "slug": "chunk-afk", "tip": "abc"}]),
        patch.object(orch, "_batch_review"),
    ):
        orch.run_orchestrate(
            holding="main",
            plan_paths=[afk],
            harness=None,
            model=None,
            dry_run=False,
        )

    mock_fan.assert_called_once()


def test_orchestrate_harness_flag_overrides_config(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "plan-h", "HITL")

    captured: list[str] = []

    def fake_run_anchored(plans, *, harness, model):
        captured.append(harness)
        return []

    with patch.object(orch, "_emit_anchored_chunks", side_effect=fake_run_anchored):
        with patch.object(orch, "_land_all", return_value=[]):
            with patch.object(orch, "_batch_review"):
                orch.run_orchestrate(
                    holding="main",
                    plan_paths=[plan],
                    harness="cursor",
                    model=None,
                    dry_run=False,
                )

    assert captured and captured[0] == "cursor"


# ── concurrency cap (ADR-0004) ──────────────────────────────────────────────


class _ScriptedPopen:
    """Popen stand-in whose poll() returns None for `live_ticks` calls, then 0."""

    def __init__(self, live_ticks: int) -> None:
        self._remaining = live_ticks
        self.returncode = 0

    def poll(self):
        if self._remaining > 0:
            self._remaining -= 1
            return None
        return 0

    def wait(self):
        self._remaining = 0
        self.returncode = 0
        return 0


def test_concurrency_cap_defaults_to_3_when_config_missing(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    assert orch._concurrency_cap() == 3


def test_concurrency_cap_reads_config_jsonc(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 7})
    assert orch._concurrency_cap() == 7


def test_concurrency_cap_clamps_to_min_1(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 0})
    assert orch._concurrency_cap() == 1
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": -5})
    assert orch._concurrency_cap() == 1


def test_concurrency_cap_rejects_bad_value(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": "lots"})
    assert orch._concurrency_cap() == 3


def test_fan_out_plans_blocks_until_slot_free(monkeypatch, tmp_path):
    """With cap=2 and 4 plans, _fan_out_plans must NOT spawn plans 3+ while 2 are live."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 2})

    plans = [routing.Plan(slug=f"p{i}", class_="AFK", blocked_by=[], path=tmp_path / f"p{i}.md") for i in range(4)]

    # Track concurrent live count at spawn time. Each fake Popen reports "live"
    # for 2 polls then exits — so the cap must throttle at plans 3 and 4.
    live: list = []
    high_watermark = {"n": 0}

    def fake_spawn(plan, harness=None, model=None):
        n_live = sum(1 for p in live if p._remaining > 0)
        high_watermark["n"] = max(high_watermark["n"], n_live + 1)
        proc = _ScriptedPopen(live_ticks=2)
        live.append(proc)
        return (f"sess-{plan.slug}", proc)

    monkeypatch.setattr(orch._fan_out, "spawn_with_proc", fake_spawn)
    # Avoid sleeping 100ms × N — patch time.sleep to no-op.
    monkeypatch.setattr(orch.time, "sleep", lambda _s: None)

    results = orch._fan_out_plans(plans, harness=None, model=None)
    assert [p.slug for p, _rc in results] == ["p0", "p1", "p2", "p3"]
    assert all(rc == 0 for _p, rc in results)
    assert high_watermark["n"] <= 2, f"cap=2 was breached; saw {high_watermark['n']} concurrent live subprocesses"
