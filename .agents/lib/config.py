"""Mentat config: layered TOML reader + JSONC helper for devcontainer files. Stdlib only."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

_CONFIG_NAME = "config.toml"
_LEGACY_NAME = "config.jsonc"

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
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return {}


_shim_warned = False


def _warn_legacy_once(path: Path) -> None:
    global _shim_warned
    if not _shim_warned:
        print(f"mentat: {path} is deprecated — rename to {_CONFIG_NAME} (TOML).", file=sys.stderr)
        _shim_warned = True


def load_config_file(path: Path) -> dict[str, object]:
    """Load one config file by suffix: .toml (preferred) or .jsonc (one-release shim). {} if missing/bad."""
    if not path.exists():
        return {}
    if path.suffix == ".jsonc":
        _warn_legacy_once(path)
        return load_jsonc(path)
    return _load_toml(path)


def _layer_path(mentat_dir: Path) -> Path | None:
    """The config file to read for one .mentat dir: config.toml if present, else legacy config.jsonc."""
    toml_path = mentat_dir / _CONFIG_NAME
    if toml_path.exists():
        return toml_path
    legacy = mentat_dir / _LEGACY_NAME
    return legacy if legacy.exists() else None


def _load_layer(mentat_dir: Path) -> dict[str, object]:
    """One config layer. Prefer config.toml; shim to config.jsonc (warn once) until it is retired."""
    path = _layer_path(mentat_dir)
    return load_config_file(path) if path is not None else {}


def config_status(mentat_dir: Path) -> tuple[str, str | None]:
    """Diagnostic validation of a .mentat dir's config. Prefer config.toml; accept legacy config.jsonc.

    Returns (human status, warning-or-None). Uses the canonical parsers (string-preserving JSONC),
    so a file that load_config_file would accept never reports 'invalid'.
    """
    toml_path = mentat_dir / _CONFIG_NAME
    if toml_path.exists():
        try:
            with toml_path.open("rb") as fh:
                tomllib.load(fh)
            return ("valid", None)
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            return ("invalid — parse error", f"{_CONFIG_NAME} parse error")
    legacy = mentat_dir / _LEGACY_NAME
    if legacy.exists():
        try:
            json.loads(_strip_comments(legacy.read_text()))
            return (f"legacy {_LEGACY_NAME} — rename to {_CONFIG_NAME}", None)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return ("invalid — parse error", f"{_LEGACY_NAME} parse error")
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
