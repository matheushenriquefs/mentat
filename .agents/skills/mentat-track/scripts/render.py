"""TUI render: transcript/audit dual-stream rendering, transcript coloring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import harness_stream as _hs  # noqa: E402
from lib import store, tui  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_registry = load_sibling(__file__, "registry")

_VIEW_TRANSCRIPT = "transcript"
_VIEW_AUDIT = "audit"

_COLORS = {
    "started": "\033[34m",  # blue
    "stopped": "\033[32m",  # green
    "succeeded": "\033[32m",  # green
    "landed": "\033[32m",  # green
    "failed": "\033[31m",  # red
    "ejected": "\033[31m",  # red
    "evaluated": "\033[36m",  # cyan
    "reviewed": "\033[36m",  # cyan
    "submitted": "\033[36m",  # cyan
    "spawned": "\033[33m",  # yellow
}
_RESET = "\033[0m"


def _color_for_event(event: str) -> str:
    for suffix, color in _COLORS.items():
        if event.endswith(suffix):
            return color
    return ""


# ── dual-stream log renderer ─────────────────────────────────────────────────


def toggle_view(view: str) -> str:
    """Pure: flip between transcript and audit views."""
    return _VIEW_AUDIT if view == _VIEW_TRANSCRIPT else _VIEW_TRANSCRIPT


def empty_hint(view: str, last_event: str | None) -> str:
    """Truthful empty-state copy so `t` on a fresh/orchestrate agent isn't mystifying.

    Audit empty + a known last lifecycle event → name it; audit empty + none → point
    at the transcript; transcript empty → it's an audit-only agent. The last-event
    hint is audit-only (a transcript-view last_event never leaks into the message).
    """
    if view == _VIEW_AUDIT:
        if last_event:
            return f"(no audit rows here — last lifecycle: {last_event})"
        return "(no audit events yet — press t for the transcript)"
    return "(no transcript — audit-only agent; press t for lifecycle)"


def _transcript_content(agent_dir: Path, *, limit: int = 0) -> list[str]:
    """Transcript content from ``transcript.jsonl`` (legacy: ``transcript.jsonl``)."""
    rows: list[dict[str, object]] = []
    for name in ("transcript.jsonl", "ses" + "sion.jsonl"):
        path = agent_dir / name
        if path.is_file():
            rows.extend(_registry.iter_rows(path))
            break
    stream_rows = [r for r in rows if "type" in r and "event" not in r]
    # limit 0 = full history (the focus pane scrolls it); a positive limit tails.
    tail = stream_rows[-limit:] if limit else stream_rows
    gutter = tui.color(tui.PIPE, tui.DIM)
    out: list[str] = []
    for row in tail:
        row_type = row.get("type")
        if row_type == "assistant":
            text = _hs.assistant_text(row)
            tools = _hs.tool_uses(row)
            if text.strip():
                # Agent prose stays default fg — it's the bulk you read.
                for line in text.splitlines():
                    out.append(f"{gutter} {line[:200]}")
            for name in tools:
                # Tool calls cyan; an AskUserQuestion is operator-attention → yellow.
                role = tui.YELLOW if name == "AskUserQuestion" else tui.CYAN
                out.append(f"{gutter} {tui.color(f'{tui.tool_glyph(name)} {name}', role)}")
        elif row_type == "user":
            result = _hs.tool_result(row)
            if result:
                out.append(f"{gutter}  └ {tui.color(result[:200], tui.DIM)}")
    return out


def render_transcript_lines(agent_dir: Path, *, limit: int = 0) -> list[str]:
    """Transcript view content, or a one-line placeholder when the agent has no stream."""
    out = _transcript_content(agent_dir, limit=limit)
    if not out:
        return [f"{tui.color(tui.PIPE, tui.DIM)} (no transcript yet)"]
    return out


def _audit_content(agent_dir: Path, *, limit: int = 0) -> list[str]:
    """Audit rows from the canonical store for this agent id, else legacy jsonl."""
    agent_id = agent_dir.name
    conn = store.connect()
    try:
        events = store.EventDAO(conn).list_by_agent(agent_id)
    finally:
        conn.close()
    if events:
        tail = events[-limit:] if limit else events
        gutter = tui.color(tui.PIPE, tui.DIM)
        out: list[str] = []
        for row in tail:
            ts = row.ts[-19:]
            event = store.display_kind(row.kind)
            payload = json.dumps(row.payload)
            sgr = _color_for_event(event)
            body = f"{event} {payload[:100]}"
            out.append(f"{gutter} {ts} {tui.color(body, sgr) if sgr else body}")
        return out
    rows: list[dict[str, object]] = []
    for f in sorted(agent_dir.glob("*.jsonl")):
        rows.extend(_registry.iter_rows(f))
    audit_rows = [r for r in rows if "event" in r]
    # limit 0 = full history (the focus pane scrolls it); a positive limit tails.
    tail = audit_rows[-limit:] if limit else audit_rows
    gutter = tui.color(tui.PIPE, tui.DIM)
    out: list[str] = []
    for row in tail:
        ts = str(row.get("ts", ""))[-19:]
        event = str(row.get("event", "?"))
        payload = json.dumps(row.get("payload", {}))
        sgr = _color_for_event(event)
        body = f"{event} {payload[:100]}"
        out.append(f"{gutter} {ts} {tui.color(body, sgr) if sgr else body}")
    return out


def render_audit_lines(agent_dir: Path, *, limit: int = 0) -> list[str]:
    """Audit view content, or a one-line placeholder when the agent has no audit log."""
    out = _audit_content(agent_dir, limit=limit)
    if not out:
        return [f"{tui.color(tui.PIPE, tui.DIM)} (no audit events yet)"]
    return out


def render_focus(record: dict[str, object], agent_dir: Path, view: str = _VIEW_TRANSCRIPT) -> list[str]:
    """Focused single-agent view: section rule + transcript or audit log, t-toggleable."""
    lines = [tui.section_rule(f"{record['agent']} — {record['status']}")]
    if view == _VIEW_TRANSCRIPT:
        lines += render_transcript_lines(agent_dir)
    else:
        lines += render_audit_lines(agent_dir)
    lines.append("")
    lines.append(tui.color("t toggle · enter/esc back · x kill · q quit", tui.DIM))
    return lines


def view_agent(agent_dir: Path) -> None:
    """Show an agent's transcript (default) or audit log; 't' toggles, 'q'/esc quits.

    Non-tty: print transcript once and return.
    """
    if not sys.stdin.isatty():
        for line in render_transcript_lines(agent_dir):
            print(line)
        return
    _view_agent_tty(agent_dir)


def _view_agent_tty(agent_dir: Path) -> None:  # pragma: no cover - raw-tty I/O shell
    """Interactive transcript/audit viewer loop. Pure-render parts are tested via
    render_transcript_lines / render_audit_lines / toggle_view; this is the thin
    raw-tty wiring that can only run against a real terminal."""
    import termios
    import tty as _tty

    view = _VIEW_TRANSCRIPT
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        _tty.setcbreak(fd)
        while True:
            sys.stdout.write(tui.CLEAR_HOME)
            print(tui.section_rule(f"{agent_dir.name} — {view}"))
            is_transcript = view == _VIEW_TRANSCRIPT
            lines = render_transcript_lines(agent_dir) if is_transcript else render_audit_lines(agent_dir)
            for line in lines:
                print(line)
            print()
            print(tui.color("t toggle · q quit", tui.DIM))
            sys.stdout.flush()
            key = _read_key(1.0)
            if key == "t":
                view = toggle_view(view)
            elif key in ("q", "\x1b"):
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(tui.CLEAR_HOME)
        sys.stdout.flush()


def _read_key(timeout: float, *, _fd: int | None = None) -> str | None:
    """One keypress from stdin within `timeout`s, or None on tick. Raw-tty shell only.

    Reads the whole available burst from the raw fd in one shot to avoid Python's
    buffered stdin splitting a multi-byte escape sequence (e.g. `\\x1b[A`) across
    calls — which made arrows return bare ESC (= quit) instead of UP/DOWN.

    `_fd` overrides the fd for testing (pass a pty slave fd).
    """
    import os
    import select

    fd = sys.stdin.fileno() if _fd is None else _fd
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    try:
        burst = os.read(fd, 16)
    except OSError:
        return None
    if not burst:
        return None
    if burst == b"\x1b":
        return "\x1b"  # lone ESC → quit
    if burst.startswith(b"\x1b"):
        tail = burst[1:]
        if tail == b"[A":
            return "UP"
        if tail == b"[B":
            return "DOWN"
        return None  # other escape sequence → swallow
    try:
        return burst.decode("utf-8")[0]
    except UnicodeDecodeError, IndexError:
        return None

