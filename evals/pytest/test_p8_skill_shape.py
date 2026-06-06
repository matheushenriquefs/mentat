"""S12: SKILL.md shape tests for local skills and reviewer cross-reference."""
import os
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
AGENTS_DIR = REPO_ROOT / ".agents" / "agents"
ORCHESTRATE = REPO_ROOT / ".agents" / "bin" / "mentat-orchestrate"
IMPLEMENT_CMD = REPO_ROOT / ".agents" / "commands" / "mentat-implement.md"

LOCAL_SKILLS = [
    d for d in SKILLS_DIR.iterdir()
    if d.is_dir() and d.name not in ("vendor", "triage") and (d / "SKILL.md").exists()
]

REVIEWER_NAMES = [
    "mentat-plan-reviewer",
    "mentat-test-reviewer",
    "mentat-bug-reviewer",
    "mentat-smell-reviewer",
]


# --- local SKILL.md shape ---

@pytest.mark.parametrize("skill_dir", LOCAL_SKILLS, ids=lambda d: d.name)
def test_skill_frontmatter_present(skill_dir):
    skill_md = (skill_dir / "SKILL.md").read_text()
    assert skill_md.startswith("---"), f"{skill_dir.name}: SKILL.md must start with YAML frontmatter"


@pytest.mark.parametrize("skill_dir", LOCAL_SKILLS, ids=lambda d: d.name)
def test_skill_name_matches_dirname(skill_dir):
    skill_md = (skill_dir / "SKILL.md").read_text()
    parts = skill_md.split("---", 2)
    assert len(parts) >= 3, f"{skill_dir.name}: malformed frontmatter"
    fm = yaml.safe_load(parts[1])
    assert fm.get("name") == skill_dir.name, (
        f"{skill_dir.name}: frontmatter name={fm.get('name')!r} != dirname={skill_dir.name!r}"
    )


@pytest.mark.parametrize("skill_dir", LOCAL_SKILLS, ids=lambda d: d.name)
def test_skill_description_present_and_short(skill_dir):
    skill_md = (skill_dir / "SKILL.md").read_text()
    parts = skill_md.split("---", 2)
    fm = yaml.safe_load(parts[1])
    desc = fm.get("description", "")
    assert desc, f"{skill_dir.name}: frontmatter missing description"
    assert len(desc) <= 400, f"{skill_dir.name}: description too long ({len(desc)} chars > 400)"


# --- reviewer agent files exist ---

@pytest.mark.parametrize("reviewer", REVIEWER_NAMES)
def test_reviewer_agent_file_exists(reviewer):
    agent_file = AGENTS_DIR / f"{reviewer}.md"
    assert agent_file.exists(), f"Missing agent file: {agent_file}"


@pytest.mark.parametrize("reviewer", REVIEWER_NAMES)
def test_reviewer_name_ends_with_reviewer(reviewer):
    agent_file = AGENTS_DIR / f"{reviewer}.md"
    if not agent_file.exists():
        pytest.skip(f"{reviewer}.md not found")
    text = agent_file.read_text()
    parts = text.split("---", 2)
    if len(parts) < 3:
        pytest.skip(f"{reviewer}.md has no frontmatter")
    fm = yaml.safe_load(parts[1])
    name = fm.get("name", "")
    assert name.endswith("-reviewer"), f"{reviewer}: frontmatter name={name!r} must end with -reviewer"


# --- orchestrate references all 4 reviewers ---

def test_orchestrate_references_smell_reviewer():
    text = ORCHESTRATE.read_text()
    assert "mentat-smell-reviewer" in text, "mentat-orchestrate must reference mentat-smell-reviewer"


def test_implement_cmd_references_smell_reviewer():
    text = IMPLEMENT_CMD.read_text()
    assert "mentat-smell-reviewer" in text, "mentat-implement.md must reference mentat-smell-reviewer"


def test_orchestrate_references_all_reviewers():
    text = ORCHESTRATE.read_text()
    for r in REVIEWER_NAMES:
        assert r in text, f"mentat-orchestrate missing reference to {r}"
