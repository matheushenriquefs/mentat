"""Pure install plan computation. No side effects."""

from __future__ import annotations

from pathlib import Path

_SKILL_NAMES = [
    "mentat-log",
    "mentat-container",
    "mentat-plan",
    "mentat-implement",
    "mentat-orchestrate",
    "mentat-skill",
    "mentat-git",
    "mentat-track",
    "mentat-install",
    "mentat-tasks",
    "mentat-prd",
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
    # Stale broken symlinks (target file missing .md suffix). Re-install fixes.
    ".claude/agents/mentat-bug-reviewer",
    ".claude/agents/mentat-plan-reviewer",
    ".claude/agents/mentat-smell-reviewer",
    ".claude/agents/mentat-test-reviewer",
    ".cursor/agents/mentat-bug-reviewer",
    ".cursor/agents/mentat-plan-reviewer",
    ".cursor/agents/mentat-smell-reviewer",
    ".cursor/agents/mentat-test-reviewer",
    # Renamed mentat-session → mentat-track (ADR-0018).
    ".agents/skills/mentat-session",
    ".claude/skills/mentat-session",
    ".cursor/skills/mentat-session",
    # Pre-rehome: mentat-private dirs were under ~/.agents/ — now under ~/.mentat/.
    ".agents/bin",
    ".agents/lib",
    ".agents/docs",
]


# Absolute target → rel-source under <clone>/.
# Maps the post-rehome layout:
#   ~/.agents/  — harness/community surface (AGENTS.md, agents/)
#   ~/.mentat/  — mentat-private surface (bin/, lib/, docs/)
def _bulk_symlinks(home: Path) -> dict[Path, str]:
    return {
        home / ".agents" / "AGENTS.md": ".agents/AGENTS.md",
        home / ".agents" / "agents": ".agents/agents",
        home / ".mentat" / "bin": ".agents/bin",
        home / ".mentat" / "lib": ".agents/lib",
        home / ".mentat" / "docs" / "PATHS.md": ".agents/docs/PATHS.md",
        # ADRs ship from repo root — user-facing canonical location.
        home / ".mentat" / "docs" / "adr": "docs/adr",
    }


def _discover_reviewers(clone_root: Path | None) -> list[str]:
    """All .agents/agents/*.md file stems. Falls back to hardcoded list when no clone."""
    if clone_root is not None:
        agents_dir = clone_root / ".agents" / "agents"
        if agents_dir.is_dir():
            return sorted(p.stem for p in agents_dir.glob("*.md"))
    return [
        "mentat-bug-reviewer",
        "mentat-context-reviewer",
        "mentat-plan-reviewer",
        "mentat-researcher",
        "mentat-smell-reviewer",
        "mentat-test-reviewer",
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
        conflicts: list[Path],
        missing_companions: list[str],
        skipped: list[Action],
    ) -> None:
        self.add = add
        self.update = update
        self.stale = stale
        self.conflicts = conflicts
        self.missing_companions = missing_companions
        self.skipped = skipped


def _plan_symlink(
    source: Path,
    target: Path,
    add: list[Action],
    update: list[Action],
    conflicts: list[Path],
) -> None:
    """Classify one symlink action: add / update / conflict-abort."""
    if not target.exists() and not target.is_symlink():
        add.append(Action("symlink", source, target))
        return
    if target.is_symlink():
        if target.resolve() != source.resolve():
            update.append(Action("symlink", source, target))
        return
    # Exists as real file/dir — abort, no silent overwrite.
    conflicts.append(target)


def compute_plan(home: Path, clone_root: Path | None) -> InstallPlan:
    """Pure: compute install actions without touching the filesystem."""
    add: list[Action] = []
    update: list[Action] = []
    stale: list[Path] = []
    conflicts: list[Path] = []
    skipped: list[Action] = []
    reviewer_names = _discover_reviewers(clone_root)

    agents_skills = home / ".agents" / "skills"
    # 1. ~/.mentat/{} dirs and config
    mentat_dir = home / ".mentat"
    if not mentat_dir.exists():
        add.append(Action("mkdir", None, mentat_dir))
    # bin and lib are bulk-symlink targets — don't mkdir them (would conflict).
    for sub in ("logs", "docs"):
        sub_dir = mentat_dir / sub
        if not sub_dir.exists():
            add.append(Action("mkdir", None, sub_dir))
    config_file = mentat_dir / "config.toml"
    if not config_file.exists():
        add.append(Action("file-create", None, config_file))

    # 2. Skill symlinks/copies at ~/.agents/skills/<bin>
    for skill in _SKILL_NAMES:
        target = agents_skills / skill
        if clone_root is not None:
            source = clone_root / ".agents" / "skills" / skill
            _plan_symlink(source, target, add, update, conflicts)
        else:
            if not target.exists():
                add.append(Action("copy", None, target))

    # 3. Bulk symlinks (harness surface + mentat-private surface)
    if clone_root is not None:
        for target, rel_source in _bulk_symlinks(home).items():
            source = clone_root / rel_source
            _plan_symlink(source, target, add, update, conflicts)

    # 4. Per-harness fanout
    agents_agents = home / ".agents" / "agents"
    for harness_dir in [".claude", ".cursor"]:
        h_path = home / harness_dir
        if not h_path.exists():
            for skill in _SKILL_NAMES:
                skipped.append(Action("symlink", None, h_path / "skills" / skill))
            for reviewer in reviewer_names:
                skipped.append(Action("symlink", None, h_path / "agents" / reviewer))
            continue
        for skill in _SKILL_NAMES:
            link = h_path / "skills" / skill
            source = clone_root / ".agents" / "skills" / skill if clone_root is not None else agents_skills / skill
            _plan_symlink(source, link, add, update, conflicts)
        for reviewer in reviewer_names:
            link = h_path / "agents" / f"{reviewer}.md"
            if clone_root is not None:
                source = clone_root / ".agents" / "agents" / f"{reviewer}.md"
            else:
                source = agents_agents / f"{reviewer}.md"
            _plan_symlink(source, link, add, update, conflicts)

    # 5. Stale paths (include broken symlinks — .exists() returns False on dangling)
    for stale_rel in _STALE_PATHS:
        stale_path = home / stale_rel
        if stale_path.exists() or stale_path.is_symlink():
            stale.append(stale_path)

    missing_companions: list[str] = []

    return InstallPlan(
        add=add,
        update=update,
        stale=stale,
        conflicts=conflicts,
        missing_companions=missing_companions,
        skipped=skipped,
    )
