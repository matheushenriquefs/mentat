"""mentat-skill eval subcommand."""

from __future__ import annotations

import importlib.util as _ilu
import shutil
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


_utils = _load_sibling("utils")


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
