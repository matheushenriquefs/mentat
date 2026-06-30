"""Canonical mentat session-id minting + propagation.

One format for every entrypoint: ``<role>-<slug>-<pid>``.

  role  ∈ {implement, orchestrate} — which entrypoint owns the session.
  slug  = plan stem (implement) or holding branch (orchestrate); always present.
  pid   = os.getpid() — tiebreaks concurrent same-slug runs.

``ensure_session`` exports ``MENTAT_SESSION`` + ``MENTAT_SESSION_LOG`` into the
environment *before any harness spawn*, so events and ``session.jsonl`` capture
are keyed from the first event instead of relying on an emit-time fallback.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def mint_session(role: str, slug: str, *, pid: int | None = None) -> str:
    """Return the canonical session id ``<role>-<slug>-<pid>``."""
    if pid is None:
        pid = os.getpid()
    return f"{role}-{slug}-{pid}"


# ── session-log-path seam ────────────────────────────────────────────────────
# One owner of base/repo/session path arithmetic; each caller delegates so
# divergence is impossible.


def log_root() -> Path:
    """Base log dir. Honors MENTAT_LOG_PATH (default ~/.mentat/logs)."""
    return Path(os.environ.get("MENTAT_LOG_PATH", str(Path.home() / ".mentat" / "logs")))


def _repo_root() -> Path | None:
    """Absolute path of the repo's main working tree, or None outside a git repo.

    Resolves via the *common* git dir so a linked worktree and a nested subdir
    both report the same repo the writer froze at the repo root, rather than the
    worktree/subdir basename.
    """
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

    Honors MENTAT_REPO (the writer freezes it at spawn). Otherwise the basename of
    the repo's main working tree, so a reader invoked from a worktree or a nested
    subdir resolves the same name the writer froze at the repo root — without it, a
    fresh `track` shell fell back to the cwd basename and scanned an empty log dir.
    Falls back to the cwd basename outside a git repo.
    """
    env = os.environ.get("MENTAT_REPO")
    if env:
        return env
    root = _repo_root()
    if root is not None:
        return root.name
    return Path.cwd().name


def session_dir(session_id: str) -> Path:
    """Dir for all files belonging to session_id: log_root/repo/session_id."""
    safe_id = session_id.replace("/", "-")
    return log_root() / repo_name() / safe_id


def summary_file(session_id: str) -> Path:
    """Canonical summary.md path for session_id."""
    return session_dir(session_id) / "summary.md"


def diagnosis_file(session_id: str) -> Path:
    """Canonical diagnosis.md path for session_id."""
    return session_dir(session_id) / "diagnosis.md"


def session_log_path(session_id: str) -> Path:
    """The session's ``session.jsonl`` path. Honors MENTAT_LOG_PATH + MENTAT_REPO."""
    return session_dir(session_id) / "session.jsonl"


def ensure_session(role: str, slug: str) -> str:
    """Mint + export MENTAT_SESSION and MENTAT_SESSION_LOG if unset.

    Idempotent: an already-set ``MENTAT_SESSION`` (e.g. one exported by a parent
    orchestrate for its fan-out child) is preserved, not re-minted. Creates the
    session log dir (0o700) when minting the log path. Returns the effective id.
    """
    session_id = os.environ.get("MENTAT_SESSION")
    if not session_id:
        session_id = mint_session(role, slug)
        os.environ["MENTAT_SESSION"] = session_id
    # Freeze the repo name now, while cwd is still the repo. implement chdir's
    # into its worktree before it emits / doctors / promotes a summary; a bare
    # cwd().name there resolves to the slug worktree dir, splitting those outputs
    # from session.jsonl (frozen to the repo dir here). Exporting it once keeps
    # every later MENTAT_REPO reader pointed at one log dir.
    if not os.environ.get("MENTAT_REPO"):
        os.environ["MENTAT_REPO"] = repo_name()
    if not os.environ.get("MENTAT_SESSION_LOG"):
        log = session_log_path(session_id)
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ["MENTAT_SESSION_LOG"] = str(log)
    return session_id
