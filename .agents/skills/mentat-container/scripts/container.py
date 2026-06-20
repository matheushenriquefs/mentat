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
_AGENTS_ROOT = _SCRIPTS.parents[2]  # .agents/
sys.path.insert(0, str(_SCRIPTS))
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

import compose_render  # noqa: E402
import utils  # noqa: E402


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


def _git_mount_for_worktree(wt: Path) -> str | None:
    """Return a bind-mount string for the main repo's .git dir if wt is a worktree."""
    git_path = wt / ".git"
    if not git_path.is_file():
        return None
    content = git_path.read_text().strip()
    if not content.startswith("gitdir:"):
        return None
    gitdir = content.split(":", 1)[1].strip()
    main_git = str(Path(gitdir).parent.parent)
    return f"source={main_git},target={main_git},type=bind"


def _ensure_devcontainer_json(wt: Path, slug: str) -> None:
    import json as _json
    import re as _re

    dcj = wt / ".devcontainer" / "devcontainer.json"
    expected_ws = f"/workspaces/{slug}"
    git_mount = _git_mount_for_worktree(wt)

    if dcj.exists():
        # Strip JSONC comments via the canonical string-preserving parser so
        # inline `//` inside quoted values (e.g. https:// URLs in postCreateCommand)
        # is not mistaken for a line comment. Returns {} on any read/parse error.
        from lib.jsonc import load_jsonc

        data = load_jsonc(dcj)
        ws_ok = data.get("workspaceFolder") == expected_ws
        mount_ok = git_mount is None or git_mount in data.get("mounts", [])
        if ws_ok and mount_ok:
            return
        if not ws_ok:
            old_ws = data.get("workspaceFolder") or "/workspaces/mentat"
            data["name"] = slug
            data["workspaceFolder"] = expected_ws
            if "workspaceMount" in data:
                data["workspaceMount"] = _re.sub(r"target=[^,]+", f"target={expected_ws}", data["workspaceMount"])
            for key in ("postCreateCommand", "onCreateCommand"):
                if key in data:
                    data[key] = data[key].replace(old_ws, expected_ws)
        if git_mount and git_mount not in data.get("mounts", []):
            data.setdefault("mounts", []).append(git_mount)
        content = _json.dumps(data, indent=2)
    else:
        try:
            content = compose_render.synth(wt)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        if git_mount:
            data = _json.loads(content)
            data.setdefault("mounts", []).append(git_mount)
            content = _json.dumps(data, indent=2)

    dcj.parent.mkdir(parents=True, exist_ok=True)
    tmp = dcj.parent / (dcj.name + ".tmp")
    tmp.write_text(content)
    tmp.replace(dcj)


def _ensure_safe_directory(wt: Path, ws: str, slug: str, cid: str) -> None:
    subprocess.run(
        [
            _docker(),
            "exec",
            cid,
            "git",
            "config",
            "--global",
            "--add",
            "safe.directory",
            ws,
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
        capture_output=True,
        text=True,
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
        _git_parts = (wt / ".git").read_text().split()
        if not _git_parts:
            return
        git_target = _git_parts[-1]
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
        capture_output=True,
        text=True,
        cwd=str(wt),
    )
    git_dir = git_dir_result.stdout.strip() if git_dir_result.returncode == 0 else ""

    cmd = [
        "devcontainer",
        "up",
        "--workspace-folder",
        str(wt),
        "--id-label",
        f"mentat_slug={slug}",
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
        return 69
    ws = utils.resolve_workspace_folder(wt)
    result = subprocess.run(
        [
            _docker(),
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


def cmd_down(*, slug: str) -> int:
    from lib import devcontainer

    return 0 if devcontainer.down(slug) else 1


def _col(label: str, value: str) -> str:
    return f"  {label:<14}: {value}"


def cmd_doctor(wt: Path) -> int:  # noqa: C901
    import json as _json
    import platform as _platform

    warnings: list[str] = []
    advisories: list[str] = []

    print("\nmentat-container doctor\n")

    # ── [host] ──────────────────────────────────────────────────────────────
    try:
        host_arch = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        host_arch = "unknown"
    host_os = f"{_platform.system().lower()} {_platform.release()}"
    print("[host]")
    print(_col("arch", host_arch))
    print(_col("os", host_os))
    print()

    # ── [container] ─────────────────────────────────────────────────────────
    slug = wt.name
    print("[container]")
    try:
        daemon_ok = subprocess.run([_docker(), "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        daemon_ok = False
    if not daemon_ok:
        print(_col("daemon", "not running"))
        warnings.append("docker daemon not running")
    else:
        print(_col("daemon", "running"))
        cid = utils.container_id_for(slug)
        if cid:
            inspect = subprocess.run(
                [_docker(), "inspect", "--format", "{{.Platform}}", cid],
                capture_output=True,
                text=True,
            )
            img_platform = inspect.stdout.strip() if inspect.returncode == 0 else "unknown"
            print(_col("image platf", img_platform))
            # arch mismatch
            if (host_arch == "arm64" and "amd64" in img_platform) or (
                host_arch in ("x86_64", "amd64") and "arm64" in img_platform
            ):
                print(_col("emulation", "qemu (slow — expect 3-5x perf hit)"))
                warnings.append("arch emulation")
            else:
                print(_col("emulation", "none"))
            ws = utils.resolve_workspace_folder(wt)
            print(_col("state", "running"))
            print(_col("workspace", ws))
        else:
            print(_col("state", f"no container for slug={slug}"))
            warnings.append(f"container not running (slug={slug})")
    print()

    # ── [harness] ───────────────────────────────────────────────────────────
    print("[harness]")
    claude_dir = Path.home() / ".claude"
    cursor_dir = Path.home() / ".cursor"
    if claude_dir.exists():
        print(_col("claude-code", f"detected at {claude_dir}/"))
        agents_dir = claude_dir / "agents"
        agents_n = len(list(agents_dir.glob("mentat-*"))) if agents_dir.exists() else 0
        skills_n = len(list((claude_dir / "skills").glob("mentat-*"))) if (claude_dir / "skills").exists() else 0
        print(_col("agents link", f"{agents_n} mentat-* subagents linked"))
        print(_col("skills link", f"{skills_n} mentat-* skills linked"))
    else:
        print(_col("claude-code", "not detected"))
    if cursor_dir.exists():
        print(_col("cursor", f"detected at {cursor_dir}/"))
    else:
        print(_col("cursor", "not detected"))
    print()

    # ── [companions] ────────────────────────────────────────────────────────
    print("[companions]")
    pocock = (Path.home() / ".claude/skills/diagnose/SKILL.md").exists()
    caveman = (Path.home() / ".claude/plugins/marketplaces/caveman").exists()
    print(_col("matt-pocock", "present" if pocock else "missing — run mentat-install"))
    print(_col("julius-caveman", "present" if caveman else "missing — run mentat-install"))
    if not pocock or not caveman:
        advisories.append("companion(s) missing")
    print()

    # ── [mentat state] ──────────────────────────────────────────────────────
    print("[mentat state]")
    mentat_dir = Path.home() / ".mentat"
    config = mentat_dir / "config.jsonc"
    print(_col("~/.mentat/", "present" if mentat_dir.exists() else "absent"))
    if config.exists():
        try:
            lines = [ln for ln in config.read_text().splitlines() if not ln.strip().startswith("//")]
            _json.loads("\n".join(lines))
            print(_col("config.jsonc (global)", "valid"))
        except Exception:
            print(_col("config.jsonc (global)", "invalid — parse error"))
            warnings.append("config.jsonc parse error")
    else:
        print(_col("config.jsonc (global)", "absent"))
    _repo_root_r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if _repo_root_r.returncode == 0:
        repo_cfg = Path(_repo_root_r.stdout.strip()) / ".mentat" / "config.jsonc"
        if repo_cfg.exists():
            try:
                lines = [ln for ln in repo_cfg.read_text().splitlines() if not ln.strip().startswith("//")]
                _json.loads("\n".join(lines))
                print(_col("config.jsonc (repo overlay)", "valid"))
            except Exception:
                print(_col("config.jsonc (repo overlay)", "invalid — parse error"))
                warnings.append("repo config.jsonc parse error")
        else:
            print(_col("config.jsonc (repo overlay)", "absent"))
    logs_dir = mentat_dir / "logs"
    if logs_dir.exists():
        session_n = sum(1 for _ in logs_dir.iterdir() if _.is_dir())
        print(_col("logs dir", f"{session_n} sessions"))
    else:
        print(_col("logs dir", "absent"))
    print()

    # ── [tests] ─────────────────────────────────────────────────────────────
    print("[tests]")
    plans_dir = Path.home() / ".agents" / "plans"
    if plans_dir.exists():
        manifests = list(plans_dir.glob("*.tests.json"))
        if manifests:
            for mf in sorted(manifests):
                try:
                    data = _json.loads(mf.read_text())
                    closed = data.get("closed", [])
                    open_ = data.get("open", [])
                    ro = [p for p in closed if p not in set(open_)]
                    print(_col(mf.stem, f"{len(ro)} ro-mounted, {len(open_)} open"))
                except Exception:
                    print(_col(mf.stem, "manifest parse error"))
        else:
            print("  no test manifests")
    else:
        print("  no plans dir")
    print()

    # ── verdict ─────────────────────────────────────────────────────────────
    warn_str = f"{len(warnings)} warning ({', '.join(warnings)})" if warnings else "0 warnings"
    adv_str = f"{len(advisories)} advisory ({', '.join(advisories)})" if advisories else "0 advisories"
    print(f"verdict: {warn_str}, {adv_str}")

    return 1 if warnings else 0


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
        slug = args.slug if args.slug else _git_root().name
        sys.exit(cmd_down(slug=slug))
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(Path.cwd()))


if __name__ == "__main__":
    main()
