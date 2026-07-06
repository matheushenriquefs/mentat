"""Tests for mentat-orchestrate top-level CLI."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import TEST_CHUNK_ID, bind_plan, load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan_file(tmp_path: Path, slug: str, kind: str = "AFK") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nkind: {kind}\n---\n")
    return p


def test_orchestrate_full_pipeline_exits_0_on_all_success(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "plan-a", "AFK")

    with (
        patch.object(orch._batch, "_fan_out_plans", return_value=[]),
        patch.object(orch._batch._land_queue, "drain", return_value=[{"slug": "plan-a", "status": "success"}]),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
    ):
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

    plan_obj = routing.Plan(slug="plan-b", kind="AFK", blocked_by=[], path=plan)

    with (
        patch.object(orch._batch, "_fan_out_plans", return_value=[(plan_obj, EX_HITL_REQUIRED)]),
        patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path),
        patch.object(orch._batch._land_queue, "drain", return_value=[]),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_emit_event", lambda *a, **k: None),
        patch.object(orch._batch, "_emit_event", lambda *a, **k: None),
    ):
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
    (plans_dir / "bare-slug.md").write_text("---\nid: bare-slug\nkind: AFK\n---\n")
    abs_plan = tmp_path / "abs-plan.md"
    abs_plan.write_text("---\nid: abs-plan\nkind: AFK\n---\n")

    paths = [orch._utils.resolve_plan_ref(r) for r in ["bare-slug", str(abs_plan)]]
    assert len(paths) == 2


def test_orchestrate_dry_run_flag_skips_spawn(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "dry-plan", "AFK")

    with (
        patch.object(orch._batch, "_fan_out_plans") as mock_fan,
        patch.object(orch._batch, "_land_all", return_value=[]),
    ):
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

    with (
        patch.object(orch, "_emit_anchored_chunks", side_effect=fake_run_anchored),
        patch.object(orch._batch._land_queue, "drain", return_value=[]),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
    ):
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
        patch.object(orch._batch, "_fan_out_plans", return_value=[]) as mock_fan,
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._batch._land_queue, "drain", return_value=[{"status": "success", "slug": "chunk-afk"}]),
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

    with (
        patch.object(orch, "_emit_anchored_chunks", side_effect=fake_run_anchored),
        patch.object(orch._batch._land_queue, "drain", return_value=[]),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
    ):
        orch.run_orchestrate(
            holding="main",
            plan_paths=[plan],
            harness="cursor",
            model=None,
            dry_run=False,
        )

    assert captured and captured[0] == "cursor"


# ── B5: diff suggestion is raw git diff ───────────────────────────────────────


def test_run_orchestrate_diff_suggestion_is_raw_git_diff(tmp_path, capsys):
    orch = load_module("orchestrate")

    plan = _make_plan_file(tmp_path, "diff-plan", "AFK")

    with (
        patch.object(orch._batch, "_fan_out_plans", return_value=[]),
        patch.object(orch._batch._land_queue, "drain", return_value=[{"slug": "diff-plan", "status": "success"}]),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
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


# ── eject summary: drain-carried eject reasons are named on stderr ───────────


def test_run_orchestrate_prints_drain_eject_reasons(tmp_path, capsys):
    """A land-queue eject verdict in drain_results is printed as `slug — reason`."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    fail = _make_plan_file(tmp_path, "p-fail", "AFK")
    land = _make_plan_file(tmp_path, "p-land", "AFK")
    bind_plan("p-fail")
    bind_plan("p-land")
    fail_obj = routing.Plan(slug="p-fail", kind="AFK", blocked_by=[], path=fail)
    land_obj = routing.Plan(slug="p-land", kind="AFK", blocked_by=[], path=land)

    drain_out = [{"slug": "p-land", "status": "eject", "reason": "gate_failed"}]

    with (
        patch.object(orch._batch, "_fan_out_plans", return_value=[(fail_obj, 1), (land_obj, 0)]),
        patch.object(
            orch._batch,
            "_worktree_for_slug",
            side_effect=lambda s: tmp_path / ".mentat" / "worktrees" / TEST_CHUNK_ID / s,
        ),
        patch.object(orch._batch._land_queue, "drain", return_value=drain_out),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_emit_event", lambda *a, **k: None),
        patch.object(orch._batch, "_emit_event", lambda *a, **k: None),
    ):
        rc = orch.run_orchestrate(
            holding="main",
            plan_paths=[fail, land],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 1
    err = capsys.readouterr().err
    # drain-carried eject → slug + reason line
    assert "ejected p-land — gate_failed" in err, err
    # partition-ejected slug (not in drain) → bare slug line
    assert "ejected p-fail" in err, err


# ── anchored cascade victims are emitted as UPSTREAM_EJECTED ──────────────────


def test_run_orchestrate_emits_upstream_ejected_for_anchored_cascade(tmp_path):
    """When an auto upstream ejects, an anchored downstream victim is emitted."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    # Y (auto) — no HITL relation.  Z (HITL, anchored).  X (AFK, blocked_by Y+Z)
    # → anchored via upstream-HITL.  Ejecting Y cascades onto anchored X.
    y = routing.Plan(slug="y", kind="AFK", blocked_by=[], path=tmp_path / "y.md")
    z = routing.Plan(slug="z", kind="HITL", blocked_by=[], path=tmp_path / "z.md")
    x = routing.Plan(slug="x", kind="AFK", blocked_by=["y", "z"], path=tmp_path / "x.md")

    emitted: list[tuple[str, dict]] = []

    with (
        patch.object(orch, "_load_plans", return_value=[y, z, x]),
        patch.object(orch, "_emit_anchored_chunks", lambda *a, **k: []),
        patch.object(orch._batch, "_fan_out_plans", return_value=[(y, 1)]),
        patch.object(
            orch._batch,
            "_worktree_for_slug",
            side_effect=lambda s: tmp_path / ".mentat" / "worktrees" / TEST_CHUNK_ID / s,
        ),
        patch.object(orch._batch._land_queue, "drain", return_value=[]),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))),
        patch.object(orch._batch, "_emit_event", lambda ev, p: emitted.append((ev, p))),
    ):
        rc = orch.run_orchestrate(
            holding="main",
            plan_paths=[tmp_path / "batch.md"],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 1
    upstream = [p for ev, p in emitted if ev == "chunk_ejected" and p.get("reason") == "upstream_ejected"]
    assert any(p["slug"] == "x" for p in upstream), f"anchored victim x not emitted: {emitted}"


# ── build_parser + main() dispatch ───────────────────────────────────────────


def test_build_parser_accepts_all_subcommands():
    orch = load_module("orchestrate")
    parser = orch.build_parser()

    assert parser.parse_args(["run", "main", "slug-a"]).cmd == "run"
    assert parser.parse_args(["fan-out", "slug-a"]).cmd == "fan-out"
    assert parser.parse_args(["land-queue", "main"]).cmd == "land-queue"
    assert parser.parse_args(["batch-review", "sess-1"]).cmd == "batch-review"


def test_main_run_dispatches_to_run_orchestrate(monkeypatch, tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "run-plan", "AFK")

    monkeypatch.setattr(orch.sys, "argv", ["mentat-orchestrate", "run", "main", str(plan)])
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", lambda r: Path(r))

    seen: dict[str, object] = {}

    def fake_run(holding, plan_paths, *, harness, model, dry_run):
        seen.update(holding=holding, plans=plan_paths, harness=harness, model=model, dry_run=dry_run)
        return 0

    with patch.object(orch, "run_orchestrate", side_effect=fake_run):
        with pytest.raises(SystemExit) as exc:
            orch.main()

    assert exc.value.code == 0
    assert seen["holding"] == "main"


def test_main_fan_out_spawns_each_plan(monkeypatch, tmp_path):
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan_obj = routing.Plan(slug="fo", kind="AFK", blocked_by=[], path=tmp_path / "fo.md")

    monkeypatch.setattr(orch.sys, "argv", ["mentat-orchestrate", "fan-out", "fo"])
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", lambda r: tmp_path / f"{r}.md")

    spawned: list[str] = []
    with (
        patch.object(orch, "_load_plans", return_value=[plan_obj]),
        patch.object(orch._spawn, "spawn", side_effect=lambda p: spawned.append(p.slug)),
    ):
        orch.main()

    assert spawned == ["fo"]


def test_main_land_queue_reads_stdin_and_prints_json(monkeypatch, capsys):
    orch = load_module("orchestrate")

    monkeypatch.setattr(orch.sys, "argv", ["mentat-orchestrate", "land-queue", "main"])
    monkeypatch.setattr(orch.sys, "stdin", io.StringIO("slug-a\n\nslug-b\n"))
    # slugs resolve to non-existent paths → lq_plans falls back to None.
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", lambda s: Path(f"/nonexistent/{s}.md"))

    with patch.object(orch._batch, "_land_all", return_value=[{"slug": "slug-a", "status": "success"}]) as mock_land:
        orch.main()

    args, kwargs = mock_land.call_args
    assert args[0] == ["slug-a", "slug-b"]
    assert kwargs["plans"] is None
    out = capsys.readouterr().out
    assert '"slug-a"' in out and '"success"' in out


def test_main_land_queue_resolves_existing_plans(monkeypatch, tmp_path):
    orch = load_module("orchestrate")
    existing = _make_plan_file(tmp_path, "real-slug", "AFK")

    monkeypatch.setattr(orch.sys, "argv", ["mentat-orchestrate", "land-queue", "main"])
    monkeypatch.setattr(orch.sys, "stdin", io.StringIO("real-slug\n"))
    monkeypatch.setattr(orch._utils, "resolve_plan_ref", lambda s: existing)

    captured: dict[str, object] = {}
    with (
        patch.object(orch, "_load_plans", return_value=["PLAN"]) as mock_load,
        patch.object(
            orch._batch, "_land_all", side_effect=lambda slugs, *, holding, plans: captured.update(plans=plans) or []
        ),
    ):
        orch.main()

    mock_load.assert_called_once()
    assert captured["plans"] == ["PLAN"]


def test_main_unknown_cmd_falls_through_cleanly(monkeypatch):
    """A cmd matching no branch falls through main() without dispatching or raising."""
    orch = load_module("orchestrate")

    class _Args:
        cmd = "mystery"

    class _Parser:
        def parse_args(self):
            return _Args()

    monkeypatch.setattr(orch, "build_parser", lambda: _Parser())
    # No dispatch branch should fire.
    with patch.object(orch, "run_orchestrate", side_effect=AssertionError("must not run")):
        orch.main()  # must return without error


def test_main_batch_review_emits_event(monkeypatch):
    orch = load_module("orchestrate")

    monkeypatch.setattr(orch.sys, "argv", ["mentat-orchestrate", "batch-review", "sess-xyz"])

    events: list[tuple] = []
    with patch.object(orch._utils, "emit_event", side_effect=lambda ev, p: events.append((ev, p))):
        orch.main()

    assert events and events[0][0] == "batch_reviewed"
    assert events[0][1]["session"] == "sess-xyz"
