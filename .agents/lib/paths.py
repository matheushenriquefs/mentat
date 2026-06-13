"""Frozen path constants for all mentat skills. Stdlib only (ADR-0008)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Paths:
    MENTAT_DIR: Path
    MENTAT_LIB_DIR: Path
    MENTAT_BIN_DIR: Path
    MENTAT_DOCS_DIR: Path
    MENTAT_WORKTREES_DIR: Path
    AGENTS_DIR: Path
    SKILLS_DIR: Path
    PLANS_DIR: Path
    LOGS_DIR: Path
    LOG_SCRIPT: Path
    CONTAINER_SCRIPT: Path
    GATES_CODE_DIR: Path


_mentat: Path = Path.home() / ".mentat"
_agents: Path = Path.home() / ".agents"

sys.modules[__name__] = _Paths(  # type: ignore[assignment]
    MENTAT_DIR=_mentat,
    MENTAT_LIB_DIR=_mentat / "lib",
    MENTAT_BIN_DIR=_mentat / "bin",
    MENTAT_DOCS_DIR=_mentat / "docs",
    MENTAT_WORKTREES_DIR=_mentat / "worktrees",
    AGENTS_DIR=_agents,
    SKILLS_DIR=_agents / "skills",
    PLANS_DIR=_agents / "plans",
    LOGS_DIR=_mentat / "logs",
    LOG_SCRIPT=_agents / "skills" / "mentat-log" / "scripts" / "log.py",
    CONTAINER_SCRIPT=_agents / "skills" / "mentat-container" / "scripts" / "container.py",
    GATES_CODE_DIR=_mentat / "lib" / "gates" / "code",
)
