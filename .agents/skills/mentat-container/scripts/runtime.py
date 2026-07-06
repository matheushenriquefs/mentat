"""Host-vs-container runtime selection: the `runtime = "host"` opt-out (ADR-0004)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _host_runtime() -> bool:
    """True iff config opts out of containerization with ``runtime = "host"``.

    Default (key unset, ``"docker"``, or ``"container"``) → containerized. Only the
    explicit ``"host"`` value forfeits ADR-0004 isolation. Reads through the live
    config reader (``config.toml``).
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


def _subprocess_env_for_wt(wt: Path) -> dict[str, str]:
    from lib.git import git_subprocess_env

    return git_subprocess_env(cwd=wt.resolve())


def _run_on_host(command: str, cwd: Path) -> int:
    """Execute a command on the host (runtime=host opt-out). No container."""
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=str(cwd),
        env=_subprocess_env_for_wt(cwd),
    ).returncode


def _inside_devcontainer(wt: Path) -> bool:
    parts = wt.resolve().parts
    return len(parts) >= 3 and parts[1] == "workspaces"
