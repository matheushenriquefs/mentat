"""Frozen path constants for all mentat skills. Stdlib only (ADR-0008)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Paths:
    AGENTS_DIR: Path
    LIB_DIR: Path
    SKILLS_DIR: Path
    LOG_SCRIPT: Path
    CONTAINER_SCRIPT: Path
    GATES_CODE_DIR: Path
    PLANS_DIR: Path
    LOGS_DIR: Path


_agents: Path = Path(__file__).resolve().parents[1]

sys.modules[__name__] = _Paths(  # type: ignore[assignment]
    AGENTS_DIR=_agents,
    LIB_DIR=_agents / "lib",
    SKILLS_DIR=_agents / "skills",
    LOG_SCRIPT=_agents / "skills" / "mentat-log" / "scripts" / "log.py",
    CONTAINER_SCRIPT=_agents / "skills" / "mentat-container" / "scripts" / "container.py",
    GATES_CODE_DIR=_agents / "lib" / "gates" / "code",
    PLANS_DIR=Path.home() / ".agents" / "plans",
    LOGS_DIR=Path.home() / ".mentat" / "logs",
)
