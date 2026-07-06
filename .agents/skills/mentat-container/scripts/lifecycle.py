"""Container lifecycle: bring a chunk's devcontainer up, or tear it down."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import client as utils
import override
import runtime
from lib.exits import EX_FAILURE, EX_OK, EX_UNAVAILABLE


def _git_mount_for_worktree(wt: Path) -> str | None:
    """Return a bind-mount string for the main repo's .git dir if wt is a worktree."""
    git_path = wt / ".git"
    if not git_path.is_file():
        return None
    try:
        content = git_path.read_text().strip()
    except OSError, UnicodeDecodeError:
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
    except OSError, UnicodeDecodeError:
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = content.split(":", 1)[1].strip()
    return Path(gitdir).parent.parent.parent


def _atomic_write(path: Path, text: str) -> None:
    """Write text atomically via mkstemp + replace (matches frontmatter._write_atomic)."""
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


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
        from lib.config import parse_devcontainer_json

        data = parse_devcontainer_json(dcj_src)
    else:
        try:
            spec = override.synth_spec(wt)
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
                utils._docker(),
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


def _propagate_git_identity(ws: str, cid: str, repo_root: Path | None) -> None:
    """Mirror main-worktree user.name/user.email into the container at bring-up."""
    from lib.git import host_commit_identity

    ident = host_commit_identity(cwd=repo_root) if repo_root is not None else {}
    for key in ("user.name", "user.email"):
        val = ident.get(key)
        if not val:
            continue
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run(
                [utils._docker(), "exec", "-u", "vscode", "--workdir", ws, cid, "git", "config", "--global", key, val],
                capture_output=True,
                timeout=30,
            )


def cmd_up(wt: Path) -> int:
    chunk_slug = utils._chunk_slug_for_wt(wt)
    if runtime._host_runtime():
        runtime._warn_host_runtime_once(chunk_slug)
        return 0  # nothing to bring up — tools run on the host
    cid = utils.container_id_for(chunk_slug)
    ws = utils.workspace_folder_for(wt)

    if cid:
        _ensure_safe_directory(ws, cid)
        _propagate_git_identity(ws, cid, _main_repo_root_for_wt(wt))
        return 0

    # created/paused/restarting/dead states must not be silently skipped to cold-start.
    try:
        stopped = subprocess.run(
            [
                utils._docker(),
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
            start_result = subprocess.run([utils._docker(), "start"] + ids, capture_output=True, text=True, timeout=30)
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
        _propagate_git_identity(ws, cid2, _main_repo_root_for_wt(wt))
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
        _propagate_git_identity(ws, final_cid, repo_root)
    return 0


def cmd_down(*, slug: str) -> int:
    if runtime._host_runtime():
        return 0  # host mode brought nothing up — nothing to tear down
    from lib import devcontainer

    return EX_OK if devcontainer.down(slug) else EX_FAILURE
