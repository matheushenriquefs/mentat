"""Slice C: read_config() must layer repo overlay over global config."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))


def _load_utils():
    spec = importlib.util.spec_from_file_location("orch_utils_layered", ORCH_SCRIPTS / "utils.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["orch_utils_layered"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_jsonc(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _jsonc_mod():
    import lib.jsonc as _m

    return _m


def test_global_only(tmp_path, monkeypatch):
    """No repo config → returns global dict."""
    home = tmp_path / "home"
    global_cfg = home / ".mentat" / "config.jsonc"
    _write_jsonc(global_cfg, '{"harness": "claude-code"}')
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _load_utils()
    monkeypatch.setattr(_jsonc_mod(), "_repo_config_path", lambda: None)

    result = _jsonc_mod().read_config()
    assert result == {"harness": "claude-code"}


def test_repo_only(tmp_path, monkeypatch):
    """No global file, repo config present → returns repo dict."""
    home = tmp_path / "home"
    repo_cfg = tmp_path / "repo" / ".mentat" / "config.jsonc"
    _write_jsonc(repo_cfg, '{"harness": "cursor"}')
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _load_utils()
    monkeypatch.setattr(_jsonc_mod(), "_repo_config_path", lambda: repo_cfg)

    result = _jsonc_mod().read_config()
    assert result == {"harness": "cursor"}


def test_repo_overlay_wins(tmp_path, monkeypatch):
    """Both present → shallow merge, repo keys win."""
    home = tmp_path / "home"
    global_cfg = home / ".mentat" / "config.jsonc"
    _write_jsonc(global_cfg, '{"harness": "claude-code", "concurrency": 3}')
    repo_cfg = tmp_path / "repo" / ".mentat" / "config.jsonc"
    _write_jsonc(repo_cfg, '{"harness": "cursor"}')
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _load_utils()
    monkeypatch.setattr(_jsonc_mod(), "_repo_config_path", lambda: repo_cfg)

    result = _jsonc_mod().read_config()
    assert result["harness"] == "cursor"
    assert result["concurrency"] == 3


def test_repo_harness_overrides_global(tmp_path, monkeypatch):
    """repo harness:cursor overrides global harness:claude-code."""
    home = tmp_path / "home"
    global_cfg = home / ".mentat" / "config.jsonc"
    _write_jsonc(global_cfg, '{"harness": "claude-code"}')
    repo_cfg = tmp_path / "repo" / ".mentat" / "config.jsonc"
    _write_jsonc(repo_cfg, '{"harness": "cursor"}')
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _load_utils()
    monkeypatch.setattr(_jsonc_mod(), "_repo_config_path", lambda: repo_cfg)

    result = _jsonc_mod().read_config()
    assert result.get("harness") == "cursor"


def test_no_git_repo_falls_back_to_global(tmp_path, monkeypatch):
    """cwd outside any git repo → no exception, returns global only."""
    home = tmp_path / "home"
    global_cfg = home / ".mentat" / "config.jsonc"
    _write_jsonc(global_cfg, '{"harness": "claude-code"}')
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _load_utils()
    monkeypatch.setattr(_jsonc_mod(), "_repo_config_path", lambda: None)

    result = _jsonc_mod().read_config()
    assert result == {"harness": "claude-code"}


def test_malformed_repo_overlay_falls_back_to_global(tmp_path, monkeypatch):
    """Malformed repo JSONC → keep global, swallow JSON error."""
    home = tmp_path / "home"
    global_cfg = home / ".mentat" / "config.jsonc"
    _write_jsonc(global_cfg, '{"harness": "claude-code"}')
    repo_cfg = tmp_path / "repo" / ".mentat" / "config.jsonc"
    _write_jsonc(repo_cfg, "{ this is not valid json }")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    _load_utils()
    monkeypatch.setattr(_jsonc_mod(), "_repo_config_path", lambda: repo_cfg)

    result = _jsonc_mod().read_config()
    assert result == {"harness": "claude-code"}
