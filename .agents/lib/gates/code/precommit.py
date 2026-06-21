"""Deterministic pre-commit gate.

File-class dispatcher: ADR docs need three sections, agent/command docs need YAML
frontmatter, workflow docs need at least one cross-ref link, *.jsonc must parse
as JSON after stripping pure `//` comment lines.

External-interpreter checks (bash -n, jq) block when the interpreter is absent.
A missing interpreter for a file that needs it is a hard error — not an advisory.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_WALK_DIR = Path(__file__).resolve().parents[1]
_AGENTS_ROOT = _WALK_DIR.parents[1]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.gates._walk import iter_files as _iter_files  # noqa: E402

_LINK_RE = re.compile(r"\[.+?\]\(.+?\.md\)")
_COMMENT_LINE_RE = re.compile(r"^\s*//")
_SUFFIX_CLASS: dict[str, str] = {".jsonc": "jsonc", ".sh": "shell", ".jq": "jq"}


def _classify(path: Path) -> str | None:
    parts = path.parts
    name = path.name
    suffix = path.suffix

    cls = _SUFFIX_CLASS.get(suffix)
    if cls:
        return cls
    if name == "CONTEXT.md":
        return "workflow"
    if "docs" in parts and "adr" in parts and suffix == ".md" and name != "README.md":
        return "adr"
    if "commands" in parts and suffix == ".md":
        return "command"
    if "skills" in parts and name == "SKILL.md":
        return "skill"
    if "agents" in parts and name != "AGENTS.md" and suffix == ".md":
        return "skill"
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
    """Return (block_msg, advise_msg). Block if bash not on PATH."""
    if shutil.which("bash") is None:
        return f"{path}: bash not on PATH — cannot verify shell syntax", None
    r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return f"{path}: bash -n syntax error: {(r.stderr or '').strip()}", None
    return None, None


def _gate_jq(path: Path) -> tuple[str | None, str | None]:
    """Return (block_msg, advise_msg). Block if jq not on PATH."""
    if shutil.which("jq") is None:
        return f"{path}: jq not on PATH — cannot verify jq syntax", None
    r = subprocess.run(["jq", "-n", "-c", "-f", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode != 0:
        return f"{path}: jq parse fail: {(r.stderr or '').strip()}", None
    return None, None


def _check(path: Path, cls: str) -> tuple[list[str], list[str]]:
    blocks: list[str] = []
    advisories: list[str] = []
    if cls in ("skill", "command"):
        msg = _gate_frontmatter(path)
        if msg:
            blocks.append(msg)
        return blocks, advisories
    if cls == "adr":
        msg = _gate_adr(path)
        if msg:
            blocks.append(msg)
        return blocks, advisories
    if cls == "workflow":
        msg = _gate_workflow(path)
        if msg:
            blocks.append(msg)
        return blocks, advisories
    if cls == "jsonc":
        msg = _gate_jsonc(path)
        if msg:
            blocks.append(msg)
        return blocks, advisories
    if cls == "shell":
        block, advise = _gate_shell(path)
        if block:
            blocks.append(block)
        if advise:
            advisories.append(advise)
        return blocks, advisories
    if cls == "jq":
        block, advise = _gate_jq(path)
        if block:
            blocks.append(block)
        if advise:
            advisories.append(advise)
    return blocks, advisories


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
            new_blocks, new_advisories = _check(path, cls)
            blocks.extend(new_blocks)
            advisories.extend(new_advisories)
        except OSError as e:
            advisories.append(f"{path}: read error: {e}")

    if blocks:
        return ("block", "\n".join(blocks))
    if advisories:
        return ("advise", "\n".join(advisories))
    return ("pass", "")


class _PrecommitGate:
    id = "precommit"
    priority = 10

    def run(self, ctx: object) -> tuple[str, str]:
        chunk_path = getattr(ctx, "chunk_path", None)
        return run(chunk_path)


gate = _PrecommitGate()
