"""Container utility helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CHUNK_LABEL = "mentat_chunk"


def slug_for_cwd() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return Path.cwd().name
    return Path(result.stdout.strip()).name


def _docker() -> str:
    return os.environ.get("MENTAT_DOCKER", "docker")


class _DaemonDownType:
    """Falsy sentinel: docker ps rc != 0 or timeout → daemon unreachable."""

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "DAEMON_DOWN"


DAEMON_DOWN = _DaemonDownType()


def workspace_folder_for(worktree: Path) -> str:
    """Pure derivation of the in-container workspace path from a worktree path."""
    resolved = worktree.resolve()
    parts = resolved.parts
    for i, part in enumerate(parts):
        if part == "worktrees" and i + 2 < len(parts):
            chunk_id, slug = parts[i + 1], parts[i + 2]
            return f"/workspaces/{chunk_id}/{slug}"
    return f"/workspaces/{worktree.name}"


def resolve_workspace_folder(cwd: Path) -> str:
    return workspace_folder_for(cwd)


def chunk_slug_for_worktree(worktree: Path) -> str | None:
    """Return chunk_slug when worktree lives under chunk-keyed layout."""
    resolved = worktree.resolve()
    parts = resolved.parts
    for i, part in enumerate(parts):
        if part == "worktrees" and i + 2 < len(parts):
            return f"{parts[i + 1]}/{parts[i + 2]}"
    return None


def container_id_for(slug: str, *, label: str = CHUNK_LABEL) -> str | _DaemonDownType | None:
    try:
        result = subprocess.run(
            [_docker(), "ps", "-q", "--filter", f"label={label}={slug}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("mentat-container: docker ps timed out (daemon unresponsive?)", file=sys.stderr)
        return DAEMON_DOWN
    if result.returncode != 0:
        return DAEMON_DOWN
    cid = result.stdout.strip().splitlines()
    return cid[0] if cid else None


def container_oom_killed(slug: str, *, label: str = CHUNK_LABEL) -> bool:
    """True iff the labeled container's last exit was an OOM kill (not exit 137 alone)."""
    cid = container_id_for(slug, label=label)
    if not cid or cid is DAEMON_DOWN:
        try:
            result = subprocess.run(
                [
                    _docker(),
                    "ps",
                    "-aq",
                    "--filter",
                    f"label={label}={slug}",
                    "--filter",
                    "status=exited",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0 or not result.stdout.strip():
            return False
        cid = result.stdout.strip().splitlines()[0]
    try:
        inspect = subprocess.run(
            [_docker(), "inspect", "--format", "{{.State.OOMKilled}}", cid],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    if inspect.returncode != 0:
        return False
    return inspect.stdout.strip().lower() == "true"


def assert_safe_directory() -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("mentat-container: must run from inside a git worktree", file=sys.stderr)
        raise SystemExit(2)
