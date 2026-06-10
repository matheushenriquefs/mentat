"""Built-in git diff provider — fallback when no plugin fills the diff slot."""

from __future__ import annotations

import subprocess


class GitDiffProvider:
    """Runs `git diff HEAD` in the worktree."""

    def get_diff(self, worktree: str) -> str:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True,
            text=True,
            cwd=worktree,
        )
        return result.stdout
