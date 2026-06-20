"""Canonical mentat session-id minting + propagation.

One format for every entrypoint: ``<role>-<slug>-<pid>``.

  role  ∈ {implement, orchestrate} — which entrypoint owns the session.
  slug  = plan stem (implement) or holding branch (orchestrate); always present.
  pid   = os.getpid() — tiebreaks concurrent same-slug runs.

Replaces four divergent legacy formats (``mentat-manual-<pid>``,
``mentat-manual-<epoch>-<pid>``, ``auto-<stem>-<pid>``,
``mentat-orchestrate-<pid>``). The ``<epoch>`` was noise (pid already
disambiguates live processes) and made ids unstable + ungreppable; the
``manual``/``auto`` literals lied once real sessions were minted.

``ensure_session`` exports ``MENTAT_SESSION`` + ``MENTAT_SESSION_LOG`` into the
environment *before any harness spawn*, so events and ``session.jsonl`` capture
are keyed from the first event instead of relying on an emit-time fallback.
"""

from __future__ import annotations

import os
from pathlib import Path


def mint_session(role: str, slug: str, *, pid: int | None = None) -> str:
    """Return the canonical session id ``<role>-<slug>-<pid>``."""
    if pid is None:
        pid = os.getpid()
    return f"{role}-{slug}-{pid}"


def session_log_path(session_id: str) -> Path:
    """The session's ``session.jsonl`` path. Honors MENTAT_LOG_PATH + MENTAT_REPO."""
    base = Path(os.environ.get("MENTAT_LOG_PATH", str(Path.home() / ".mentat" / "logs")))
    repo = os.environ.get("MENTAT_REPO", Path.cwd().name)
    return base / repo / session_id / "session.jsonl"


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
        os.environ["MENTAT_REPO"] = Path.cwd().name
    if not os.environ.get("MENTAT_SESSION_LOG"):
        log = session_log_path(session_id)
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ["MENTAT_SESSION_LOG"] = str(log)
    return session_id
