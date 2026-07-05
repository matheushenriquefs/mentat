"""E2E: the install plan graph computed over a real fresh HOME + this repo as clone root.

``compute_plan`` is the pure planner behind ``mentat-install``: it diffs a target HOME
against the shipped clone tree and yields add / update / conflict / stale / skipped
actions. This drives it over a real empty HOME with the actual repo as clone root, then
re-plans after materializing the symlinks to prove a settled tree yields nothing to add,
and renders both plans. Real filesystem throughout; in-process so both modules are measured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-install/scripts"


def _mods():
    plan = load_script(INSTALL_SCRIPTS / "plan.py", "e2e_installplan")
    render = load_script(INSTALL_SCRIPTS / "render.py", "e2e_installrender")
    return plan, render


def test_compute_plan_over_fresh_home_adds_symlinks(tmp_path):
    plan, render = _mods()
    home = tmp_path / "home"
    home.mkdir()

    result = plan.compute_plan(home, REPO_ROOT)

    # A fresh HOME needs the mentat dir + config + skill symlinks added.
    add_targets = {str(a.target) for a in result.add}
    assert any(t.endswith(".mentat/config.toml") for t in add_targets), "config must be planned"
    assert any(t.endswith(".mentat") for t in add_targets), "mentat dir must be planned"
    assert any("/.agents/skills/mentat-session" in t for t in add_targets), "skill symlink must be planned"
    # No harness dirs present → their fanout is skipped, not added.
    assert result.skipped, "absent .claude/.cursor harness dirs are skipped"
    assert not result.conflicts, "a clean fresh HOME has no conflicts"

    rendered = render.render(result, color=False)
    assert "Added:" in rendered
    assert "Skipped (harness not detected):" in rendered


def test_compute_plan_flags_a_real_file_conflict(tmp_path):
    plan, render = _mods()
    home = tmp_path / "home"
    (home / ".agents" / "skills").mkdir(parents=True)
    # A real (non-symlink) file where a skill symlink should go → conflict.
    conflict_target = home / ".agents" / "skills" / "mentat-session"
    conflict_target.write_text("not a symlink\n")

    result = plan.compute_plan(home, REPO_ROOT)
    assert conflict_target in result.conflicts, "a real file at a symlink target is a conflict"

    rendered = render.render(result, color=False)
    assert "Conflicts" in rendered


def test_compute_plan_detects_settled_symlink_as_no_op(tmp_path):
    plan, _ = _mods()
    home = tmp_path / "home"
    skills = home / ".agents" / "skills"
    skills.mkdir(parents=True)
    # Materialize the exact symlink compute_plan wants → it must not re-add it.
    target = skills / "mentat-session"
    target.symlink_to(REPO_ROOT / ".agents" / "skills" / "mentat-session")

    result = plan.compute_plan(home, REPO_ROOT)
    add_targets = {str(a.target) for a in result.add}
    assert not any(t.endswith("/.agents/skills/mentat-session") for t in add_targets), (
        "a correctly-linked skill is neither re-added nor updated"
    )
    update_targets = {str(a.target) for a in result.update}
    assert not any(t.endswith("/.agents/skills/mentat-session") for t in update_targets)


def test_compute_plan_flags_wrong_symlink_as_update(tmp_path):
    plan, _ = _mods()
    home = tmp_path / "home"
    skills = home / ".agents" / "skills"
    skills.mkdir(parents=True)
    # A symlink pointing somewhere stale → planned as an update.
    stale_src = tmp_path / "stale"
    stale_src.mkdir()
    target = skills / "mentat-session"
    target.symlink_to(stale_src)

    result = plan.compute_plan(home, REPO_ROOT)
    update_targets = {str(a.target) for a in result.update}
    assert any(t.endswith("/.agents/skills/mentat-session") for t in update_targets), (
        "a symlink pointing at the wrong source must be re-pointed (update)"
    )


def test_render_empty_plan(tmp_path):
    plan, render = _mods()
    empty = plan.InstallPlan(add=[], update=[], stale=[], conflicts=[], missing_companions=[], skipped=[])
    assert render.render(empty, color=False).strip() == "Nothing to install."


def test_render_colorizes_when_requested(tmp_path):
    plan, render = _mods()
    p = plan.InstallPlan(
        add=[plan.Action("mkdir", None, Path("/x"))],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    out = render.render(p, color=True)
    assert "\033[32m" in out, "color=True emits ANSI"
