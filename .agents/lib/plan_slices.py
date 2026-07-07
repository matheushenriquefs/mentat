"""Parse vertical slices from plan markdown bodies."""

from __future__ import annotations

import re
from pathlib import Path

from lib.support import frontmatter

_SLICE_HEADER = re.compile(
    r"^## Slice (S\d+)\b[^\n]*\((AFK|HITL)\)",
    re.MULTILINE,
)


def parse_slices_text(text: str) -> list[tuple[str, str]]:
    """Return ordered (slice_key, kind) pairs from plan body text."""
    _, body_start = frontmatter.parse(text)
    body = "\n".join(text.splitlines()[body_start:])
    return [(m.group(1), m.group(2)) for m in _SLICE_HEADER.finditer(body)]


def parse_slices(plan_path: Path) -> list[tuple[str, str]]:
    """Return ordered (slice_key, kind) pairs from a plan file."""
    if not plan_path.is_file():
        return []
    return parse_slices_text(plan_path.read_text())
