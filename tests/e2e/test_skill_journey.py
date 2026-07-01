"""E2E: scaffold a brand-new mentat skill into a temp skills tree, then eval it.

Scaffold writes a real skill skeleton (SKILL.md, scripts/<name>.py, __init__.py) and a
real evals/<name>.json onto disk under a temp root, then the freshly-written main script
runs as a real subprocess (its "not yet implemented" stub exits 1). The eval path runs
against the scaffolded eval file and degrades cleanly when promptfoo is absent — the
realistic dev-box state. Roots are temp dirs so nothing lands in the repo's own tree.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-skill/scripts"


def test_scaffold_writes_skeleton_and_stub_runs(tmp_path):
    scaffold = load_script(SCRIPTS / "scaffold.py", "e2e_scaffold")
    skills_root = tmp_path / "skills"
    evals_dir = tmp_path / "evals"

    rc = scaffold.cmd_scaffold("mentat-widget", skills_root=skills_root, evals_dir=evals_dir)
    assert rc == 0

    skill_dir = skills_root / "mentat-widget"
    skill_md = skill_dir / "SKILL.md"
    main_script = skill_dir / "scripts" / "mentat-widget.py"
    init = skill_dir / "scripts" / "__init__.py"
    eval_json = evals_dir / "mentat-widget.json"

    for artifact in (skill_md, main_script, init, eval_json):
        assert artifact.exists(), f"scaffold must write {artifact}"

    assert "name: mentat-widget" in skill_md.read_text()

    # The scaffolded stub is a runnable script that exits 1 with its placeholder line.
    proc = subprocess.run([sys.executable, str(main_script)], capture_output=True, text=True)
    assert proc.returncode == 1
    assert "not yet implemented" in proc.stdout


def test_scaffold_is_idempotent(tmp_path):
    scaffold = load_script(SCRIPTS / "scaffold.py", "e2e_scaffold2")
    skills_root = tmp_path / "skills"
    evals_dir = tmp_path / "evals"

    assert scaffold.cmd_scaffold("mentat-thing", skills_root=skills_root, evals_dir=evals_dir) == 0

    # Hand-edit the SKILL.md, then re-scaffold: an existing file is preserved, not clobbered.
    skill_md = skills_root / "mentat-thing" / "SKILL.md"
    skill_md.write_text("custom body\n")
    assert scaffold.cmd_scaffold("mentat-thing", skills_root=skills_root, evals_dir=evals_dir) == 0
    assert skill_md.read_text() == "custom body\n"


def test_eval_gate_passes_when_no_eval_file(tmp_path):
    ev = load_script(SCRIPTS / "eval.py", "e2e_eval")
    # No eval file for this skill → the gate is a clean pass (nothing to run).
    assert ev.run_eval_gate("nonexistent-skill", evals_dir=tmp_path / "evals") is True


def test_eval_missing_eval_file_exits(tmp_path):
    ev = load_script(SCRIPTS / "eval.py", "e2e_eval2")
    with pytest.raises(SystemExit) as exc:
        ev.cmd_eval("ghost-skill", evals_dir=tmp_path / "evals")
    assert exc.value.code == 1
