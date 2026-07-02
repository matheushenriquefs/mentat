"""E2E: drive the layered TOML config reader + JSONC helper over real files.

Every journey writes real files to a tmp dir (and, for :func:`read_config`, a real
``git init`` repo) then asserts on parsed/merged output. No mocks — these exercise
the actual filesystem, ``tomllib``, ``json``, and the ``git rev-parse`` subprocess
the config layer shells out to.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
config = load_script(REPO_ROOT / ".agents/lib/config.py", "config")


def test_load_jsonc_strips_comments_and_preserves_quoted_slashes(tmp_path):
    """load_jsonc parses a real JSONC file: // line-comments are stripped while a
    quoted string containing // is preserved verbatim. Covers lines 18-22, 27-28."""
    path = tmp_path / "devcontainer.json"
    path.write_text(
        "{\n"
        "  // this whole line is a comment\n"
        '  "image": "mcr.microsoft.com/devcontainers/base",  // trailing comment\n'
        '  "url": "https://example.com//path"\n'
        "}\n"
    )

    data = config.load_jsonc(path)

    assert data["image"] == "mcr.microsoft.com/devcontainers/base", "value must survive comment stripping"
    assert data["url"] == "https://example.com//path", "// inside a quoted string must NOT be treated as a comment"


def test_load_jsonc_returns_empty_on_bad_json(tmp_path):
    """load_jsonc swallows a JSONDecodeError and returns {}. Covers line 29-30."""
    path = tmp_path / "broken.json"
    path.write_text("{ this is not valid json ]")

    assert config.load_jsonc(path) == {}, "malformed JSONC must yield an empty dict"


def test_load_jsonc_returns_empty_on_missing_file(tmp_path):
    """load_jsonc swallows the OSError from a missing file and returns {}. Covers 29-30."""
    missing = tmp_path / "does-not-exist.json"

    assert config.load_jsonc(missing) == {}, "missing JSONC file must yield an empty dict"


def test_load_config_file_parses_valid_toml(tmp_path):
    """load_config_file reads a well-formed config.toml off disk. Covers lines 33-36, 45."""
    path = tmp_path / "config.toml"
    path.write_text('model = "opus"\n[gate]\nthreshold = 8\n')

    data = config.load_config_file(path)

    assert data["model"] == "opus", "top-level key must parse"
    assert data["gate"] == {"threshold": 8}, "nested table must parse"


def test_load_config_file_returns_empty_on_missing_file(tmp_path):
    """load_config_file short-circuits on a missing path. Covers line 44."""
    missing = tmp_path / "nope.toml"

    assert config.load_config_file(missing) == {}, "missing config file must yield {}"


def test_load_config_file_returns_empty_on_malformed_toml(tmp_path):
    """load_config_file returns {} when tomllib raises on garbage. Covers lines 37-38."""
    path = tmp_path / "config.toml"
    path.write_text("this is = = not toml\n")

    assert config.load_config_file(path) == {}, "malformed TOML must yield {}"


def test_config_status_valid(tmp_path):
    """config_status reports 'valid' for a parseable config.toml. Covers lines 63-68."""
    mentat_dir = tmp_path / ".mentat"
    mentat_dir.mkdir()
    (mentat_dir / "config.toml").write_text('model = "sonnet"\n')

    status, warning = config.config_status(mentat_dir)

    assert status == "valid", "well-formed config.toml must report valid"
    assert warning is None, "a valid config carries no warning"


def test_config_status_invalid(tmp_path):
    """config_status reports a parse error for malformed TOML. Covers lines 69-70."""
    mentat_dir = tmp_path / ".mentat"
    mentat_dir.mkdir()
    (mentat_dir / "config.toml").write_text("model = = broken\n")

    status, warning = config.config_status(mentat_dir)

    assert status == "invalid — parse error", "malformed config.toml must report a parse error"
    assert warning == "config.toml parse error", "the warning must name the offending file"


def test_config_status_absent(tmp_path):
    """config_status reports 'absent' when there is no config.toml. Covers line 71."""
    mentat_dir = tmp_path / ".mentat"
    mentat_dir.mkdir()

    status, warning = config.config_status(mentat_dir)

    assert status == "absent", "a dir with no config.toml must report absent"
    assert warning is None, "an absent config carries no warning"


def _write_layer(mentat_dir: Path, body: str) -> None:
    mentat_dir.mkdir(parents=True, exist_ok=True)
    (mentat_dir / "config.toml").write_text(body)


def test_read_config_empty_when_neither_layer_present(tmp_path, monkeypatch):
    """read_config returns {} when neither ~/.mentat nor repo .mentat exists.
    Covers lines 74-78 (git resolves) and 81-86 with both layers empty."""
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(repo)

    assert config.read_config() == {}, "no config layers must merge to an empty dict"


def test_read_config_global_only(tmp_path, monkeypatch):
    """read_config surfaces the global ~/.mentat layer when the repo has none.
    Covers the global branch of the shallow merge (lines 83-86)."""
    home = tmp_path / "home"
    home.mkdir()
    _write_layer(home / ".mentat", 'model = "opus"\nparallelism = 3\n')

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(repo)

    merged = config.read_config()

    assert merged == {"model": "opus", "parallelism": 3}, (
        "with no repo layer the global layer must pass through unchanged"
    )


def test_read_config_repo_overrides_global(tmp_path, monkeypatch):
    """read_config shallow-merges with the repo .mentat layer winning per key, while
    global-only keys survive. Covers _repo_mentat_dir resolving (74-78) and the merge (86)."""
    home = tmp_path / "home"
    home.mkdir()
    _write_layer(home / ".mentat", 'model = "opus"\nparallelism = 3\n')

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    _write_layer(repo / ".mentat", 'model = "sonnet"\n')

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(repo)

    merged = config.read_config()

    assert merged["model"] == "sonnet", "repo layer must override the global key"
    assert merged["parallelism"] == 3, "a global-only key must survive the merge"


def test_read_config_ignores_repo_layer_outside_git(tmp_path, monkeypatch):
    """read_config falls back to the global layer only when cwd is not in a git repo,
    exercising the returncode != 0 branch of _repo_mentat_dir. Covers lines 76-77, 85."""
    home = tmp_path / "home"
    home.mkdir()
    _write_layer(home / ".mentat", 'model = "opus"\n')

    non_repo = tmp_path / "loose"
    non_repo.mkdir()

    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(non_repo)

    merged = config.read_config()

    assert merged == {"model": "opus"}, "outside a git repo, only the global layer contributes"
