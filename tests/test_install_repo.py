"""mentat-install: plan computation + repo scaffold tests."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

INSTALL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-install/scripts"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_install():
    spec = importlib.util.spec_from_file_location("install_mod", INSTALL_SCRIPTS / "install.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["install_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_plan():
    key = "plan_mod"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, INSTALL_SCRIPTS / "plan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)


# ---------------------------------------------------------------------------
# plan.py compute_plan tests (new layout)
# ---------------------------------------------------------------------------


def test_compute_plan_bulk_symlinks_target_mentat(tmp_path):
    """bin, lib, docs land under ~/.mentat/, not ~/.agents/."""
    plan_mod = _load_plan()
    home = tmp_path / "home"
    clone = tmp_path / "clone"
    # Minimal clone tree — enough for compute_plan to produce bulk symlink actions.
    (clone / ".agents" / "agents").mkdir(parents=True)
    (clone / ".agents" / "bin").mkdir(parents=True)
    (clone / ".agents" / "lib").mkdir(parents=True)
    (clone / ".agents" / "docs").mkdir(parents=True)
    (clone / "docs" / "adr").mkdir(parents=True)
    (clone / ".agents" / "AGENTS.md").write_text("")
    (clone / ".agents" / "docs" / "PATHS.md").write_text("")

    result = plan_mod.compute_plan(home, clone)
    all_actions = result.add + result.update

    target_paths = {str(a.target) for a in all_actions if a.action_type == "symlink"}

    # Mentat-private targets
    mentat = str(home / ".mentat")
    assert any(t.startswith(mentat + "/bin") for t in target_paths), "bin must land under ~/.mentat/"
    assert any(t.startswith(mentat + "/lib") for t in target_paths), "lib must land under ~/.mentat/"
    assert any(t.startswith(mentat + "/docs") for t in target_paths), "docs must land under ~/.mentat/"

    # Must NOT land under ~/.agents/{bin,lib,docs}
    agents = str(home / ".agents")
    assert not any(t == agents + "/bin" for t in target_paths), "bin must NOT be under ~/.agents/"
    assert not any(t == agents + "/lib" for t in target_paths), "lib must NOT be under ~/.agents/"
    assert not any(t.startswith(agents + "/docs") for t in target_paths), "docs must NOT be under ~/.agents/"


def test_compute_plan_symlinks_all_11_skills(tmp_path):
    """compute_plan includes mentat-tasks and mentat-prd in the skill set."""
    plan_mod = _load_plan()
    home = tmp_path / "home"
    clone = tmp_path / "clone"
    skills_dir = clone / ".agents" / "skills"

    expected_skills = {
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
    }
    for skill in expected_skills:
        (skills_dir / skill).mkdir(parents=True)
    (clone / ".agents" / "agents").mkdir(parents=True)
    (clone / ".agents" / "AGENTS.md").write_text("")

    result = plan_mod.compute_plan(home, clone)
    all_actions = result.add + result.update
    skill_targets = {
        a.target.name for a in all_actions if a.action_type == "symlink" and ".agents/skills" in str(a.target)
    }
    assert "mentat-tasks" in skill_targets, "mentat-tasks missing from plan"
    assert "mentat-prd" in skill_targets, "mentat-prd missing from plan"
    assert len(skill_targets) >= 11, f"Expected ≥11 skills, got {sorted(skill_targets)}"


def test_manifest_audit_predicate():
    """_SKILL_NAMES matches skills on disk — catches missed additions."""
    plan_mod = _load_plan()
    on_disk = {p.name for p in (REPO_ROOT / ".agents" / "skills").iterdir() if p.is_dir()}
    in_manifest = set(plan_mod._SKILL_NAMES)
    assert in_manifest == on_disk, (
        f"_SKILL_NAMES out of sync with .agents/skills/:\n"
        f"  missing from manifest: {on_disk - in_manifest}\n"
        f"  extra in manifest: {in_manifest - on_disk}"
    )


# ---------------------------------------------------------------------------
# install.py --repo scaffold tests (unchanged)
# ---------------------------------------------------------------------------


def test_repo_install_creates_config(tmp_path):
    """--repo creates .mentat/config.toml template."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)

    install = _load_install()
    rc = install.do_repo_install(repo_path=repo)

    assert rc == 0
    cfg = repo / ".mentat" / "config.toml"
    assert cfg.exists(), f"config.toml not created at {cfg}"
    content = cfg.read_text()
    assert "harness" in content


def test_repo_install_appends_gitignore(tmp_path):
    """--repo appends .mentat/ to .gitignore if absent."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)

    install = _load_install()
    install.do_repo_install(repo_path=repo)

    gi = repo / ".gitignore"
    assert gi.exists(), ".gitignore not created"
    assert ".mentat/" in gi.read_text()


def test_repo_install_gitignore_existing_not_duplicated(tmp_path):
    """--repo doesn't duplicate .mentat/ if already in .gitignore."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)
    gi = repo / ".gitignore"
    gi.write_text(".mentat/\n")

    install = _load_install()
    install.do_repo_install(repo_path=repo)

    content = gi.read_text()
    assert content.count(".mentat/") == 1


def test_repo_install_noop_if_config_exists(tmp_path):
    """--repo is no-op if .mentat/config.toml already present."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)
    cfg = repo / ".mentat" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('harness = "cursor"\n')

    install = _load_install()
    rc = install.do_repo_install(repo_path=repo)

    assert rc == 0
    assert cfg.read_text() == 'harness = "cursor"\n', "existing config must not be overwritten"
