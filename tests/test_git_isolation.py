"""Fast checks that pytest git isolation hides the live checkout."""

from __future__ import annotations

import subprocess

from tests.conftest import REPO_ROOT, init_git_repo


def test_ceiling_hides_live_repo_from_bare_tmp(tmp_path) -> None:
    live = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0 or r.stdout.strip() != live


def test_ephemeral_repo_does_not_move_live_head(tmp_path) -> None:
    live_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    repo = tmp_path / "sandbox"
    init_git_repo(repo, ceiling=tmp_path)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True)
    (repo / "delta").write_text("x\n")
    subprocess.run(["git", "add", "delta"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "delta"], cwd=repo, check=True, capture_output=True)
    live_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert live_before == live_after
