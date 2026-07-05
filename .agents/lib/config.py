"""Mentat config: layered TOML reader + JSONC helper for devcontainer files. Stdlib only."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

_CONFIG_NAME = "config.toml"

# Match // line-comments OR quoted strings (preserve strings, strip comments)
_COMMENT_RE = re.compile(r'//[^\n]*|"(?:[^"\\]|\\.)*"')


def _strip_comments(text: str) -> str:
    def _replacer(m: re.Match[str]) -> str:
        s = m.group(0)
        return "" if s.startswith("//") else s

    return _COMMENT_RE.sub(_replacer, text)


def load_jsonc(path: Path) -> dict[str, object]:
    """Parse a JSONC file (e.g. .devcontainer/devcontainer.json). {} on read/parse error."""
    try:
        return json.loads(_strip_comments(path.read_text()))  # type: ignore[no-any-return]
    except json.JSONDecodeError, OSError, UnicodeDecodeError:
        return {}


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError, OSError, UnicodeDecodeError:
        return {}


def load_config_file(path: Path) -> dict[str, object]:
    """Load a config.toml file. {} if missing or malformed."""
    if not path.exists():
        return {}
    return _load_toml(path)


def _layer_path(mentat_dir: Path) -> Path | None:
    toml_path = mentat_dir / _CONFIG_NAME
    return toml_path if toml_path.exists() else None


def _load_layer(mentat_dir: Path) -> dict[str, object]:
    path = _layer_path(mentat_dir)
    return load_config_file(path) if path is not None else {}


def config_status(mentat_dir: Path) -> tuple[str, str | None]:
    """Diagnostic validation of a .mentat dir's config.toml.

    Returns (human status, warning-or-None).
    """
    toml_path = mentat_dir / _CONFIG_NAME
    if toml_path.exists():
        try:
            with toml_path.open("rb") as fh:
                tomllib.load(fh)
            return ("valid", None)
        except tomllib.TOMLDecodeError, OSError, UnicodeDecodeError:
            return ("invalid — parse error", f"{_CONFIG_NAME} parse error")
    return ("absent", None)


def _repo_mentat_dir() -> Path | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip()) / ".mentat"


def read_config() -> dict[str, object]:
    """Layered config: ~/.mentat < repo .mentat (repo wins, shallow merge). {} if neither present."""
    global_cfg = _load_layer(Path.home() / ".mentat")
    repo_dir = _repo_mentat_dir()
    repo_cfg = _load_layer(repo_dir) if repo_dir is not None else {}
    return {**global_cfg, **repo_cfg}
