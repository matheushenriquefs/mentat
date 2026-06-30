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
