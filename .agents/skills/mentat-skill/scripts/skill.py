#!/usr/bin/env python3
"""mentat-skill — eval / shrink / scaffold."""

from __future__ import annotations

import argparse
import importlib.util as _ilu
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


_eval = _load_sibling("eval")
_shrink = _load_sibling("shrink")
_scaffold = _load_sibling("scaffold")

# Re-exports
cmd_eval = _eval.cmd_eval
cmd_scaffold = _scaffold.cmd_scaffold
_invoke_shrink_harness = _shrink._invoke_shrink_harness
_run_eval_gate = _eval.run_eval_gate


def cmd_shrink(skill_name: str, *, skills_root: Path | None = None, evals_dir: Path | None = None) -> int:
    return _shrink.cmd_shrink(skill_name, skills_root=skills_root, evals_dir=evals_dir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-skill")
    sub = p.add_subparsers(dest="cmd", required=True)

    eval_p = sub.add_parser("eval", help="Run evals for a skill")
    eval_p.add_argument("skill_name", nargs="?", default=None)

    shrink_p = sub.add_parser("shrink", help="Propose leaner SKILL.md")
    shrink_p.add_argument("skill_name", nargs="?", default=None)

    scaffold_p = sub.add_parser("scaffold", help="Scaffold a new skill")
    scaffold_p.add_argument("skill_name")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "eval":
        sys.exit(cmd_eval(args.skill_name or Path.cwd().name))
    elif args.cmd == "shrink":
        sys.exit(cmd_shrink(args.skill_name or Path.cwd().name))
    elif args.cmd == "scaffold":
        sys.exit(cmd_scaffold(args.skill_name))


if __name__ == "__main__":
    main()
