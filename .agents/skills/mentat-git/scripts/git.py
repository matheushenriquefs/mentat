#!/usr/bin/env python3
"""mentat-git — commit / rebase / diff."""

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


_commit = _load_sibling("commit")
_rebase = _load_sibling("rebase")
_diff = _load_sibling("diff")
_worktree = _load_sibling("worktree")

# Re-exports
utils = _commit.utils
cmd_commit = _commit.cmd_commit
cmd_rebase = _rebase.cmd_rebase
cmd_diff = _diff.cmd_diff
cmd_worktree_create = _worktree.cmd_worktree_create


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-git")
    sub = p.add_subparsers(dest="cmd", required=True)

    commit_p = sub.add_parser("commit", help="Stage and commit")
    commit_p.add_argument("git_args", nargs="*", help="Args passed to git commit")

    rebase_p = sub.add_parser("rebase", help="Fast-forward-only rebase")
    rebase_p.add_argument("holding", help="Holding branch to rebase onto")

    diff_p = sub.add_parser("diff", help="Cumulative diff vs base")
    diff_p.add_argument("base", nargs="?", default="main", help="Base branch (default: main)")

    wt_p = sub.add_parser("worktree", help="Worktree management")
    wt_sub = wt_p.add_subparsers(dest="wt_cmd", required=True)
    wt_create = wt_sub.add_parser("create", help="Create a sibling worktree on a new branch")
    wt_create.add_argument("slug", help="Worktree dir name + new branch name")
    wt_create.add_argument("--base", default="main", help="Base branch (default: main)")
    wt_create.add_argument("--parent", default=None, help="Parent dir (default: sibling of main repo)")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "commit":
        sys.exit(cmd_commit(args.git_args))
    elif args.cmd == "rebase":
        sys.exit(cmd_rebase(args.holding))
    elif args.cmd == "diff":
        sys.exit(cmd_diff(args.base))
    elif args.cmd == "worktree" and args.wt_cmd == "create":
        parent = Path(args.parent) if args.parent else None
        sys.exit(cmd_worktree_create(args.slug, base=args.base, parent=parent))


if __name__ == "__main__":
    main()
