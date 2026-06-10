"""Shared helpers for mentat-skill."""

from __future__ import annotations

from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parents[3]


def default_skills_root() -> Path:
    return _SKILL_ROOT / ".agents" / "skills"


def default_evals_dir() -> Path:
    return _SKILL_ROOT / "evals"
