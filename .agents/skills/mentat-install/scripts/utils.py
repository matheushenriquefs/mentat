"""Filesystem helpers for install."""

from __future__ import annotations

import shutil
from pathlib import Path


def safe_symlink(source: Path, target: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    # Path.mkdir(exist_ok=True) raises FileExistsError if parent is a broken symlink,
    # because is_dir() returns False when the target is missing. Clear it first.
    if target.parent.is_symlink() and not target.parent.exists():
        target.parent.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(source)


def safe_copy(source: Path, target: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.copytree(str(source), str(target), dirs_exist_ok=True)


def safe_mkdir(path: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    path.mkdir(parents=True, exist_ok=True)


def write_default_config(path: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps({"harness": "claude-code", "diff_tool": None}, indent=2) + "\n")
