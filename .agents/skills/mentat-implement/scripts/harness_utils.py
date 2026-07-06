"""Shared helpers for mentat-implement."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

_TRACK_REGISTRY = Path(__file__).resolve().parents[2] / "mentat-track" / "scripts" / "registry.py"
_spec = importlib.util.spec_from_file_location("mentat_track_registry", _TRACK_REGISTRY)
_track_registry = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_track_registry)

from lib import harness_stream  # noqa: E402
from lib.config import read_config  # noqa: E402


def default_harness() -> str:
    harness = read_config().get("harness", "claude-code")
    return harness if isinstance(harness, str) else "claude-code"


def detect_self_answer(agent_log_path: Path | str | None) -> bool:
    """Return True if any assistant turn invoked AskUserQuestion.

    The AskUserQuestion stream-json shape is owned by `lib.harness_stream`; this
    scans the captured agent log (written when MENTAT_AGENT_LOG is set) for
    any such row — the self-answer signal for AFK plans (eject with exit 42).
    """
    if not agent_log_path:
        return False
    path = Path(agent_log_path)
    if not path.exists():
        return False
    return any(harness_stream.is_ask_user_question(row) for row in _track_registry.iter_rows(path))
