"""mentat-git diff subcommand."""

from __future__ import annotations

import importlib.util as _ilu
import subprocess
import sys
from pathlib import Path


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


utils = _load_sibling("utils")


def cmd_diff(base: str) -> int:
    """Show cumulative diff vs base. Respects config diff_tool."""
    config = utils.read_config()
    diff_tool = config.get("diff_tool")

    result = subprocess.run([diff_tool, base, "HEAD"]) if diff_tool else subprocess.run(["git", "diff", base, "HEAD"])
    return result.returncode
