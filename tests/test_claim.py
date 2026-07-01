"""Tests for tasks.py — claim + release subcommands (slice port-tasks-claim)."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import threading
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
def task_file(td: Path) -> Path:
    p = td / "T001-x.md"
    p.write_text("---\nid: T001\nstatus: todo\nclaimed_by: \nclaim_expires_at: \n---\n# x\n")
    return p


RFC3339_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_claim_creates_lock_sentinel(task_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["claim", str(task_file), "agent-a", "600"])
    lock = task_file.with_suffix(".md.lock")
    assert lock.exists()
    from lib import frontmatter

    fm, _ = frontmatter.parse(task_file.read_text())
    assert fm["claimed_by"] == "agent-a"
    assert fm["status"] == "in-progress"
    assert RFC3339_RE.match(fm["claim_expires_at"])


def test_claim_already_claimed_exits_nonzero(task_file: Path) -> None:
    lock = task_file.with_suffix(".md.lock")
    lock.touch()  # pre-existing lock sentinel
    t = _reload("tasks")
    with patch("lib.events._spawn"), pytest.raises(SystemExit) as exc_info:
        t.main(["claim", str(task_file), "agent-b", "600"])
    assert exc_info.value.code != 0
    assert not task_file.read_text().__contains__("agent-b")


def test_claim_mutate_failure_releases_lock(task_file: Path) -> None:
    """If frontmatter.mutate raises after the lock is taken, the lock is cleaned up."""
    t = _reload("tasks")
    with (
        patch("lib.events._spawn"),
        patch.object(t.frontmatter, "mutate", side_effect=OSError("boom")),
        pytest.raises(OSError),
    ):
        t.main(["claim", str(task_file), "agent-a", "600"])
    lock = task_file.with_suffix(".md.lock")
    assert not lock.exists()


def test_claim_atomicity_under_race(task_file: Path) -> None:
    t = _reload("tasks")
    results: list[int] = []

    def try_claim() -> None:
        try:
            with patch("lib.events._spawn"):
                t.main(["claim", str(task_file), "agent-x", "600"])
            results.append(0)
        except SystemExit as e:
            results.append(e.code if isinstance(e.code, int) else 1)

    threads = [threading.Thread(target=try_claim) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert results.count(0) == 1, f"exactly one winner expected, got {results}"


def test_release_removes_lock_and_resets_fields(task_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["claim", str(task_file), "agent-a", "600"])
        t.main(["release", str(task_file)])
    lock = task_file.with_suffix(".md.lock")
    assert not lock.exists()
    from lib import frontmatter

    fm, _ = frontmatter.parse(task_file.read_text())
    assert fm["claimed_by"] == ""
    assert fm["claim_expires_at"] == ""
    assert fm["status"] == "todo"


def test_claim_emits_task_claimed(task_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn") as mock_spawn:
        t.main(["claim", str(task_file), "agent-a", "600"])
    from lib import frontmatter

    fm, _ = frontmatter.parse(task_file.read_text())
    expires = fm["claim_expires_at"]
    mock_spawn.assert_called_once_with(
        "mentat-tasks", "task.claimed", {"id": "T001", "agent": "agent-a", "expires_at": expires}
    )


def test_release_emits_task_released(task_file: Path) -> None:
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["claim", str(task_file), "agent-a", "600"])
    with patch("lib.events._spawn") as mock_spawn:
        t.main(["release", str(task_file)])
    mock_spawn.assert_called_once_with("mentat-tasks", "task.released", {"id": "T001"})


# ── LT2: session routing tests ───────────────────────────────────────────────


def test_cmd_create_sets_session_when_unset(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without MENTAT_SESSION, tasks calls ensure_session → MENTAT_SESSION set to mentat-tasks-*."""
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setattr(sys, "stdin", io.StringIO("# body\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["create", "test-task"])
    session = os.environ.get("MENTAT_SESSION")
    assert session is not None, "MENTAT_SESSION not set; ensure_session not called"
    assert session.startswith("mentat-tasks-"), f"unexpected session prefix: {session!r}"


def test_cmd_create_inherits_parent_session_unchanged(td: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With MENTAT_SESSION already set, ensure_session must not overwrite it."""
    monkeypatch.setenv("MENTAT_SESSION", "orchestrate-parent-999")
    monkeypatch.setattr(sys, "stdin", io.StringIO("# body\n"))
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["create", "test-task"])
    assert os.environ.get("MENTAT_SESSION") == "orchestrate-parent-999"


# ── LT3: state machine guard tests ───────────────────────────────────────────


def test_done_on_todo_task_errors(task_file: Path) -> None:
    """done on a todo task must be rejected — task must be in-progress first."""
    t = _reload("tasks")
    with patch("lib.events._spawn"), pytest.raises(SystemExit) as exc_info:
        t.main(["done", str(task_file)])
    assert exc_info.value.code != 0


def test_wontfix_on_todo_task_errors(task_file: Path) -> None:
    """wontfix on a todo task must be rejected."""
    t = _reload("tasks")
    with patch("lib.events._spawn"), pytest.raises(SystemExit) as exc_info:
        t.main(["wontfix", str(task_file)])
    assert exc_info.value.code != 0


def test_legal_path_todo_to_inprogress_to_done(task_file: Path) -> None:
    """Legal path: claim (todo→in-progress) then done (in-progress→done)."""
    t = _reload("tasks")
    with patch("lib.events._spawn"):
        t.main(["claim", str(task_file), "agent-a", "600"])
        t.main(["done", str(task_file)])
    from lib import frontmatter

    fm, _ = frontmatter.parse(task_file.read_text())
    assert fm["status"] == "done"
