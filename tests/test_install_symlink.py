"""D13 — symlink fabric: idempotency, 6-reviewer coverage, conflict-abort."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "mentat-install" / "scripts"


def _load(name: str):
    key = f"_mentat_install_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_clone(tmp_path: Path) -> Path:
    """Minimal repo: .agents/skills/*/, .agents/agents/*.md, docs/adr/, .agents/{AGENTS.md,bin,lib,docs}."""
    clone = tmp_path / "clone"
    (clone / ".agents" / "agents").mkdir(parents=True)
    (clone / ".agents" / "bin").mkdir()
    (clone / ".agents" / "lib").mkdir()
    (clone / ".agents" / "docs").mkdir()
    (clone / ".agents" / "AGENTS.md").write_text("# AGENTS\n")
    (clone / ".agents" / "docs" / "PATHS.md").write_text("# PATHS\n")
    (clone / "docs" / "adr").mkdir(parents=True)
    (clone / "docs" / "adr" / "README.md").write_text("# ADRs\n")
    for skill in (
        "mentat-log",
        "mentat-container",
        "mentat-plan",
        "mentat-implement",
        "mentat-orchestrate",
        "mentat-skill",
        "mentat-git",
        "mentat-session",
        "mentat-install",
    ):
        (clone / ".agents" / "skills" / skill).mkdir(parents=True)
    reviewers = [
        "mentat-bug-reviewer",
        "mentat-context-reviewer",
        "mentat-plan-reviewer",
        "mentat-researcher",
        "mentat-smell-reviewer",
        "mentat-test-reviewer",
    ]
    for r in reviewers:
        (clone / ".agents" / "agents" / f"{r}.md").write_text(f"# {r}\n")
    return clone


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".cursor").mkdir()
    return home


def test_six_reviewers_discovered(fake_clone: Path, fake_home: Path) -> None:
    plan = _load("plan")
    ip = plan.compute_plan(home=fake_home, clone_root=fake_clone)
    targets = {str(a.target) for a in ip.add}
    for r in (
        "mentat-bug-reviewer",
        "mentat-context-reviewer",
        "mentat-plan-reviewer",
        "mentat-researcher",
        "mentat-smell-reviewer",
        "mentat-test-reviewer",
    ):
        assert str(fake_home / ".claude" / "agents" / f"{r}.md") in targets
        assert str(fake_home / ".cursor" / "agents" / f"{r}.md") in targets


def test_bulk_symlinks_present(fake_clone: Path, fake_home: Path) -> None:
    plan = _load("plan")
    ip = plan.compute_plan(home=fake_home, clone_root=fake_clone)
    targets = {str(a.target) for a in ip.add}
    # Harness surface stays at ~/.agents/
    for rel in ("AGENTS.md", "agents"):
        assert str(fake_home / ".agents" / rel) in targets, f"missing ~/.agents/ symlink: {rel}"
    # Mentat-private surface moves to ~/.mentat/
    for rel in ("bin", "lib", "docs/PATHS.md", "docs/adr"):
        assert str(fake_home / ".mentat" / rel) in targets, f"missing ~/.mentat/ symlink: {rel}"
    # Must NOT be under ~/.agents/ anymore
    for rel in ("bin", "lib"):
        assert str(fake_home / ".agents" / rel) not in targets, "bin/lib must NOT be under ~/.agents/"


def test_idempotent_second_run(fake_clone: Path, fake_home: Path) -> None:
    plan = _load("plan")
    utils = _load("filesystem")
    ip = plan.compute_plan(home=fake_home, clone_root=fake_clone)
    for action in ip.add:
        if action.action_type == "symlink" and action.source:
            utils.safe_symlink(action.source, action.target)
    ip2 = plan.compute_plan(home=fake_home, clone_root=fake_clone)
    symlink_adds = [a for a in ip2.add if a.action_type == "symlink"]
    assert symlink_adds == [], f"expected no symlink adds on second run, got: {symlink_adds}"


def test_conflict_abort_on_non_symlink(fake_clone: Path, fake_home: Path) -> None:
    plan = _load("plan")
    blocker = fake_home / ".agents" / "AGENTS.md"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("user-owned content\n")
    ip = plan.compute_plan(home=fake_home, clone_root=fake_clone)
    assert blocker in ip.conflicts


def test_safe_symlink_raises_on_conflict(tmp_path: Path) -> None:
    utils = _load("filesystem")
    real_file = tmp_path / "real.md"
    real_file.write_text("user content\n")
    source = tmp_path / "src.md"
    source.write_text("source\n")
    with pytest.raises(utils.InstallConflict):
        utils.safe_symlink(source, real_file)
