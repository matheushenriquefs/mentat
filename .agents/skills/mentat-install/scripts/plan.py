"""Pure install plan computation. No side effects."""

from __future__ import annotations

from pathlib import Path

_SKILL_NAMES = [
    "mentat-log", "mentat-container", "mentat-plan", "mentat-implement",
    "mentat-orchestrate", "mentat-skill", "mentat-git", "mentat-session", "mentat-install",
]

_REVIEWER_NAMES = [
    "mentat-bug-reviewer",
    "mentat-plan-reviewer",
    "mentat-smell-reviewer",
    "mentat-test-reviewer",
]

_STALE_PATHS = [
    ".agents/mentat",
    ".agents/bin/mentat-config",
    ".agents/bin/mentat-precommit",
    ".agents/bin/mentat-update",
    ".agents/bin/lib/audit.sh",
    ".agents/bin/lib/audit-schema.jsonc",
    ".agents/bin/lib/harness-registry.jsonc",
    ".agents/lib/gates/llm",
]


class Action:
    def __init__(self, action_type: str, source: Path | None, target: Path) -> None:
        self.action_type = action_type
        self.source = source
        self.target = target

    def __repr__(self) -> str:
        return f"Action({self.action_type!r}, {self.source!r} → {self.target!r})"


class InstallPlan:
    def __init__(
        self,
        add: list[Action],
        update: list[Action],
        stale: list[Path],
        missing_companions: list[str],
        skipped: list[Action],
    ) -> None:
        self.add = add
        self.update = update
        self.stale = stale
        self.missing_companions = missing_companions
        self.skipped = skipped


def compute_plan(home: Path, clone_root: Path | None) -> InstallPlan:
    """Pure: compute install actions without touching the filesystem."""
    add: list[Action] = []
    update: list[Action] = []
    stale: list[Path] = []
    skipped: list[Action] = []

    agents_skills = home / ".agents" / "skills"
    # 1. ~/.mentat/{} dirs and config
    mentat_dir = home / ".mentat"
    if not mentat_dir.exists():
        add.append(Action("mkdir", None, mentat_dir))
    logs_dir = mentat_dir / "logs"
    if not logs_dir.exists():
        add.append(Action("mkdir", None, logs_dir))
    config_file = mentat_dir / "config.jsonc"
    if not config_file.exists():
        add.append(Action("file-create", None, config_file))

    # 2. Skill symlinks/copies at ~/.agents/skills/<bin>
    for skill in _SKILL_NAMES:
        target = agents_skills / skill
        if clone_root is not None:
            source = clone_root / ".agents" / "skills" / skill
            if target.exists():
                if target.is_symlink() and target.resolve() != source.resolve():
                    update.append(Action("symlink", source, target))
            else:
                add.append(Action("symlink", source, target))
        else:
            if not target.exists():
                add.append(Action("copy", None, target))

    # 3. Harness detection
    agents_agents = home / ".agents" / "agents"
    for harness_dir, harness_name in [(".claude", "claude-code"), (".cursor", "cursor")]:
        h_path = home / harness_dir
        if not h_path.exists():
            for skill in _SKILL_NAMES:
                skipped.append(Action("symlink", None, h_path / "skills" / skill))
            for reviewer in _REVIEWER_NAMES:
                skipped.append(Action("symlink", None, h_path / "agents" / reviewer))
            continue
        for skill in _SKILL_NAMES:
            link = h_path / "skills" / skill
            if clone_root is not None:
                source = clone_root / ".agents" / "skills" / skill
            else:
                source = agents_skills / skill
            if link.exists():
                if link.is_symlink() and link.resolve() != source.resolve():
                    update.append(Action("symlink", source, link))
            else:
                add.append(Action("symlink", source, link))
        for reviewer in _REVIEWER_NAMES:
            link = h_path / "agents" / reviewer
            if clone_root is not None:
                source = clone_root / ".agents" / "agents" / reviewer
            else:
                source = agents_agents / reviewer
            if link.exists():
                if link.is_symlink() and link.resolve() != source.resolve():
                    update.append(Action("symlink", source, link))
            else:
                add.append(Action("symlink", source, link))

    # 4. Stale paths
    for stale_rel in _STALE_PATHS:
        stale_path = home / stale_rel
        if stale_path.exists():
            stale.append(stale_path)

    missing_companions: list[str] = []

    return InstallPlan(
        add=add,
        update=update,
        stale=stale,
        missing_companions=missing_companions,
        skipped=skipped,
    )
