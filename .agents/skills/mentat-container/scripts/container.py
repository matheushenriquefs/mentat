#!/usr/bin/env python3
"""mentat-container — up / run / down / doctor."""

from __future__ import annotations

import argparse
import contextlib
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
import container_ops as utils  # noqa: E402
from lib.exits import EX_ARGPARSE, EX_FAILURE, EX_OK, EX_UNAVAILABLE  # noqa: E402

_docker = utils._docker


def _host_runtime() -> bool:
    """True iff config opts out of containerization with ``runtime = "host"``.

    Default (key unset, ``"docker"``, or ``"container"``) → containerized. Only the
    explicit ``"host"`` value forfeits ADR-0004 isolation. Reads through the live
    config reader, so it works against ``config.toml`` (or the deprecated
    ``config.jsonc`` overlay — migrate to ``config.toml``).
    """
    from lib.config import read_config

    return str(read_config().get("runtime", "")).strip().lower() == "host"


def _warn_host_runtime_once(slug: str) -> None:
    """Print the isolation-forfeit warning, at most once per slug.

    A marker under ``~/.mentat`` suppresses repeats so every ``run`` does not spam
    it — the warning is loud the first time and silent after.
    """
    marker_dir = Path.home() / ".mentat" / ".host-runtime-warned"
    marker = marker_dir / slug
    if marker.exists():
        return
    print(
        'mentat-container: runtime = "host" — ADR-0004 container isolation is FORFEITED.\n'
        "  Project tools run directly on the host; the host toolchain may be unset or\n"
        "  mismatched and the worktree is not sandboxed (pollution possible). This is an\n"
        '  explicit opt-out — unset `runtime` (or set it to "docker") to restore isolation.',
        file=sys.stderr,
    )
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass  # best-effort suppression; a missing marker only costs an extra warning


def _run_on_host(command: str, cwd: Path) -> int:
    """Execute a command on the host (runtime=host opt-out). No container."""
    return subprocess.run(["bash", "-lc", command], cwd=str(cwd)).returncode


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


def _git_mount_for_worktree(wt: Path) -> str | None:
    """Return a bind-mount string for the main repo's .git dir if wt is a worktree."""
    git_path = wt / ".git"
    if not git_path.is_file():
        return None
    try:
        content = git_path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = content.split(":", 1)[1].strip()
    main_git = str(Path(gitdir).parent.parent)
    return f"source={main_git},target={main_git},type=bind"


def _main_repo_root_for_wt(wt: Path) -> Path | None:
    """Return the main repo root for a worktree (.git file pointer), or None."""
    git_path = wt / ".git"
    if not git_path.is_file():
        return None
    try:
        content = git_path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = content.split(":", 1)[1].strip()
    return Path(gitdir).parent.parent.parent


def _atomic_write(path: Path, text: str) -> None:
    """Write text via a sibling .tmp then atomic replace."""
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _repo_root_for_wt(wt: Path) -> Path:
    main = _main_repo_root_for_wt(wt)
    if main is not None:
        return main
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=str(wt),
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return wt


def _chunk_slug_for_wt(wt: Path) -> str:
    cs = utils.chunk_slug_for_worktree(wt)
    return cs if cs else wt.name


def _absolutize_build(data: dict, wt: Path) -> None:
    build = data.get("build")
    if not isinstance(build, dict):
        return
    dcj_parent = wt / ".devcontainer"
    ctx = build.get("context")
    if ctx and not str(ctx).startswith("/"):
        build["context"] = str((dcj_parent / ctx).resolve())
    df = build.get("dockerfile")
    if df and not str(df).startswith("/"):
        base = Path(str(build.get("context") or dcj_parent))
        build["dockerfile"] = str((base / df).resolve())


def _patch_compose_paths(data: dict, wt: Path) -> None:
    dcf = data.get("dockerComposeFile")
    if not dcf:
        return
    original_base = wt / ".devcontainer"
    files = [dcf] if isinstance(dcf, str) else list(dcf)
    abs_files: list[str] = []
    for f in files:
        if str(f).startswith("/"):
            abs_files.append(str(f))
            continue
        candidate = (original_base / f).resolve()
        if candidate.exists():
            abs_files.append(str(candidate))
        else:
            abs_files.append(str((wt / f).resolve()))
    data["dockerComposeFile"] = abs_files[0] if isinstance(dcf, str) else abs_files


def _write_override_config(wt: Path, chunk_slug: str) -> Path:
    """Write per-chunk devcontainer override outside the worktree; never touch tracked json."""
    import json as _json
    import re as _re

    from lib.chunk import override_config_dir

    repo_root = _repo_root_for_wt(wt)
    expected_ws = utils.workspace_folder_for(wt)
    git_mount = _git_mount_for_worktree(wt)
    override_dir = override_config_dir(repo_root, chunk_slug)
    override_dir.mkdir(parents=True, exist_ok=True)

    dcj_src = wt / ".devcontainer" / "devcontainer.json"
    extra_files: dict[str, str] = {}
    if dcj_src.exists():
        from lib.config import load_jsonc

        data = load_jsonc(dcj_src)
    else:
        try:
            spec = compose_render.synth_spec(wt)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        data = _json.loads(spec.devcontainer_json)
        extra_files = spec.extra_files

    old_ws = data.get("workspaceFolder") or "/workspaces/mentat"
    plan_slug = chunk_slug.split("/", 1)[-1]
    data["name"] = plan_slug
    data["workspaceFolder"] = expected_ws
    if "workspaceMount" in data:
        data["workspaceMount"] = _re.sub(r"target=[^,]+", f"target={expected_ws}", data["workspaceMount"])
    for key in ("postCreateCommand", "onCreateCommand"):
        if key in data and isinstance(data[key], str):
            data[key] = data[key].replace(old_ws, expected_ws)
    if git_mount and git_mount not in data.get("mounts", []):
        data.setdefault("mounts", []).append(git_mount)

    _absolutize_build(data, wt)
    _patch_compose_paths(data, wt)

    mem = os.environ.get("MENTAT_CHUNK_MEMORY", "").strip()
    if mem:
        run_args = list(data.get("runArgs") or [])
        run_args.extend(["--memory", mem, "--memory-swap", mem])
        data["runArgs"] = run_args

    override_path = override_dir / "devcontainer.json"
    _atomic_write(override_path, _json.dumps(data, indent=2))
    for fname, text in extra_files.items():
        _atomic_write(override_dir / fname, text)
    return override_path


def _ensure_safe_directory(ws: str, cid: str) -> None:
    with contextlib.suppress(subprocess.TimeoutExpired):
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
            timeout=30,
        )


def cmd_up(wt: Path) -> int:
    chunk_slug = _chunk_slug_for_wt(wt)
    if _host_runtime():
        _warn_host_runtime_once(chunk_slug)
        return 0  # nothing to bring up — tools run on the host
    cid = utils.container_id_for(chunk_slug)
    ws = utils.workspace_folder_for(wt)

    if cid:
        _ensure_safe_directory(ws, cid)
        return 0

    # created/paused/restarting/dead states must not be silently skipped to cold-start.
    try:
        stopped = subprocess.run(
            [
                _docker(),
                "ps",
                "-aq",
                "--filter",
                f"label={utils.CHUNK_LABEL}={chunk_slug}",
                "--filter",
                "status=exited",
                "--filter",
                "status=created",
                "--filter",
                "status=paused",
                "--filter",
                "status=restarting",
                "--filter",
                "status=dead",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("mentat-container: docker ps timed out (daemon unresponsive?)", file=sys.stderr)
        return EX_UNAVAILABLE
    if stopped.returncode == 0 and stopped.stdout.strip():
        ids = stopped.stdout.strip().split()
        try:
            start_result = subprocess.run([_docker(), "start"] + ids, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            print("mentat-container: docker start timed out", file=sys.stderr)
            return EX_UNAVAILABLE
        if start_result.returncode != 0:
            print(
                f"mentat-container: docker start failed: {start_result.stderr.strip()}",
                file=sys.stderr,
            )
            return EX_FAILURE
        cid2 = utils.container_id_for(chunk_slug)
        if not cid2:
            print(
                f"mentat-container: docker start succeeded but no usable container found for chunk={chunk_slug}",
                file=sys.stderr,
            )
            return EX_FAILURE
        _ensure_safe_directory(ws, cid2)
        return 0

    # Cold start — external override config; tracked devcontainer.json stays pristine.
    override_path = _write_override_config(wt, chunk_slug)

    # Symlink shared dirs from main repo
    repo_root = _main_repo_root_for_wt(wt)
    if repo_root is not None:
        for d in ("vendor", "node_modules"):
            src = repo_root / d
            dst = wt / d
            if src.is_dir() and not dst.exists() and not dst.is_symlink():
                dst.symlink_to(src)
        env_src = repo_root / ".env"
        env_dst = wt / ".env"
        if env_src.exists() and not env_dst.exists():
            shutil.copy2(env_src, env_dst)

    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(wt),
            timeout=30,
        )
        git_dir = git_dir_result.stdout.strip() if git_dir_result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        git_dir = ""

    cmd = [
        "devcontainer",
        "up",
        "--workspace-folder",
        str(wt),
        "--override-config",
        str(override_path),
        "--id-label",
        f"{utils.CHUNK_LABEL}={chunk_slug}",
    ]
    if git_dir:
        cmd += ["--remote-env", f"GIT_DIR={git_dir}"]
        cmd += ["--remote-env", f"GIT_WORK_TREE={ws}"]

    _up_timeout = int(os.environ.get("MENTAT_UP_TIMEOUT", "900"))
    try:
        result = subprocess.run(cmd, capture_output=False, timeout=_up_timeout)
    except FileNotFoundError:
        print(
            "mentat-container: devcontainer CLI not on PATH — install via: npm install -g @devcontainers/cli",
            file=sys.stderr,
        )
        return EX_FAILURE
    except subprocess.TimeoutExpired:
        print(
            f"mentat-container: devcontainer up timed out after {_up_timeout}s",
            file=sys.stderr,
        )
        return EX_UNAVAILABLE
    if result.returncode != 0:
        return EX_FAILURE

    final_cid = utils.container_id_for(chunk_slug)
    if final_cid:
        _ensure_safe_directory(ws, final_cid)
    return 0


def cmd_run(wt: Path, command: str) -> int:
    chunk_slug = _chunk_slug_for_wt(wt)
    if _host_runtime():
        _warn_host_runtime_once(chunk_slug)
        return _run_on_host(command, wt)
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
    if _host_runtime():
        return 0  # host mode brought nothing up — nothing to tear down
    from lib import devcontainer

    return EX_OK if devcontainer.down(slug) else EX_FAILURE


def _col(label: str, value: str) -> str:
    return f"  {label:<14}: {value}"


def _doctor_section_host(host_arch: str, host_os: str) -> tuple[list[str], list[str]]:
    print("[host]")
    print(_col("arch", host_arch))
    print(_col("os", host_os))
    print()
    return [], []


def _doctor_section_container(wt: Path, host_arch: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    chunk_slug = _chunk_slug_for_wt(wt)
    print("[container]")
    try:
        daemon_ok = subprocess.run([_docker(), "info"], capture_output=True, timeout=30).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        daemon_ok = False
    if not daemon_ok:
        print(_col("daemon", "not running"))
        warnings.append("docker daemon not running")
    else:
        print(_col("daemon", "running"))
        cid = utils.container_id_for(chunk_slug)
        if cid:
            try:
                inspect = subprocess.run(
                    [_docker(), "inspect", "--format", "{{.Platform}}", cid],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                img_platform = inspect.stdout.strip() if inspect.returncode == 0 else "unknown"
            except subprocess.TimeoutExpired:
                img_platform = "unknown"
            print(_col("image platf", img_platform))
            if (host_arch == "arm64" and "amd64" in img_platform) or (
                host_arch in ("x86_64", "amd64") and "arm64" in img_platform
            ):
                print(_col("emulation", "qemu (slow — expect 3-5x perf hit)"))
                warnings.append("arch emulation")
            else:
                print(_col("emulation", "none"))
            ws = utils.workspace_folder_for(wt)
            print(_col("state", "running"))
            print(_col("workspace", ws))
        else:
            print(_col("state", f"no container for chunk={chunk_slug}"))
            warnings.append(f"container not running (chunk={chunk_slug})")
    print()
    return warnings, []


def _doctor_section_harness() -> tuple[list[str], list[str]]:
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
    return [], []


def _doctor_section_companions() -> tuple[list[str], list[str]]:
    advisories: list[str] = []
    print("[companions]")
    pocock = (Path.home() / ".claude/skills/diagnose/SKILL.md").exists()
    caveman = (Path.home() / ".claude/plugins/marketplaces/caveman").exists()
    print(_col("matt-pocock", "present" if pocock else "missing — run mentat-install"))
    print(_col("julius-caveman", "present" if caveman else "missing — run mentat-install"))
    if not pocock or not caveman:
        advisories.append("companion(s) missing")
    print()
    return [], advisories


def _doctor_section_mentat_state(wt: Path) -> tuple[list[str], list[str]]:
    from lib.config import config_status

    warnings: list[str] = []
    print("[mentat state]")
    mentat_dir = Path.home() / ".mentat"
    print(_col("~/.mentat/", "present" if mentat_dir.exists() else "absent"))
    g_status, g_warn = config_status(mentat_dir)
    print(_col("config (global)", g_status))
    if g_warn:
        warnings.append(g_warn)
    _repo_root_r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if _repo_root_r.returncode == 0:
        r_status, r_warn = config_status(Path(_repo_root_r.stdout.strip()) / ".mentat")
        print(_col("config (repo)", r_status))
        if r_warn:
            warnings.append(f"repo {r_warn}")
    logs_dir = mentat_dir / "logs"
    if logs_dir.exists():
        session_n = sum(1 for _ in logs_dir.iterdir() if _.is_dir())
        print(_col("logs dir", f"{session_n} sessions"))
    else:
        print(_col("logs dir", "absent"))
    print()
    return warnings, []


def _doctor_section_tests() -> tuple[list[str], list[str]]:
    import json as _json

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
    return [], []


def cmd_doctor(wt: Path) -> int:
    import platform as _platform

    try:
        host_arch = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        host_arch = "unknown"
    host_os = f"{_platform.system().lower()} {_platform.release()}"

    print("\nmentat-container doctor\n")

    all_warnings: list[str] = []
    all_advisories: list[str] = []
    for w, a in [
        _doctor_section_host(host_arch, host_os),
        _doctor_section_container(wt, host_arch),
        _doctor_section_harness(),
        _doctor_section_companions(),
        _doctor_section_mentat_state(wt),
        _doctor_section_tests(),
    ]:
        all_warnings.extend(w)
        all_advisories.extend(a)

    warn_str = f"{len(all_warnings)} warning ({', '.join(all_warnings)})" if all_warnings else "0 warnings"
    adv_str = f"{len(all_advisories)} advisory ({', '.join(all_advisories)})" if all_advisories else "0 advisories"
    print(f"verdict: {warn_str}, {adv_str}")

    return EX_FAILURE if all_warnings else EX_OK


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
