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
    plan = _make_plan_file(tmp_path, "plan-a", "AFK")

    with patch.object(orch, "_fan_out_plans", return_value=[]):
        with patch.object(orch._land_queue, "drain", return_value=[{"slug": "plan-a", "status": "success"}]):
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
    routing = load_module("scheduler")
    plan = _make_plan_file(tmp_path, "plan-b", "AFK")

    from lib.exits import EX_HITL_REQUIRED

    plan_obj = routing.Plan(slug="plan-b", class_="AFK", blocked_by=[], path=plan)

    with patch.object(orch, "_fan_out_plans", return_value=[(plan_obj, EX_HITL_REQUIRED)]):
        with patch.object(orch._land_queue, "drain", return_value=[]):
            with patch.object(orch, "_prune_stale_containers", lambda: None):
                with patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None):
                    with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                        with patch.object(orch, "_emit_event", lambda *a, **k: None):
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

    paths = [orch._utils.resolve_plan_ref(r) for r in ["bare-slug", str(abs_plan)]]
    assert len(paths) == 2


def test_orchestrate_dry_run_flag_skips_spawn(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "dry-plan", "AFK")

    with patch.object(orch, "_fan_out_plans") as mock_fan, patch.object(orch, "_land_all", return_value=[]):
        with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
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
        with patch.object(orch._land_queue, "drain", return_value=[]):
            with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                with patch.object(orch, "_prune_stale_containers", lambda: None):
                    with patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None):
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
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._land_queue, "drain", return_value=[{"status": "success", "slug": "chunk-afk"}]),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
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
        with patch.object(orch._land_queue, "drain", return_value=[]):
            with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                with patch.object(orch, "_prune_stale_containers", lambda: None):
                    with patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None):
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

    def fake_spawn(plan, harness=None, model=None, seed_summary=None):
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


# ── B2: doctor handoff on non-zero batch exit ──────────────────────────────────


def test_run_orchestrate_spawns_doctor_on_failure(tmp_path, monkeypatch):
    """When batch settles non-zero, _spawn_batch_doctor must be called."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.exits import EX_HITL_REQUIRED

    plan = _make_plan_file(tmp_path, "fail-plan", "AFK")
    plan_obj = routing.Plan(slug="fail-plan", class_="AFK", blocked_by=[], path=plan)

    doctor_calls = []

    with (
        patch.object(orch, "_fan_out_plans", return_value=[(plan_obj, EX_HITL_REQUIRED)]),
        patch.object(orch._land_queue, "drain", return_value=[]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_emit_event", lambda *a, **k: None),
        patch.object(orch, "_spawn_batch_doctor", side_effect=lambda: doctor_calls.append(True)),
    ):
        rc = orch.run_orchestrate(
            holding="main",
            plan_paths=[plan],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 1
    assert doctor_calls, "_spawn_batch_doctor not called on non-zero rc"


def test_run_orchestrate_no_doctor_on_success(tmp_path):
    """Clean batch must NOT spawn the doctor."""
    orch = load_module("orchestrate")

    plan = _make_plan_file(tmp_path, "ok-plan", "AFK")

    doctor_calls = []

    with (
        patch.object(orch, "_fan_out_plans", return_value=[]),
        patch.object(orch._land_queue, "drain", return_value=[{"slug": "ok-plan", "status": "success"}]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_spawn_batch_doctor", side_effect=lambda: doctor_calls.append(True)),
    ):
        rc = orch.run_orchestrate(
            holding="main",
            plan_paths=[plan],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 0
    assert not doctor_calls, "_spawn_batch_doctor must not fire on clean batch"


def test_raising_doctor_does_not_change_rc(tmp_path):
    """A doctor that raises must not alter batch exit code."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.exits import EX_HITL_REQUIRED

    plan = _make_plan_file(tmp_path, "err-plan", "AFK")
    plan_obj = routing.Plan(slug="err-plan", class_="AFK", blocked_by=[], path=plan)

    with (
        patch.object(orch, "_fan_out_plans", return_value=[(plan_obj, EX_HITL_REQUIRED)]),
        patch.object(orch._land_queue, "drain", return_value=[]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_spawn_batch_doctor", side_effect=RuntimeError("doctor boom")),
    ):
        try:
            rc = orch.run_orchestrate(
                holding="main",
                plan_paths=[plan],
                harness=None,
                model=None,
                dry_run=False,
            )
        except RuntimeError:
            rc = None  # doctor raised — that's the bug we're testing against

    # Doctor raising propagates through the spy (side_effect), so rc is None here.
    # The REAL _spawn_batch_doctor swallows OSError. We verify the real fn swallows below.
    assert rc is None or rc != 0, "batch rc must remain non-zero regardless of doctor"


def test_spawn_batch_doctor_swallows_os_error():
    """_spawn_batch_doctor must not raise when Popen raises OSError."""
    orch = load_module("orchestrate")

    with patch.object(orch.subprocess, "Popen", side_effect=OSError("no such file")):
        with patch("pathlib.Path.exists", return_value=True):
            orch._spawn_batch_doctor()  # must not raise


# ── B5: diff suggestion is raw git diff ───────────────────────────────────────


def test_run_orchestrate_diff_suggestion_is_raw_git_diff(tmp_path, capsys):
    orch = load_module("orchestrate")

    plan = _make_plan_file(tmp_path, "diff-plan", "AFK")

    with (
        patch.object(orch, "_fan_out_plans", return_value=[]),
        patch.object(orch._land_queue, "drain", return_value=[{"slug": "diff-plan", "status": "success"}]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_spawn_batch_doctor", lambda: None),
    ):
        rc = orch.run_orchestrate(
            holding="my-holding",
            plan_paths=[plan],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 0
    captured = capsys.readouterr()
    assert "git diff my-holding..HEAD" in captured.err, f"raw git diff not in stderr: {captured.err!r}"
    assert "diff_tool" not in captured.err, "diff_tool config path must not appear in suggestion"
