"""E2E: the mentat-plan write + resolve-slug journey, driven in-process.

``main()`` runs through real argv dispatch: ``write`` copies a body file into the plans
dir and emits real chunk_started/agent_stopped audit rows through the mentat-log
subprocess; ``resolve-slug`` canonicalizes both a bare slug and an explicit path. Agent
state points at tmp so the audit trail is real; HOME stays real so the emitter resolves.
In-process so the plan dispatch is measured.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.conftest import event_kinds, load_script

pytestmark = pytest.mark.e2e

PLAN_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-plan/scripts/plan.py"


@pytest.fixture
def audit(tmp_path, monkeypatch):
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "planrepo")
    monkeypatch.setenv("MENTAT_AGENT", "orchestrate-main-1")
    return log_root


def _plan_events(agent_id: str) -> list[str]:
    return event_kinds(agent_id)


def _run_main(plan, argv: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["plan.py", *argv])
    try:
        plan.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_plan_write_lands_file_and_audit(tmp_path, audit, monkeypatch):
    plan = load_script(PLAN_PY, "e2e_plan_write")
    plans_dir = tmp_path / "plans"

    body = tmp_path / "body.md"
    body.write_text("---\nid: my-plan\nkind: AFK\n---\n# My plan\nDo the thing.\n")

    dest = plan.write_plan("my-plan", body, plans_dir=plans_dir)
    assert dest == plans_dir / "my-plan.md"
    assert dest.read_text() == body.read_text()

    # The handoff hint closes the plan → tasks loop.
    assert "/mentat-tasks my-plan" in plan.suggest_tasks("my-plan")


def test_plan_main_write_and_resolve_dispatch(tmp_path, audit, monkeypatch, capsys):
    plan = load_script(PLAN_PY, "e2e_plan_main")

    # write via main(): default plans dir is ~/.agents/plans — resolve-slug proves the mapping.
    by_slug = plan.resolve_plan("some-slug")
    assert by_slug == Path.home() / ".agents" / "plans" / "some-slug.md"

    # resolve-slug via main() prints the canonical path for an explicit .md.
    explicit = tmp_path / "elsewhere" / "p.md"
    explicit.parent.mkdir()
    explicit.write_text("body\n")
    capsys.readouterr()
    assert _run_main(plan, ["resolve-slug", str(explicit)], monkeypatch) == 0
    assert capsys.readouterr().out.strip() == str(explicit.resolve())


def test_plan_no_subcommand_exits_nonzero(audit, monkeypatch, capsys):
    plan = load_script(PLAN_PY, "e2e_plan_help")
    rc = _run_main(plan, [], monkeypatch)
    assert rc != 0
    assert "usage" in capsys.readouterr().out.lower()
