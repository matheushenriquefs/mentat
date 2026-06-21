"""Slice 1: _load_plans expands parent-index plans into their listed siblings.

A plan with siblings: [a, b] in frontmatter is a parent index — not a runnable
slice. _load_plans replaces it with the sibling plans, in order. The parent slug
does not appear in the result. Nested parent indexes (sibling itself has siblings)
are rejected with SystemExit(65).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    key = f"mentat-orchestrate.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parent_index_expands_to_siblings(tmp_path):
    orchestrate = _load("orchestrate")

    parent = tmp_path / "parent.md"
    a_plan = tmp_path / "a.md"
    b_plan = tmp_path / "b.md"

    parent.write_text("---\nid: parent\nstatus: ready\nclass: AFK\nblocked_by: []\nsiblings: [a, b]\n---\n# Parent\n")
    a_plan.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")
    b_plan.write_text("---\nid: b\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# b\n")

    plans = orchestrate._load_plans([parent])
    slugs = [p.slug for p in plans]

    assert slugs == ["a", "b"], f"expected ['a', 'b'], got {slugs}"
    assert "parent" not in slugs


def test_parent_not_present_in_result(tmp_path):
    orchestrate = _load("orchestrate")

    parent = tmp_path / "parent.md"
    a_plan = tmp_path / "a.md"

    parent.write_text("---\nid: parent\nstatus: ready\nclass: AFK\nblocked_by: []\nsiblings: [a]\n---\n")
    a_plan.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n")

    plans = orchestrate._load_plans([parent])
    slugs = [p.slug for p in plans]

    assert "parent" not in slugs
    assert "a" in slugs


def test_plan_without_siblings_unchanged(tmp_path):
    orchestrate = _load("orchestrate")

    plan = tmp_path / "plain.md"
    plan.write_text("---\nid: plain\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n")

    plans = orchestrate._load_plans([plan])
    assert len(plans) == 1
    assert plans[0].slug == "plain"


def test_nested_parent_index_raises_exit_65(tmp_path, capsys):
    orchestrate = _load("orchestrate")

    parent = tmp_path / "parent.md"
    child = tmp_path / "child.md"
    grandchild = tmp_path / "grandchild.md"

    parent.write_text("---\nid: parent\nstatus: ready\nclass: AFK\nblocked_by: []\nsiblings: [child]\n---\n")
    child.write_text("---\nid: child\nstatus: ready\nclass: AFK\nblocked_by: []\nsiblings: [grandchild]\n---\n")
    grandchild.write_text("---\nid: grandchild\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n")

    with pytest.raises(SystemExit) as exc_info:
        orchestrate._load_plans([parent])
    assert exc_info.value.code == 65
    captured = capsys.readouterr()
    assert "nested parent index" in captured.err
    assert "child" in captured.err
