"""Stdlib YAML-flat frontmatter codec. parse + encode + mutate."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_LINE = re.compile(r"^(\w[\w-]*):\s*(.*)$")


class FrontmatterError(ValueError):
    """Unsupported or malformed YAML-flat frontmatter."""


def parse(text: str) -> tuple[dict[str, str], int]:
    """Return (frontmatter dict, body-start line index). Empty fm → ({}, 0)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, 0
    end = 1
    while end < len(lines) and lines[end].strip() != "---":
        end += 1
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            raise FrontmatterError("nested/indented frontmatter is not supported")
        m = _LINE.match(line)
        if not m:
            raise FrontmatterError(f"unsupported frontmatter line: {line!r}")
        fm[m.group(1)] = m.group(2).strip()
    return fm, end + 1


def encode(fm: dict[str, str], body: str) -> str:
    """Render a frontmatter block followed by body. Preserves dict order."""
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def _write_atomic(path: Path, fm: dict[str, str], body: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(encode(fm, body))
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def mutate(path: Path, **updates: str) -> None:
    """Atomic in-place update of frontmatter fields. Body preserved."""
    text = path.read_text(encoding="utf-8")
    fm, body_start = parse(text)
    fm.update({k: str(v) for k, v in updates.items()})
    _write_atomic(path, fm, "\n".join(text.splitlines()[body_start:]))
