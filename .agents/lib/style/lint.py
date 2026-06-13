#!/usr/bin/env python3
"""Tier-1 deterministic style linter for mentat skill and agent files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1]
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from frontmatter import parse as _parse_frontmatter  # noqa: E402

BANNED_RE = re.compile(
    r"\b(just|simply|really|basically|actually|obviously|certainly|moreover)\b"
    r"|sure[,!.]|of course|happy to|might want to|feel free to",
    re.IGNORECASE,
)
ARTICLE_RE = re.compile(r"(?<!\w)(a|an|the)\s", re.IGNORECASE)

_THIN = {"mentat-install"}
_FULL = {
    "mentat-prd",
    "mentat-tasks",
    "mentat-implement",
    "mentat-orchestrate",
    "mentat-container",
    "mentat-log",
    "mentat-session",
    "mentat-git",
    "mentat-plan",
    "mentat-skill",
}


def _classify(path: Path) -> str | None:
    parent = path.parent.name
    if path.name == "SKILL.md":
        if parent in _THIN:
            return "thin"
        if parent in _FULL:
            return "full"
    if ".agents/agents/" in str(path) and path.name.endswith(".md"):
        return "crew"
    return None


def _strip_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def lint_file(path: Path) -> list[str]:
    cls = _classify(path)
    if cls is None:
        return []

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    loc = len(lines)
    fm, fm_end = _parse_frontmatter(text)
    errs: list[str] = []

    required: set[str] = {"name", "description"} | ({"tools"} if cls == "crew" else set())
    for k in sorted(required - set(fm)):
        errs.append(f"{path}: missing frontmatter key '{k}'")

    if cls == "thin" and loc > 40:
        errs.append(f"{path}: thin skill {loc} LOC exceeds 40")
    elif cls == "full" and not (75 <= loc <= 120):
        errs.append(f"{path}: full skill {loc} LOC ({loc}) not in 75–120")
    elif cls == "crew" and not (60 <= loc <= 100):
        errs.append(f"{path}: agent {loc} LOC not in 60–100")

    body = "\n".join(lines[fm_end:])
    clean = _strip_fences(body)

    for m in BANNED_RE.finditer(clean):
        raw_pos = body.find(m.group())
        lineno = (body[:raw_pos].count("\n") if raw_pos >= 0 else 0) + fm_end + 1
        errs.append(f"{path}:{lineno}: banned word/phrase '{m.group().strip()}'")

    if cls == "crew":
        for m in ARTICLE_RE.finditer(clean):
            raw_pos = body.find(m.group())
            lineno = (body[:raw_pos].count("\n") if raw_pos >= 0 else 0) + fm_end + 1
            errs.append(f"{path}:{lineno}: agent must drop article '{m.group().strip()}'")

    return errs


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: lint.py <file> [<file> ...]", file=sys.stderr)
        return 64

    all_errs: list[str] = []
    for a in args:
        p = Path(a)
        if p.is_file():
            all_errs.extend(lint_file(p))

    for e in all_errs:
        print(e, file=sys.stderr)
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main())
