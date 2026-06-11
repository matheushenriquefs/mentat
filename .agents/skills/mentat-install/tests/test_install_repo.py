"""Slice D: mentat-install --repo scaffolds per-repo config."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

INSTALL_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load_install():
    spec = importlib.util.spec_from_file_location("install_mod", INSTALL_SCRIPTS / "install.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["install_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)


def test_repo_install_creates_config(tmp_path):
    """--repo creates .mentat/config.jsonc template."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)

    install = _load_install()
    rc = install.do_repo_install(repo_path=repo)

    assert rc == 0
    cfg = repo / ".mentat" / "config.jsonc"
    assert cfg.exists(), f"config.jsonc not created at {cfg}"
    content = cfg.read_text()
    assert "harness" in content


def test_repo_install_appends_gitignore(tmp_path):
    """--repo appends .mentat/ to .gitignore if absent."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)

    install = _load_install()
    install.do_repo_install(repo_path=repo)

    gi = repo / ".gitignore"
    assert gi.exists(), ".gitignore not created"
    assert ".mentat/" in gi.read_text()


def test_repo_install_gitignore_existing_not_duplicated(tmp_path):
    """--repo doesn't duplicate .mentat/ if already in .gitignore."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)
    gi = repo / ".gitignore"
    gi.write_text(".mentat/\n")

    install = _load_install()
    install.do_repo_install(repo_path=repo)

    content = gi.read_text()
    assert content.count(".mentat/") == 1


def test_repo_install_noop_if_config_exists(tmp_path):
    """--repo is no-op if .mentat/config.jsonc already present."""
    repo = tmp_path / "myrepo"
    _init_git_repo(repo)
    cfg = repo / ".mentat" / "config.jsonc"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{"harness": "cursor"}')

    install = _load_install()
    rc = install.do_repo_install(repo_path=repo)

    assert rc == 0
    assert cfg.read_text() == '{"harness": "cursor"}', "existing config must not be overwritten"
