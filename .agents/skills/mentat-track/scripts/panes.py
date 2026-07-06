"""Multi-AFK navigator: pane layout, viewport windowing, keypress reducer.

No push hooks → timer-poll the registry each tick. Pure layout lives in
``pane_layout.py`` (gate-tested); ``navigate`` is the thin raw-tty/select I/O shell.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

import pane_layout  # noqa: E402
from lib import store, tui  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_render = load_sibling(__file__, "render")
_registry_mod = load_sibling(__file__, "registry")

POLL_SECS = 1.0
PREVIEW_LINES = 20
_FOCUS_OVERHEAD = 5
_STATUS_COL = 8

Entry = pane_layout.Entry
resolve_focus_index = pane_layout.resolve_focus_index
window_lines = pane_layout.window_lines
scroll = pane_layout.scroll
handle_key = pane_layout.handle_key
render_preview = pane_layout.render_preview
frame_fingerprint = pane_layout.frame_fingerprint
restore_seq = pane_layout.restore_seq
selected_entry = pane_layout.selected_entry
_record_of = pane_layout.record_of
_focus_frame = pane_layout.focus_frame
_frame_fingerprint = pane_layout.frame_fingerprint
_restore_seq = pane_layout.restore_seq
_selected = pane_layout.selected_entry


def render_list(
    records: list[dict[str, object]],
    selected: int,
    *,
    viewport_height: int | None = None,
) -> list[str]:
    return pane_layout.render_list(
        records,
        selected,
        viewport_height=viewport_height,
        humanize_age=_registry_mod._humanize_age,
    )


def _tools(agent_dir: Path, *, limit: int) -> list[str]:
    return cast("list[str]", _registry_mod.agent_stream_tools(agent_dir, limit=limit))


def _terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
        return size.columns, size.lines
    except OSError:
        return 80, 20


def _frame(entries: list[Entry], selected: int, repo: str, *, rows: int) -> list[str]:
    tool_names: list[str] = []
    if entries:
        _, agent_dir = selected_entry(entries, selected)
        tool_names = _tools(agent_dir, limit=PREVIEW_LINES)
    return pane_layout.list_frame(
        entries,
        selected,
        repo,
        rows=rows,
        preview_lines=PREVIEW_LINES,
        tool_names=tool_names,
        humanize_age=_registry_mod._humanize_age,
    )


_TERMINATE = False


def _on_sigterm(signum: int, frame: object) -> None:
    global _TERMINATE
    _TERMINATE = True


def navigate(repo_dir: Path, *, repo: str, active_only: bool = True) -> int:
    """Live multi-AFK navigator: timer-poll the registry, raw-tty key handling."""
    if not sys.stdin.isatty():
        entries = _registry_entries(repo_dir, active_only=active_only)
        for line in render_list([rec for rec, _ in entries], 0):
            print(line)
        return 0
    return _navigate_tty(repo_dir, repo=repo, active_only=active_only)


def _navigate_tty(repo_dir: Path, *, repo: str, active_only: bool) -> int:  # pragma: no cover
    entries = _registry_entries(repo_dir, active_only=active_only)
    import atexit
    import signal
    import termios
    import tty

    selected, focused, view = 0, False, _render._VIEW_TRANSCRIPT
    scroll_top: int | None = None
    cursor_agent: str | None = str(entries[0][0]["agent"]) if entries else None
    pinned: str | None = None
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    def _restore() -> None:
        sys.stdout.write(pane_layout.restore_seq())
        sys.stdout.flush()

    global _TERMINATE
    _TERMINATE = False
    prev_sigterm = signal.signal(signal.SIGTERM, _on_sigterm)
    atexit.register(_restore)
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
                record, agent_dir = selected_entry(entries, selected)
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
                frame = pane_layout.focus_frame(record, focus_content, scroll_top=scroll_top, height=focus_height)
            else:
                frame = _frame(entries, selected, repo, rows=rows)
            fp = pane_layout.frame_fingerprint(frame, cols, rows)
            if fp != last_fp:
                sys.stdout.write(tui.paint(frame, rows=rows))
                sys.stdout.flush()
                last_fp = fp
            key = _render._read_key(POLL_SECS)
            if _TERMINATE:
                break
            if key is not None and focused:
                total = len(focus_content)
                if key == "q":
                    break
                if key in ("\n", "\r", "\x1b"):
                    focused, pinned, scroll_top = False, None, None
                elif key == "t":
                    view, scroll_top = _render.toggle_view(view), None
                elif key == "x" and entries:
                    _kill(selected_entry(entries, selected)[1])
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
                    cursor_agent = str(selected_entry(entries, selected)[0]["agent"])
                if action == "quit":
                    break
                if action == "focus" and entries:
                    focused, scroll_top = True, None
                    pinned = str(selected_entry(entries, selected)[0]["agent"])
                if action == "toggle":
                    view = _render.toggle_view(view)
                if action == "kill" and entries:
                    _kill(selected_entry(entries, selected)[1])
            entries = _registry_entries(repo_dir, active_only=active_only)
            cursor_idx = resolve_focus_index(entries, cursor_agent, None)
            selected = cursor_idx if cursor_idx is not None else min(selected, max(len(entries) - 1, 0))
            cursor_agent = str(selected_entry(entries, selected)[0]["agent"]) if entries else None
            if focused:
                focus_idx = resolve_focus_index(entries, pinned, None)
                if focus_idx is None:
                    focused, pinned, scroll_top = False, None, None
                else:
                    selected, cursor_agent = focus_idx, pinned
            if not entries:
                focused, scroll_top = False, None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        signal.signal(signal.SIGTERM, prev_sigterm)
        sys.stdout.write(pane_layout.restore_seq())
        sys.stdout.flush()
        atexit.unregister(_restore)
    return 0


def _registry_entries(repo_dir: Path, *, active_only: bool = True) -> list[Entry]:
    rows = store.list_track_entries(repo_dir.name, active_only=active_only)
    return [(r, repo_dir / str(r["agent"])) for r in rows]


_registry = _registry_entries


def _kill(agent_dir: Path) -> None:
    worktree = _registry_mod.agent_worktree(agent_dir)
    if not isinstance(worktree, str) or not worktree:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "worktree", "remove", "--force", "--", worktree],
            check=False,
            capture_output=True,
        )
