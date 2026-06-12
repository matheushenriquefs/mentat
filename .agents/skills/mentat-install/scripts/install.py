#!/usr/bin/env python3
"""mentat-install — idempotent install of mentat skills."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

import importlib.util as _ilu

from lib.events import bind  # noqa: E402

_emit_installed_fn = bind("mentat-install")


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
_companions = _load_sibling("companions")


def _emit_installed() -> None:
    _emit_installed_fn("plan.started", {"path": "install"})


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
    skip_companions: bool = False,
) -> int:
    if home is None:
        home = Path.home()

    ip = _plan.compute_plan(home=home, clone_root=clone_root)
    output = _render.render(ip, color=color)
    print(output, end="")

    if dry_run:
        print("[dry-run] no changes made.")
        return 0

    if ip.conflicts:
        print("Aborted: real file/dir at one or more symlink targets (D13).", file=sys.stderr)
        print("Resolve manually and re-run.", file=sys.stderr)
        return 65

    if not skip_companions:
        _companions.install_all(yes=yes)

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


_REPO_CONFIG_TEMPLATE = """\
{
  // Per-repo mentat config. Keys here overlay ~/.mentat/config.jsonc (repo wins, shallow merge).
  // Uncomment and set values to override the global default.
  //
  // "harness": "cursor",        // claude-code | cursor
  // "model": "claude-opus-4-7",
  // "concurrency": 3,
  // "plugins": []
}
"""


def do_repo_install(*, repo_path: Path | None = None) -> int:
    """Scaffold .mentat/config.jsonc + .gitignore entry in a repo.

    repo_path defaults to git rev-parse --show-toplevel. No-op if
    .mentat/config.jsonc already exists (exits 0 without overwriting).
    """
    if repo_path is None:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode != 0:
            print("mentat-install --repo: not inside a git repo", file=sys.stderr)
            return 1
        repo_path = Path(r.stdout.strip())

    cfg = repo_path / ".mentat" / "config.jsonc"
    if cfg.exists():
        print(f"mentat-install --repo: {cfg} already exists, skipping.")
        return 0

    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(_REPO_CONFIG_TEMPLATE)
    print(f"mentat-install --repo: created {cfg}")

    gi = repo_path / ".gitignore"
    if gi.exists():
        lines = gi.read_text().splitlines()
        if ".mentat/" not in lines:
            gi.write_text(gi.read_text().rstrip("\n") + "\n.mentat/\n")
            print(f"mentat-install --repo: appended .mentat/ to {gi}")
    else:
        gi.write_text(".mentat/\n")
        print(f"mentat-install --repo: created {gi} with .mentat/")

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mentat-install",
        description="Install mentat skills and configure ~/.mentat/",
    )
    p.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI output")
    p.add_argument("--skip-companions", action="store_true", help="Skip 3rd-party companion install prompts")
    p.add_argument(
        "--repo",
        metavar="PATH",
        nargs="?",
        const="",
        help="Scaffold per-repo .mentat/config.jsonc (defaults to git repo root)",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.repo is not None:
        repo_path = Path(args.repo).resolve() if args.repo else None
        sys.exit(do_repo_install(repo_path=repo_path))

    color = False if args.no_color else None

    clone_root: Path | None = None
    cwd = Path.cwd()
    if (cwd / ".agents" / "skills").is_dir():
        clone_root = cwd

    sys.exit(
        do_install(
            yes=args.yes,
            dry_run=args.dry_run,
            color=color,
            clone_root=clone_root,
            skip_companions=args.skip_companions,
        )
    )


if __name__ == "__main__":
    main()
