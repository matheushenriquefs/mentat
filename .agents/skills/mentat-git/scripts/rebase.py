"""mentat-git rebase subcommand."""

from __future__ import annotations

import subprocess
import sys


def cmd_rebase(holding: str) -> int:
    """Fast-forward-only rebase onto holding branch."""
    result = subprocess.run(
        ["git", "rebase", holding],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(
            f"mentat-git: rebase onto {holding!r} failed (not fast-forward):\n{result.stderr}",
            file=sys.stderr,
        )
        raise SystemExit(result.returncode)
    return 0
