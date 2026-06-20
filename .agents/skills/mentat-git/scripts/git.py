#!/usr/bin/env python3
"""mentat-git — commit / rebase / diff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

_commit = load_sibling(__file__, "commit")
_rebase = load_sibling(__file__, "rebase")
_diff = load_sibling(__file__, "diff")
_worktree = load_sibling(__file__, "worktree")

# Re-exports
utils = _commit.utils
cmd_commit = _commit.cmd_commit
cmd_rebase = _rebase.cmd_rebase
cmd_diff = _diff.cmd_diff
cmd_worktree_create = _worktree.cmd_worktree_create
is_main_worktree = _worktree.is_main_worktree


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
    wt_create.add_argument("--base", default=None, help="Base branch (auto-detected when omitted)")
    wt_create.add_argument("--parent", default=None, help="Parent dir (default: <repo>/.mentat/worktrees/)")

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
