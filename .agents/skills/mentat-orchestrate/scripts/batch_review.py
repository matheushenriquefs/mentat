"""End-of-queue advisory batch review."""

from __future__ import annotations

import importlib.util as _ilu
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


_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import bind  # noqa: E402

_emit_event = bind("mentat-orchestrate")


def review(session_id: str) -> dict:
    """Run advisory batch review. Emits batch.reviewed. Returns summary."""
    summary = f"batch review for session {session_id} — advisory"
    _emit_event(
        "batch.reviewed",
        {
            "session": session_id,
            "summary": summary,
        },
    )
    return {"session": session_id, "summary": summary}
