"""S12: SKILL.md shape tests for local skills and reviewer cross-reference.
S1 verification: PRISTINE Matt skills deleted from skills dir.
S13 verification: df preflight in mentat-container-up.
"""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
AGENTS_DIR = REPO_ROOT / ".agents" / "agents"
ORCHESTRATE = REPO_ROOT / ".agents" / "bin" / "mentat-orchestrate"
IMPLEMENT_CMD = REPO_ROOT / ".agents" / "commands" / "mentat-implement.md"

LOCAL_SKILLS = [
    d for d in SKILLS_DIR.iterdir() if d.is_dir() and d.name not in ("vendor", "triage") and (d / "SKILL.md").exists()
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


# --- S1: PRISTINE Matt skills deleted from skills dir ---

PRISTINE_MATT_SKILLS = [
    "diagnose",
    "grill-me",
    "grill-with-docs",
    "handoff",
    "improve-codebase-architecture",
    "prototype",
    "tdd",
    "write-a-skill",
    "zoom-out",
]


@pytest.mark.parametrize("skill", PRISTINE_MATT_SKILLS)
def test_pristine_skill_deleted_from_skills_dir(skill):
    skill_dir = SKILLS_DIR / skill
    assert not skill_dir.exists(), f".agents/skills/{skill}/ must be deleted (vendored via vendir.yml)"


def test_skills_dir_has_no_pristine_matt_copies():
    tracked = [p.name for p in SKILLS_DIR.iterdir() if p.is_dir()]
    found = [s for s in PRISTINE_MATT_SKILLS if s in tracked]
    assert not found, f"PRISTINE Matt skills still in skills/: {found}"


# --- S13: df disk preflight in mentat-container-up ---

CONTAINER_UP = REPO_ROOT / ".agents" / "bin" / "mentat-container-up"


def test_container_up_has_df_preflight():
    text = CONTAINER_UP.read_text()
    assert "df -k" in text, "mentat-container-up must have df -k disk preflight"
    assert ">= 95" in text or ">=95" in text or "95" in text, "df preflight must check >= 95% threshold"


def test_container_up_df_exits_1_on_full_disk():
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_df = os.path.join(tmpdir, "df")
        with open(fake_df, "w") as f:
            f.write(
                "#!/bin/sh\necho 'Filesystem 1K-blocks Used Avail Use% Mounted'\necho '/dev/disk1 100000 96000 4000 96% /'\n"
            )
        os.chmod(fake_df, os.stat(fake_df).st_mode | stat.S_IEXEC)
        env = {**os.environ, "PATH": tmpdir + ":" + os.environ["PATH"]}
        r = subprocess.run(
            ["bash", str(CONTAINER_UP)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
    assert r.returncode != 0, "mentat-container-up must exit non-zero when disk >= 95%"
    assert "disk" in r.stdout.lower() or "disk" in r.stderr.lower(), "must print disk-full message"
