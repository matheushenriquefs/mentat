"""LQ5: _load_plans exits 65 on a blocked_by slug not found in the batch."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan(tmp_path: Path, slug: str, class_: str = "AFK", blocked_by: list[str] | None = None) -> Path:
    body = f"---\nid: {slug}\nclass: {class_}\n"
    if blocked_by:
        body += f"blocked_by: [{', '.join(blocked_by)}]\n"
    body += "---\n"
    p = tmp_path / f"{slug}.md"
    p.write_text(body)
    return p


def test_load_plans_exits_65_on_dangling_blocked_by_ref(tmp_path: Path) -> None:
    """A plan whose blocked_by slug is not in the batch exits 65."""
    orch = load_module("orchestrate")
    plan_a = _make_plan(tmp_path, "plan-a", blocked_by=["nonexistent-typo-slug"])

    with pytest.raises(SystemExit) as exc_info:
        orch._load_plans([plan_a])

    assert exc_info.value.code == 65, f"expected exit 65, got {exc_info.value.code}"


def test_load_plans_does_not_exit_on_valid_in_batch_blocked_by(tmp_path: Path) -> None:
    """A plan blocked_by another plan in the batch loads without error."""
    orch = load_module("orchestrate")
    plan_a = _make_plan(tmp_path, "plan-a")
    plan_b = _make_plan(tmp_path, "plan-b", blocked_by=["plan-a"])

    plans = orch._load_plans([plan_a, plan_b])

    assert len(plans) == 2
    slugs = {p.slug for p in plans}
    assert slugs == {"plan-a", "plan-b"}


def test_load_plans_does_not_exit_on_empty_blocked_by(tmp_path: Path) -> None:
    """A plan with no blocked_by loads cleanly."""
    orch = load_module("orchestrate")
    plan = _make_plan(tmp_path, "standalone")

    plans = orch._load_plans([plan])

    assert len(plans) == 1
    assert plans[0].slug == "standalone"
