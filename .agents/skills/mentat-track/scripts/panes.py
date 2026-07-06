"""Multi-AFK navigator: pane layout, viewport windowing, keypress reducer.

No push hooks → timer-poll the registry each tick. The pure parts below
(keypress reducer + list/preview renderers) are gate-tested; `navigate` is the
thin raw-tty/select I/O shell that wires them to the live filesystem.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import store, tui  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_render = load_sibling(__file__, "render")
_registry_mod = load_sibling(__file__, "registry")

POLL_SECS = 1.0  # registry re-scan cadence
PREVIEW_LINES = 20  # tool-calls tailed in the list-view preview pane
_FOCUS_OVERHEAD = 5  # header + 2 scroll affordances + blank + hint reserved around the focus window
_STATUS_COL = 8  # status column width in the list pane

# A registry entry: the status record paired with its absolute agent dir.
# The dir is kept alongside (not stuffed into the record) so Agent stays
# the pure registry contract and the navigator's preview/kill target is explicit.
Entry = tuple[dict[str, object], Path]


def _record_of(entry: object) -> dict[str, object]:
    """The status record of a registry element — a bare record or an (record, path) Entry."""
    return cast("dict[str, object]", entry[0] if isinstance(entry, tuple) else entry)


def resolve_focus_index(entries: Sequence[object], pinned_session: str | None, fallback: int | None) -> int | None:
    """Index of the record whose `session == pinned_session`, pinning focus to identity.

    Pure. The registry re-sorts by (rank, age) every tick, so a fixed integer index
    drifts onto a different agent after a status flip — tracking the *name* instead
    keeps focus and the list cursor glued to the agent the operator chose.

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
    toggles the single-agent zoom view in the shell.
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
    """List pane: one row per agent, `>` on the selection, status dot + name + last event.

    When viewport_height is given, scrolls to keep the selected row visible and
    appends a '… N more' affordance when records are truncated at the bottom.
    """
    all_lines: list[str] = []
    for i, r in enumerate(records):
        cursor = ">" if i == selected else " "
        dot = tui.status_dot(str(r["status"]))
        last = r.get("last_event") or "-"
        age = _registry_mod._humanize_age(cast("float", r.get("age", 0.0)))
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
    """Preview pane: the selected agent's recent tool calls under a `│` gutter."""
    gutter = tui.color(tui.PIPE, tui.DIM)
    if not tool_names:
        return [f"{gutter} (no activity yet)"]
    return [f"{gutter} {tui.tool_glyph(n)} {n}" for n in tool_names]


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


def _tools(agent_dir: Path, *, limit: int) -> list[str]:
    return cast("list[str]", _registry_mod.agent_stream_tools(agent_dir, limit=limit))


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

    The focused single-agent frame is built by `_focus_frame` in the navigate
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
        record, agent_dir = _selected(entries, selected)
        lines.append("")
        lines.append(tui.section_rule(str(record["session"])))
        lines += render_preview(_tools(agent_dir, limit=preview_cap))
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
        entries = _registry_entries(repo_dir, active_only=active_only)
        for line in render_list([rec for rec, _ in entries], 0):
            print(line)
        return 0
    return _navigate_tty(repo_dir, repo=repo, active_only=active_only)


def _navigate_tty(repo_dir: Path, *, repo: str, active_only: bool) -> int:  # pragma: no cover - raw-tty I/O shell
    """Live raw-tty navigator loop. The pure parts it drives (handle_key, scroll,
    resolve_focus_index, render_*, _frame_fingerprint) are gate-tested; this is the
    thin select/termios shell that can only run against a real terminal."""
    entries = _registry_entries(repo_dir, active_only=active_only)
    import atexit
    import signal
    import termios
    import tty

    selected, focused, view = 0, False, _render._VIEW_TRANSCRIPT
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
                record, agent_dir = _selected(entries, selected)
                focus_content = (
                    _render._transcript_content(agent_dir)
                    if view == _render._VIEW_TRANSCRIPT
                    else _render._audit_content(agent_dir)
                )
                if not focus_content:
                    last = record.get("last_event")
                    hint = _render.empty_hint(view, last if isinstance(last, str) else None)
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
            key = _render._read_key(POLL_SECS)
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
                    view, scroll_top = _render.toggle_view(view), None
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
                    view = _render.toggle_view(view)
                if action == "kill" and entries:
                    _kill(_selected(entries, selected)[1])
            entries = _registry_entries(repo_dir, active_only=active_only)
            # Re-resolve the cursor against the freshly re-sorted registry; if its
            # agent was reaped, clamp to the old slot.
            cursor_idx = resolve_focus_index(entries, cursor_session, None)
            selected = cursor_idx if cursor_idx is not None else min(selected, max(len(entries) - 1, 0))
            cursor_session = str(_selected(entries, selected)[0]["session"]) if entries else None
            # Re-resolve focus the same way; a reaped focus agent drops the zoom.
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


def _registry_entries(repo_dir: Path, *, active_only: bool = True) -> list[Entry]:
    """Registry from the canonical store, paired with each agent's log dir."""
    rows = store.list_track_entries(repo_dir.name, active_only=active_only)
    return [(r, repo_dir / str(r["session"])) for r in rows]


_registry = _registry_entries


def _kill(agent_dir: Path) -> None:
    """Best-effort teardown of the selected agent's worktree (kill bind).

    Reads the worktree path from the agent's spawn audit and removes it via git.
    Best-effort: a missing worktree or git error is swallowed so the navigator
    survives and re-emits the list. `--` separates the path so a worktree string
    starting with `-` can't be parsed as a git option.
    """
    worktree = _registry_mod.agent_worktree(agent_dir)
    if not isinstance(worktree, str) or not worktree:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "worktree", "remove", "--force", "--", worktree],
            check=False,
            capture_output=True,
        )
