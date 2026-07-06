#!/usr/bin/env python3
"""mentat-container — up / run / down / doctor."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Resolve peer scripts without package install
_SCRIPTS = Path(__file__).resolve().parent
_AGENTS_ROOT = _SCRIPTS.parents[2]  # .agents/
sys.path.insert(0, str(_SCRIPTS))
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

import client as utils  # noqa: E402
import doctor as _doctor  # noqa: E402
import lifecycle as _lifecycle  # noqa: E402
import override  # noqa: E402, F401 — e2e tests patch cc.override
import runtime  # noqa: E402
from lib.exits import EX_ARGPARSE, EX_FAILURE, EX_OK, EX_UNAVAILABLE  # noqa: E402, F401

cmd_up = _lifecycle.cmd_up
cmd_down = _lifecycle.cmd_down
cmd_doctor = _doctor.cmd_doctor
_git_mount_for_worktree = _lifecycle._git_mount_for_worktree
_write_override_config = _lifecycle._write_override_config
_ensure_safe_directory = _lifecycle._ensure_safe_directory
_propagate_git_identity = _lifecycle._propagate_git_identity
_repo_root_for_wt = _lifecycle._repo_root_for_wt
_main_repo_root_for_wt = _lifecycle._main_repo_root_for_wt
_atomic_write = _lifecycle._atomic_write
_warn_host_runtime_once = runtime._warn_host_runtime_once
_host_runtime = runtime._host_runtime
_run_on_host = runtime._run_on_host
_doctor_section_host = _doctor._doctor_section_host
_doctor_section_container = _doctor._doctor_section_container
_doctor_section_harness = _doctor._doctor_section_harness
_doctor_section_companions = _doctor._doctor_section_companions
_doctor_section_mentat_state = _doctor._doctor_section_mentat_state
_doctor_section_tests = _doctor._doctor_section_tests
lifecycle = _lifecycle
doctor = _doctor


def _git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("mentat-container: must run from inside a git worktree", file=sys.stderr)
        raise SystemExit(EX_ARGPARSE)
    return Path(result.stdout.strip())


def _chunk_slug_for_wt(wt: Path) -> str:
    return utils._chunk_slug_for_wt(wt)


def cmd_run(wt: Path, command: str) -> int:
    chunk_slug = _chunk_slug_for_wt(wt)
    if runtime._host_runtime():
        runtime._warn_host_runtime_once(chunk_slug)
        return runtime._run_on_host(command, wt)
    if runtime._inside_devcontainer(wt):
        return subprocess.run(
            ["bash", "-lc", command],
            cwd=str(wt.resolve()),
            env=runtime._subprocess_env_for_wt(wt),
        ).returncode
    cid = utils.container_id_for(chunk_slug)
    if cid is utils.DAEMON_DOWN:
        print(
            f"mentat-container: docker daemon not reachable for chunk {chunk_slug} (is Docker running?)",
            file=sys.stderr,
        )
        return EX_UNAVAILABLE
    if not cid:
        print(
            f"mentat-container: container not running for chunk {chunk_slug} (run 'mentat-container up' first)",
            file=sys.stderr,
        )
        return EX_UNAVAILABLE
    ws = utils.workspace_folder_for(wt)
    result = subprocess.run(
        [
            utils._docker(),
            "exec",
            "--workdir",
            ws,
            "-u",
            "vscode",
            cid,
            "bash",
            "-lc",
            f"git config --global --add safe.directory '*' 2>/dev/null || true; {command}",
        ],
    )
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-container", description="Devcontainer lifecycle manager")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="Start devcontainer for cwd worktree")
    run_p = sub.add_parser("run", help="Exec command inside container")
    run_p.add_argument("command", nargs="+", help="Command to run")
    down_p = sub.add_parser("down", help="Stop and remove container")
    down_p.add_argument("--slug", default=None, help="Container slug (default: cwd git root name)")
    sub.add_parser("doctor", help="Diagnose container invariants")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "up":
        sys.exit(cmd_up(_git_root()))
    elif args.cmd == "run":
        sys.exit(cmd_run(_git_root(), " ".join(args.command)))
    elif args.cmd == "down":
        slug = args.slug if args.slug else _chunk_slug_for_wt(_git_root())
        sys.exit(cmd_down(slug=slug))
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(Path.cwd()))


if __name__ == "__main__":
    main()
