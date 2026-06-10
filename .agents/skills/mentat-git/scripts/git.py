#!/usr/bin/env python3
"""mentat-git — commit / rebase / diff."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import utils


def cmd_commit(git_args: list[str]) -> int:
    """Stage and commit. Route through container if present."""
    cid = utils.container_id_for_cwd()
    if cid:
        docker = os.environ.get("MENTAT_DOCKER", "docker")
        wt_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
        )
        ws = f"/workspaces/{Path(wt_result.stdout.strip()).name}" if wt_result.returncode == 0 else "/workspaces/mentat"
        cmd = [docker, "exec", "--workdir", ws, cid, "git", "commit"] + git_args
        result = subprocess.run(cmd)
    else:
        result = subprocess.run(["git", "commit"] + git_args)
    return result.returncode


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


def cmd_diff(base: str) -> int:
    """Show cumulative diff of current branch vs base. Respects config diff_tool."""
    config = utils.read_config()
    diff_tool = config.get("diff_tool")

    if diff_tool:
        result = subprocess.run([diff_tool, base, "HEAD"])
    else:
        result = subprocess.run(["git", "diff", base, "HEAD"])
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-git")
    sub = p.add_subparsers(dest="cmd", required=True)

    commit_p = sub.add_parser("commit", help="Stage and commit")
    commit_p.add_argument("git_args", nargs="*", help="Args passed to git commit")

    rebase_p = sub.add_parser("rebase", help="Fast-forward-only rebase")
    rebase_p.add_argument("holding", help="Holding branch to rebase onto")

    diff_p = sub.add_parser("diff", help="Cumulative diff vs base")
    diff_p.add_argument("base", nargs="?", default="main", help="Base branch (default: main)")

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


if __name__ == "__main__":
    main()
