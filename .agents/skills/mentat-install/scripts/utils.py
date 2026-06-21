"""Filesystem helpers for install."""

from __future__ import annotations

import shutil
from pathlib import Path


class InstallConflict(RuntimeError):
    """Raised when a non-symlink target blocks the install (D13 policy: no silent overwrite)."""


def safe_symlink(source: Path, target: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    # Path.mkdir(exist_ok=True) raises FileExistsError if parent is a broken symlink,
    # because is_dir() returns False when the target is missing. Clear it first.
    if target.parent.is_symlink() and not target.parent.exists():
        target.parent.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    # D13 conflict policy: real file/dir at target → abort. Symlinks may be replaced.
    if target.exists() and not target.is_symlink():
        raise InstallConflict(f"refusing to overwrite non-symlink at {target}")
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


_GLOBAL_CONFIG_TEMPLATE = """\
# Global mentat config. Repo .mentat/config.toml overlays these (repo wins, shallow merge).
harness = "claude-code"        # claude-code | cursor
# model = "claude-opus-4-8"
# concurrency = 3
# runtime = "docker"           # docker (containerized, default) | host (unsafe — ADR-0004 forfeit)
"""


def write_default_config(path: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_GLOBAL_CONFIG_TEMPLATE)
