"""E2E: the pure install-plan computer.

Drives ``plan.py`` — the side-effect-free ``compute_plan`` plus its helpers
(``_discover_reviewers``, ``_plan_symlink``) — over real tmp filesystems. Both
clone modes are exercised: copy mode (``clone_root is None``) and symlink mode
(a real clone tree under tmp). No monkeypatch of subprocess is needed since the
module never touches the process world; it only reads directory state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/plan.py"


def _load():
    return load_script(PLAN_PY, "install_plan")


def _build_clone(root: Path) -> Path:
    """A minimal real clone tree with everything the bulk-symlinks + skills need."""
    agents = root / ".agents"
    (agents).mkdir(parents=True)
    (agents / "AGENTS.md").write_text("agents\n")
    reviewers = agents / "agents"
    reviewers.mkdir()
    (reviewers / "mentat-bug-reviewer.md").write_text("bug\n")
    (reviewers / "mentat-plan-reviewer.md").write_text("plan\n")
    skills = agents / "skills"
    skills.mkdir()
    for name in (
        "mentat-log",
        "mentat-container",
        "mentat-plan",
        "mentat-implement",
        "mentat-orchestrate",
        "mentat-skill",
        "mentat-git",
        "mentat-session",
        "mentat-install",
        "mentat-tasks",
        "mentat-prd",
    ):
        (skills / name).mkdir()
    (agents / "bin").mkdir()
    (agents / "lib").mkdir()
    docs = agents / "docs"
    docs.mkdir()
    (docs / "PATHS.md").write_text("paths\n")
    (root / "docs" / "adr").mkdir(parents=True)
    return root


def _targets(actions) -> set[Path]:
    return {a.target for a in actions}


# ── _discover_reviewers ───────────────────────────────────────────────────────


def test_discover_reviewers_none_returns_hardcoded_fallback():
    plan = _load()
    result = plan._discover_reviewers(None)
    assert result == [
        "mentat-bug-reviewer",
        "mentat-context-reviewer",
        "mentat-plan-reviewer",
        "mentat-researcher",
        "mentat-smell-reviewer",
        "mentat-test-reviewer",
    ]


def test_discover_reviewers_reads_sorted_stems_from_clone(tmp_path):
    plan = _load()
    agents_dir = tmp_path / ".agents" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "zeta-reviewer.md").write_text("z\n")
    (agents_dir / "alpha-reviewer.md").write_text("a\n")
    # A non-md file must be ignored by the *.md glob.
    (agents_dir / "notes.txt").write_text("nope\n")
    assert plan._discover_reviewers(tmp_path) == ["alpha-reviewer", "zeta-reviewer"]


def test_discover_reviewers_clone_without_agents_dir_falls_back(tmp_path):
    plan = _load()
    # clone_root set, but no .agents/agents directory → fallback list.
    assert plan._discover_reviewers(tmp_path) == plan._discover_reviewers(None)


# ── _plan_symlink (direct) ────────────────────────────────────────────────────


def test_plan_symlink_absent_target_is_added(tmp_path):
    plan = _load()
    add, update, conflicts = [], [], []
    source = tmp_path / "src"
    source.write_text("x\n")
    target = tmp_path / "missing"
    plan._plan_symlink(source, target, add, update, conflicts)
    assert _targets(add) == {target}
    assert update == [] and conflicts == []


def test_plan_symlink_wrong_pointer_is_update(tmp_path):
    plan = _load()
    add, update, conflicts = [], [], []
    source = tmp_path / "src"
    source.write_text("x\n")
    other = tmp_path / "other"
    other.write_text("y\n")
    target = tmp_path / "link"
    target.symlink_to(other)
    plan._plan_symlink(source, target, add, update, conflicts)
    assert _targets(update) == {target}
    assert add == [] and conflicts == []


def test_plan_symlink_correct_pointer_is_noop(tmp_path):
    plan = _load()
    add, update, conflicts = [], [], []
    source = tmp_path / "src"
    source.write_text("x\n")
    target = tmp_path / "link"
    target.symlink_to(source)
    plan._plan_symlink(source, target, add, update, conflicts)
    assert add == [] and update == [] and conflicts == []


def test_plan_symlink_real_file_is_conflict(tmp_path):
    plan = _load()
    add, update, conflicts = [], [], []
    source = tmp_path / "src"
    source.write_text("x\n")
    target = tmp_path / "real"
    target.write_text("already here\n")
    plan._plan_symlink(source, target, add, update, conflicts)
    assert conflicts == [target]
    assert add == [] and update == []


# ── compute_plan: mode A (copy, clone_root is None) ───────────────────────────


def test_compute_plan_copy_mode_fresh_home(tmp_path):
    plan = _load()
    home = tmp_path / "home"
    home.mkdir()
    result = plan.compute_plan(home, None)

    add_targets = _targets(result.add)
    assert home / ".mentat" in add_targets  # .mentat mkdir
    assert home / ".mentat" / "logs" in add_targets
    assert home / ".mentat" / "docs" in add_targets
    assert home / ".mentat" / "config.toml" in add_targets  # config file-create

    # Skills are copied in copy mode.
    copy_actions = [a for a in result.add if a.action_type == "copy"]
    assert copy_actions, "expected copy actions for skills in copy mode"
    assert home / ".agents" / "skills" / "mentat-log" in _targets(copy_actions)

    # .claude / .cursor absent → their skills + reviewers are skipped.
    assert result.skipped, "expected skipped harness actions"
    assert result.conflicts == []
    # No bulk symlinks in copy mode.
    assert not any(a.action_type == "symlink" for a in result.add)


# ── compute_plan: mode B (symlink) ────────────────────────────────────────────


def test_compute_plan_symlink_mode_fresh_home_adds_all(tmp_path):
    plan = _load()
    clone = _build_clone(tmp_path / "clone")
    home = tmp_path / "home"
    home.mkdir()
    result = plan.compute_plan(home, clone)

    add_targets = _targets(result.add)
    # Skills land as symlinks.
    assert home / ".agents" / "skills" / "mentat-log" in add_targets
    # Bulk symlinks land.
    assert home / ".agents" / "AGENTS.md" in add_targets
    assert home / ".agents" / "agents" in add_targets
    assert home / ".mentat" / "bin" in add_targets
    assert home / ".mentat" / "lib" in add_targets
    assert home / ".mentat" / "docs" / "PATHS.md" in add_targets
    assert home / ".mentat" / "docs" / "adr" in add_targets

    assert result.update == []
    assert result.conflicts == []


def test_compute_plan_symlink_mode_second_run_classifies_buckets(tmp_path):
    plan = _load()
    clone = _build_clone(tmp_path / "clone")
    home = tmp_path / "home"

    # Pre-create the .agents/skills dir so we can lay symlinks into it.
    agents_skills = home / ".agents" / "skills"
    agents_skills.mkdir(parents=True)

    # 1) Correct symlink → no-op.
    correct = agents_skills / "mentat-log"
    correct.symlink_to(clone / ".agents" / "skills" / "mentat-log")

    # 2) Wrong-pointing symlink → update.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    wrong = agents_skills / "mentat-plan"
    wrong.symlink_to(elsewhere)

    # 3) Real file where a symlink belongs → conflict.
    conflict = agents_skills / "mentat-git"
    conflict.write_text("real file\n")

    result = plan.compute_plan(home, clone)

    assert correct not in _targets(result.add)
    assert correct not in _targets(result.update)
    assert wrong in _targets(result.update)
    assert conflict in result.conflicts


# ── compute_plan: mode C (mentat_dir exists → no mkdir) ────────────────────────


def test_compute_plan_existing_mentat_dir_skips_mkdir(tmp_path):
    plan = _load()
    home = tmp_path / "home"
    mentat = home / ".mentat"
    mentat.mkdir(parents=True)
    # Also pre-create logs/docs + config so those false branches are hit too.
    (mentat / "logs").mkdir()
    (mentat / "docs").mkdir()
    (mentat / "config.toml").write_text("x\n")

    result = plan.compute_plan(home, None)
    mkdir_targets = _targets([a for a in result.add if a.action_type == "mkdir"])
    assert mentat not in mkdir_targets
    assert mentat / "logs" not in mkdir_targets
    assert mentat / "docs" not in mkdir_targets
    assert home / ".mentat" / "config.toml" not in _targets(result.add)


# ── compute_plan: mode D (.claude present → harness fanout symlink path) ───────


def test_compute_plan_harness_present_fans_out_symlinks_copy_mode(tmp_path):
    plan = _load()
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    result = plan.compute_plan(home, None)

    add_targets = _targets(result.add)
    # Harness skill + reviewer symlinks land in add (copy-mode source selection).
    assert home / ".claude" / "skills" / "mentat-log" in add_targets
    assert home / ".claude" / "agents" / "mentat-bug-reviewer.md" in add_targets
    # .cursor still absent → its actions are skipped.
    skipped_targets = _targets(result.skipped)
    assert home / ".cursor" / "skills" / "mentat-log" in skipped_targets


def test_compute_plan_harness_present_fans_out_symlinks_clone_mode(tmp_path):
    plan = _load()
    clone = _build_clone(tmp_path / "clone")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    result = plan.compute_plan(home, clone)

    add_targets = _targets(result.add)
    # Harness skill + reviewer symlinks resolve to clone sources and land in add.
    assert home / ".claude" / "skills" / "mentat-log" in add_targets
    assert home / ".claude" / "agents" / "mentat-bug-reviewer.md" in add_targets
    # Reviewer set comes from the discovered clone stems.
    assert home / ".claude" / "agents" / "mentat-plan-reviewer.md" in add_targets


# ── compute_plan: mode E (stale paths, incl. dangling symlink) ────────────────


def test_compute_plan_reports_stale_paths_including_dangling(tmp_path):
    plan = _load()
    home = tmp_path / "home"
    home.mkdir()

    # A real stale file.
    stale_file = home / ".agents" / "mentat"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("legacy\n")

    # A dangling symlink stale path — .exists() is False, .is_symlink() is True.
    dangling = home / ".claude" / "agents" / "mentat-bug-reviewer"
    dangling.parent.mkdir(parents=True)
    dangling.symlink_to(home / "nonexistent-target")

    result = plan.compute_plan(home, None)
    assert stale_file in result.stale
    assert dangling in result.stale


# ── InstallPlan / Action shape ────────────────────────────────────────────────


def test_install_plan_fields_are_lists(tmp_path):
    plan = _load()
    home = tmp_path / "home"
    home.mkdir()
    result = plan.compute_plan(home, None)
    for field in (
        result.add,
        result.update,
        result.stale,
        result.conflicts,
        result.missing_companions,
        result.skipped,
    ):
        assert isinstance(field, list)
    assert result.missing_companions == []


def test_action_repr_contains_action_type(tmp_path):
    plan = _load()
    action = plan.Action("mkdir", None, tmp_path / "d")
    assert "mkdir" in repr(action)
