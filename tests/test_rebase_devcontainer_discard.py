"""LQ-BUG1: _rebase_chunk discards .devcontainer/ before rebasing.

mentat-container up MODIFIES tracked .devcontainer/devcontainer.json in the
worktree (changes workspaceFolder, name, etc.) but never stages the change.
git rebase then refuses "You have unstaged changes", causing a spurious
rebase-conflicted eject.  The fix calls git.discard_path on .devcontainer/
before the rebase.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import lib.git as git_lib

from tests.conftest import load_script

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _cmd(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _setup_rebase_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Repo where both main and feature have committed devcontainer.json.

    main is one commit ahead of feature's base so a rebase is needed.
    Returns (main_repo, feature_worktree).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _cmd(["init", "-b", "main", str(repo)], tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "T"), ("commit.gpgsign", "false")):
        _cmd(["config", k, v], repo)

    # Commit devcontainer.json on main
    (repo / ".devcontainer").mkdir()
    (repo / ".devcontainer" / "devcontainer.json").write_text('{"name": "mentat"}\n')
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "base with devcontainer"], repo)

    # Feature branch adds feature.txt
    _cmd(["checkout", "-b", "feature"], repo)
    (repo / "feature.txt").write_text("feat\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "feature"], repo)

    # Main advances (causes divergence so rebase is needed)
    _cmd(["checkout", "main"], repo)
    (repo / "holding.txt").write_text("holding\n")
    _cmd(["add", "."], repo)
    _cmd(["commit", "-m", "main advance"], repo)

    feature_wt = tmp_path / "feature-wt"
    _cmd(["worktree", "add", str(feature_wt), "feature"], repo)
    return repo, feature_wt


def test_discard_path_preserves_untracked_devcontainer(tmp_path: Path) -> None:
    """discard_path must NOT remove untracked files under .devcontainer/.

    Synthesized overlay files (e.g. devcontainer-lock.json, mentat-dev.compose.yml)
    are untracked but required for container bring-up. git clean -fd would silently
    delete them — discard_path must only restore tracked files (git checkout --).
    """
    _repo, feature_wt = _setup_rebase_fixture(tmp_path)

    # Simulate a synthesized overlay file that was NOT committed.
    (feature_wt / ".devcontainer" / "devcontainer-lock.json").write_text('{"lockfileVersion": 1}\n')

    git_lib.discard_path(feature_wt, ".devcontainer/")

    assert (feature_wt / ".devcontainer" / "devcontainer-lock.json").exists(), (
        "discard_path must preserve untracked overlay files in .devcontainer/"
    )


def test_discard_path_restores_tracked_devcontainer(tmp_path: Path) -> None:
    """discard_path must restore tracked .devcontainer/ files to HEAD."""
    _repo, feature_wt = _setup_rebase_fixture(tmp_path)

    # Simulate mentat-container up overwriting the tracked devcontainer.json
    dcj = feature_wt / ".devcontainer" / "devcontainer.json"
    assert dcj.exists(), "devcontainer.json must exist as tracked file in fixture"
    dcj.write_text('{"name": "mentat-overwritten-by-container-up"}\n')

    git_lib.discard_path(feature_wt, ".devcontainer/")

    content = dcj.read_text()
    assert "mentat-overwritten-by-container-up" not in content
    assert "mentat" in content


def test_rebase_chunk_succeeds_with_dirty_devcontainer(tmp_path: Path) -> None:
    """_rebase_chunk must succeed when .devcontainer/devcontainer.json has unstaged changes.

    RED: fails before fix because git rebase refuses "You have unstaged changes"
    when mentat-container up overwrites the tracked devcontainer.json.
    GREEN: passes after _rebase_chunk calls discard_path before rebasing.
    """
    _repo, feature_wt = _setup_rebase_fixture(tmp_path)

    # Simulate mentat-container up: overwrite tracked devcontainer.json (unstaged)
    dcj = feature_wt / ".devcontainer" / "devcontainer.json"
    dcj.write_text('{"name": "mentat-overwritten-by-container-up", "workspaceFolder": "/workspaces/feature-wt"}\n')

    lq = load_script(_SCRIPTS / "landing.py", "landing")
    chunk = lq.Chunk(slug="feature", worktree=feature_wt)

    tip, err = lq._rebase_chunk(chunk, "main")

    assert err is None, f"rebase must succeed despite dirty .devcontainer/: {err}"
    assert tip is not None and len(tip) == 40
