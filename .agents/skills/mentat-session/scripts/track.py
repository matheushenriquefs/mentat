"""Live event stream for a session (tail -f style) + multi-AFK navigator."""

from __future__ import annotations

import contextlib
import json
import os
import select
import subprocess
import sys
import time
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


def _is_tty() -> bool:
    return sys.stdout.isatty()


def stream(session_dir: Path, *, follow: bool = True, use_color: bool | None = None) -> None:
    color = _is_tty() if use_color is None else use_color

    seen_files: dict[Path, int] = {}
    end_time = time.time() + (60 if follow else 0)

    while True:
        for log_file in sorted(session_dir.glob("*.jsonl")):
            offset = seen_files.get(log_file, 0)
            with log_file.open() as f:
                f.seek(offset)
                content = f.read()
                seen_files[log_file] = f.tell()
            for row in _sessions.iter_rows_from_text(content):
                event = row.get("event", "")
                c = _color_for_event(event) if color else ""
                reset = _RESET if color else ""
                payload = json.dumps(row.get("payload", {}))
                print(f"{c}{row.get('ts', '')} [{row.get('agent', '')}] {event} {payload}{reset}")

        if not follow or time.time() > end_time:
            break
        time.sleep(0.1)


# ── dual-stream log renderer ─────────────────────────────────────────────────


def toggle_view(view: str) -> str:
    """Pure: flip between transcript and audit views."""
    return _VIEW_AUDIT if view == _VIEW_TRANSCRIPT else _VIEW_TRANSCRIPT


def render_transcript_lines(session_dir: Path, *, limit: int = 0) -> list[str]:
    """Transcript view: assistant text + tool_glyph calls + result summaries, newest tail.

    Reads all *.jsonl in session_dir, filters to harness stream rows (type-keyed,
    no event key), takes the last `limit` rows (0 = FOCUS_LINES), renders chat.
    """
    rows: list[dict[str, object]] = []
    for f in sorted(session_dir.glob("*.jsonl")):
        rows.extend(_sessions.iter_rows(f))
    stream_rows = [r for r in rows if "type" in r and "event" not in r]
    cap = limit or FOCUS_LINES
    tail = stream_rows[-cap:]
    gutter = tui.color(tui.PIPE, tui.DIM)
    out: list[str] = []
    for row in tail:
        row_type = row.get("type")
        if row_type == "assistant":
            text = _hs.assistant_text(row)
            tools = _hs.tool_uses(row)
            if text.strip():
                for line in text.splitlines():
                    out.append(f"{gutter} {line[:200]}")
            for name in tools:
                out.append(f"{gutter} {tui.tool_glyph(name)} {name}")
        elif row_type == "user":
            result = _hs.tool_result(row)
            if result:
                out.append(f"{gutter}  └ {result[:200]}")
    if not out:
        out = [f"{gutter} (no transcript yet)"]
    return out


def render_audit_lines(session_dir: Path, *, limit: int = 0) -> list[str]:
    """Audit view: envelope rows (event key) as 'ts event payload', newest tail."""
    rows: list[dict[str, object]] = []
    for f in sorted(session_dir.glob("*.jsonl")):
        rows.extend(_sessions.iter_rows(f))
    audit_rows = [r for r in rows if "event" in r]
    cap = limit or FOCUS_LINES
    tail = audit_rows[-cap:]
    gutter = tui.color(tui.PIPE, tui.DIM)
    out: list[str] = []
    for row in tail:
        ts = str(row.get("ts", ""))[-19:]
        event = row.get("event", "?")
        payload = json.dumps(row.get("payload", {}))
        out.append(f"{gutter} {ts} {event} {payload[:100]}")
    if not out:
        out = [f"{gutter} (no audit events yet)"]
    return out


def view_session(session_dir: Path) -> None:
    """Show a session's transcript (default) or audit log; 't' toggles, 'q'/esc quits.

    Non-tty: print transcript once and return.
    """
    if not sys.stdin.isatty():
        for line in render_transcript_lines(session_dir):
            print(line)
        return

    import termios
    import tty as _tty

    view = _VIEW_TRANSCRIPT
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        _tty.setcbreak(fd)
        while True:
            sys.stdout.write(tui.CLEAR_HOME)
            label = view
            print(tui.section_rule(f"{session_dir.name} — {label}"))
            if view == _VIEW_TRANSCRIPT:
                lines = render_transcript_lines(session_dir)
            else:
                lines = render_audit_lines(session_dir)
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
FOCUS_LINES = 40  # tool-calls tailed in the focused single-session view
_STATUS_COL = 8  # status column width in the list pane

# A registry entry: the status record paired with its absolute session dir.
# The dir is kept alongside (not stuffed into the record) so SessionRecord stays
# the pure registry contract and the navigator's preview/kill target is explicit.
Entry = tuple[dict[str, object], Path]


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
        all_lines.append(f"{cursor} {dot} {r['status']:<{_STATUS_COL}} {r['session']}  {last}")

    if viewport_height is None or len(all_lines) <= viewport_height:
        return all_lines

    half = viewport_height // 2
    offset = max(0, min(selected - half, len(all_lines) - viewport_height))
    window = all_lines[offset : offset + viewport_height]
    remaining = len(all_lines) - (offset + viewport_height)
    if remaining > 0:
        window.append(f"  … {remaining} more")
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


def _terminal_height() -> int:
    """Terminal row count (fallback 20 when unknown)."""
    try:
        import shutil

        return shutil.get_terminal_size((80, 20)).lines
    except Exception:
        return 20


def _draw(entries: list[Entry], selected: int, repo: str, *, focused: bool, view: str = _VIEW_TRANSCRIPT) -> None:
    sys.stdout.write(tui.CLEAR_HOME)
    if focused and entries:
        record, session_dir = _selected(entries, selected)
        for line in render_focus(record, session_dir, view):
            print(line)
        sys.stdout.flush()
        return
    records = [rec for rec, _ in entries]
    print(tui.section_rule(f"{repo} — {len(records)} session(s)"))
    h = _terminal_height()
    list_viewport = max(5, h - PREVIEW_LINES - 5)
    for line in render_list(records, selected, viewport_height=list_viewport):
        print(line)
    if entries:
        record, session_dir = _selected(entries, selected)
        print()
        print(tui.section_rule(str(record["session"])))
        for line in render_preview(_tools(session_dir, limit=PREVIEW_LINES)):
            print(line)
    print()
    print(tui.color("j/k move · enter focus · x kill · q quit", tui.DIM))
    sys.stdout.flush()


def navigate(repo_dir: Path, *, repo: str, active_only: bool = True) -> int:
    """Live multi-AFK navigator: timer-poll the registry, raw-tty key handling.

    Thin I/O shell over the gate-tested pure parts. Falls back to a one-shot list
    print when stdin is not a tty (CI / piped).
    """
    entries = _registry(repo_dir, active_only=active_only)
    if not sys.stdin.isatty():
        for line in render_list([rec for rec, _ in entries], 0):
            print(line)
        return 0

    import termios
    import tty

    selected, focused, view = 0, False, _VIEW_TRANSCRIPT
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            _draw(entries, selected, repo, focused=focused, view=view)
            key = _read_key(POLL_SECS)
            if key is not None:
                selected, action = handle_key(key, selected, len(entries))
                if action == "quit":
                    break
                if action == "focus" and entries:
                    focused = not focused
                if action == "toggle":
                    view = toggle_view(view)
                if action == "kill" and entries:
                    _kill(_selected(entries, selected)[1])
            entries = _registry(repo_dir, active_only=active_only)
            selected = min(selected, max(len(entries) - 1, 0))
            if not entries:
                focused = False
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(tui.CLEAR_HOME)
        sys.stdout.flush()
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
