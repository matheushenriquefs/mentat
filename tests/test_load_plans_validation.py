"""LQ5: _load_plans validates blocked_by refs and handles external deps."""

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


def test_load_plans_warns_on_out_of_batch_blocked_by_ref(tmp_path: Path, capsys) -> None:
    """Out-of-batch blocked_by slug warns but loads — LQ1 treats it as external dep."""
    orch = load_module("orchestrate")
    plan_a = _make_plan(tmp_path, "plan-a", blocked_by=["prior-batch-slug"])

    plans = orch._load_plans([plan_a])

    assert len(plans) == 1
    assert plans[0].slug == "plan-a"
    err = capsys.readouterr().err
    assert "prior-batch-slug" in err, f"warning must name the unknown slug; stderr={err!r}"


def test_load_plans_exits_65_on_parent_index_blocked_by(tmp_path: Path) -> None:
    """Blocking on a parent-index slug still exits 65 — always invalid."""
    orch = load_module("orchestrate")
    # Write parent as a parent-index (with siblings list).
    _make_plan(tmp_path, "sib")
    parent = tmp_path / "parent-idx.md"
    parent.write_text("---\nid: parent-idx\nclass: AFK\nblocked_by: []\nsiblings: [sib]\n---\n")
    blocker = _make_plan(tmp_path, "child", blocked_by=["parent-idx"])

    with pytest.raises(SystemExit) as exc_info:
        orch._load_plans([parent, blocker])

    assert exc_info.value.code == 65, f"expected exit 65 for parent-index dep, got {exc_info.value.code}"


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
