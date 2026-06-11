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
        capture_output=True,
        text=True,
    )
    if slug_result.returncode != 0:
        return None
    slug = Path(slug_result.stdout.strip()).name
    docker = os.environ.get("MENTAT_DOCKER", "docker")
    result = subprocess.run(
        [docker, "ps", "-q", "--filter", f"label=mentat_slug={slug}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    cids = result.stdout.strip().splitlines()
    return cids[0] if cids else None


def _load_jsonc(path: Path) -> dict:
    text = "\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("//"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _repo_config_path() -> Path | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip()) / ".mentat" / "config.jsonc"


def read_config() -> dict:
    global_path = Path.home() / ".mentat" / "config.jsonc"
    global_cfg = _load_jsonc(global_path) if global_path.exists() else {}
    repo_path = _repo_config_path()
    if repo_path is None or not repo_path.exists():
        return global_cfg
    return {**global_cfg, **_load_jsonc(repo_path)}
