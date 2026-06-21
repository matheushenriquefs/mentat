"""mentat-git diff subcommand."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

utils = load_sibling(__file__, "identity")


def cmd_diff(base: str) -> int:
    """Show cumulative diff vs base. Respects config diff_tool."""
    config = utils.read_config()
    diff_tool = config.get("diff_tool")
    if diff_tool:
        return subprocess.run([diff_tool, base, "HEAD"]).returncode
    return subprocess.run(["git", "diff", base, "HEAD"]).returncode
