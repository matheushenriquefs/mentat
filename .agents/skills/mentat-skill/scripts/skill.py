#!/usr/bin/env python3
"""mentat-skill — eval / shrink / scaffold."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

_eval = load_sibling(__file__, "eval")
_shrink = load_sibling(__file__, "shrink")
_scaffold = load_sibling(__file__, "scaffold")

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
