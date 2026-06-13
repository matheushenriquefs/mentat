"""Shared helpers for mentat-orchestrate."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
from lib import frontmatter as _frontmatter  # noqa: E402
from lib import jsonc as _jsonc  # noqa: E402
from lib import paths  # noqa: E402,F401  # type: ignore[reportUnusedImport]  # pyright: ignore[reportUnusedImport]
from lib.events import bind  # noqa: E402
from lib.gates import engine as _gate_engine  # noqa: E402

emit_event = bind("mentat-orchestrate")
read_config = _jsonc.read_config


def resolve_plan_ref(ref: str) -> Path:
    if "/" in ref or ref.endswith(".md"):
        return Path(ref).expanduser().resolve()
    return Path.home() / ".agents" / "plans" / f"{ref}.md"


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    return _frontmatter.parse(plan_path.read_text())[0]


def run_gates(chunk_path: Path | None) -> tuple[str, str]:
    if chunk_path is None:
        return ("pass", "")
    return _gate_engine.evaluate(chunk_path)
