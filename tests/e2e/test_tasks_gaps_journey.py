"""E2E gap-closer: tasks CLI error/edge arms the main journey test skips.

Companion to ``test_tasks_journey.py``. Reaches the create/claim failure
rollback arms (temp-file cleanup on os.replace failure, lock release on a
mutate failure), the empty/garbage-store list arms, and the no-subcommand
help+usage-exit path — over real temp task stores. In-process.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_PY = REPO_ROOT / ".agents/skills/mentat-tasks/scripts/tasks.py"


@pytest.fixture
def store(tmp_path, monkeypatch):
    tasks_dir = tmp_path / "tasks"
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_TASKS_DIR", str(tasks_dir))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "taskrepo")
    monkeypatch.setenv("MENTAT_AGENT", "orchestrate-main-gaps")
    return tasks_dir, log_root


def _tasks():
    return load_script(TASKS_PY, "e2e_tasks_gaps")


def _run(t, argv: list[str], *, stdin: str = "") -> int:
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


# ── cmd_create: os.replace failure rolls back the temp file (66-68) ───────────


def test_create_rolls_back_temp_file_on_replace_failure(store, monkeypatch):
    tasks_dir, _ = store
    t = _tasks()

    def boom(*_a, **_k):
        raise OSError("replace failed")

    monkeypatch.setattr(t.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        _run(t, ["create", "doomed"], stdin="# doomed\n")

    # The rollback unlinked the temp file — no leftover .tmp litters the store,
    # and the real task file was never created.
    assert list(tasks_dir.glob(".*.tmp")) == []
    assert list(tasks_dir.glob("T*-doomed.md")) == []


# ── cmd_claim: mutate failure releases the lock (88-90) ───────────────────────


def test_claim_releases_lock_when_mutate_fails(store, monkeypatch):
    tasks_dir, _ = store
    t = _tasks()

    _run(t, ["create", "flappy"], stdin="# flappy\n")
    task_file = tasks_dir / "T001-flappy.md"

    def boom(*_a, **_k):
        raise RuntimeError("mutate failed")

    monkeypatch.setattr(t.frontmatter, "mutate", boom)
    with pytest.raises(RuntimeError, match="mutate failed"):
        _run(t, ["claim", str(task_file), "agent-x", "600"])

    # The except arm removed the lockfile it had just created, so the task is
    # claimable again rather than stuck behind a stale lock.
    assert not task_file.with_suffix(".md.lock").exists()


# ── cmd_list: nonexistent store → clean rc 0, no output (101) ─────────────────


def test_list_on_missing_store_is_clean_noop(store, capsys):
    _tasks_dir, _ = store
    t = _tasks()
    capsys.readouterr()
    assert _run(t, ["list"]) == 0
    assert capsys.readouterr().out == ""


# ── cmd_list: a file whose T-prefix isn't numeric is skipped (107) ────────────


def test_list_skips_non_numeric_id_files(store, capsys):
    tasks_dir, _ = store
    t = _tasks()

    # Create one real task, then drop a decoy matching the T*-*.md glob whose
    # stem ("Tabc") is not T + digits → the continue at 107 skips it.
    _run(t, ["create", "real"], stdin="# real\n")
    (tasks_dir / "Tabc-decoy.md").write_text("not a real task\n")

    capsys.readouterr()
    assert _run(t, ["list"]) == 0
    out = capsys.readouterr().out
    assert "T001" in out
    assert "Tabc" not in out, "a non-numeric T-prefixed file is not listed"


# ── main: no subcommand → help to stderr + EX_USAGE exit (220-221) ────────────


def test_main_without_subcommand_prints_help_and_exits_usage(store, capsys):
    _tasks_dir, _ = store
    t = _tasks()
    rc = _run(t, [])
    assert rc == t.EX_USAGE
    assert "usage" in capsys.readouterr().err.lower()
