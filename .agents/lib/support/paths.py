"""Frozen path constants for all mentat skills. Stdlib only (ADR-0008)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _mentat_root() -> Path:
    return Path.home() / ".mentat"


def _agents_root() -> Path:
    override = os.environ.get("MENTAT_AGENTS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".agents"


def _repo_root() -> Path:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        return Path(r.stdout.strip())
    return Path(__file__).resolve().parents[3]


class _Paths:
    @property
    def MENTAT_DIR(self) -> Path:
        return _mentat_root()

    @property
    def MENTAT_LIB_DIR(self) -> Path:
        return self.MENTAT_DIR / "lib"

    @property
    def MENTAT_BIN_DIR(self) -> Path:
        return self.MENTAT_DIR / "bin"

    @property
    def MENTAT_DOCS_DIR(self) -> Path:
        return self.MENTAT_DIR / "docs"

    @property
    def MENTAT_WORKTREES_DIR(self) -> Path:
        return self.MENTAT_DIR / "worktrees"

    @property
    def AGENTS_DIR(self) -> Path:
        return _agents_root()

    @property
    def SKILLS_DIR(self) -> Path:
        return self.AGENTS_DIR / "skills"

    @property
    def PLANS_DIR(self) -> Path:
        return self.AGENTS_DIR / "plans"

    @property
    def REPO_ROOT(self) -> Path:
        return _repo_root()

    @property
    def REPO_SKILLS_DIR(self) -> Path:
        return self.REPO_ROOT / ".agents" / "skills"

    @property
    def EVALS_DIR(self) -> Path:
        return self.REPO_ROOT / "evals"

    @property
    def LOGS_DIR(self) -> Path:
        return self.MENTAT_DIR / "logs"

    @property
    def LOG_SCRIPT(self) -> Path:
        return self.AGENTS_DIR / "skills" / "mentat-log" / "scripts" / "log.py"

    @property
    def CONTAINER_SCRIPT(self) -> Path:
        return self.AGENTS_DIR / "skills" / "mentat-container" / "scripts" / "container.py"

    @property
    def GATES_CODE_DIR(self) -> Path:
        return self.MENTAT_DIR / "lib" / "gates" / "code"

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is frozen")


sys.modules[__name__] = _Paths()  # type: ignore[assignment]
