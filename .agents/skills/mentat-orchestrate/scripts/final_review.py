"""End-of-queue advisory final review."""

from __future__ import annotations

import sys
from pathlib import Path

import importlib.util as _ilu


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


_utils = _load_sibling("utils")


def _emit_event(event: str, payload: dict) -> None:
    _utils.emit_event(event, payload)


def review(session_id: str) -> dict:
    """Run advisory final review. Emits batch.reviewed. Returns summary."""
    summary = f"batch review for session {session_id} — advisory"
    _emit_event("batch.reviewed", {
        "session": session_id,
        "summary": summary,
    })
    return {"session": session_id, "summary": summary}
