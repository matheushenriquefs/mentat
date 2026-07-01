"""E2E: a real ``mentat-install`` into a temp HOME, run twice for idempotency.

Runs the actual install CLI as a subprocess against a temp HOME with this repo as the
clone root — real symlinks, real config write — then runs it a second time. A second
run must be a clean no-op: exit 0, no conflict abort, and an identical symlink farm.
This guards the install contract that re-running after a `git pull` never double-installs
or trips over its own prior links.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/install.py"


def _run_install(home: Path) -> subprocess.CompletedProcess[str]:
    """Run the real install CLI non-interactively, with this repo as the clone root."""
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(INSTALL_PY), "--yes", "--no-color", "--skip-companions"],
        cwd=str(REPO_ROOT),  # cwd has .agents/skills → install auto-detects it as clone root
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def _repo_install(repo: Path) -> int:
    """Run the real per-repo scaffold (`do_repo_install`) in-process for one repo path."""
    install = load_script(INSTALL_PY, "e2e_install")
    return install.do_repo_install(repo_path=repo)


def _symlink_farm(home: Path) -> dict[str, str]:
    """Every symlink under HOME mapped to its resolved target — the deterministic
    install footprint (regular files like logs / shell rc are intentionally excluded)."""
    farm: dict[str, str] = {}
    for p in home.rglob("*"):
        if p.is_symlink():
            farm[str(p.relative_to(home))] = str(p.resolve())
    return farm


def test_install_is_idempotent(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    first = _run_install(home)
    assert first.returncode == 0, f"first install must succeed:\n{first.stderr}"
    assert "Aborted" not in first.stdout, f"first install must not abort:\n{first.stdout}"

    # Real artifacts landed: config + the canonical skill/harness symlinks.
    assert (home / ".mentat" / "config.toml").exists()
    skill_link = home / ".agents" / "skills" / "mentat-session"
    assert skill_link.is_symlink()
    assert skill_link.resolve() == (REPO_ROOT / ".agents/skills/mentat-session").resolve()

    farm_after_first = _symlink_farm(home)
    assert farm_after_first, "first install must create symlinks"

    # Re-run: clean no-op.
    second = _run_install(home)
    assert second.returncode == 0, f"re-install must succeed:\n{second.stderr}"
    assert "Aborted" not in second.stdout, f"re-install must not abort:\n{second.stdout}"

    # Idempotent: the symlink farm is byte-for-byte identical after the re-run.
    assert _symlink_farm(home) == farm_after_first, "re-install must not change the symlink farm"


def test_repo_install_scaffolds_config_and_gitignore(tmp_path, capsys):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".gitignore").write_text("*.pyc\n")

    assert _repo_install(repo) == 0

    cfg = repo / ".mentat" / "config.toml"
    assert cfg.exists(), "repo install must scaffold .mentat/config.toml"
    gi_lines = (repo / ".gitignore").read_text().splitlines()
    assert ".mentat/" in gi_lines, "repo install must append .mentat/ to an existing .gitignore"
    assert "*.pyc" in gi_lines, "existing .gitignore entries must be preserved"

    body_before = cfg.read_text()
    capsys.readouterr()

    # Re-run: existing config is a clean no-op skip, gitignore not double-appended.
    assert _repo_install(repo) == 0
    assert "already exists" in capsys.readouterr().out
    assert cfg.read_text() == body_before, "re-run must not rewrite the config"
    assert (repo / ".gitignore").read_text().splitlines().count(".mentat/") == 1


def test_repo_install_creates_gitignore_when_absent(tmp_path):
    repo = tmp_path / "bare"
    repo.mkdir()

    assert _repo_install(repo) == 0
    gi = repo / ".gitignore"
    assert gi.exists(), "repo install must create .gitignore when absent"
    assert gi.read_text().splitlines() == [".mentat/"]
