"""Live event stream for a session (tail -f style) + multi-AFK navigator (S7)."""

from __future__ import annotations

import contextlib
import json
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import tui  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_sessions = load_sibling(__file__, "sessions")

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


# ── multi-AFK navigator (S7) ──────────────────────────────────────────────────
# No push hooks → timer-poll the S6 registry each tick. The pure parts below
# (keypress reducer + list/preview renderers) are gate-tested; `navigate` is the
# thin raw-tty/select I/O shell that wires them to the live filesystem.

POLL_SECS = 1.0  # registry re-scan cadence
PREVIEW_LINES = 20  # tool-calls tailed in the list-view preview pane
FOCUS_LINES = 40  # tool-calls tailed in the focused single-session view
_STATUS_COL = 8  # status column width in the list pane

# A registry entry: the S6 status record paired with its absolute session dir.
# The dir is kept alongside (not stuffed into the record) so SessionRecord stays
# the pure S6 contract and the navigator's preview/kill target is explicit.
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
    return selected, None


def render_list(records: list[dict[str, object]], selected: int) -> list[str]:
    """List pane: one row per session, `>` on the selection, status dot + name + last event."""
    out: list[str] = []
    for i, r in enumerate(records):
        cursor = ">" if i == selected else " "
        dot = tui.status_dot(str(r["status"]))
        last = r.get("last_event") or "-"
        out.append(f"{cursor} {dot} {r['status']:<{_STATUS_COL}} {r['session']}  {last}")
    return out


def render_preview(tool_names: list[str]) -> list[str]:
    """Preview pane: the selected session's recent tool calls under a `│` gutter."""
    gutter = tui.color(tui.PIPE, tui.DIM)
    if not tool_names:
        return [f"{gutter} (no activity yet)"]
    return [f"{gutter} {tui.tool_glyph(n)} {n}" for n in tool_names]


def render_focus(record: dict[str, object], tool_names: list[str]) -> list[str]:
    """Focused single-session view: the `── [session] ──` rule + a deeper tool tail."""
    lines = [tui.section_rule(f"{record['session']} — {record['status']}")]
    lines += render_preview(tool_names)
    lines.append("")
    lines.append(tui.color("enter/esc back · x kill · q quit", tui.DIM))
    return lines


def _read_key(timeout: float) -> str | None:
    """One keypress from stdin within `timeout`s, or None on tick. Raw-tty shell only.

    A bare ESC (no follow byte) is quit; a recognized arrow maps to UP/DOWN; any
    other escape sequence is fully drained and swallowed (None) so its trailing
    bytes don't leak into the next read as spurious keystrokes.
    """
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    ch = sys.stdin.read(1)
    if ch != "\x1b":
        return ch
    seq = ""
    while True:  # consume the whole sequence that arrived with the ESC
        more, _, _ = select.select([sys.stdin], [], [], 0.01)
        if not more:
            break
        seq += sys.stdin.read(1)
    if not seq:
        return "\x1b"  # bare ESC → quit
    return {"[A": "UP", "[B": "DOWN"}.get(seq)  # arrow → UP/DOWN; anything else → None


def _tools(session_dir: Path, *, limit: int) -> list[str]:
    return cast("list[str]", _sessions.session_stream_tools(session_dir, limit=limit))


def _selected(entries: list[Entry], selected: int) -> Entry:
    """The cursor's entry, clamped to range (callers guard `entries` non-empty)."""
    return entries[min(selected, len(entries) - 1)]


def _draw(entries: list[Entry], selected: int, repo: str, *, focused: bool) -> None:
    sys.stdout.write(tui.CLEAR_HOME)
    if focused and entries:
        record, session_dir = _selected(entries, selected)
        for line in render_focus(record, _tools(session_dir, limit=FOCUS_LINES)):
            print(line)
        sys.stdout.flush()
        return
    records = [rec for rec, _ in entries]
    print(tui.section_rule(f"{repo} — {len(records)} session(s)"))
    for line in render_list(records, selected):
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


def navigate(repo_dir: Path, *, repo: str) -> int:
    """Live multi-AFK navigator: timer-poll the registry, raw-tty key handling.

    Thin I/O shell over the gate-tested pure parts. Falls back to a one-shot list
    print when stdin is not a tty (CI / piped).
    """
    entries = _registry(repo_dir)
    if not sys.stdin.isatty():
        for line in render_list([rec for rec, _ in entries], 0):
            print(line)
        return 0

    import termios
    import tty

    selected, focused = 0, False
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            _draw(entries, selected, repo, focused=focused)
            key = _read_key(POLL_SECS)
            if key is not None:
                selected, action = handle_key(key, selected, len(entries))
                if action == "quit":
                    break
                if action == "focus" and entries:
                    focused = not focused
                if action == "kill" and entries:
                    _kill(_selected(entries, selected)[1])
            entries = _registry(repo_dir)
            selected = min(selected, max(len(entries) - 1, 0))
            if not entries:
                focused = False
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(tui.CLEAR_HOME)
        sys.stdout.flush()
    return 0


def _registry(repo_dir: Path) -> list[Entry]:
    """Registry status records paired with each session's absolute dir (for preview/kill)."""
    rows = cast("list[dict[str, object]]", _sessions.list_sessions(repo_dir))
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
