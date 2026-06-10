#!/usr/bin/env python3
"""mentat-container — up / run / down / doctor."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve peer scripts without package install
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import utils
import compose_synth


def _docker() -> str:
    return os.environ.get("MENTAT_DOCKER", "docker")


def _git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("mentat-container: must run from inside a git worktree", file=sys.stderr)
        raise SystemExit(2)
    return Path(result.stdout.strip())


def _ensure_devcontainer_json(wt: Path, slug: str) -> None:
    dcj = wt / ".devcontainer" / "devcontainer.json"
    if dcj.exists():
        return
    try:
        content = compose_synth.synth(wt)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    dcj.parent.mkdir(parents=True, exist_ok=True)
    tmp = dcj.parent / (dcj.name + ".tmp")
    tmp.write_text(content)
    tmp.replace(dcj)


def _ensure_safe_directory(wt: Path, ws: str, slug: str, cid: str) -> None:
    subprocess.run(
        [
            _docker(), "exec", cid,
            "git", "config", "--global", "--add", "safe.directory", ws,
        ],
        capture_output=True,
    )


def cmd_up(wt: Path) -> int:
    slug = wt.name
    cid = utils.container_id_for(slug)
    ws = utils.resolve_workspace_folder(wt)

    if cid:
        _ensure_safe_directory(wt, ws, slug, cid)
        return 0

    # Stopped container
    stopped = subprocess.run(
        [_docker(), "ps", "-aq", "--filter", f"label=mentat_slug={slug}", "--filter", "status=exited"],
        capture_output=True, text=True,
    )
    if stopped.returncode == 0 and stopped.stdout.strip():
        subprocess.run([_docker(), "start", stopped.stdout.strip()], check=True, capture_output=True)
        ws = utils.resolve_workspace_folder(wt)
        cid2 = utils.container_id_for(slug)
        if cid2:
            _ensure_safe_directory(wt, ws, slug, cid2)
        return 0

    # Cold start
    _ensure_devcontainer_json(wt, slug)
    ws = utils.resolve_workspace_folder(wt)

    # Symlink shared dirs from main repo
    if (wt / ".git").is_file():
        git_target = (wt / ".git").read_text().split()[-1]
        root = Path(git_target).parent
        while root.name != ".git" and root != root.parent:
            root = root.parent
        repo_root = root.parent
        for d in ("vendor", "node_modules"):
            src = repo_root / d
            dst = wt / d
            if src.is_dir() and not dst.exists():
                dst.symlink_to(src)
        env_src = repo_root / ".env"
        env_dst = wt / ".env"
        if env_src.exists() and not env_dst.exists():
            shutil.copy2(env_src, env_dst)

    git_dir_result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True, text=True, cwd=str(wt),
    )
    git_dir = git_dir_result.stdout.strip() if git_dir_result.returncode == 0 else ""

    cmd = [
        "devcontainer", "up",
        "--workspace-folder", str(wt),
        "--id-label", f"mentat_slug={slug}",
    ]
    if git_dir:
        cmd += ["--remote-env", f"GIT_DIR={git_dir}"]
        cmd += ["--remote-env", f"GIT_WORK_TREE={ws}"]

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        cid2 = utils.container_id_for(slug)
        if not cid2:
            return 1

    final_cid = utils.container_id_for(slug)
    if final_cid:
        _ensure_safe_directory(wt, ws, slug, final_cid)
    return 0


def cmd_run(wt: Path, command: str) -> int:
    slug = wt.name
    cid = utils.container_id_for(slug)
    if not cid:
        print(
            f"mentat-container: container not running for slug {slug} (run 'mentat-container up' first)",
            file=sys.stderr,
        )
        return 99
    ws = utils.resolve_workspace_folder(wt)
    result = subprocess.run(
        [_docker(), "exec", "--workdir", ws, "-u", "vscode", cid,
         "bash", "-lc", f"git config --global --add safe.directory '*' 2>/dev/null || true; {command}"],
    )
    return result.returncode


def cmd_down(wt: Path) -> int:
    slug = wt.name
    cid = utils.container_id_for(slug)
    if not cid:
        print(f"mentat-container: no running container for slug {slug}", file=sys.stderr)
        return 0
    result = subprocess.run([_docker(), "stop", cid], capture_output=True)
    if result.returncode == 0:
        print(cid)
    return result.returncode


def cmd_doctor(wt: Path) -> int:
    slug = wt.name
    issues: list[str] = []

    # Check git tree
    git_check = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True, text=True, cwd=str(wt),
    )
    if git_check.returncode != 0:
        issues.append(f"  [FAIL] {wt} is not inside a git worktree")
    else:
        print(f"  [OK]   git worktree: {wt}")

    # Check devcontainer.json
    dcj = wt / ".devcontainer" / "devcontainer.json"
    if dcj.exists():
        print(f"  [OK]   devcontainer.json: {dcj}")
    else:
        issues.append(f"  [WARN] devcontainer.json not found: {dcj}")

    # Check container running
    cid = utils.container_id_for(slug)
    if cid:
        print(f"  [OK]   container running: {cid}")
        ws = utils.resolve_workspace_folder(wt)
        # Check workspaceFolder accessible
        ws_check = subprocess.run(
            [_docker(), "exec", cid, "test", "-d", ws],
            capture_output=True,
        )
        if ws_check.returncode == 0:
            print(f"  [OK]   workspaceFolder accessible: {ws}")
        else:
            issues.append(f"  [FAIL] workspaceFolder not accessible inside container: {ws}")
    else:
        issues.append(f"  [FAIL] no container running for slug={slug} — run 'mentat-container up'")

    for issue in issues:
        print(issue)

    return 1 if any("[FAIL]" in i for i in issues) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-container", description="Devcontainer lifecycle manager")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="Start devcontainer for cwd worktree")
    run_p = sub.add_parser("run", help="Exec command inside container")
    run_p.add_argument("command", nargs="+", help="Command to run")
    sub.add_parser("down", help="Stop container")
    sub.add_parser("doctor", help="Diagnose container invariants")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    wt = _git_root() if args.cmd != "doctor" else Path.cwd()

    if args.cmd == "up":
        sys.exit(cmd_up(wt))
    elif args.cmd == "run":
        sys.exit(cmd_run(wt, " ".join(args.command)))
    elif args.cmd == "down":
        sys.exit(cmd_down(wt))
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(Path.cwd()))


if __name__ == "__main__":
    main()
