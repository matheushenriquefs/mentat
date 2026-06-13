"""Tests for tasks.py — next-id and create subcommands (slice port-tasks-create)."""

from __future__ import annotations

import importlib.util
import re
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[1]
_SCRIPTS = _SKILL_DIR / "scripts"
_AGENTS_DIR = _SKILL_DIR.parents[1]  # .agents/

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


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


RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# --- next-id ---


def test_next_id_empty_dir(td: Path) -> None:
    u = _reload("utils")
    assert u.next_id(td) == "T001"


def test_next_id_with_existing(td: Path) -> None:
    (td / "T001-a.md").touch()
    (td / "T003-c.md").touch()
    u = _reload("utils")
    assert u.next_id(td) == "T004"


def test_next_id_zero_pad(td: Path) -> None:
    (td / "T009-x.md").touch()
    u = _reload("utils")
    assert u.next_id(td) == "T010"


# --- create ---


def test_create_writes_file_with_frontmatter(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("# My task\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["create", "my-slug"])
    created = td / "T001-my-slug.md"
    assert created.exists()
    from lib import frontmatter

    fm, _ = frontmatter.parse(created.read_text())
    assert fm["id"] == "T001"
    assert fm["status"] == "todo"
    assert fm.get("claimed_by", "") == ""
    assert fm.get("claim_expires_at", "") == ""
    assert RFC3339_RE.match(fm["created_at"])


def test_create_emits_task_created_via_bind(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("# body\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn") as mock_spawn:
        t.main(["create", "my-slug"])
    mock_spawn.assert_called_once_with("mentat-tasks", "task.created", {"id": "T001", "slug": "my-slug"})


def test_create_rejects_existing_file(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (td / "T001-my-slug.md").write_text("---\nid: T001\nstatus: todo\n---\n# existing\n")
    monkeypatch.setattr("sys.stdin", StringIO("# new\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn"), pytest.raises(SystemExit) as exc_info:
        t.main(["create", "my-slug"])
    assert exc_info.value.code != 0
