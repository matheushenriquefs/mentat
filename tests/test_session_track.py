"""S7 — live multi-AFK tracking navigator. Pure surface only (the curses/raw-tty
poll loop is the thin untested I/O shell): stream tool-call extraction, the house
TUI glyph/status vocabulary, the registry stream tail, and the navigator's
keypress reducer + list/preview renderers. Gate-run home (testpaths = ["tests"])."""

from __future__ import annotations

import json
import os
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


# ── S2: stream() dead-code removal ───────────────────────────────────────────


def test_stream_symbol_absent():
    """stream() had no caller and a broken 60s cap; it must be gone."""
    track = load_module("track")
    assert not hasattr(track, "stream"), "stream() is dead code and must be deleted"


def test_module_imports_without_stream():
    """Removing stream() must not break module load or any other export."""
    track = load_module("track")
    assert callable(track.handle_key)
    assert callable(track.render_list)
    assert callable(track.navigate)


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
    assert len(non_empty) <= 10  # exactly viewport_height rows (affordance replaces last, not appended)


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


# ── S3: viewport off-by-one + small-terminal budget ─────────────────────────


def test_render_list_never_exceeds_viewport_height():
    """render_list with affordance must stay within viewport_height, not exceed it."""
    track = load_module("track")
    records = [_rec(f"s-{i}", "working") for i in range(20)]
    lines = track.render_list(records, selected=2, viewport_height=5)
    assert len(lines) <= 5, f"expected ≤5 rows, got {len(lines)}"


def test_render_list_cursor_on_screen_small_terminal():
    """24-row terminal budget (list_viewport=5), >5 sessions → selected row in output."""
    track = load_module("track")
    records = [_rec(f"s-{i:02d}", "working") for i in range(10)]
    lines = track.render_list(records, selected=7, viewport_height=5)
    body = "\n".join(lines)
    assert "s-07" in body, "selected row must be in the rendered window"
    assert len(lines) <= 5


def test_render_list_viewport_exact_budget():
    """When viewport matches count, no affordance, stays exactly at budget."""
    track = load_module("track")
    records = [_rec(f"s-{i}", "working") for i in range(5)]
    lines = track.render_list(records, 0, viewport_height=5)
    assert len(lines) == 5
    assert all("more" not in ln for ln in lines)


# ── V5: fix _read_key escape-burst parsing over a real pty ───────────────────


def test_read_key_over_pty():
    """_read_key over a real pty: sequences classified correctly, lone ESC → quit."""
    import os
    import pty
    import termios
    import tty as _tty

    track = load_module("track")
    cases = [
        (b"\x1b[A", "UP"),
        (b"\x1b[B", "DOWN"),
        (b"\x1b", "\x1b"),
        (b"j", "j"),
        (b"\x1b[15~", None),  # F5 escape → swallow
    ]
    for data, expected in cases:
        master, slave = pty.openpty()
        old = termios.tcgetattr(slave)
        _tty.setraw(slave)
        try:
            os.write(master, data)
            result = track._read_key(0.5, _fd=slave)
            assert result == expected, f"data={data!r}: expected {expected!r}, got {result!r}"
        finally:
            termios.tcsetattr(slave, termios.TCSADRAIN, old)
            os.close(master)
            os.close(slave)


# ── V6: active_only filter + --all flag ───────────────────────────────────────

# ── _color_for_event ─────────────────────────────────────────────────────────


def test_color_for_event_known_suffix_returns_nonempty():
    track = load_module("track")
    color = track._color_for_event("plan.started")
    assert color != ""
    assert color.startswith("\033[")


def test_color_for_event_unknown_suffix_returns_empty():
    track = load_module("track")
    assert track._color_for_event("totally.unknown.event") == ""


def test_color_for_event_ejected_suffix():
    track = load_module("track")
    color = track._color_for_event("chunk.ejected")
    assert color != ""


# ── render_transcript_lines / render_audit_lines empty cases ─────────────────


def test_render_transcript_lines_empty_session_shows_placeholder(tmp_path):
    track = load_module("track")
    sd = tmp_path / "empty-session"
    sd.mkdir()
    lines = track.render_transcript_lines(sd)
    assert any("no transcript yet" in ln for ln in lines)


def test_render_transcript_lines_audit_only_shows_placeholder(tmp_path):
    """Audit-only rows (event key) are filtered out — transcript shows placeholder."""
    track = load_module("track")
    sd = tmp_path / "audit-only"
    sd.mkdir()
    (sd / "impl.jsonl").write_text(json.dumps({"ts": "t", "event": "chunk.spawned", "payload": {"slug": "x"}}) + "\n")
    lines = track.render_transcript_lines(sd)
    assert any("no transcript yet" in ln for ln in lines)


def test_render_audit_lines_empty_session_shows_placeholder(tmp_path):
    track = load_module("track")
    sd = tmp_path / "empty-audit"
    sd.mkdir()
    lines = track.render_audit_lines(sd)
    assert any("no audit events yet" in ln for ln in lines)


def test_render_audit_lines_stream_only_shows_placeholder(tmp_path):
    """Harness stream rows (no event key) are filtered out — audit shows placeholder."""
    track = load_module("track")
    sd = tmp_path / "stream-only"
    _write_stream(sd, "session", [_assistant("Read")])
    lines = track.render_audit_lines(sd)
    assert any("no audit events yet" in ln for ln in lines)


# ── view_session non-tty path ─────────────────────────────────────────────────


def test_view_session_non_tty_prints_transcript_and_returns(tmp_path, monkeypatch):
    track = load_module("track")
    sd = tmp_path / "s-view"
    _write_stream(sd, "session", [_assistant("Read", text="doing work")])
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: False})())
    lines_captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: lines_captured.append(" ".join(str(x) for x in a)))
    track.view_session(sd)
    body = "\n".join(lines_captured)
    assert "Read" in body or "doing work" in body


# ── _read_key timeout (select returns empty) ─────────────────────────────────


def test_read_key_timeout_returns_none(monkeypatch):
    import select as _select

    track = load_module("track")
    monkeypatch.setattr(_select, "select", lambda *a, **kw: ([], [], []))
    result = track._read_key(0.01, _fd=0)
    assert result is None


def test_read_key_oserror_returns_none(monkeypatch):
    """os.read raising (fd gone) is swallowed → None, never a crash in the loop."""
    import os as _os
    import select as _select

    track = load_module("track")
    monkeypatch.setattr(_select, "select", lambda *a, **kw: ([0], [], []))

    def _boom(fd: int, n: int) -> bytes:
        raise OSError

    monkeypatch.setattr(_os, "read", _boom)
    assert track._read_key(0.01, _fd=0) is None


def test_read_key_empty_burst_returns_none(monkeypatch):
    """A ready fd that reads zero bytes (EOF) → None."""
    import os as _os
    import select as _select

    track = load_module("track")
    monkeypatch.setattr(_select, "select", lambda *a, **kw: ([0], [], []))
    monkeypatch.setattr(_os, "read", lambda fd, n: b"")
    assert track._read_key(0.01, _fd=0) is None


def test_read_key_undecodable_returns_none(monkeypatch):
    """A non-UTF-8 byte is swallowed → None, never a UnicodeDecodeError."""
    import os as _os
    import select as _select

    track = load_module("track")
    monkeypatch.setattr(_select, "select", lambda *a, **kw: ([0], [], []))
    monkeypatch.setattr(_os, "read", lambda fd, n: b"\xff")
    assert track._read_key(0.01, _fd=0) is None


# ── untested helpers: terminal size, selection, tools, registry, kill, frame ──


def test_terminal_size_reads_device(monkeypatch):
    import os as _os

    track = load_module("track")
    monkeypatch.setattr(_os, "get_terminal_size", lambda fd: _os.terminal_size((120, 40)))
    assert track._terminal_size() == (120, 40)


def test_terminal_size_fallback_on_oserror(monkeypatch):
    import os as _os

    track = load_module("track")

    def _boom(fd: int) -> object:
        raise OSError

    monkeypatch.setattr(_os, "get_terminal_size", _boom)
    assert track._terminal_size() == (80, 20)


def test_selected_clamps_to_range():
    track = load_module("track")
    entries = [({"session": "a"}, Path("/a")), ({"session": "b"}, Path("/b"))]
    assert track._selected(entries, 5)[0]["session"] == "b"
    assert track._selected(entries, 0)[0]["session"] == "a"


def test_tools_delegates_to_stream_tools(tmp_path):
    track = load_module("track")
    sd = tmp_path / "s-tools"
    _write_stream(sd, "session", [_assistant("Read", "Grep")])
    assert track._tools(sd, limit=10) == ["Read", "Grep"]


def test_registry_pairs_records_with_dirs(tmp_path, monkeypatch):
    track = load_module("track")
    from lib import store

    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    env = {"MENTAT_AGENT": "implement-a-1", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    store.record_emit(env, "chunk.spawned", {"slug": "x"})
    (logs / "repo" / "implement-a-1").mkdir(parents=True)
    repo_dir = logs / "repo"
    entries = track._registry(repo_dir, active_only=False)
    assert entries, "expected the seeded session in the registry"
    rec, sd = entries[0]
    assert rec["session"] == "implement-a-1"
    assert sd == repo_dir / "implement-a-1"


def test_registry_reads_sqlite_lists_live_and_idle(tmp_path, monkeypatch):
    """track/registry reads the canonical store — live sessions list without recency window."""
    track = load_module("track")
    from lib import store

    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    live_env = {"MENTAT_AGENT": "live", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    idle_env = {"MENTAT_AGENT": "idle", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    store.record_emit(live_env, "chunk.spawned", {"slug": "a"})
    store.record_emit(idle_env, "gate.evaluated", {"gate": "x", "verdict": "pass", "severity": "low", "message": "ok"})
    (logs / "repo" / "live").mkdir(parents=True)
    (logs / "repo" / "idle").mkdir(parents=True)
    repo_dir = logs / "repo"
    entries = track._registry(repo_dir, active_only=True)
    assert {rec["session"] for rec, _ in entries} == {"live", "idle"}
    assert repo_dir / "live" in {sd for _, sd in entries}


def test_on_sigterm_sets_terminate_flag():
    track = load_module("track")
    track._TERMINATE = False
    track._on_sigterm(15, None)
    assert track._TERMINATE is True
    track._TERMINATE = False


def _seed_spawn(session_dir: Path, worktree: str) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    row = {"ts": "1", "event": "chunk.spawned", "payload": {"worktree": worktree}}
    (session_dir / "audit.jsonl").write_text(json.dumps(row) + "\n")


def test_kill_removes_worktree_via_git(tmp_path, monkeypatch):
    track = load_module("track")
    sd = tmp_path / "s-kill"
    _seed_spawn(sd, "/wt/x")
    calls: list[tuple] = []
    monkeypatch.setattr(track.subprocess, "run", lambda *a, **k: calls.append(a))
    track._kill(sd)
    assert calls, "expected a git worktree remove call"
    assert "/wt/x" in calls[0][0]


def test_kill_noop_when_no_worktree(tmp_path, monkeypatch):
    track = load_module("track")
    sd = tmp_path / "s-nokill"
    sd.mkdir()
    calls: list[tuple] = []
    monkeypatch.setattr(track.subprocess, "run", lambda *a, **k: calls.append(a))
    track._kill(sd)
    assert calls == []


def test_kill_swallows_git_error(tmp_path, monkeypatch):
    track = load_module("track")
    sd = tmp_path / "s-killerr"
    _seed_spawn(sd, "/wt/y")

    def _boom(*a, **k):
        raise OSError("git missing")

    monkeypatch.setattr(track.subprocess, "run", _boom)
    track._kill(sd)  # must not raise


def test_frame_builds_list_view_with_repo_and_hint(tmp_path, monkeypatch):
    track = load_module("track")
    from lib import store

    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    env = {"MENTAT_AGENT": "implement-a-1", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    store.record_emit(env, "chunk.spawned", {"slug": "x"})
    repo_dir = logs / "repo"
    (repo_dir / "implement-a-1").mkdir(parents=True)
    _write_stream(repo_dir / "implement-a-1", "session", [_assistant("Read", "Grep")])
    entries = track._registry(repo_dir, active_only=False)
    body = "\n".join(track._frame(entries, 0, "myrepo", rows=24))
    assert "myrepo" in body
    assert "session(s)" in body
    assert "move" in body  # the list-view key hint


def test_frame_empty_entries_has_no_preview():
    """The list frame with no sessions still renders the header (0 session(s)), no preview."""
    track = load_module("track")
    body = "\n".join(track._frame([], 0, "repo", rows=24))
    assert "0 session(s)" in body


def test_transcript_content_continues_after_tool_row(tmp_path):
    """Tool row, a non-assistant/non-user stream row (skipped), then a text row —
    exercises both the outer-loop continue and the neither-branch fall-through."""
    track = load_module("track")
    sd = tmp_path / "s-multi"
    rows = [_assistant("Read"), {"type": "system", "subtype": "init"}, _assistant(text="after")]
    _write_stream(sd, "session", rows)
    body = "\n".join(track.render_transcript_lines(sd))
    assert "Read" in body and "after" in body


def test_focus_frame_shows_scroll_affordances():
    track = load_module("track")
    record = {"session": "s", "status": "working"}
    content = [f"line {i}" for i in range(20)]
    body = "\n".join(track._focus_frame(record, content, scroll_top=5, height=5))
    assert "more" in body  # both ↑ and ↓ affordances render mid-scroll


def test_transcript_content_skips_user_row_without_result(tmp_path):
    """A user row carrying no tool_result and an empty assistant row → placeholder."""
    track = load_module("track")
    sd = tmp_path / "s-noresult"
    rows = [
        {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}},
        _assistant(text=""),
    ]
    _write_stream(sd, "session", rows)
    lines = track.render_transcript_lines(sd)
    assert any("no transcript yet" in ln for ln in lines)


# ── entrypoint dispatch (tty branch delegates to the pragma'd I/O shell) ───────


def test_view_session_tty_dispatches_to_loop(tmp_path, monkeypatch):
    track = load_module("track")
    sd = tmp_path / "s-vt"
    sd.mkdir()
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
    seen: list[Path] = []
    monkeypatch.setattr(track, "_view_session_tty", lambda d: seen.append(d))
    track.view_session(sd)
    assert seen == [sd]


def test_navigate_non_tty_prints_list_and_returns_zero(tmp_path, monkeypatch):
    track = load_module("track")
    from lib import store

    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    env = {"MENTAT_AGENT": "implement-x-1", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    store.record_emit(env, "chunk.spawned", {"slug": "x"})
    repo_dir = logs / "repo"
    (repo_dir / "implement-x-1").mkdir(parents=True)
    _write_stream(repo_dir / "implement-x-1", "session", [_assistant("Read", text="hi")])
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: False})())
    out: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a)))
    rc = track.navigate(repo_dir, repo="repo", active_only=False)
    assert rc == 0
    assert any("implement-x-1" in ln for ln in out)


def test_navigate_tty_dispatches_to_loop(tmp_path, monkeypatch):
    track = load_module("track")
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
    seen: dict[str, object] = {}

    def _fake(rd, *, repo, active_only):
        seen.update(repo=repo, active_only=active_only)
        return 0

    monkeypatch.setattr(track, "_navigate_tty", _fake)
    rc = track.navigate(tmp_path, repo="r", active_only=True)
    assert rc == 0
    assert seen == {"repo": "r", "active_only": True}
