"""Tests for tasks.py — next-id and create subcommands (slice port-tasks-create)."""

from __future__ import annotations

import importlib.util
import re
import sys
from io import StringIO
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


RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# --- next-id ---


def test_next_id_empty_dir(td: Path) -> None:
    u = _reload("lifecycle")
    assert u.next_id(td) == "T001"


def test_next_id_with_existing(td: Path) -> None:
    (td / "T001-a.md").touch()
    (td / "T003-c.md").touch()
    u = _reload("lifecycle")
    assert u.next_id(td) == "T004"


def test_next_id_zero_pad(td: Path) -> None:
    (td / "T009-x.md").touch()
    u = _reload("lifecycle")
    assert u.next_id(td) == "T010"


# --- create ---


def test_create_writes_file_with_frontmatter(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("# My task\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["create", "my-slug"])
    created = td / "T001-my-slug.md"
    assert created.exists()
    from lib.support import frontmatter

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
    mock_spawn.assert_called_once_with("mentat-tasks", "task_created", {"id": "T001", "slug": "my-slug"})


def test_create_rejects_existing_file(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (td / "T001-my-slug.md").write_text("---\nid: T001\nstatus: todo\n---\n# existing\n")
    monkeypatch.setattr("sys.stdin", StringIO("# new\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn"), pytest.raises(SystemExit) as exc_info:
        t.main(["create", "my-slug"])
    assert exc_info.value.code != 0


# --- next-id command dispatch ---


def test_next_id_command_missing_dir_prints_t001(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    tasks = tmp_path / "tasks-absent"  # not created
    monkeypatch.setenv("MENTAT_TASKS_DIR", str(tasks))
    t = _reload("tasks")
    assert t.cmd_next_id(None) == 0
    assert capsys.readouterr().out.strip() == "T001"


def test_next_id_command_existing_dir_prints_next(td: Path, capsys) -> None:
    (td / "T005-x.md").touch()
    t = _reload("tasks")
    assert t.cmd_next_id(None) == 0
    assert capsys.readouterr().out.strip() == "T006"


# --- create cleans up tmp on write failure ---


def test_create_cleans_tmp_on_write_failure(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("# body\n"))
    t = _reload("tasks")
    with (
        patch("lib.events._spawn"),
        patch.object(t.os, "replace", side_effect=OSError("disk full")),
        pytest.raises(OSError),
    ):
        t.main(["create", "boom-slug"])
    assert not list(td.glob("*.tmp")), "temp file must be cleaned up"


# --- main with no subcommand ---


def test_main_no_subcommand_exits_usage() -> None:
    t = _reload("tasks")
    with pytest.raises(SystemExit) as exc_info:
        t.main([])
    assert exc_info.value.code == t.EX_USAGE


# --- sys.path bootstrap ---


def test_tasks_inserts_agents_dir_on_sys_path(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _reload("tasks")
    parent = str(t._AGENTS_DIR)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != parent])
    reloaded = _reload("tasks")  # re-exec bootstrap with parent absent
    assert str(reloaded._AGENTS_DIR) in sys.path


# --- lifecycle: default tasks_dir + non-numeric stem skip ---


def test_tasks_dir_defaults_to_cwd_mentat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    u = _reload("lifecycle")
    monkeypatch.delenv("MENTAT_TASKS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert u.tasks_dir() == tmp_path / ".mentat" / "tasks"


def test_next_id_skips_non_numeric_stem(td: Path) -> None:
    u = _reload("lifecycle")
    (td / "T001-a.md").touch()
    (td / "Tbad-x.md").touch()  # glob-matches but stem not T+digits → skipped
    assert u.next_id(td) == "T002"
