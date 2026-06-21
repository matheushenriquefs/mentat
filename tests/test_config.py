"""lib/config.py: layered TOML read_config, devcontainer load_jsonc, and config_status."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import config  # noqa: E402

# ── load_jsonc (genuine JSONC, e.g. devcontainer.json) ────────────────────────


def test_load_jsonc_strips_line_comments(tmp_path):
    f = tmp_path / "devcontainer.json"
    f.write_text('{"a": 1, // comment\n"b": 2}')
    assert config.load_jsonc(f) == {"a": 1, "b": 2}


def test_load_jsonc_preserves_inline_url(tmp_path):
    f = tmp_path / "devcontainer.json"
    f.write_text('{"postCreate": "echo https://example.com"}')
    assert config.load_jsonc(f) == {"postCreate": "echo https://example.com"}


def test_load_jsonc_returns_empty_on_invalid(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not valid json")
    assert config.load_jsonc(f) == {}


# ── read_config layering (TOML, repo over global) ─────────────────────────────


def test_read_config_global_only(tmp_path):
    (tmp_path / ".mentat").mkdir()
    (tmp_path / ".mentat" / "config.toml").write_text('harness = "test-harness"\n')
    with patch.object(config, "_repo_mentat_dir", return_value=None), patch("pathlib.Path.home", return_value=tmp_path):
        result = config.read_config()
    assert result == {"harness": "test-harness"}


def test_read_config_repo_overrides_global(tmp_path):
    global_dir = tmp_path / "home"
    (global_dir / ".mentat").mkdir(parents=True)
    (global_dir / ".mentat" / "config.toml").write_text('harness = "global"\nconcurrency = 3\n')
    repo_mentat = tmp_path / "repo" / ".mentat"
    repo_mentat.mkdir(parents=True)
    (repo_mentat / "config.toml").write_text('harness = "repo"\n')
    with (
        patch.object(config, "_repo_mentat_dir", return_value=repo_mentat),
        patch("pathlib.Path.home", return_value=global_dir),
    ):
        result = config.read_config()
    assert result["harness"] == "repo"
    assert result["concurrency"] == 3


def test_read_config_missing_returns_empty(tmp_path):
    with patch.object(config, "_repo_mentat_dir", return_value=None), patch("pathlib.Path.home", return_value=tmp_path):
        assert config.read_config() == {}


def test_read_config_malformed_repo_falls_back_to_global(tmp_path):
    global_dir = tmp_path / "home"
    (global_dir / ".mentat").mkdir(parents=True)
    (global_dir / ".mentat" / "config.toml").write_text('harness = "claude-code"\n')
    repo_mentat = tmp_path / "repo" / ".mentat"
    repo_mentat.mkdir(parents=True)
    (repo_mentat / "config.toml").write_text("this = = not valid toml")
    with (
        patch.object(config, "_repo_mentat_dir", return_value=repo_mentat),
        patch("pathlib.Path.home", return_value=global_dir),
    ):
        result = config.read_config()
    assert result == {"harness": "claude-code"}


# ── load_config_file ──────────────────────────────────────────────────────────


def test_load_config_file_reads_toml(tmp_path):
    toml_f = tmp_path / "config.toml"
    toml_f.write_text("concurrency = 4\n")
    assert config.load_config_file(toml_f) == {"concurrency": 4}
    assert config.load_config_file(tmp_path / "absent.toml") == {}


# ── config_status diagnostic (used by mentat-container doctor) ─────────────────


def test_config_status_toml_valid(tmp_path):
    (tmp_path / "config.toml").write_text('harness = "x"\n')
    status, warn = config.config_status(tmp_path)
    assert status == "valid"
    assert warn is None


def test_config_status_invalid_toml_warns(tmp_path):
    (tmp_path / "config.toml").write_text("not = = valid")
    status, warn = config.config_status(tmp_path)
    assert "invalid" in status
    assert warn is not None


def test_load_jsonc_returns_empty_on_non_utf8(tmp_path):
    f = tmp_path / "devcontainer.json"
    f.write_bytes(b'{"a": "\xff\xfe not utf-8"}')
    assert config.load_jsonc(f) == {}


def test_load_config_file_toml_non_utf8_returns_empty(tmp_path):
    f = tmp_path / "config.toml"
    f.write_bytes(b'harness = "\xff\xfe"\n')
    assert config.load_config_file(f) == {}


def test_config_status_non_utf8_toml_is_invalid_not_crash(tmp_path):
    """Regression: a non-UTF-8 config file must report 'invalid', never raise
    UnicodeDecodeError (a ValueError subclass, not caught by the OSError arm)."""
    (tmp_path / "config.toml").write_bytes(b'harness = "\xff\xfe"\n')
    status, warn = config.config_status(tmp_path)
    assert "invalid" in status
    assert warn is not None


def test_config_status_absent(tmp_path):
    status, warn = config.config_status(tmp_path)
    assert status == "absent"
    assert warn is None


def test_config_stdlib_only():
    import ast

    src = (REPO_ROOT / ".agents" / "lib" / "config.py").read_text()
    tree = ast.parse(src)
    stdlib = sys.stdlib_module_names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] in stdlib, f"non-stdlib from-import: {node.module}"


def test_no_subprocess_when_repo_dir_mocked():
    """Guard: read_config layering tests must not shell out to git when _repo_mentat_dir is patched."""
    with (
        patch.object(config, "_repo_mentat_dir", return_value=None),
        patch.object(subprocess, "run", side_effect=AssertionError("git must not be called")),
        patch("pathlib.Path.home", return_value=Path("/nonexistent-xyz")),
    ):
        assert config.read_config() == {}
