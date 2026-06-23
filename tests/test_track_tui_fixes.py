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


# ── Slice 2: flicker-free repaint engine (flicker B) ──────────────────────────


def _tui():
    sys.path.insert(0, str(REPO_ROOT / ".agents"))
    from lib import tui

    return tui


def test_paint_uses_home_and_eol_not_full_clear():
    tui = _tui()
    out = tui.paint(["alpha", "beta"], rows=5)
    assert tui.HOME in out
    assert tui.CLEAR_EOL in out
    assert "\033[2J" not in out  # never the blank-flash full clear


def test_paint_erases_trailing_stale_rows():
    tui = _tui()
    # 2 content lines into a 5-row viewport → 2 line-erases + 3 stale-row erases.
    assert tui.paint(["a", "b"], rows=5).count(tui.CLEAR_EOL) == 5


def test_paint_no_stale_erase_when_frame_fills_viewport():
    tui = _tui()
    out = tui.paint(["a", "b", "c"], rows=2)  # more lines than rows → no negative loop
    assert out.count(tui.CLEAR_EOL) == 3


def test_paint_wraps_in_synchronized_output():
    tui = _tui()
    out = tui.paint(["x"], rows=1)
    assert out.startswith(tui.SYNC_BEGIN)
    assert out.endswith(tui.SYNC_END)


def test_frame_fingerprint_stable_and_size_sensitive():
    track = load_module("track")
    f = ["row one", "row two"]
    assert track._frame_fingerprint(f, 80, 24) == track._frame_fingerprint(list(f), 80, 24)
    assert track._frame_fingerprint(f, 80, 24) != track._frame_fingerprint(f, 100, 24)
    assert track._frame_fingerprint(f, 80, 24) != track._frame_fingerprint(f, 80, 40)
    assert track._frame_fingerprint(f, 80, 24) != track._frame_fingerprint(["row one"], 80, 24)


def test_restore_sequence_shows_cursor_and_exits_alt_screen():
    track = load_module("track")
    tui = _tui()
    seq = track._restore_seq()
    assert tui.SHOW_CURSOR in seq
    assert tui.ALT_EXIT in seq


# ── Slice 3: scrollback in the focused transcript ─────────────────────────────


def _write_stream(session_dir: Path, name: str, rows: list[dict]) -> None:
    import json

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def _assistant(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def test_render_transcript_lines_returns_full_history(tmp_path):
    """Drop the pre-tail cap so the focus pane has something to scroll."""
    track = load_module("track")
    sd = tmp_path / "s-1"
    _write_stream(sd, "session", [_assistant(f"line {i}") for i in range(60)])  # > old FOCUS_LINES cap
    lines = track.render_transcript_lines(sd)
    body = "\n".join(lines)
    assert "line 0" in body and "line 59" in body  # head and tail both present


def test_window_lines_follows_tail_when_unfrozen():
    track = load_module("track")
    lines = [str(i) for i in range(10)]
    vis, above, below = track.window_lines(lines, scroll_top=None, height=3)
    assert vis == ["7", "8", "9"]
    assert above == 7 and below == 0


def test_window_lines_frozen_top_anchored():
    track = load_module("track")
    lines = [str(i) for i in range(10)]
    vis, above, below = track.window_lines(lines, scroll_top=2, height=3)
    assert vis == ["2", "3", "4"]
    assert above == 2 and below == 5


def test_window_lines_clamps_out_of_range_without_raising():
    track = load_module("track")
    lines = [str(i) for i in range(5)]
    vis, above, below = track.window_lines(lines, scroll_top=999, height=3)
    assert vis == ["2", "3", "4"] and above == 2 and below == 0  # clamped to max_top
    vis2, above2, _ = track.window_lines(lines, scroll_top=-5, height=3)
    assert vis2 == ["0", "1", "2"] and above2 == 0


def test_window_lines_shorter_than_height():
    track = load_module("track")
    vis, above, below = track.window_lines(["a", "b"], scroll_top=None, height=10)
    assert vis == ["a", "b"] and above == 0 and below == 0


def test_scroll_rearms_tail_at_bottom():
    track = load_module("track")
    # total 10, height 3 → max_top 7; from 6 stepping +1 reaches the bottom → None.
    assert track.scroll(6, 1, 10, 3) is None


def test_scroll_up_from_tail_freezes_absolute():
    track = load_module("track")
    assert track.scroll(None, -1, 10, 3) == 6  # tail max_top 7, up one → frozen at 6


def test_scroll_half_page_delta_is_height_over_two():
    track = load_module("track")
    assert track.scroll(10, 6 // 2, 20, 6) == 13  # +half-page from 10


def test_scroll_clamps_top_to_zero():
    track = load_module("track")
    assert track.scroll(1, -5, 10, 3) == 0


# ── Slice 4: honest empty states (audit toggle) ───────────────────────────────


def test_empty_hint_audit_with_known_last_event():
    track = load_module("track")
    assert track.empty_hint("audit", "chunk.landed") == "(no audit rows here — last lifecycle: chunk.landed)"


def test_empty_hint_audit_without_last_event():
    track = load_module("track")
    assert track.empty_hint("audit", None) == "(no audit events yet — press t for the transcript)"


def test_empty_hint_transcript():
    track = load_module("track")
    assert track.empty_hint("transcript", None) == "(no transcript — audit-only session; press t for lifecycle)"


def test_empty_hint_last_event_only_used_for_audit():
    """A last_event in transcript view never leaks the lifecycle hint."""
    track = load_module("track")
    assert track.empty_hint("transcript", "chunk.landed") == track.empty_hint("transcript", None)
