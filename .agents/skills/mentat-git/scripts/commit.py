"""mentat-git commit subcommand."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import devcontainer  # noqa: E402
from lib.exits import EX_UNAVAILABLE, EX_USAGE  # noqa: E402
from lib.git import host_commit_identity  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

utils = load_sibling(__file__, "identity")


def _workspace_in_container(wt: Path) -> str:
    parts = wt.resolve().parts
    for i, part in enumerate(parts):
        if part == "worktrees" and i + 2 < len(parts):
            return f"/workspaces/{parts[i + 1]}/{parts[i + 2]}"
    return f"/workspaces/{wt.name}"


def _host_identity() -> list[str]:
    """`git -c user.*` args carrying the host's commit identity into the container."""
    args: list[str] = []
    for key, val in host_commit_identity().items():
        args.extend(["-c", f"{key}={val}"])
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
            return EX_UNAVAILABLE
    wt_result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if wt_result.returncode != 0:
        print(
            "mentat-git: cannot resolve git worktree toplevel for commit — refusing to guess",
            file=sys.stderr,
        )
        return EX_USAGE
    wt_path = Path(wt_result.stdout.strip())
    ws = _workspace_in_container(wt_path)
    parts = wt_path.resolve().parts
    slug = wt_path.name
    for i, part in enumerate(parts):
        if part == "worktrees" and i + 2 < len(parts):
            slug = f"{parts[i + 1]}/{parts[i + 2]}"
            break
    # `safe.directory=*`: bind-mounted workspace is owned by host UID; git-as-vscode
    # would otherwise refuse with "dubious ownership".
    result = devcontainer.exec(
        slug,
        ["git", "-c", "safe.directory=*", *_host_identity(), "commit"] + git_args,
        workdir=ws,
        user="vscode",
    )
    if result is None:
        return EX_UNAVAILABLE
    return result.returncode
