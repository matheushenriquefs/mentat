"""Shared file-walk utilities for code gates. Stdlib only."""

from __future__ import annotations

from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        ".dmux",
        ".mentat",
        "context",
        ".venv",
    }
)


def iter_files(root: Path):
    """Yield all files under root, skipping SKIP_DIRS."""
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p
