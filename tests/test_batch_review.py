"""batch_reviewed event: run_orchestrate emits it after land, advisory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_run_orchestrate_emits_batch_reviewed(tmp_path):
    orch = load_module("orchestrate")
    plan = tmp_path / "p.md"
    plan.write_text("---\nid: p\nclass: AFK\nblocked_by: []\n---\n")

    emitted: list[str] = []

    with (
        patch.object(orch, "_fan_out_plans", return_value=[]),
        patch.object(orch._land_queue, "drain", return_value=[]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda **kw: None),
        patch.object(orch._utils, "emit_event", side_effect=lambda e, p: emitted.append(e)),
    ):
        orch.run_orchestrate("main", [plan], harness=None, model=None, dry_run=False)

    assert any("batch_reviewed" in e for e in emitted)
