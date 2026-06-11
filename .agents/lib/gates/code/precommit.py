"""Deterministic pre-commit gate.

File-class dispatcher: ADR docs need three sections, agent/command docs need YAML
frontmatter, workflow docs need at least one cross-ref link, *.jsonc must parse
as JSON after stripping pure `//` comment lines.

External-interpreter checks (bash -n, jq) are downgraded to "advise" when their
interpreters aren't on PATH so the gate stays portable in container or host runs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

_SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", "node_modules", ".dmux", ".mentat", "context"}

_LINK_RE = re.compile(r"\[.+?\]\(.+?\.md\)")
_COMMENT_LINE_RE = re.compile(r"^\s*//")


def _iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


def _classify(path: Path) -> str | None:
    parts = path.parts
    name = path.name

    if "docs" in parts and "adr" in parts and path.suffix == ".md" and name != "README.md":
        return "adr"
    if "skills" in parts and path.suffix == ".md":
        return "skill"
    if "agents" in parts and name != "AGENTS.md" and path.suffix == ".md":
        return "skill"
    if "commands" in parts and path.suffix == ".md":
        return "command"
    if name == "CONTEXT.md":
        return "workflow"
    if path.suffix == ".jsonc":
        return "jsonc"
    if path.suffix == ".sh":
        return "shell"
    if path.suffix == ".jq":
        return "jq"
    return None


def _gate_adr(path: Path) -> str | None:
    text = path.read_text()
    missing = [
        section
        for section in ("## Context", "## Decision", "## Consequences")
        if not re.search(rf"^{re.escape(section)}", text, re.MULTILINE)
    ]
    if missing:
        return f"{path}: missing {', '.join(missing)}"
    return None


def _gate_frontmatter(path: Path) -> str | None:
    head = path.read_text().splitlines()[:10]
    if not any(line.strip() == "---" for line in head):
        return f"{path}: missing YAML frontmatter (no `---` in first 10 lines)"
    return None


def _gate_workflow(path: Path) -> str | None:
    if not _LINK_RE.search(path.read_text()):
        return f"{path}: no cross-ref links found ([text](*.md))"
    return None


def _gate_jsonc(path: Path) -> str | None:
    text = path.read_text()
    stripped = "\n".join(line for line in text.splitlines() if not _COMMENT_LINE_RE.match(line))
    try:
        json.loads(stripped)
    except json.JSONDecodeError as e:
        return f"{path}: jsonc parse fail at line {e.lineno}: {e.msg}"
    return None


def _gate_shell(path: Path) -> tuple[str | None, str | None]:
    """Return (block_msg, advise_msg). Advise if bash not on PATH."""
    if shutil.which("bash") is None:
        return None, f"{path}: bash not on PATH — syntax check skipped"
    r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return f"{path}: bash -n syntax error: {(r.stderr or '').strip()}", None
    return None, None


def _gate_jq(path: Path) -> tuple[str | None, str | None]:
    if shutil.which("jq") is None:
        return None, f"{path}: jq not on PATH — parse check skipped"
    r = subprocess.run(["jq", "-n", "-c", "-f", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode != 0:
        return f"{path}: jq parse fail: {(r.stderr or '').strip()}", None
    return None, None


def run(chunk_path: Path | None) -> tuple[str, str]:
    """Return (verdict, message). verdict in {'pass', 'block', 'advise'}."""
    if chunk_path is None or not chunk_path.exists():
        return ("pass", "")

    root = chunk_path if chunk_path.is_dir() else chunk_path.parent
    blocks: list[str] = []
    advisories: list[str] = []

    for path in _iter_files(root):
        cls = _classify(path)
        if cls is None:
            continue
        try:
            if cls == "adr":
                msg = _gate_adr(path)
                if msg:
                    blocks.append(msg)
            elif cls in ("skill", "command"):
                msg = _gate_frontmatter(path)
                if msg:
                    blocks.append(msg)
            elif cls == "workflow":
                msg = _gate_workflow(path)
                if msg:
                    blocks.append(msg)
            elif cls == "jsonc":
                msg = _gate_jsonc(path)
                if msg:
                    blocks.append(msg)
            elif cls == "shell":
                block, advise = _gate_shell(path)
                if block:
                    blocks.append(block)
                if advise:
                    advisories.append(advise)
            elif cls == "jq":
                block, advise = _gate_jq(path)
                if block:
                    blocks.append(block)
                if advise:
                    advisories.append(advise)
        except OSError as e:
            advisories.append(f"{path}: read error: {e}")

    if blocks:
        return ("block", "\n".join(blocks))
    if advisories:
        return ("advise", "\n".join(advisories))
    return ("pass", "")
