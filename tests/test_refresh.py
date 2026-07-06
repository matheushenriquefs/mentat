"""Tests for tasks.py — refresh subcommand (slice port-tasks-refresh)."""

from __future__ import annotations

import importlib.util
import sys
import time
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
        t.main(["claim", str(p), "agent-a", "10"])
    return p


def test_refresh_bumps_expiry(claimed_file: Path) -> None:
    from lib.support import frontmatter

    fm_before, _ = frontmatter.parse(claimed_file.read_text())
    old_expiry = fm_before["claim_expires_at"]

    time.sleep(1)

    t = _reload("tasks")
    t.main(["refresh", str(claimed_file), "600"])

    fm_after, _ = frontmatter.parse(claimed_file.read_text())
    new_expiry = fm_after["claim_expires_at"]

    assert new_expiry != old_expiry
    assert new_expiry > old_expiry


def test_refresh_requires_existing_claim(td: Path) -> None:
    p = td / "T001-x.md"
    p.write_text("---\nid: T001\nstatus: todo\nclaimed_by: \nclaim_expires_at: \n---\n# x\n")
    t = _reload("tasks")
    with pytest.raises(SystemExit) as exc_info:
        t.main(["refresh", str(p), "600"])
    assert exc_info.value.code != 0


def test_refresh_no_event(claimed_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn") as mock_spawn:
        t.main(["refresh", str(claimed_file), "600"])
    mock_spawn.assert_not_called()
