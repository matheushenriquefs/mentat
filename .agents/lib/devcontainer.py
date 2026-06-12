"""Devcontainer module API. Wraps docker CLI. Stdlib only (ADR-0008)."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LABEL = "mentat_slug"
DEFAULT_UNTIL = "1h"


@dataclass(frozen=True)
class PruneResult:
    reclaimed_bytes: int | None
    containers_removed: int


def _run_docker(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError:
        print("devcontainer: docker not on PATH", file=sys.stderr)
        return None


def prune(label: str = DEFAULT_LABEL, until: str = DEFAULT_UNTIL) -> PruneResult:
    r = _run_docker(["docker", "container", "prune", "-f", "--filter", f"label={label}", "--filter", f"until={until}"])
    if r is None or r.returncode != 0:
        return PruneResult(None, 0)
    reclaimed: int | None = None
    m = re.search(r"Total reclaimed space:\s+(\d+)", r.stdout)
    if m:
        reclaimed = int(m.group(1))
    removed = sum(
        1
        for line in r.stdout.splitlines()
        if line.strip() and line.strip() not in ("Deleted Containers:",) and not line.startswith("Total")
    )
    return PruneResult(reclaimed, removed)


def list_active_slugs(label: str = DEFAULT_LABEL) -> set[str]:
    r = _run_docker(
        [
            "docker",
            "ps",
            "--filter",
            f"label={label}",
            "--format",
            f'{{{{.Label "{label}"}}}}',
        ]
    )
    if r is None or r.returncode != 0:
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def container_id_for_slug(slug: str, label: str = DEFAULT_LABEL) -> str | None:
    r = _run_docker(
        [
            "docker",
            "ps",
            "--filter",
            f"label={label}={slug}",
            "--format",
            "{{.ID}}",
        ]
    )
    if r is None or r.returncode != 0:
        return None
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return lines[0] if lines else None


def down(slug: str) -> bool:
    """Remove container by slug. Returns True if removed or confirmed not running. False on docker error."""
    cid = container_id_for_slug(slug)
    if cid is None:
        # Distinguish "not found" from "docker error" via stopped-container check
        r = _run_docker(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label={DEFAULT_LABEL}={slug}",
                "--filter",
                "status=exited",
            ]
        )
        if r is None or r.returncode != 0:
            return False  # docker error — cannot confirm
        if not r.stdout.strip():
            return True  # confirmed not running
        cid = r.stdout.strip().splitlines()[0]
    r = _run_docker(["docker", "rm", "-f", cid])
    return r is not None and r.returncode == 0


def up(slug: str, wt: Path) -> bool:
    """Bring container up from stopped or cold state. Returns True if container running."""
    # Restart a stopped container
    r = _run_docker(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label={DEFAULT_LABEL}={slug}",
            "--filter",
            "status=exited",
        ]
    )
    if r and r.returncode == 0 and r.stdout.strip():
        _run_docker(["docker", "start", r.stdout.strip()])
        return container_id_for_slug(slug) is not None
    # Cold start via devcontainer CLI
    git_dir_r = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        cwd=str(wt),
    )
    git_dir = git_dir_r.stdout.strip() if git_dir_r.returncode == 0 else ""
    ws = f"/workspaces/{slug}"
    cmd = [
        "devcontainer",
        "up",
        "--workspace-folder",
        str(wt),
        "--id-label",
        f"{DEFAULT_LABEL}={slug}",
    ]
    if git_dir:
        cmd += ["--remote-env", f"GIT_DIR={git_dir}", "--remote-env", f"GIT_WORK_TREE={ws}"]
    try:
        result = subprocess.run(cmd, capture_output=False)
    except FileNotFoundError:
        print("devcontainer: devcontainer CLI not on PATH", file=sys.stderr)
        return False
    return result.returncode == 0 or container_id_for_slug(slug) is not None


def run(slug: str, cmd: str) -> subprocess.CompletedProcess[str] | None:
    cid = container_id_for_slug(slug)
    if cid is None:
        return None
    return _run_docker(["docker", "exec", cid, "sh", "-c", cmd])
