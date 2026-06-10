"""Live event stream for a session (tail -f style with colors)."""

from __future__ import annotations

import importlib.util as _ilu
import json
import sys
import time
from pathlib import Path


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_sessions = _load_sibling("sessions")

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
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    event = row.get("event", "")
                    c = _color_for_event(event) if color else ""
                    reset = _RESET if color else ""
                    payload = json.dumps(row.get("payload", {}))
                    print(f"{c}{row.get('ts', '')} [{row.get('agent', '')}] {event} {payload}{reset}")
                seen_files[log_file] = f.tell()

        if not follow or time.time() > end_time:
            break
        time.sleep(0.1)
