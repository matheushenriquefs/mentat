"""Tests for mentat-orchestrate top-level CLI."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _make_plan_file(tmp_path: Path, slug: str, class_: str = "AFK") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nclass: {class_}\n---\n")
    return p


def test_orchestrate_full_pipeline_exits_0_on_all_success(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "plan-a", "AFK")

    with patch.object(orch, "_fan_out_plans", return_value=["chunk-a"]):
        with patch.object(orch, "_land_all", return_value=[{"outcome": "success", "slug": "chunk-a", "tip": "abc"}]):
            with patch.object(orch, "_final_review"):
                rc = orch.run_orchestrate(
                    holding="main",
                    plan_paths=[plan],
                    harness=None, model=None, dry_run=False,
                )
    assert rc == 0


def test_orchestrate_exits_1_on_any_ejection(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "plan-b", "AFK")

    with patch.object(orch, "_fan_out_plans", return_value=["chunk-b"]):
        with patch.object(orch, "_land_all", return_value=[{"outcome": "eject", "slug": "chunk-b", "reason": "gate-fail"}]):
            with patch.object(orch, "_final_review"):
                rc = orch.run_orchestrate(
                    holding="main",
                    plan_paths=[plan],
                    harness=None, model=None, dry_run=False,
                )
    assert rc == 1


def test_orchestrate_holding_positional_required():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "orchestrate.py"), "run"],
        capture_output=True, text=True,
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

    with patch.object(orch, "_fan_out_plans") as mock_fan:
        with patch.object(orch, "_land_all", return_value=[]):
            with patch.object(orch, "_final_review"):
                orch.run_orchestrate(
                    holding="main",
                    plan_paths=[plan],
                    harness=None, model=None, dry_run=True,
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

    with patch.object(orch, "_run_anchored_plans", side_effect=fake_run_anchored):
        with patch.object(orch, "_land_all", return_value=[{"outcome": "success", "slug": "chunk-hitl", "tip": "abc"}]):
            with patch.object(orch, "_final_review"):
                orch.run_orchestrate(
                    holding="main",
                    plan_paths=[hitl],
                    harness=None, model=None, dry_run=False,
                )

    assert anchored_calls


def test_orchestrate_auto_spawn_runs_headless(tmp_path):
    orch = load_module("orchestrate")
    afk = _make_plan_file(tmp_path, "afk-plan", "AFK")

    with patch.object(orch, "_fan_out_plans") as mock_fan:
        mock_fan.return_value = ["chunk-afk"]
        with patch.object(orch, "_land_all", return_value=[{"outcome": "success", "slug": "chunk-afk", "tip": "abc"}]):
            with patch.object(orch, "_final_review"):
                orch.run_orchestrate(
                    holding="main",
                    plan_paths=[afk],
                    harness=None, model=None, dry_run=False,
                )

    mock_fan.assert_called_once()


def test_orchestrate_harness_flag_overrides_config(tmp_path):
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "plan-h", "HITL")

    captured: list[str] = []

    def fake_run_anchored(plans, *, harness, model):
        captured.append(harness)
        return []

    with patch.object(orch, "_run_anchored_plans", side_effect=fake_run_anchored):
        with patch.object(orch, "_land_all", return_value=[]):
            with patch.object(orch, "_final_review"):
                orch.run_orchestrate(
                    holding="main",
                    plan_paths=[plan],
                    harness="cursor", model=None, dry_run=False,
                )

    assert captured and captured[0] == "cursor"
