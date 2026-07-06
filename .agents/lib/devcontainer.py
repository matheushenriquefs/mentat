"""Devcontainer module API. Wraps docker CLI. Stdlib only (ADR-0008)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_LABEL = "mentat_chunk"
DEFAULT_UNTIL = "1h"


@dataclass(frozen=True)
class PruneResult:
    reclaimed_bytes: int | None
    containers_removed: int


def _docker_bin() -> str:
    return os.environ.get("MENTAT_DOCKER", "docker")


def _run_docker(argv: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str] | None:
    cmd = [_docker_bin()] + argv[1:]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        print("devcontainer: docker not on PATH", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"devcontainer: docker command timed out after {timeout}s", file=sys.stderr)
        return None


def prune(label: str = DEFAULT_LABEL, until: str = DEFAULT_UNTIL) -> PruneResult:
    r = _run_docker(["docker", "container", "prune", "-f", "--filter", f"label={label}", "--filter", f"until={until}"])
    if r is None or r.returncode != 0:
        return PruneResult(None, 0)
    reclaimed: int | None = None
    m = re.search(r"Total reclaimed space:\s+(\d+)", r.stdout)
    if m:
        reclaimed = int(m.group(1))
    removed = sum(
        1
        for line in r.stdout.splitlines()
        if line.strip() and line.strip() not in ("Deleted Containers:",) and not line.startswith("Total")
    )
    return PruneResult(reclaimed, removed)


def list_active_slugs(label: str = DEFAULT_LABEL) -> set[str]:
    r = _run_docker(
        [
            "docker",
            "ps",
            "--filter",
            f"label={label}",
            "--format",
            f'{{{{.Label "{label}"}}}}',
        ]
    )
    if r is None or r.returncode != 0:
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def container_id_for_slug(slug: str, label: str = DEFAULT_LABEL) -> str | None:
    r = _run_docker(
        [
            "docker",
            "ps",
            "--filter",
            f"label={label}={slug}",
            "--format",
            "{{.ID}}",
        ]
    )
    if r is None or r.returncode != 0:
        return None
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return lines[0] if lines else None


def down(slug: str, *, label: str = DEFAULT_LABEL) -> bool:
    """Remove all containers with the chunk label. Returns True on success or if none found."""
    r = _run_docker(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label={label}={slug}",
        ]
    )
    if r is None or r.returncode != 0:
        return False
    cids = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    if not cids:
        return True
    ok = True
    for cid in cids:
        rm = _run_docker(["docker", "rm", "-f", cid])
        if rm is None or rm.returncode != 0:
            ok = False
    return ok


def down_run(chunk_slugs: set[str], *, label: str = DEFAULT_LABEL) -> int:
    """Tear down containers for exactly these chunk slugs. Returns success count."""
    return sum(1 for cs in chunk_slugs if down(cs, label=label))


def container_oom_killed(slug: str, *, label: str = DEFAULT_LABEL) -> bool:
    """True iff the labeled container's last exit was OOM-killed."""
    r = _run_docker(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label={label}={slug}",
            "--filter",
            "status=exited",
        ]
    )
    if r is None or r.returncode != 0 or not r.stdout.strip():
        cid_r = _run_docker(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label={label}={slug}",
            ]
        )
        if cid_r is None or cid_r.returncode != 0 or not cid_r.stdout.strip():
            return False
        cid = cid_r.stdout.strip().splitlines()[0]
    else:
        cid = r.stdout.strip().splitlines()[0]
    inspect = _run_docker(["docker", "inspect", "--format", "{{.State.OOMKilled}}", cid])
    if inspect is None or inspect.returncode != 0:
        return False
    return inspect.stdout.strip().lower() == "true"


def run(slug: str, cmd: str) -> subprocess.CompletedProcess[str] | None:
    cid = container_id_for_slug(slug)
    if cid is None:
        return None
    return _run_docker(["docker", "exec", cid, "sh", "-c", cmd])


def exec(  # noqa: A001
    slug: str,
    argv: list[str],
    *,
    workdir: str | None = None,
    user: str | None = None,
) -> subprocess.CompletedProcess[bytes] | None:
    """Run a command inside the container for ``slug`` with live output.

    Unlike ``run()``, this passes through stdin/stdout/stderr so streaming
    and interactive output works. Returns None if the container is not running.
    Respects ``MENTAT_DOCKER`` env var for the docker binary path.
    """
    cid = container_id_for_slug(slug)
    if cid is None:
        return None
    docker = _docker_bin()
    cmd = [docker, "exec"]
    if workdir:
        cmd += ["--workdir", workdir]
    if user:
        cmd += ["-u", user]
    cmd.append(cid)
    cmd.extend(argv)
    try:
        return subprocess.run(cmd)
    except FileNotFoundError:
        print("devcontainer: docker not on PATH", file=sys.stderr)
        return None
