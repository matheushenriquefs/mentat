"""Git skill helpers."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[3]
_CONTAINER_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-container/scripts/container.py"


def container_id_for_cwd() -> str | None:
    """Return container ID for the current worktree slug, or None."""
    slug_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if slug_result.returncode != 0:
        return None
    slug = Path(slug_result.stdout.strip()).name
    docker = os.environ.get("MENTAT_DOCKER", "docker")
    result = subprocess.run(
        [docker, "ps", "-q", "--filter", f"label=mentat_slug={slug}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    cids = result.stdout.strip().splitlines()
    return cids[0] if cids else None


def read_config() -> dict:
    config_path = Path.home() / ".mentat" / "config.jsonc"
    if not config_path.exists():
        return {}
    text = "\n".join(
        line for line in config_path.read_text().splitlines()
        if not line.lstrip().startswith("//")
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
