"""E2E gap-closer: the two lifecycle branches other task tests miss.

Covers ``tasks_dir``'s cwd fallback when MENTAT_TASKS_DIR is unset, and
``next_id``'s skip arm for a T*-*.md file whose id segment is not numeric.
Real temp dirs; in-process.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_PY = REPO_ROOT / ".agents/skills/mentat-tasks/scripts/lifecycle.py"


def _lifecycle():
    return load_script(LIFECYCLE_PY, "e2e_lifecycle_gaps")


# ── tasks_dir: unset env → cwd/.mentat/tasks fallback (line 30) ───────────────


def test_tasks_dir_falls_back_to_cwd_when_env_unset(tmp_path, monkeypatch):
    lc = _lifecycle()
    monkeypatch.delenv("MENTAT_TASKS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert lc.tasks_dir() == tmp_path / ".mentat" / "tasks"


# ── next_id: a T*-*.md file with a non-numeric id segment is skipped (42->40) ──


def test_next_id_skips_non_numeric_id_files(tmp_path):
    lc = _lifecycle()
    # One real numeric task + a decoy whose prefix ("Tabc") fails isdigit() →
    # the loop's if is false and it continues; max is taken from the real id.
    (tmp_path / "T007-real.md").write_text("x\n")
    (tmp_path / "Tabc-decoy.md").write_text("x\n")
    assert lc.next_id(tmp_path) == "T008"


def test_next_id_starts_at_one_when_only_non_numeric_files_exist(tmp_path):
    lc = _lifecycle()
    # No numeric ids at all → the skip arm fires for the decoy and the ids list
    # stays empty, so next_id defaults to T001.
    (tmp_path / "Txyz-decoy.md").write_text("x\n")
    assert lc.next_id(tmp_path) == "T001"
