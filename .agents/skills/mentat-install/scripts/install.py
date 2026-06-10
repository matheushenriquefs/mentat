#!/usr/bin/env python3
"""mentat-install — idempotent install of mentat skills."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parents[2]
_LOG_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-log/scripts/log.py"

import importlib.util as _ilu


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


_plan = _load_sibling("plan")
_render = _load_sibling("render")
_utils = _load_sibling("utils")


def _emit_installed() -> None:
    subprocess.run(
        ["python3", str(_LOG_SCRIPT), "emit", "mentat-install", "plan.started",
         '{"path":"install"}'],
        capture_output=True,
    )


def _execute_actions(ip, *, dry_run: bool) -> None:
    for action in ip.add:
        if action.action_type == "mkdir":
            _utils.safe_mkdir(action.target, dry_run=dry_run)
        elif action.action_type == "file-create":
            _utils.write_default_config(action.target, dry_run=dry_run)
        elif action.action_type == "symlink" and action.source:
            _utils.safe_symlink(action.source, action.target, dry_run=dry_run)
        elif action.action_type == "copy" and action.source:
            _utils.safe_copy(action.source, action.target, dry_run=dry_run)
    for action in ip.update:
        if action.action_type == "symlink" and action.source:
            _utils.safe_symlink(action.source, action.target, dry_run=dry_run)


def do_install(
    *,
    home: Path | None = None,
    clone_root: Path | None = None,
    yes: bool = False,
    dry_run: bool = False,
    color: bool | None = None,
) -> int:
    if home is None:
        home = Path.home()

    ip = _plan.compute_plan(home=home, clone_root=clone_root)
    output = _render.render(ip, color=color)
    print(output, end="")

    if dry_run:
        print("[dry-run] no changes made.")
        return 0

    if not yes and sys.stdin.isatty():
        answer = input("Proceed? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1

    _execute_actions(ip, dry_run=False)

    mentat_dir = home / ".mentat"
    config_file = mentat_dir / "config.jsonc"
    _utils.safe_mkdir(mentat_dir)
    _utils.write_default_config(config_file)

    _emit_installed()
    print("mentat-install: done.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mentat-install",
        description="Install mentat skills and configure ~/.mentat/",
    )
    p.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI output")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    color = False if args.no_color else None

    clone_root: Path | None = None
    cwd = Path.cwd()
    if (cwd / ".agents" / "skills").is_dir():
        clone_root = cwd

    sys.exit(do_install(yes=args.yes, dry_run=args.dry_run, color=color, clone_root=clone_root))


if __name__ == "__main__":
    main()
