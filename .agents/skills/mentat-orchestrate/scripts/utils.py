"""Shared helpers for mentat-orchestrate."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
from lib import jsonc as _jsonc  # noqa: E402
from lib import paths  # noqa: E402
from lib.events import bind  # noqa: E402

emit_event = bind("mentat-orchestrate")
read_config = _jsonc.read_config


def resolve_plan_ref(ref: str) -> Path:
    if "/" in ref or ref.endswith(".md"):
        return Path(ref).expanduser().resolve()
    return Path.home() / ".agents" / "plans" / f"{ref}.md"


def parse_frontmatter(plan_path: Path) -> dict[str, str]:
    text = plan_path.read_text()
    fm: dict[str, str] = {}
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm:
            m = re.match(r"^(\w+):\s*(.+)$", line)
            if m:
                fm[m.group(1)] = m.group(2).strip()
    return fm


def run_gates(chunk_path: Path | None) -> tuple[str, str]:
    if not paths.GATES_CODE_DIR.exists():
        return ("pass", "")
    for gate_file in sorted(paths.GATES_CODE_DIR.glob("*.py")):
        if gate_file.stem == "__init__":
            continue
        spec = importlib.util.spec_from_file_location(gate_file.stem, gate_file)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        if hasattr(mod, "run"):
            verdict, message = mod.run(chunk_path)
            if verdict == "block":
                return ("block", message)
    return ("pass", "")
