"""Shared helpers for mentat-orchestrate."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[3]
_LOG_SCRIPT = _SKILL_ROOT / ".agents/skills/mentat-log/scripts/log.py"
_GATES_CODE = _SKILL_ROOT / ".agents/lib/gates/code"


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


def emit_event(event: str, payload: dict) -> None:
    subprocess.run(
        ["python3", str(_LOG_SCRIPT), "emit", "mentat-orchestrate", event, json.dumps(payload)],
        capture_output=True,
    )


def run_gates(chunk_path: Path | None) -> tuple[str, str]:
    if not _GATES_CODE.exists():
        return ("pass", "")
    for gate_file in sorted(_GATES_CODE.glob("*.py")):
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


def read_config() -> dict:
    config_path = Path.home() / ".mentat" / "config.jsonc"
    if not config_path.exists():
        return {}
    text = "\n".join(
        line for line in config_path.read_text().splitlines()
        if not line.lstrip().startswith("//")
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
