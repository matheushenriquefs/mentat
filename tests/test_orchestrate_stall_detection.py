"""LQ4: run_orchestrate returns 1 when drain emits a stalled verdict."""

from __future__ import annotations

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


def test_run_orchestrate_returns_1_on_stalled_drain(tmp_path: Path) -> None:
    """run_orchestrate exits 1 when drain returns a stalled result."""
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "stall-plan")

    stalled_results = [{"slug": None, "status": "stalled", "pending": ["stall-plan"]}]

    with patch.object(orch, "_fan_out_plans", return_value=[]):
        with patch.object(orch._land_queue, "drain", return_value=stalled_results):
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

    assert rc == 1, f"expected rc=1 on stalled drain, got rc={rc}"


def test_run_orchestrate_returns_0_on_no_stall(tmp_path: Path) -> None:
    """run_orchestrate exits 0 when drain succeeds and no ejections."""
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "ok-plan")

    success_results = [{"slug": "ok-plan", "status": "success", "tip": "abc123"}]

    with patch.object(orch, "_fan_out_plans", return_value=[]):
        with patch.object(orch._land_queue, "drain", return_value=success_results):
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

    assert rc == 0, f"expected rc=0 on success drain, got rc={rc}"
