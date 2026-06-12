"""Git skill helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))


def container_id_for_cwd() -> str | None:
    """Return container ID for the current worktree slug, or None."""
    from lib import devcontainer

    slug = Path.cwd().name
    return devcontainer.container_id_for_slug(slug)


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
