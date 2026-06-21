"""S7 — live multi-AFK tracking navigator. Pure surface only (the curses/raw-tty
poll loop is the thin untested I/O shell): stream tool-call extraction, the house
TUI glyph/status vocabulary, the registry stream tail, and the navigator's
keypress reducer + list/preview renderers. Gate-run home (testpaths = ["tests"])."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.conftest import load_script

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-session/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import harness_stream, tui  # noqa: E402


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _assistant(*tool_names: str, text: str = "") -> dict:
    blocks = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks += [{"type": "tool_use", "name": n} for n in tool_names]
    return {"type": "assistant", "message": {"content": blocks}}


def _tool_result(content: str) -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": content}]}}


# ── harness_stream.tool_uses — tool-call names from one stream row ─────────────


def test_tool_uses_lists_tool_names_in_order():
    assert harness_stream.tool_uses(_assistant("Read", "Edit", "Bash")) == ["Read", "Edit", "Bash"]


def test_tool_uses_empty_for_non_assistant_or_text():
    assert harness_stream.tool_uses({"type": "user"}) == []
    assert harness_stream.tool_uses({"type": "assistant", "message": {"content": [{"type": "text"}]}}) == []
    assert harness_stream.tool_uses("not a dict") == []
    assert harness_stream.tool_uses({"type": "assistant", "message": {"content": "bad"}}) == []


def test_tool_uses_skips_blocks_with_non_str_name():
    row = {"type": "assistant", "message": {"content": [{"type": "tool_use"}, {"type": "tool_use", "name": "Read"}]}}
    assert harness_stream.tool_uses(row) == ["Read"]


def test_is_ask_user_question_consistent_with_tool_uses():
    """The AFK self-answer detector is the AskUserQuestion case of tool_uses (no schema drift)."""
    assert harness_stream.is_ask_user_question(_assistant("AskUserQuestion")) is True
    assert harness_stream.is_ask_user_question(_assistant("Read")) is False


# ── tui — tracking glyph + status vocabulary ──────────────────────────────────


def test_tool_glyph_known_and_fallback():
    assert tui.tool_glyph("Read") == "·"
    assert tui.tool_glyph("Edit") == "~"
    assert tui.tool_glyph("Write") == "+"
    assert tui.tool_glyph("Bash") == "$"
    assert tui.tool_glyph("Grep") == "/"
    assert tui.tool_glyph("Task") == "»"
    assert tui.tool_glyph("Unknown") == "·"  # fallback, single-width


def test_lifecycle_glyph_reuses_house_vocabulary():
    assert tui.lifecycle_glyph("spawned") == "+"
    assert tui.lifecycle_glyph("landed") == tui.DONE  # reuse ✓
    assert tui.lifecycle_glyph("ejected") == "✗"
    assert tui.lifecycle_glyph("hitl") == tui.PROMPT_ASK  # reuse ◆


def test_all_glyphs_single_width():
    """No emoji / wide glyphs — install + tracker share one look."""
    allowed_nonascii = {"·", "»", tui.DONE, tui.PROMPT_ASK, "✗", "●"}
    glyphs = [tui.tool_glyph(n) for n in ("Read", "Edit", "Write", "Bash", "Grep", "Task", "X")]
    glyphs += [tui.lifecycle_glyph(n) for n in ("spawned", "landed", "ejected", "hitl")]
    for g in glyphs:
        assert len(g) == 1  # single codepoint, no emoji ZWJ sequences
        assert g.isascii() or g in allowed_nonascii


def test_status_color_maps_rank_palette():
    assert tui.status_color("waiting") == tui.status_color("waiting")  # stable
    assert tui.status_color("waiting") != tui.status_color("idle")
    assert tui.status_color("working") != tui.status_color("idle")
    # unknown falls back (dim), never raises
    assert isinstance(tui.status_color("nope"), str)


def test_status_dot_is_colored_dot():
    # not a tty under pytest → color() returns plain text
    assert tui.status_dot("idle") == "●"


def test_section_rule_wraps_label():
    assert tui.section_rule("impl-a-1") == "── [impl-a-1] ──"


# ── sessions.session_stream_tools — registry stream tail ──────────────────────


def _write_stream(session_dir: Path, name: str, rows: list[dict]) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    f = session_dir / f"{name}.jsonl"
    with f.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return f


def test_session_stream_tools_returns_tool_names_in_order(tmp_path):
    sessions = load_module("sessions")
    sd = tmp_path / "s-1"
    _write_stream(sd, "session", [_assistant("Read"), {"type": "user"}, _assistant("Edit", "Bash")])
    assert sessions.session_stream_tools(sd) == ["Read", "Edit", "Bash"]


def test_session_stream_tools_tails_last_n(tmp_path):
    sessions = load_module("sessions")
    sd = tmp_path / "s-1"
    _write_stream(sd, "session", [_assistant(f"T{i}") for i in range(10)])
    assert sessions.session_stream_tools(sd, limit=3) == ["T7", "T8", "T9"]


def test_session_stream_tools_ignores_audit_rows(tmp_path):
    """Audit rows (event key, no assistant tool_use) contribute nothing."""
    sessions = load_module("sessions")
    sd = tmp_path / "s-1"
    _write_stream(sd, "mentat-implement", [{"ts": "t", "event": "chunk.spawned", "payload": {}}])
    _write_stream(sd, "session", [_assistant("Read")])
    assert sessions.session_stream_tools(sd) == ["Read"]


def test_session_stream_tools_empty_when_absent(tmp_path):
    sessions = load_module("sessions")
    assert sessions.session_stream_tools(tmp_path / "nope") == []


# ── sessions.session_worktree — kill-bind target lookup ───────────────────────


def test_session_worktree_from_spawn_event(tmp_path):
    sessions = load_module("sessions")
    sd = tmp_path / "s-1"
    sd.mkdir(parents=True)
    (sd / "mentat-implement.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.spawned",
                "payload": {"slug": "x", "worktree": "/wt/x"},
            }
        )
        + "\n"
    )
    assert sessions.session_worktree(sd) == "/wt/x"


def test_session_worktree_none_when_no_spawn(tmp_path):
    sessions = load_module("sessions")
    sd = tmp_path / "s-1"
    sd.mkdir(parents=True)
    (sd / "a.jsonl").write_text(json.dumps({"ts": "t", "event": "gate.evaluated", "payload": {}}) + "\n")
    assert sessions.session_worktree(sd) is None


# ── track — navigator keypress reducer (pure) ─────────────────────────────────


def test_handle_key_quit():
    track = load_module("track")
    assert track.handle_key("q", 0, 3) == (0, "quit")
    assert track.handle_key("\x1b", 1, 3) == (1, "quit")


def test_handle_key_navigation_clamps():
    track = load_module("track")
    assert track.handle_key("j", 0, 3) == (1, None)
    assert track.handle_key("j", 2, 3) == (2, None)  # clamp at bottom
    assert track.handle_key("k", 0, 3) == (0, None)  # clamp at top
    assert track.handle_key("k", 2, 3) == (1, None)


def test_handle_key_navigation_empty_list():
    track = load_module("track")
    assert track.handle_key("j", 0, 0) == (0, None)


def test_handle_key_focus_and_kill():
    track = load_module("track")
    assert track.handle_key("\r", 1, 3) == (1, "focus")
    assert track.handle_key("x", 2, 3) == (2, "kill")


def test_handle_key_unknown_is_noop():
    track = load_module("track")
    assert track.handle_key("z", 1, 3) == (1, None)


# ── track — list + preview renderers (pure) ───────────────────────────────────


def _rec(session: str, status: str, last_event: str | None = None) -> dict:
    return {"session": session, "status": status, "mtime": 0.0, "age": 0.0, "last_event": last_event}


def test_render_list_marks_selection_and_status():
    track = load_module("track")
    records = [_rec("s-a", "waiting", "chunk.ejected"), _rec("s-b", "working")]
    lines = track.render_list(records, selected=1)
    assert len(lines) == 2
    assert "s-a" in lines[0] and "s-b" in lines[1]
    assert lines[1].startswith(">")  # cursor on selected
    assert not lines[0].startswith(">")
    assert "●" in lines[0]  # status dot present


def test_render_list_empty():
    track = load_module("track")
    assert track.render_list([], selected=0) == []


def test_render_preview_gutter_and_glyphs():
    track = load_module("track")
    lines = track.render_preview(["Read", "Edit"])
    body = "\n".join(lines)
    assert tui.PIPE in body  # │ gutter
    assert tui.tool_glyph("Read") in body
    assert tui.tool_glyph("Edit") in body
    assert "Read" in body and "Edit" in body


def test_render_preview_empty_still_renders_gutter():
    track = load_module("track")
    lines = track.render_preview([])
    assert isinstance(lines, list)


def test_render_focus_shows_session_rule_and_tools(tmp_path):
    track = load_module("track")
    sd = tmp_path / "s-a"
    _write_stream(sd, "session", [_assistant("Read", "Bash")])
    rec = _rec("s-a", "working", "chunk.spawned")
    lines = track.render_focus(rec, sd)
    body = "\n".join(lines)
    assert tui.section_rule("s-a — working") in body  # focused header rule
    assert "Read" in body and "Bash" in body
    assert tui.PIPE in body  # preview gutter reused
    assert "back" in body  # exit hint


# ── V2: harness_stream extractors + dual-stream renderers ────────────────────


def test_assistant_text_extracts_text_blocks():
    row = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "hello world"},
                {"type": "tool_use", "name": "Read"},
            ]
        },
    }
    assert harness_stream.assistant_text(row) == "hello world"


def test_assistant_text_empty_for_non_assistant():
    assert harness_stream.assistant_text({"type": "user"}) == ""
    assert harness_stream.assistant_text({"type": "assistant", "message": {"content": []}}) == ""
    assert harness_stream.assistant_text("bad") == ""


def test_tool_result_extracts_string_content():
    row = _tool_result("file contents here")
    assert "file contents here" in harness_stream.tool_result(row)


def test_tool_result_empty_for_non_user():
    assert harness_stream.tool_result({"type": "assistant"}) == ""
    assert harness_stream.tool_result("bad") == ""


def test_render_transcript_shows_chat_not_blank(tmp_path):
    """session.jsonl with only harness rows renders chat text, not '[] {}'."""
    track = load_module("track")
    sd = tmp_path / "s-1"
    _write_stream(
        sd,
        "session",
        [
            _assistant("Read", text="Let me read that."),
            _tool_result("file contents"),
        ],
    )
    lines = track.render_transcript_lines(sd)
    body = "\n".join(lines)
    assert "Let me read that." in body
    assert "Read" in body
    assert "[] {}" not in body


def test_render_audit_shows_events(tmp_path):
    """Audit-only dir renders event timeline."""
    track = load_module("track")
    sd = tmp_path / "s-audit"
    sd.mkdir()
    (sd / "mentat-impl.jsonl").write_text(
        json.dumps({"ts": "2026-01-01T00:00:00+00:00", "event": "chunk.spawned", "payload": {"slug": "x"}}) + "\n"
    )
    lines = track.render_audit_lines(sd)
    body = "\n".join(lines)
    assert "chunk.spawned" in body


def test_toggle_view_flips():
    track = load_module("track")
    assert track.toggle_view("transcript") == "audit"
    assert track.toggle_view("audit") == "transcript"


# ── V3: handle_key toggle + render_focus wired to dual-stream renderer ────────


def test_handle_key_toggle():
    track = load_module("track")
    assert track.handle_key("t", 1, 3) == (1, "toggle")


def test_render_focus_transcript_shows_chat(tmp_path):
    """render_focus in transcript view shows assistant text and tool names."""
    track = load_module("track")
    sd = tmp_path / "s-1"
    _write_stream(sd, "session", [_assistant("Read", text="doing stuff")])
    rec = _rec("s-1", "working")
    lines = track.render_focus(rec, sd, "transcript")
    body = "\n".join(lines)
    assert "doing stuff" in body
    assert "Read" in body
    assert tui.section_rule("s-1 — working") in body
    assert "back" in body


def test_render_focus_audit_shows_events(tmp_path):
    """render_focus in audit view shows event timeline."""
    track = load_module("track")
    sd = tmp_path / "s-1"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "mentat-impl.jsonl").write_text(json.dumps({"ts": "t", "event": "chunk.spawned", "payload": {}}) + "\n")
    rec = _rec("s-1", "working")
    lines = track.render_focus(rec, sd, "audit")
    body = "\n".join(lines)
    assert "chunk.spawned" in body


# ── V4: viewport bounding for the list pane ───────────────────────────────────


def test_render_list_viewport_keeps_cursor_visible():
    """50 records, viewport=10, selected=30 → window around row 30, row 0 absent."""
    track = load_module("track")
    records = [_rec(f"s-{i:02d}", "working") for i in range(50)]
    lines = track.render_list(records, 30, viewport_height=10)
    body = "\n".join(lines)
    assert "s-30" in body
    assert "s-00" not in body
    non_empty = [ln for ln in lines if ln.strip()]
    assert len(non_empty) <= 11  # 10 records + optional "… N more"


def test_render_list_no_viewport_shows_all():
    track = load_module("track")
    records = [_rec(f"s-{i}", "working") for i in range(5)]
    lines = track.render_list(records, 0)
    assert len(lines) == 5


def test_render_list_affordance_when_truncated():
    """… N more line appears when viewport cuts records at the bottom."""
    track = load_module("track")
    records = [_rec(f"s-{i}", "working") for i in range(20)]
    lines = track.render_list(records, 0, viewport_height=5)
    body = "\n".join(lines)
    assert "more" in body
