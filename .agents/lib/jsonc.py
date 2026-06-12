"""JSONC (JSON with comments) parser + layered config reader. Stdlib only."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# Match // line-comments OR quoted strings (preserve strings, strip comments)
_COMMENT_RE = re.compile(r'//[^\n]*|"(?:[^"\\]|\\.)*"')


def _strip_comments(text: str) -> str:
    def _replacer(m: re.Match[str]) -> str:
        s = m.group(0)
        return "" if s.startswith("//") else s

    return _COMMENT_RE.sub(_replacer, text)


def load_jsonc(path: Path) -> dict[str, object]:
    try:
        return json.loads(_strip_comments(path.read_text()))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return {}


def _repo_config_path() -> Path | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip()) / ".mentat" / "config.jsonc"


def read_config() -> dict[str, object]:
    global_path = Path.home() / ".mentat" / "config.jsonc"
    global_cfg: dict[str, object] = load_jsonc(global_path) if global_path.exists() else {}
    repo_path = _repo_config_path()
    if repo_path is None or not repo_path.exists():
        return global_cfg
    return {**global_cfg, **load_jsonc(repo_path)}
