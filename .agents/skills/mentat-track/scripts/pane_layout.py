"""Pure pane layout: focus index, scroll windowing, list/preview renderers.

Terminal-free — no termios, select, or subprocess. The navigator tty shell in
``panes.py`` wires these to the live registry and filesystem.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from lib import tui

Entry = tuple[dict[str, object], Path]

_STATUS_COL = 8
_FOCUS_OVERHEAD = 5


def record_of(entry: object) -> dict[str, object]:
    """Status record of a registry element — bare record or (record, path) Entry."""
    return cast("dict[str, object]", entry[0] if isinstance(entry, tuple) else entry)


def resolve_focus_index(entries: Sequence[object], pinned_agent: str | None, fallback: int | None) -> int | None:
    """Index of the record whose ``agent == pinned_agent``."""
    if pinned_agent is None:
        return fallback
    for i, e in enumerate(entries):
        if record_of(e).get("agent") == pinned_agent:
            return i
    return None


def window_lines(all_lines: list[str], *, scroll_top: int | None, height: int) -> tuple[list[str], int, int]:
    """Slice focus history into a viewport. Pure."""
    total = len(all_lines)
    max_top = max(0, total - height)
    start = max_top if scroll_top is None else max(0, min(scroll_top, max_top))
    visible = all_lines[start : start + height]
    above = start
    below = max(0, total - (start + len(visible)))
    return visible, above, below


def scroll(scroll_top: int | None, delta: int, total: int, height: int) -> int | None:
    """Apply scroll delta, clamped. Reaching the bottom returns None (tail-follow)."""
    max_top = max(0, total - height)
    current = max_top if scroll_top is None else scroll_top
    new = max(0, min(current + delta, max_top))
    return None if new >= max_top else new


def handle_key(key: str, selected: int, count: int) -> tuple[int, str | None]:
    """Reduce one keypress to (new_selection, action). Pure."""
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


def render_list(
    records: list[dict[str, object]],
    selected: int,
    *,
    viewport_height: int | None = None,
    humanize_age: Callable[[float], str],
) -> list[str]:
    """List pane rows with status dot, age, and last event."""
    all_lines: list[str] = []
    for i, r in enumerate(records):
        cursor = ">" if i == selected else " "
        dot = tui.status_dot(str(r["status"]))
        last = r.get("last_event") or "-"
        age = humanize_age(cast("float", r.get("age", 0.0)))
        all_lines.append(f"{cursor} {dot} {r['status']:<{_STATUS_COL}} {r['agent']}  {age:>9}  {last}")

    if viewport_height is None or len(all_lines) <= viewport_height:
        return all_lines

    half = viewport_height // 2
    offset = max(0, min(selected - half, len(all_lines) - viewport_height))
    window = all_lines[offset : offset + viewport_height]
    remaining = len(all_lines) - (offset + viewport_height)
    if remaining > 0:
        window[-1] = f"  … {remaining + 1} more"
    return window


def render_preview(tool_names: list[str]) -> list[str]:
    """Preview pane: recent tool calls under a dim gutter."""
    gutter = tui.color(tui.PIPE, tui.DIM)
    if not tool_names:
        return [f"{gutter} (no activity yet)"]
    return [f"{gutter} {tui.tool_glyph(n)} {n}" for n in tool_names]


def focus_frame(record: dict[str, object], content: list[str], *, scroll_top: int | None, height: int) -> list[str]:
    """Scroll-windowed focus frame with header and scroll affordances."""
    visible, above, below = window_lines(content, scroll_top=scroll_top, height=height)
    lines = [tui.color(tui.section_rule(f"{record['agent']} — {record['status']}"), tui.BOLD)]
    if above:
        lines.append(tui.color(f"↑ {above} more", tui.DIM))
    lines += visible
    if below:
        lines.append(tui.color(f"↓ {below} more", tui.DIM))
    lines.append("")
    lines.append(tui.color("j/k·d/u scroll · t toggle · enter/esc back · x kill · q quit", tui.DIM))
    return lines


def frame_fingerprint(lines: list[str], cols: int, rows: int) -> int:
    """Hash of rendered frame + terminal size for repaint dedup."""
    return hash((tuple(lines), cols, rows))


def restore_seq() -> str:
    """Terminal-restore escapes: show cursor and leave alternate screen."""
    return tui.SHOW_CURSOR + tui.ALT_EXIT


def selected_entry(entries: list[Entry], selected: int) -> Entry:
    """Cursor entry, clamped to range."""
    return entries[min(selected, len(entries) - 1)]


def list_frame(
    entries: list[Entry],
    selected: int,
    repo: str,
    *,
    rows: int,
    preview_lines: int,
    tool_names: list[str],
    humanize_age: Callable[[float], str],
) -> list[str]:
    """Build the list-view frame as lines (no I/O)."""
    records = [rec for rec, _ in entries]
    lines = [tui.section_rule(f"{repo} — {len(records)} agent(s)")]
    overhead = 5
    available = max(6, rows - overhead)
    preview_cap = min(preview_lines, max(3, available // 2))
    list_viewport = max(3, available - preview_cap)
    lines += render_list(records, selected, viewport_height=list_viewport, humanize_age=humanize_age)
    if entries:
        record, _ = selected_entry(entries, selected)
        lines.append("")
        lines.append(tui.section_rule(str(record["agent"])))
        lines += render_preview(tool_names)
    lines.append("")
    lines.append(tui.color("j/k move · enter focus · x kill · q quit", tui.DIM))
    return lines
