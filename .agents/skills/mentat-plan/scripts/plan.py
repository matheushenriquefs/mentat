#!/usr/bin/env python3
"""mentat-plan — write and resolve plan files."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[3]
_LOG_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-log/scripts/log.py"


def resolve_plan(ref: str) -> Path:
    """Resolve a plan slug-or-path to a canonical absolute Path.

    Pure path arithmetic — does not stat.
    """
    if "/" in ref or ref.endswith(".md"):
        return Path(ref).expanduser().resolve()
    return Path.home() / ".agents" / "plans" / f"{ref}.md"


def _emit(event: str, payload: str) -> None:
    subprocess.run(
        ["python3", str(_LOG_SCRIPT), "emit", "mentat-plan", event, payload],
        capture_output=True,
    )


def write_plan(slug: str, body_path: Path, *, plans_dir: Path | None = None) -> Path:
    if plans_dir is None:
        plans_dir = Path.home() / ".agents" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    dest = plans_dir / f"{slug}.md"
    path_str = str(dest)

    _emit("plan.started", f'{{"path":"{path_str}"}}')
    try:
        dest.write_text(body_path.read_text())
        _emit("plan.succeeded", f'{{"path":"{path_str}"}}')
    except OSError as exc:
        _emit("plan.failed", f'{{"path":"{path_str}","reason":"{exc}"}}')
        raise
    return dest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-plan", description="Plan file manager")
    sub = p.add_subparsers(dest="cmd")

    write_p = sub.add_parser("write", help="Write a plan file")
    write_p.add_argument("slug", help="Plan slug (becomes <slug>.md)")
    write_p.add_argument("body_path", help="Path to plan body file")

    resolve_p = sub.add_parser("resolve-slug", help="Print canonical path for slug-or-path")
    resolve_p.add_argument("ref", help="Slug or path")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "write":
        write_plan(args.slug, Path(args.body_path))
    elif args.cmd == "resolve-slug":
        print(resolve_plan(args.ref))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
