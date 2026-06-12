"""Container utility helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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


def container_id_for(slug: str) -> str | None:
    result = subprocess.run(
        [_docker(), "ps", "-q", "--filter", f"label=mentat_slug={slug}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    cid = result.stdout.strip().splitlines()
    return cid[0] if cid else None


def resolve_workspace_folder(cwd: Path) -> str:
    # Worktrees have .git as a file pointer — always use slug-based path so
    # container.py run uses the correct workdir regardless of what the
    # canonical devcontainer.json says (which targets /workspaces/mentat).
    if (cwd / ".git").is_file():
        return f"/workspaces/{cwd.name}"
    dcj = cwd / ".devcontainer" / "devcontainer.json"
    if not dcj.exists():
        return f"/workspaces/{cwd.name}"
    text = "\n".join(line for line in dcj.read_text().splitlines() if not line.lstrip().startswith("//"))
    try:
        data = json.loads(text)
        return data.get("workspaceFolder") or f"/workspaces/{cwd.name}"
    except json.JSONDecodeError:
        return f"/workspaces/{cwd.name}"


def assert_safe_directory() -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("mentat-container: must run from inside a git worktree", file=sys.stderr)
        raise SystemExit(2)
