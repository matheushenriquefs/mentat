#!/usr/bin/env python3
"""mentat-plan — write and resolve plan files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import plans as _plans  # noqa: E402
from lib.agent import ensure_agent  # noqa: E402


def resolve_plan(ref: str) -> Path:
    """Resolve a plan slug-or-path to a canonical absolute Path. Pure path arithmetic — does not stat."""
    return _plans.resolve_plan_ref(ref)


def write_plan(slug: str, body_path: Path, *, plans_dir: Path | None = None) -> Path:
    if plans_dir is None:
        plans_dir = Path.home() / ".agents" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    dest = plans_dir / f"{slug}.md"

    ensure_agent("mentat-plan", slug)
    dest.write_text(body_path.read_text())
    return dest


def suggest_tasks(slug: str) -> str:
    """Next-step hint shown after a plan is written: turn slices into tasks.

    Closes the plan → tasks → track handoff so slices become trackable.
    """
    return f"Next: run `/mentat-tasks {slug}` to turn this plan's slices into trackable tasks."


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-plan", description="Plan file manager")
    sub = p.add_subparsers(dest="cmd")

    write_p = sub.add_parser("write", help="Write a plan file")
    write_p.add_argument("slug", metavar="plan-ref", help="Plan ref (bare slug → ~/.agents/plans/{plan-ref}.md)")
    write_p.add_argument("body_path", metavar="body-path", help="{body-path} plan body file")

    resolve_p = sub.add_parser("resolve-slug", help="Print canonical path for plan-ref")
    resolve_p.add_argument("ref", metavar="plan-ref", help="Plan ref (bare slug or path)")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "write":
        write_plan(args.slug, Path(args.body_path))
        print(suggest_tasks(args.slug))
    elif args.cmd == "resolve-slug":
        print(resolve_plan(args.ref))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
