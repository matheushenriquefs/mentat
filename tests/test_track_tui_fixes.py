"""TUI fixes for `mentat-session track` (the multi-AFK navigator): focus/cursor
pinning to session identity (flicker A), the flicker-free repaint engine
(flicker B), transcript scrollback, honest empty states, and transcript-by-role
coloring. Pure surface only — the raw-tty/select poll loop stays the untested I/O
shell. Gate-run home (testpaths = ["tests"])."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-session/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))

from tests.conftest import load_script  # noqa: E402


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _rec(session: str, status: str = "working", age: float = 0.0, last_event: str | None = None) -> dict:
    return {"session": session, "status": status, "mtime": 0.0, "age": age, "last_event": last_event}


# ── Slice 1: focus + list cursor pinned to session identity (flicker A) ───────


def test_resolve_focus_index_follows_pinned_across_resort():
    """A background re-sort swaps the list order; the pinned name's index moves with it."""
    track = load_module("track")
    reg_a = [_rec("s-a"), _rec("s-b")]
    reg_b = [_rec("s-b"), _rec("s-a")]  # same names, swapped by a status flip
    assert track.resolve_focus_index(reg_a, "s-a", 0) == 0
    assert track.resolve_focus_index(reg_b, "s-a", 0) == 1


def test_resolve_focus_index_none_when_pinned_session_reaped():
    track = load_module("track")
    assert track.resolve_focus_index([_rec("s-b")], "s-a", 0) is None


def test_resolve_focus_index_fallback_when_unpinned():
    """No pin yet (None) → the caller's fallback index, not a search."""
    track = load_module("track")
    assert track.resolve_focus_index([_rec("s-a"), _rec("s-b")], None, 1) == 1


def test_resolve_focus_index_accepts_entry_tuples():
    """navigate passes (record, path) entries, not bare records."""
    track = load_module("track")
    entries = [(_rec("s-a"), Path("/x/s-a")), (_rec("s-b"), Path("/x/s-b"))]
    assert track.resolve_focus_index(entries, "s-b", 0) == 1


def test_humanize_age_buckets():
    sessions = load_module("sessions")
    assert sessions._humanize_age(30) == "30s ago"  # <60s
    assert sessions._humanize_age(120) == "2m ago"  # <3600s
    assert sessions._humanize_age(7200) == "2h ago"  # <86400s
    assert sessions._humanize_age(172800) == "2d ago"  # else


def test_session_module_reexports_humanize_age():
    """cmd_list still reaches _humanize_age after the relocate (no duplicate impl)."""
    session = load_module("session")
    sessions = load_module("sessions")
    assert session._humanize_age(120) == sessions._humanize_age(120) == "2m ago"


def test_render_list_shows_age_column():
    track = load_module("track")
    lines = track.render_list([_rec("s-a", age=120)], 0)
    assert "2m ago" in lines[0]
