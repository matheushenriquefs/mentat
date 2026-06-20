"""mentat-skill eval subcommand."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

_utils = load_sibling(__file__, "utils")


def cmd_eval(skill_name: str, *, evals_dir: Path | None = None) -> int:
    if evals_dir is None:
        evals_dir = _utils.default_evals_dir()
    eval_file = evals_dir / f"{skill_name}.json"
    if not eval_file.exists():
        print(f"mentat-skill: eval file not found: {eval_file}", file=sys.stderr)
        raise SystemExit(1)
    if shutil.which("promptfoo") is None:
        print(
            "mentat-skill: promptfoo not found on PATH. Install: npm install -g promptfoo",
            file=sys.stderr,
        )
        raise SystemExit(1)
    result = subprocess.run(["promptfoo", "eval", "--config", str(eval_file)])
    return result.returncode


def run_eval_gate(skill_name: str, *, evals_dir: Path) -> bool:
    """Run eval gate against current. Returns True if passes."""
    eval_file = evals_dir / f"{skill_name}.json"
    if not eval_file.exists():
        return True
    if shutil.which("promptfoo") is None:
        return True
    result = subprocess.run(["promptfoo", "eval", "--config", str(eval_file)], capture_output=True)
    return result.returncode == 0
