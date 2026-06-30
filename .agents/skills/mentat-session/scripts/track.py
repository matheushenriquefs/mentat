"""Live event stream for a session (tail -f style) + multi-AFK navigator."""

from __future__ import annotations

import contextlib
import json
import os
import select
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import harness_stream as _hs  # noqa: E402
from lib import tui  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_sessions = load_sibling(__file__, "sessions")

_VIEW_TRANSCRIPT = "transcript"
_VIEW_AUDIT = "audit"

_COLORS = {
    "started": "\033[34m",  # blue
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
    """Truthful empty-state copy so `t` on a fresh/orchestrate session isn't mystifying.

    Audit empty + a known last lifecycle event → name it; audit empty + none → point
    at the transcript; transcript empty → it's an audit-only session. The last-event
    hint is audit-only (a transcript-view last_event never leaks into the message).
    """
    if view == _VIEW_AUDIT:
        if last_event:
            return f"(no audit rows here — last lifecycle: {last_event})"
        return "(no audit events yet — press t for the transcript)"
    return "(no transcript — audit-only session; press t for lifecycle)"


def _transcript_content(session_dir: Path, *, limit: int = 0) -> list[str]:
    """Transcript content lines (assistant text + tool calls + result summaries); [] if none.

    Reads all *.jsonl in session_dir, filters to harness stream rows (type-keyed,
    no event key); limit 0 = the full history (focus pane scrolls it), else tails.
    """
    rows: list[dict[str, object]] = []
    for f in sorted(session_dir.glob("*.jsonl")):
        rows.extend(_sessions.iter_rows(f))
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


def render_transcript_lines(session_dir: Path, *, limit: int = 0) -> list[str]:
    """Transcript view content, or a one-line placeholder when the session has no stream."""
    out = _transcript_content(session_dir, limit=limit)
    if not out:
        return [f"{tui.color(tui.PIPE, tui.DIM)} (no transcript yet)"]
    return out


def _audit_content(session_dir: Path, *, limit: int = 0) -> list[str]:
    """Audit envelope rows as 'ts event payload'; [] if the session has no audit log."""
    rows: list[dict[str, object]] = []
    for f in sorted(session_dir.glob("*.jsonl")):
        rows.extend(_sessions.iter_rows(f))
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


def render_audit_lines(session_dir: Path, *, limit: int = 0) -> list[str]:
    """Audit view content, or a one-line placeholder when the session has no audit log."""
    out = _audit_content(session_dir, limit=limit)
    if not out:
        return [f"{tui.color(tui.PIPE, tui.DIM)} (no audit events yet)"]
    return out


def view_session(session_dir: Path) -> None:
    """Show a session's transcript (default) or audit log; 't' toggles, 'q'/esc quits.

    Non-tty: print transcript once and return.
    """
    if not sys.stdin.isatty():
        for line in render_transcript_lines(session_dir):
            print(line)
        return
    _view_session_tty(session_dir)


def _view_session_tty(session_dir: Path) -> None:  # pragma: no cover - raw-tty I/O shell
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
            print(tui.section_rule(f"{session_dir.name} — {view}"))
            is_transcript = view == _VIEW_TRANSCRIPT
            lines = render_transcript_lines(session_dir) if is_transcript else render_audit_lines(session_dir)
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


# ── multi-AFK navigator ───────────────────────────────────────────────────────
# No push hooks → timer-poll the registry each tick. The pure parts below
# (keypress reducer + list/preview renderers) are gate-tested; `navigate` is the
# thin raw-tty/select I/O shell that wires them to the live filesystem.

POLL_SECS = 1.0  # registry re-scan cadence
PREVIEW_LINES = 20  # tool-calls tailed in the list-view preview pane
_FOCUS_OVERHEAD = 5  # header + 2 scroll affordances + blank + hint reserved around the focus window
_STATUS_COL = 8  # status column width in the list pane

# A registry entry: the status record paired with its absolute session dir.
# The dir is kept alongside (not stuffed into the record) so SessionRecord stays
# the pure registry contract and the navigator's preview/kill target is explicit.
Entry = tuple[dict[str, object], Path]


def _record_of(entry: object) -> dict[str, object]:
    """The status record of a registry element — a bare record or an (record, path) Entry."""
    return cast("dict[str, object]", entry[0] if isinstance(entry, tuple) else entry)


def resolve_focus_index(entries: Sequence[object], pinned_session: str | None, fallback: int | None) -> int | None:
    """Index of the record whose `session == pinned_session`, pinning focus to identity.

    Pure. The registry re-sorts by (rank, age) every tick, so a fixed integer index
    drifts onto a different session after a status flip — tracking the *name* instead
    keeps focus and the list cursor glued to the session the operator chose.

    `pinned_session is None` (nothing pinned yet) → `fallback`. Pinned but gone from
    the registry (reaped) → `None`, so the caller can drop focus / clamp the cursor.
    """
    if pinned_session is None:
        return fallback
    for i, e in enumerate(entries):
        if _record_of(e).get("session") == pinned_session:
            return i
    return None


def window_lines(all_lines: list[str], *, scroll_top: int | None, height: int) -> tuple[list[str], int, int]:
    """Slice the focus history into a viewport. Pure.

    `scroll_top is None` → follow the live tail (window the last `height`). An int →
    a frozen top-anchored view at that absolute line, clamped to [0, max(0, len-height)]
    so a growing tail doesn't shift the view while scrolled up and an out-of-range
    value never raises. Returns (visible, more_above, more_below) for the affordances.
    """
    total = len(all_lines)
    max_top = max(0, total - height)
    start = max_top if scroll_top is None else max(0, min(scroll_top, max_top))
    visible = all_lines[start : start + height]
    above = start
    below = max(0, total - (start + len(visible)))
    return visible, above, below


def scroll(scroll_top: int | None, delta: int, total: int, height: int) -> int | None:
    """Apply a scroll delta (j/k = ±1, d/u = ±height//2), clamped. Pure.

    Reaching the bottom returns `None` to re-arm tail-follow; otherwise a frozen
    absolute top. `scroll_top is None` means currently tailing (anchored at the bottom).
    """
    max_top = max(0, total - height)
    current = max_top if scroll_top is None else scroll_top
    new = max(0, min(current + delta, max_top))
    return None if new >= max_top else new


def handle_key(key: str, selected: int, count: int) -> tuple[int, str | None]:
    """Reduce one keypress to (new_selection, action). Pure — no I/O.

    Actions: "quit", "focus", "kill", or None. j/k (or arrows, mapped by the
    shell to "DOWN"/"UP") move the cursor, clamped to [0, count-1]. "focus"
    toggles the single-session zoom view in the shell.
    """
    if key in ("q", "\x1b"):
        return selected, "quit"
    if key in ("j", "DOWN"):
        return min(selected + 1, max(count - 1, 0)), None
    if key in ("k", "UP"):
        return max(selected - 1, 0), None
    if key in ("\n", "\r"):
        return selected, "focus"
    if key == "x":
        return selected, "kill"
    if key == "t":
        return selected, "toggle"
    return selected, None


def render_list(records: list[dict[str, object]], selected: int, *, viewport_height: int | None = None) -> list[str]:
    """List pane: one row per session, `>` on the selection, status dot + name + last event.

    When viewport_height is given, scrolls to keep the selected row visible and
    appends a '… N more' affordance when records are truncated at the bottom.
    """
    all_lines: list[str] = []
    for i, r in enumerate(records):
        cursor = ">" if i == selected else " "
        dot = tui.status_dot(str(r["status"]))
        last = r.get("last_event") or "-"
        age = _sessions._humanize_age(cast("float", r.get("age", 0.0)))
        all_lines.append(f"{cursor} {dot} {r['status']:<{_STATUS_COL}} {r['session']}  {age:>9}  {last}")

    if viewport_height is None or len(all_lines) <= viewport_height:
        return all_lines

    half = viewport_height // 2
    offset = max(0, min(selected - half, len(all_lines) - viewport_height))
    window = all_lines[offset : offset + viewport_height]
    remaining = len(all_lines) - (offset + viewport_height)
    if remaining > 0:
        # Replace the last row with the affordance so total stays within viewport_height.
        window[-1] = f"  … {remaining + 1} more"
    return window


def render_preview(tool_names: list[str]) -> list[str]:
    """Preview pane: the selected session's recent tool calls under a `│` gutter."""
    gutter = tui.color(tui.PIPE, tui.DIM)
    if not tool_names:
        return [f"{gutter} (no activity yet)"]
    return [f"{gutter} {tui.tool_glyph(n)} {n}" for n in tool_names]


def render_focus(record: dict[str, object], session_dir: Path, view: str = _VIEW_TRANSCRIPT) -> list[str]:
    """Focused single-session view: section rule + transcript or audit log, t-toggleable."""
    lines = [tui.section_rule(f"{record['session']} — {record['status']}")]
    if view == _VIEW_TRANSCRIPT:
        lines += render_transcript_lines(session_dir)
    else:
        lines += render_audit_lines(session_dir)
    lines.append("")
    lines.append(tui.color("t toggle · enter/esc back · x kill · q quit", tui.DIM))
    return lines


def _focus_frame(record: dict[str, object], content: list[str], *, scroll_top: int | None, height: int) -> list[str]:
    """Scroll-windowed focus frame: bold header, ↑/↓ affordances, the visible window, hint."""
    visible, above, below = window_lines(content, scroll_top=scroll_top, height=height)
    lines = [tui.color(tui.section_rule(f"{record['session']} — {record['status']}"), tui.BOLD)]
    if above:
        lines.append(tui.color(f"↑ {above} more", tui.DIM))
    lines += visible
    if below:
        lines.append(tui.color(f"↓ {below} more", tui.DIM))
    lines.append("")
    lines.append(tui.color("j/k·d/u scroll · t toggle · enter/esc back · x kill · q quit", tui.DIM))
    return lines


def _read_key(timeout: float, *, _fd: int | None = None) -> str | None:
    """One keypress from stdin within `timeout`s, or None on tick. Raw-tty shell only.

    Reads the whole available burst from the raw fd in one shot to avoid Python's
    buffered stdin splitting a multi-byte escape sequence (e.g. `\\x1b[A`) across
    calls — which made arrows return bare ESC (= quit) instead of UP/DOWN.

    `_fd` overrides the fd for testing (pass a pty slave fd).
    """
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
    except (UnicodeDecodeError, IndexError):
        return None


def _tools(session_dir: Path, *, limit: int) -> list[str]:
    return cast("list[str]", _sessions.session_stream_tools(session_dir, limit=limit))


def _selected(entries: list[Entry], selected: int) -> Entry:
    """The cursor's entry, clamped to range (callers guard `entries` non-empty)."""
    return entries[min(selected, len(entries) - 1)]


def _terminal_size() -> tuple[int, int]:
    """Live (cols, rows) from the stdout tty. Fallback (80, 20) when unknown.

    Reads the device directly via os.get_terminal_size, not shutil — shutil honors
    a stale COLUMNS/LINES env first, which would freeze the layout across a resize.
    """
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
        return size.columns, size.lines
    except OSError:
        return 80, 20


def _frame_fingerprint(lines: list[str], cols: int, rows: int) -> int:
    """Hash of the rendered frame + terminal size — repaint fires only when this changes.

    Size is part of the hash so a SIGWINCH resize repaints even when content is
    static (the fixed-width frame string alone wouldn't differ).
    """
    return hash((tuple(lines), cols, rows))


def _restore_seq() -> str:
    """Terminal-restore escapes: show the cursor and leave the alternate screen."""
    return tui.SHOW_CURSOR + tui.ALT_EXIT


def _frame(entries: list[Entry], selected: int, repo: str, *, rows: int) -> list[str]:
    """Build the list-view frame as a list of lines (no I/O) for the repaint engine.

    The focused single-session frame is built by `_focus_frame` in the navigate
    loop, which owns the scroll window.
    """
    records = [rec for rec, _ in entries]
    lines = [tui.section_rule(f"{repo} — {len(records)} session(s)")]
    overhead = 5  # section_rule + blank + preview-section_rule + blank + hint
    available = max(6, rows - overhead)
    preview_cap = min(PREVIEW_LINES, max(3, available // 2))
    list_viewport = max(3, available - preview_cap)
    lines += render_list(records, selected, viewport_height=list_viewport)
    if entries:
        record, session_dir = _selected(entries, selected)
        lines.append("")
        lines.append(tui.section_rule(str(record["session"])))
        lines += render_preview(_tools(session_dir, limit=preview_cap))
    lines.append("")
    lines.append(tui.color("j/k move · enter focus · x kill · q quit", tui.DIM))
    return lines


_TERMINATE = False


def _on_sigterm(signum: int, frame: object) -> None:
    """SIGTERM handler: set a flag only (signal-safe), the main loop exits and the
    `finally` restores the tty — so a kill never leaves it in cbreak / cursor hidden."""
    global _TERMINATE
    _TERMINATE = True


def navigate(repo_dir: Path, *, repo: str, active_only: bool = True) -> int:
    """Live multi-AFK navigator: timer-poll the registry, raw-tty key handling.

    Thin I/O shell over the gate-tested pure parts. Falls back to a one-shot list
    print when stdin is not a tty (CI / piped).
    """
    if not sys.stdin.isatty():
        entries = _registry(repo_dir, active_only=active_only)
        for line in render_list([rec for rec, _ in entries], 0):
            print(line)
        return 0
    return _navigate_tty(repo_dir, repo=repo, active_only=active_only)


def _navigate_tty(repo_dir: Path, *, repo: str, active_only: bool) -> int:  # pragma: no cover - raw-tty I/O shell
    """Live raw-tty navigator loop. The pure parts it drives (handle_key, scroll,
    resolve_focus_index, render_*, _frame_fingerprint) are gate-tested; this is the
    thin select/termios shell that can only run against a real terminal."""
    entries = _registry(repo_dir, active_only=active_only)
    import atexit
    import signal
    import termios
    import tty

    selected, focused, view = 0, False, _VIEW_TRANSCRIPT
    scroll_top: int | None = None  # None = follow tail; int = frozen absolute top
    # Pin the list cursor and (when zoomed) focus to the *session name*, not the
    # integer index a background re-sort keeps shuffling (flicker root cause A).
    cursor_session: str | None = str(entries[0][0]["session"]) if entries else None
    pinned: str | None = None
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    def _restore() -> None:
        sys.stdout.write(_restore_seq())
        sys.stdout.flush()

    global _TERMINATE
    _TERMINATE = False
    prev_sigterm = signal.signal(signal.SIGTERM, _on_sigterm)
    atexit.register(_restore)  # belt-and-suspenders if a hard exit skips `finally`
    last_fp: int | None = None
    try:
        tty.setcbreak(fd)
        sys.stdout.write(tui.ALT_ENTER + tui.HIDE_CURSOR)
        sys.stdout.flush()
        while True:
            cols, rows = _terminal_size()
            focus_content: list[str] = []
            focus_height = 0
            if focused and entries:
                record, session_dir = _selected(entries, selected)
                focus_content = (
                    _transcript_content(session_dir) if view == _VIEW_TRANSCRIPT else _audit_content(session_dir)
                )
                if not focus_content:
                    last = record.get("last_event")
                    hint = empty_hint(view, last if isinstance(last, str) else None)
                    focus_content = [tui.color(hint, tui.DIM)]
                focus_height = max(1, rows - _FOCUS_OVERHEAD)
                frame = _focus_frame(record, focus_content, scroll_top=scroll_top, height=focus_height)
            else:
                frame = _frame(entries, selected, repo, rows=rows)
            fp = _frame_fingerprint(frame, cols, rows)
            if fp != last_fp:
                # Repaint only when the visible frame (or terminal size) changed —
                # no per-tick full-clear blank-flash (flicker root cause B).
                sys.stdout.write(tui.paint(frame, rows=rows))
                sys.stdout.flush()
                last_fp = fp
            key = _read_key(POLL_SECS)
            if _TERMINATE:
                break
            if key is not None and focused:
                # Focus mode: j/k·d/u scroll, t toggles view (resetting scroll), enter/esc
                # backs out, x kills, q quits.
                total = len(focus_content)
                if key == "q":
                    break
                if key in ("\n", "\r", "\x1b"):
                    focused, pinned, scroll_top = False, None, None
                elif key == "t":
                    view, scroll_top = toggle_view(view), None
                elif key == "x" and entries:
                    _kill(_selected(entries, selected)[1])
                elif key in ("j", "DOWN"):
                    scroll_top = scroll(scroll_top, 1, total, focus_height)
                elif key in ("k", "UP"):
                    scroll_top = scroll(scroll_top, -1, total, focus_height)
                elif key == "d":
                    scroll_top = scroll(scroll_top, focus_height // 2, total, focus_height)
                elif key == "u":
                    scroll_top = scroll(scroll_top, -(focus_height // 2), total, focus_height)
            elif key is not None:
                selected, action = handle_key(key, selected, len(entries))
                if entries:
                    cursor_session = str(_selected(entries, selected)[0]["session"])
                if action == "quit":
                    break
                if action == "focus" and entries:
                    focused, scroll_top = True, None
                    pinned = str(_selected(entries, selected)[0]["session"])
                if action == "toggle":
                    view = toggle_view(view)
                if action == "kill" and entries:
                    _kill(_selected(entries, selected)[1])
            entries = _registry(repo_dir, active_only=active_only)
            # Re-resolve the cursor against the freshly re-sorted registry; if its
            # session was reaped, clamp to the old slot.
            cursor_idx = resolve_focus_index(entries, cursor_session, None)
            selected = cursor_idx if cursor_idx is not None else min(selected, max(len(entries) - 1, 0))
            cursor_session = str(_selected(entries, selected)[0]["session"]) if entries else None
            # Re-resolve focus the same way; a reaped focus session drops the zoom.
            if focused:
                focus_idx = resolve_focus_index(entries, pinned, None)
                if focus_idx is None:
                    focused, pinned, scroll_top = False, None, None
                else:
                    selected, cursor_session = focus_idx, pinned
            if not entries:
                focused, scroll_top = False, None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        signal.signal(signal.SIGTERM, prev_sigterm)
        sys.stdout.write(_restore_seq())
        sys.stdout.flush()
        atexit.unregister(_restore)
    return 0


def _registry(repo_dir: Path, *, active_only: bool = True) -> list[Entry]:
    """Registry status records paired with each session's absolute dir (for preview/kill)."""
    rows = cast("list[dict[str, object]]", _sessions.list_sessions(repo_dir, active_only=active_only))
    return [(r, repo_dir / str(r["session"])) for r in rows]


def _kill(session_dir: Path) -> None:
    """Best-effort teardown of the selected session's worktree (kill bind).

    Reads the worktree path from the session's spawn audit and removes it via git.
    Best-effort: a missing worktree or git error is swallowed so the navigator
    survives and re-emits the list. `--` separates the path so a worktree string
    starting with `-` can't be parsed as a git option.
    """
    worktree = _sessions.session_worktree(session_dir)
    if not isinstance(worktree, str) or not worktree:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "worktree", "remove", "--force", "--", worktree],
            check=False,
            capture_output=True,
        )
