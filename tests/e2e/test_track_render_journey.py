"""E2E journey: the track navigator's pure render + reduce layer.

``track``'s raw-tty loops (``_navigate_tty`` / ``_view_session_tty``) are
``# pragma: no cover`` I/O shells; everything they drive — the transcript/audit
renderers, the keypress reducer, the scroll/window math, the focus-index pin, the
list/preview/focus frame builders, and the sqlite-backed registry + kill bind —
is pure and exercised here against real on-disk session dirs. Non-tty stdin (the
pytest default) also drives the one-shot fallbacks of ``view_session`` /
``navigate``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

TRACK_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-track/scripts/track.py"
SCRIPTS = TRACK_PY.parent


class _TrackFacade:
    """Delegate to track/render/panes modules after the track-module split."""

    def __init__(self) -> None:
        self._track = load_script(TRACK_PY, "e2e_track")
        self._render = load_script(SCRIPTS / "render.py", "e2e_render")
        self._panes = load_script(SCRIPTS / "panes.py", "e2e_panes")

    def __setattr__(self, name: str, value) -> None:
        if name in ("_track", "_render", "_panes"):
            super().__setattr__(name, value)
            return
        for mod in (self._panes, self._render, self._track):
            if hasattr(mod, name):
                setattr(mod, name, value)
                return
        super().__setattr__(name, value)

    def __getattr__(self, name: str):
        for mod in (self._panes, self._render, self._track):
            if hasattr(mod, name):
                return getattr(mod, name)
        raise AttributeError(name)


def _track() -> _TrackFacade:
    return _TrackFacade()


def _assistant(*tool_names: str, text: str = "") -> dict:
    blocks: list[dict] = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks += [{"type": "tool_use", "name": n} for n in tool_names]
    return {"type": "assistant", "message": {"content": blocks}}


def _user_result(content: str = "ok") -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": content}]}}


def _audit(event: str, **payload) -> dict:
    return {"ts": "2026-07-01T12:00:00+00:00", "event": event, "payload": payload}


def _write(session_dir: Path, name: str, rows: list[dict]) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


# ── pure reducers: toggle / empty-hint / color ────────────────────────────────


def test_toggle_and_empty_hint_and_color():
    m = _track()
    assert m.toggle_view(m._VIEW_TRANSCRIPT) == m._VIEW_AUDIT
    assert m.toggle_view(m._VIEW_AUDIT) == m._VIEW_TRANSCRIPT

    assert "last lifecycle: chunk_landed" in m.empty_hint(m._VIEW_AUDIT, "chunk_landed")
    assert "no audit events yet" in m.empty_hint(m._VIEW_AUDIT, None)
    assert "audit-only session" in m.empty_hint(m._VIEW_TRANSCRIPT, None)

    assert m._color_for_event("chunk_landed") == m._COLORS["landed"]
    assert m._color_for_event("nothing.matches") == ""


# ── transcript + audit renderers, with placeholders ───────────────────────────


def test_transcript_and_audit_renderers(tmp_path):
    m = _track()
    sd = tmp_path / "sess"
    _write(
        sd,
        "session",
        [
            _assistant("Read", text="hello world"),
            _user_result("done"),
            _assistant("AskUserQuestion"),  # operator-attention tool → yellow branch
            _audit("chunk_started", slug="a"),
            _audit("chunk_landed", slug="a", sha="abc"),
        ],
    )

    transcript = m.render_transcript_lines(sd)
    assert any("hello world" in line for line in transcript)
    assert any("Read" in line for line in transcript)
    assert any("done" in line for line in transcript)

    audit = m.render_audit_lines(sd)
    assert any("chunk_started" in line for line in audit)
    assert any("chunk_landed" in line for line in audit)

    # limit tails to the last N.
    assert len(m._audit_content(sd, limit=1)) == 1

    # Placeholders on an empty dir.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "no transcript yet" in m.render_transcript_lines(empty)[0]
    assert "no audit events yet" in m.render_audit_lines(empty)[0]


def test_view_session_non_tty_prints_transcript(tmp_path, capsys):
    m = _track()
    sd = tmp_path / "sess"
    _write(sd, "session", [_assistant("Read", text="hi")])
    m.view_agent(sd)  # non-tty stdin → one-shot transcript print
    assert "hi" in capsys.readouterr().out


# ── focus-index pin + scroll/window math ──────────────────────────────────────


def test_resolve_focus_index():
    m = _track()
    entries = [({"session": "a"}, Path("/a")), ({"session": "b"}, Path("/b"))]
    assert m.resolve_focus_index(entries, None, 7) == 7  # nothing pinned → fallback
    assert m.resolve_focus_index(entries, "b", None) == 1  # pinned → its index
    assert m.resolve_focus_index(entries, "gone", None) is None  # reaped → None


def test_window_lines_tail_and_frozen():
    m = _track()
    lines = [str(i) for i in range(10)]
    visible, above, below = m.window_lines(lines, scroll_top=None, height=3)
    assert visible == ["7", "8", "9"] and above == 7 and below == 0

    visible, above, below = m.window_lines(lines, scroll_top=2, height=3)
    assert visible == ["2", "3", "4"] and above == 2 and below == 5

    # Out-of-range scroll_top is clamped, never raises.
    visible, _a, below = m.window_lines(lines, scroll_top=999, height=3)
    assert visible == ["7", "8", "9"] and below == 0


def test_scroll_clamps_and_rearms_tail():
    m = _track()
    # From the bottom (None), scrolling up freezes an absolute top.
    assert m.scroll(None, -1, 10, 3) == 6
    # Reaching the bottom returns None to re-arm tail-follow.
    assert m.scroll(6, 1, 10, 3) is None
    # Never below 0.
    assert m.scroll(0, -5, 10, 3) == 0


# ── keypress reducer ──────────────────────────────────────────────────────────


def test_handle_key_all_actions():
    m = _track()
    assert m.handle_key("q", 0, 3) == (0, "quit")
    assert m.handle_key("\x1b", 0, 3) == (0, "quit")
    assert m.handle_key("j", 0, 3) == (1, None)
    assert m.handle_key("DOWN", 2, 3) == (2, None)  # clamped to count-1
    assert m.handle_key("k", 2, 3) == (1, None)
    assert m.handle_key("UP", 0, 3) == (0, None)  # clamped to 0
    assert m.handle_key("\n", 1, 3) == (1, "focus")
    assert m.handle_key("x", 1, 3) == (1, "kill")
    assert m.handle_key("t", 1, 3) == (1, "toggle")
    assert m.handle_key("?", 1, 3) == (1, None)  # unknown → noop
    assert m.handle_key("j", 0, 0) == (0, None)  # empty list stays put


# ── list / preview / focus frame builders ─────────────────────────────────────


def _records(n: int) -> list[dict]:
    return [{"session": f"s{i}", "status": "running", "last_event": "chunk_started", "age": 1.0 * i} for i in range(n)]


def test_render_list_selection_viewport_and_affordance():
    m = _track()
    recs = _records(3)
    lines = m.render_list(recs, 1)
    assert lines[1].startswith(">"), "selected row is marked"
    assert lines[0].startswith(" ")

    # No viewport / fits → all rows.
    assert len(m.render_list(recs, 0, viewport_height=10)) == 3

    # Truncated → last row becomes a '… N more' affordance, total == viewport.
    many = m.render_list(_records(20), 0, viewport_height=5)
    assert len(many) == 5
    assert "more" in many[-1]


def test_render_preview_and_focus_and_frame(tmp_path):
    m = _track()
    assert "no activity yet" in m.render_preview([])[0]
    assert any("Read" in line for line in m.render_preview(["Read", "Edit"]))

    sd = tmp_path / "sess"
    _write(sd, "session", [_assistant("Read", text="body"), _audit("chunk_landed", slug="a")])
    rec = {"session": "sess", "status": "running"}

    focus_t = m.render_focus(rec, sd, m._VIEW_TRANSCRIPT)
    assert any("body" in line for line in focus_t)
    focus_a = m.render_focus(rec, sd, m._VIEW_AUDIT)
    assert any("chunk_landed" in line for line in focus_a)

    # _focus_frame surfaces the ↑/↓ affordances when scrolled into a tall history.
    tall = [f"line {i}" for i in range(30)]
    frame = m._focus_frame(rec, tall, scroll_top=5, height=5)
    assert any("more" in line for line in frame)


def test_frame_fingerprint_restore_and_sigterm():
    m = _track()
    fp1 = m._frame_fingerprint(["a", "b"], 80, 24)
    assert fp1 == m._frame_fingerprint(["a", "b"], 80, 24)
    assert fp1 != m._frame_fingerprint(["a", "b"], 100, 24)  # size is part of the hash
    assert m.tui.SHOW_CURSOR in m._restore_seq()

    m._TERMINATE = False
    m._on_sigterm(15, None)
    assert m._TERMINATE is True
    m._TERMINATE = False


# ── registry-backed frame + navigate fallback + kill bind ─────────────────────


def test_registry_frame_navigate_and_kill(tmp_path, monkeypatch, capsys):
    m = _track()
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))

    repo_dir = logs / "myrepo"
    repo_dir.mkdir(parents=True)
    env = {"MENTAT_AGENT": "s1", "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"}
    from lib import store

    store.record_emit(env, "chunk_started", {"slug": "x", "worktree": "/tmp/wt-s1"})
    (repo_dir / "s1").mkdir()

    entries = m._registry(repo_dir)
    assert entries and entries[0][0]["session"] == "s1"
    assert entries[0][1] == repo_dir / "s1"

    frame = m._frame(entries, 0, "myrepo", rows=24)
    assert any("session(s)" in line for line in frame)
    assert m._selected(entries, 99)[0]["session"] == "s1"  # clamped

    (cols, rows) = m._terminal_size()  # falls back to (80, 20) with no tty
    assert cols > 0 and rows > 0

    # navigate() with non-tty stdin → one-shot list print.
    assert m.navigate(repo_dir, repo="myrepo") == 0
    assert "s1" in capsys.readouterr().out

    # _kill reads the worktree from the spawn audit and shells out to git (stubbed).
    sd = repo_dir / "s1"
    _write(sd, "session", [_audit("chunk_started", slug="s1", worktree="/tmp/wt-s1")])
    calls: list = []
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    m._kill(sd)
    assert calls and "/tmp/wt-s1" in calls[0]

    # A session with no worktree in its audit → kill is a no-op.
    sd2 = repo_dir / "s2"
    _write(sd2, "session", [_audit("chunk_started", slug="s2")])
    calls.clear()
    m._kill(sd2)
    assert calls == []
