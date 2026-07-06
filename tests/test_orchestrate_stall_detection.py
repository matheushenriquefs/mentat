"""LQ4: run_orchestrate returns 1 when drain emits a stalled verdict."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from lib.exits import EX_CONFIG

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan_file(tmp_path: Path, slug: str, kind: str = "AFK") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nkind: {kind}\n---\n")
    return p


def test_run_orchestrate_returns_1_on_stalled_drain(tmp_path: Path) -> None:
    """run_orchestrate exits 1 when drain returns a stalled result."""
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "stall-plan")

    stalled_results = [{"slug": None, "status": "stalled", "pending": ["stall-plan"]}]

    with patch.object(orch._batch, "_fan_out_plans", return_value=[]):
        with patch.object(orch, "ensure_session", return_value="orch-test"):
            with patch.object(orch._batch._land_queue, "drain", return_value=stalled_results):
                with patch.object(orch._batch, "_prune_stale_containers", lambda: None):
                    with patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None):
                        with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                            rc = orch.run_orchestrate(
                                holding="main",
                                plan_paths=[plan],
                                harness=None,
                                model=None,
                                dry_run=False,
                            )

    assert rc == 1, f"expected rc=1 on stalled drain, got rc={rc}"
    assert stalled_results[0]["pending"] == ["stall-plan"], (
        f"stalled result must carry pending list; got {stalled_results[0]}"
    )


def test_run_orchestrate_returns_0_on_no_stall(tmp_path: Path) -> None:
    """run_orchestrate exits 0 when drain succeeds and no ejections."""
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "ok-plan")

    success_results = [{"slug": "ok-plan", "status": "success", "tip": "abc123"}]

    with patch.object(orch._batch, "_fan_out_plans", return_value=[]):
        with patch.object(orch, "ensure_session", return_value="orch-test"):
            with patch.object(orch._batch._land_queue, "drain", return_value=success_results):
                with patch.object(orch._batch, "_prune_stale_containers", lambda: None):
                    with patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None):
                        with patch.object(orch._utils, "emit_event", lambda *a, **k: None):
                            rc = orch.run_orchestrate(
                                holding="main",
                                plan_paths=[plan],
                                harness=None,
                                model=None,
                                dry_run=False,
                            )

    assert rc == 0, f"expected rc=0 on success drain, got rc={rc}"


def test_run_orchestrate_fails_without_git_identity(tmp_path: Path, monkeypatch) -> None:
    orch = load_module("orchestrate")
    plan = _make_plan_file(tmp_path, "no-id-plan")
    monkeypatch.setattr(orch, "ensure_session", lambda *a, **k: "orch-test")
    monkeypatch.setattr(
        orch._git,
        "require_commit_identity",
        lambda **kw: (_ for _ in ()).throw(orch._git.GitError("missing")),
    )

    rc = orch.run_orchestrate(
        holding="main",
        plan_paths=[plan],
        harness=None,
        model=None,
        dry_run=False,
    )
    assert rc == EX_CONFIG
