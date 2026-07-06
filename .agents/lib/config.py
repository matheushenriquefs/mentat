"""Mentat config: layered TOML reader + devcontainer.json parser. Stdlib only."""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

_CONFIG_NAME = "config.toml"
_DEFAULT_CONFIG_PATH = Path.home() / ".mentat" / "config.toml"


class ConfigError(ValueError):
    """Malformed or unreadable Mentat config."""


def get_config_dir() -> Path:
    """Return MENTAT_CONFIG path when set, else ~/.mentat/config.toml."""
    raw = os.environ.get("MENTAT_CONFIG", "").strip()
    if raw:
        return Path(raw)
    return _DEFAULT_CONFIG_PATH


def _strip_json_comments(text: str) -> str:
    """Return ``text`` with ``//`` line and ``/* */`` block comments removed and
    trailing commas dropped, ready for ``json.loads``.

    A single string-aware scan: comment markers and commas inside JSON string
    literals (including escaped quotes) are preserved verbatim — the footgun the
    old regex had (stripping ``//`` inside ``"https://…"``) cannot happen here.
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return _drop_trailing_commas("".join(out))


def _drop_trailing_commas(text: str) -> str:
    """Remove commas that precede a closing ``}`` or ``]`` (string-aware)."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_devcontainer_json(path: Path) -> dict[str, object]:
    """Parse a devcontainer.json (JSON + ``//``/``/* */`` comments + trailing commas).

    Fails loud: a malformed file raises :class:`ConfigError` rather than masking to
    ``{}``, so a broken devcontainer surfaces at read time instead of silently
    synthesizing a wrong container config.
    """
    try:
        return json.loads(_strip_json_comments(path.read_text()))  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: devcontainer.json parse error: {exc.msg} (line {exc.lineno})") from exc


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name} parse error") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read {path}") from exc


def load_config_file(path: Path) -> dict[str, object]:
    """Load a config.toml file. {} if missing; raises ConfigError if malformed."""
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
    """Repo-local .mentat dir — same contract as ``lib.git.repo_root()`` + ``/.mentat``."""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip()) / ".mentat"


def read_config() -> dict[str, object]:
    """Layered config: ~/.mentat < repo .mentat (repo wins, shallow merge). {} if neither present."""
    global_cfg = _load_layer(Path.home() / ".mentat")
    repo_dir = _repo_mentat_dir()
    repo_cfg = _load_layer(repo_dir) if repo_dir is not None else {}
    merged: dict[str, object] = {**global_cfg, **repo_cfg}
    if os.environ.get("MENTAT_CONFIG", "").strip():
        merged = {**merged, **load_config_file(get_config_dir())}
    return merged
