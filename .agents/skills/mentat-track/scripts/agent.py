"""Agent id resolution: agent-id → log dir, latest-agent fallback."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import store as _store  # noqa: E402
from lib.agent import log_root as _log_root  # noqa: E402
from lib.agent import resolve_agent_dir as _resolve_agent_dir  # noqa: E402
from lib.agent import resolve_track_repo as _resolve_track_repo  # noqa: E402


def _agent_dir(repo: str, agent_id: str) -> Path:
    """Preserved for test assertions; delegates to the seam."""
    return _log_root() / repo / agent_id


def _resolve_agent(agent_id: str | None) -> Path | int:
    """Resolve agent_id to an existing agent dir, or return an exit code."""
    repo = _resolve_track_repo()
    if agent_id is None:
        agent_id = _store.get_latest_agent(repo)
    if agent_id is None:
        print("mentat-track: no agents found", file=sys.stderr)
        return 1
    ad = _resolve_agent_dir(agent_id)
    if ad is None or not ad.exists():
        print(f"mentat-track: agent dir not found: {agent_id}", file=sys.stderr)
        return 1
    return ad
