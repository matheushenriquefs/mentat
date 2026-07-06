"""E2E: the full mentat-tasks lifecycle driven in-process over a temp task store.

Drives the actual ``tasks.py`` CLI through its real ``main(argv)`` dispatch across the
whole vertical: create → list → claim → refresh → done, plus release and wontfix. The
create/claim/done paths emit through the real ``mentat-log`` subprocess (session state
pointed at tmp, HOME left real so the emitter resolves), so the audit trail is written for
real. Asserts on-disk frontmatter transitions, the claim lockfile lifecycle, and the
emitted task.* audit rows. In-process so the tasks dispatch is measured.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from tests.conftest import event_kinds, load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_PY = REPO_ROOT / ".agents/skills/mentat-tasks/scripts/tasks.py"
_frontmatter = load_script(REPO_ROOT / ".agents/lib/frontmatter.py", "e2e_frontmatter")


@pytest.fixture
def store(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "tasks"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_TASKS_DIR", str(tasks_dir))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "taskrepo")
    monkeypatch.setenv("MENTAT_SESSION", "orchestrate-main-1")
    return tasks_dir, log_root


def _tasks():
    return load_script(TASKS_PY, "e2e_tasks")


def _run(t, argv: list[str], *, stdin: str = "") -> int:
    """Run one tasks subcommand through its real main() dispatch, returning rc (0 on clean)."""
    import sys

    saved = sys.stdin
    sys.stdin = StringIO(stdin)
    try:
        t.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.stdin = saved
    return 0


def _fm(path: Path) -> dict[str, str]:
    fm, _ = _frontmatter.parse(path.read_text())
    return fm


def _emitted_events(session_id: str) -> list[str]:
    return event_kinds(session_id)


def test_tasks_create_claim_refresh_done_lifecycle(store, capsys):
    tasks_dir, log_root = store
    t = _tasks()

    assert _run(t, ["create", "add-widget"], stdin="# Add a widget\n") == 0
    task_file = tasks_dir / "T001-add-widget.md"
    assert task_file.exists()
    assert _fm(task_file)["status"] == "todo"

    # list surfaces the todo task.
    capsys.readouterr()
    assert _run(t, ["list"]) == 0
    out = capsys.readouterr().out
    assert "T001" in out and "todo" in out

    # claim: status → in-progress, claimed_by set, a lockfile appears.
    assert _run(t, ["claim", str(task_file), "agent-x", "600"]) == 0
    fm = _fm(task_file)
    assert fm["status"] == "in-progress"
    assert fm["claimed_by"] == "agent-x"
    assert fm["claim_expires_at"]
    lock = task_file.with_suffix(".md.lock")
    assert lock.exists(), "claim must create a lockfile"

    # a second claim on the held task is refused.
    assert _run(t, ["claim", str(task_file), "agent-y", "600"]) == 1
    assert "already claimed" in capsys.readouterr().err

    # refresh bumps the expiry.
    old_expiry = _fm(task_file)["claim_expires_at"]
    assert _run(t, ["refresh", str(task_file), "3600"]) == 0
    assert _fm(task_file)["claim_expires_at"] >= old_expiry

    # done: terminal transition clears the claim and drops the lock.
    assert _run(t, ["done", str(task_file)]) == 0
    fm = _fm(task_file)
    assert fm["status"] == "done"
    assert fm["claimed_by"] == ""
    assert not lock.exists(), "done must release the lock"

    # --status filter narrows list output.
    capsys.readouterr()
    assert _run(t, ["list", "--status", "done"]) == 0
    assert "T001" in capsys.readouterr().out
    assert _run(t, ["list", "--status", "todo"]) == 0
    assert "T001" not in capsys.readouterr().out

    events = _emitted_events("orchestrate-main-1")
    assert "task_created" in events
    assert "task_claimed" in events
    assert "task_resolved" in events


def test_tasks_release_returns_to_todo(store):
    tasks_dir, log_root = store
    t = _tasks()

    _run(t, ["create", "flaky"], stdin="# flaky\n")
    task_file = tasks_dir / "T001-flaky.md"
    _run(t, ["claim", str(task_file), "agent-x", "600"])

    assert _run(t, ["release", str(task_file)]) == 0
    fm = _fm(task_file)
    assert fm["status"] == "todo"
    assert fm["claimed_by"] == ""
    assert not task_file.with_suffix(".md.lock").exists()
    assert "task_released" in _emitted_events("orchestrate-main-1")


def test_tasks_wontfix_after_claim(store):
    tasks_dir, log_root = store
    t = _tasks()

    _run(t, ["create", "obsolete"], stdin="# obsolete\n")
    task_file = tasks_dir / "T001-obsolete.md"
    _run(t, ["claim", str(task_file), "agent-x", "600"])

    assert _run(t, ["wontfix", str(task_file)]) == 0
    assert _fm(task_file)["status"] == "wontfix"
    assert "task_canceled" in _emitted_events("orchestrate-main-1")


def test_tasks_done_on_todo_is_illegal(store, capsys):
    tasks_dir, _ = store
    t = _tasks()

    _run(t, ["create", "unclaimed"], stdin="# unclaimed\n")
    task_file = tasks_dir / "T001-unclaimed.md"

    assert _run(t, ["done", str(task_file)]) == 1
    assert "illegal transition" in capsys.readouterr().err
    assert _fm(task_file)["status"] == "todo"


def test_tasks_refresh_without_claim_errors(store, capsys):
    tasks_dir, _ = store
    t = _tasks()
    _run(t, ["create", "cold"], stdin="# cold\n")
    task_file = tasks_dir / "T001-cold.md"
    assert _run(t, ["refresh", str(task_file), "600"]) == 1
    assert "no active claim" in capsys.readouterr().err


def test_tasks_next_id_and_duplicate_slug(store, capsys):
    tasks_dir, _ = store
    t = _tasks()

    capsys.readouterr()
    assert _run(t, ["next-id"]) == 0
    assert capsys.readouterr().out.strip() == "T001"

    _run(t, ["create", "dup"], stdin="# a\n")
    assert _run(t, ["create", "dup"], stdin="# b\n") == 1
    assert "already exists" in capsys.readouterr().err

    assert _run(t, ["next-id"]) == 0
    assert capsys.readouterr().out.strip() == "T002"
