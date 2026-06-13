"""Slice 2: _load_plans enforces three guards on parent-index plans.

Guard 1 (exit 65): parent with both siblings: and blocked_by: non-empty.
Guard 2 (exit 65): any plan's blocked_by references a parent-index slug.
Guard 3 (exit 66): a listed sibling plan file does not exist on disk.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    key = f"mentat-orchestrate.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Guard 1: siblings + blocked_by both non-empty → exit 65 ─────────────────


def test_parent_with_siblings_and_blocked_by_exits_65(tmp_path, capsys):
    orchestrate = _load("orchestrate")

    parent = tmp_path / "parent.md"
    a_plan = tmp_path / "a.md"
    c_plan = tmp_path / "c.md"

    parent.write_text("---\nid: parent\nstatus: ready\nclass: AFK\nblocked_by: [c]\nsiblings: [a]\n---\n")
    a_plan.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n")
    c_plan.write_text("---\nid: c\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n")

    with pytest.raises(SystemExit) as exc_info:
        orchestrate._load_plans([parent, a_plan, c_plan])
    assert exc_info.value.code == 65
    assert "parent index must have empty blocked_by" in capsys.readouterr().err


# ── Guard 2: plan's blocked_by references a parent-index slug → exit 65 ──────


def test_plan_blocking_on_parent_index_exits_65(tmp_path, capsys):
    orchestrate = _load("orchestrate")

    parent = tmp_path / "parent.md"
    a_plan = tmp_path / "a.md"
    c_plan = tmp_path / "c.md"

    parent.write_text("---\nid: parent\nstatus: ready\nclass: AFK\nblocked_by: []\nsiblings: [a]\n---\n")
    a_plan.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n")
    c_plan.write_text("---\nid: c\nstatus: ready\nclass: AFK\nblocked_by: [parent]\n---\n")

    with pytest.raises(SystemExit) as exc_info:
        orchestrate._load_plans([parent, c_plan])
    assert exc_info.value.code == 65
    assert "cannot block on parent index" in capsys.readouterr().err


# ── Guard 3: sibling file not found → exit 66 ────────────────────────────────


def test_missing_sibling_plan_exits_66(tmp_path, capsys):
    orchestrate = _load("orchestrate")

    parent = tmp_path / "parent.md"

    parent.write_text("---\nid: parent\nstatus: ready\nclass: AFK\nblocked_by: []\nsiblings: [missing]\n---\n")

    with pytest.raises(SystemExit) as exc_info:
        orchestrate._load_plans([parent])
    assert exc_info.value.code == 66
    assert "sibling plan not found: missing" in capsys.readouterr().err
