"""Tests for tasks.py — done + wontfix subcommands (slice port-tasks-terminal)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-tasks"
_SCRIPTS = _SKILL_DIR / "scripts"


def _reload(name: str):
    key = f"_tasks_{name}"
    spec = importlib.util.spec_from_file_location(key, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def td(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    monkeypatch.setenv("MENTAT_TASKS_DIR", str(tasks))
    return tasks


@pytest.fixture()
def claimed_file(td: Path) -> Path:
    p = td / "T001-x.md"
    p.write_text("---\nid: T001\nstatus: todo\nclaimed_by: \nclaim_expires_at: \n---\n# x\n")
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["claim", str(p), "agent-a", "600"])
    return p


def test_done_sets_status_and_clears_claim(claimed_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["done", str(claimed_file)])
    lock = claimed_file.with_suffix(".md.lock")
    assert not lock.exists()
    from lib import frontmatter

    fm, _ = frontmatter.parse(claimed_file.read_text())
    assert fm["status"] == "done"
    assert fm["claimed_by"] == ""
    assert fm["claim_expires_at"] == ""


def test_wontfix_sets_status_wontfix(claimed_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["wontfix", str(claimed_file)])
    lock = claimed_file.with_suffix(".md.lock")
    assert not lock.exists()
    from lib import frontmatter

    fm, _ = frontmatter.parse(claimed_file.read_text())
    assert fm["status"] == "wontfix"
    assert fm["claimed_by"] == ""
    assert fm["claim_expires_at"] == ""


def test_done_emits_task_done(claimed_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn") as mock_spawn:
        t.main(["done", str(claimed_file)])
    mock_spawn.assert_called_once_with("mentat-tasks", "task.done", {"id": "T001"})


def test_wontfix_emits_task_wontfix(claimed_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn") as mock_spawn:
        t.main(["wontfix", str(claimed_file)])
    mock_spawn.assert_called_once_with("mentat-tasks", "task.wontfix", {"id": "T001"})
