"""mentat-git commit subcommand."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

utils = load_sibling(__file__, "utils")


def _host_identity() -> list[str]:
    """`git -c user.*` args carrying the host's commit identity into the container.

    The container is exec'd as the OS user `vscode` (file ownership matches
    remoteUser per the devcontainers spec), but the commit must be authored as the
    operator's real git identity — not `vscode`. Mirror the host's configured
    user.name/user.email; omit either if unset (container config then applies).
    """
    args: list[str] = []
    for key in ("user.name", "user.email"):
        r = subprocess.run(["git", "config", key], capture_output=True, text=True)
        val = r.stdout.strip()
        if r.returncode == 0 and val:
            args += ["-c", f"{key}={val}"]
    return args


def cmd_commit(git_args: list[str]) -> int:
    """Stage and commit through the devcontainer. Auto-up if down (ADR-0004).

    Runs as OS user `vscode` (matches remoteUser → consistent file ownership), but
    authors the commit as the host git identity via `-c user.*`.
    """
    cid = utils.container_id_for_cwd()
    if not cid:
        container_script = Path(__file__).resolve().parents[2] / "mentat-container/scripts/container.py"
        subprocess.run(["python3", str(container_script), "up"], check=False)
        cid = utils.container_id_for_cwd()
        if not cid:
            print(
                "mentat-git: failed to bring up devcontainer for cwd (ADR-0004)",
                file=sys.stderr,
            )
            return 69
    docker = os.environ.get("MENTAT_DOCKER", "docker")
    wt_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    ws = f"/workspaces/{Path(wt_result.stdout.strip()).name}" if wt_result.returncode == 0 else "/workspaces/mentat"
    # `safe.directory=*`: the bind-mounted workspace is owned by the host UID, so
    # git-as-vscode would otherwise refuse with "dubious ownership" (matches the
    # guard `mentat-container run` applies).
    cmd = [
        docker,
        "exec",
        "--workdir",
        ws,
        "-u",
        "vscode",
        cid,
        "git",
        "-c",
        "safe.directory=*",
        *_host_identity(),
        "commit",
    ] + git_args
    result = subprocess.run(cmd)
    return result.returncode
