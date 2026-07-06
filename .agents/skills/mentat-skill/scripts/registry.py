"""Shared helpers for mentat-skill."""

from __future__ import annotations

from pathlib import Path

from lib.support import paths


def default_skills_root() -> Path:
    return paths.REPO_SKILLS_DIR


def default_evals_dir() -> Path:
    return paths.EVALS_DIR
