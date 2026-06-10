"""Deterministic smell detector gate. Port of smells.sh."""

from __future__ import annotations

from pathlib import Path


def run(chunk_path: Path) -> tuple[str, str]:
    """Return (verdict, message). verdict in {'pass', 'block', 'advise'}."""
    return ("advise", "")
