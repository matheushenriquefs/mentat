"""mentat-git commit subcommand."""

from __future__ import annotations

import importlib.util as _ilu
import os
import subprocess
import sys
from pathlib import Path


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


utils = _load_sibling("utils")


def cmd_commit(git_args: list[str]) -> int:
    """Stage and commit through the devcontainer. Auto-up if down (ADR-0004)."""
    cid = utils.container_id_for_cwd()
    if not cid:
        container_script = (
            Path(__file__).resolve().parents[2]
            / "mentat-container/scripts/container.py"
        )
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
    cmd = [docker, "exec", "--workdir", ws, cid, "git", "commit"] + git_args
    result = subprocess.run(cmd)
    return result.returncode
