"""Canonical mentat agent-id minting + propagation.

The agent id is an opaque ``uuid7`` hex — stable, collision-free, and *never*
derived from repo/branch/pid path structure. ``role`` and ``slug`` are recorded
as env fields so a ``/``-bearing branch, a reused pid, or a repo rename can
neither collide two agents nor split one across dirs.

``ensure_agent`` exports ``MENTAT_AGENT`` + ``MENTAT_AGENT_LOG`` into the
environment *before any harness spawn*, so events and ``transcript.jsonl`` capture
are keyed from the first event instead of relying on an emit-time fallback.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

_TRANSCRIPT_NAME = "transcript.jsonl"


def make_agent_id(role: str, slug: str, *, pid: int | None = None) -> str:
    """Return a fresh opaque agent id — a ``uuid7`` hex."""
    return uuid.uuid7().hex


def current_branch() -> str | None:
    """Current git branch name, or None outside a repo / when detached."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def log_root() -> Path:
    """Base log dir. Honors MENTAT_LOG_PATH (default ~/.mentat/logs)."""
    return Path(os.environ.get("MENTAT_LOG_PATH", str(Path.home() / ".mentat" / "logs")))


def _repo_root() -> Path | None:
    """Absolute path of the repo's main working tree, or None outside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    common = Path(raw)
    if not common.is_absolute():
        common = Path.cwd() / common
    return common.resolve().parent


def repo_name() -> str:
    """Repo name, stable across worktrees and subdirs.

    Honors MENTAT_REPO (frozen at spawn). Otherwise the basename of the repo's
    main working tree. Outside a git repo returns ``unknown`` — never cwd basename,
    so ``track <id>`` from /tmp still resolves the agent by id.
    """
    env = os.environ.get("MENTAT_REPO")
    if env:
        return env
    root = _repo_root()
    if root is not None:
        return root.name
    return "unknown"


def agent_dir(agent_id: str) -> Path:
    """Dir for all files belonging to agent_id: log_root/repo/agent_id."""
    safe_id = agent_id.replace("/", "-")
    return log_root() / repo_name() / safe_id


def summary_file(agent_id: str) -> Path:
    return agent_dir(agent_id) / "summary.md"


def diagnosis_file(agent_id: str) -> Path:
    return agent_dir(agent_id) / "diagnosis.md"


def transcript_log_path(agent_id: str) -> Path:
    """Harness transcript path for agent_id."""
    return agent_dir(agent_id) / _TRANSCRIPT_NAME


def agent_id_from_env(env: dict[str, str] | None = None) -> str | None:
    mapping = os.environ if env is None else env
    return mapping.get("MENTAT_AGENT") or mapping.get("MENTAT_SESSION")


def ensure_agent(role: str, slug: str) -> str:
    """Mint + export MENTAT_AGENT and MENTAT_AGENT_LOG if unset."""
    agent_id = agent_id_from_env()
    if not agent_id:
        agent_id = make_agent_id(role, slug)
    os.environ["MENTAT_AGENT"] = agent_id
    os.environ.setdefault("MENTAT_SESSION", agent_id)
    if not os.environ.get("MENTAT_REPO"):
        os.environ["MENTAT_REPO"] = repo_name()
    os.environ.setdefault("MENTAT_SLUG", slug)
    os.environ.setdefault("MENTAT_AGENT_PID", str(os.getpid()))
    if not os.environ.get("MENTAT_AGENT_LOG"):
        log = transcript_log_path(agent_id)
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ["MENTAT_AGENT_LOG"] = str(log)
    os.environ.setdefault("MENTAT_SESSION_LOG", os.environ["MENTAT_AGENT_LOG"])
    return agent_id


def session_dir(session_id: str) -> Path:
    return agent_dir(session_id)


def session_log_path(session_id: str) -> Path:
    return transcript_log_path(session_id)


def ensure_session(role: str, slug: str) -> str:
    return ensure_agent(role, slug)


def resolve_agent_dir(agent_id: str) -> Path | None:
    """Find an agent's log dir anywhere under log_root (cwd/repo-independent)."""
    safe_id = agent_id.replace("/", "-")
    direct = agent_dir(agent_id)
    if direct.is_dir():
        return direct
    root = log_root()
    if not root.is_dir():
        return None
    for repo_path in sorted(root.iterdir()):
        if not repo_path.is_dir():
            continue
        candidate = repo_path / safe_id
        if candidate.is_dir():
            return candidate
    return None
