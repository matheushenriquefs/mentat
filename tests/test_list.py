"""Tests for tasks.py — list subcommand (slice port-tasks-list)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


def _make_task(td: Path, tid: str, slug: str, status: str, cls: str = "AFK") -> Path:
    p = td / f"{tid}-{slug}.md"
    p.write_text(f"---\nid: {tid}\nstatus: {status}\nclass: {cls}\nclaimed_by: \nclaim_expires_at: \n---\n# {slug}\n")
    return p


def test_list_empty_dir(td: Path, capsys: pytest.CaptureFixture[str]) -> None:
    t = _reload("tasks")
    t.main(["list"])
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_list_shows_id_status_class_claimed_by(td: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_task(td, "T001", "alpha", "todo", "AFK")
    _make_task(td, "T002", "beta", "in-progress", "HITL")
    _make_task(td, "T003", "gamma", "done", "AFK")
    t = _reload("tasks")
    t.main(["list"])
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 3
    # ordered by id
    assert lines[0].startswith("T001")
    assert lines[1].startswith("T002")
    assert lines[2].startswith("T003")
    # TSV columns: id  status  class  claimed_by
    cols = lines[1].split("\t")
    assert cols[0] == "T002"
    assert cols[1] == "in-progress"
    assert cols[2] == "HITL"
    assert cols[3] == ""


def test_list_filter_status(td: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_task(td, "T001", "alpha", "todo")
    _make_task(td, "T002", "beta", "done")
    _make_task(td, "T003", "gamma", "todo")
    t = _reload("tasks")
    t.main(["list", "--status", "todo"])
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 2
    ids = [line.split("\t")[0] for line in lines]
    assert "T001" in ids
    assert "T003" in ids
    assert "T002" not in ids
