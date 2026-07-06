"""Agent id resolution: agent-id → log dir, latest-agent fallback."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import store as _store  # noqa: E402
from lib.session import agent_dir as _agent_dir_fn  # noqa: E402
from lib.session import log_root as _log_root  # noqa: E402
from lib.session import repo_name as _repo  # noqa: E402
from lib.session import resolve_agent_dir as _resolve_agent_dir  # noqa: E402


def _agent_dir(repo: str, agent_id: str) -> Path:
    """Preserved for test assertions; delegates to the seam."""
    return _log_root() / repo / agent_id


def _resolve_agent(agent_id: str | None) -> Path | int:
    """Resolve agent_id to an existing agent dir, or return an exit code."""
    repo = _repo()
    ad = _resolve_agent_dir(agent_id) if agent_id else None
    if agent_id is not None and ad is None:
        ad = _agent_dir_fn(agent_id)
    if agent_id is None:
        agent_id = _store.get_latest_agent(repo)
    if agent_id is None:
        print("mentat-track: no agents found", file=sys.stderr)
        return 1
    if ad is None:
        ad = _resolve_agent_dir(agent_id) or _agent_dir_fn(agent_id)
    if not ad.exists():
        print(f"mentat-track: agent dir not found: {ad}", file=sys.stderr)
        return 1
    return ad
