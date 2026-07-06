#!/usr/bin/env python3
"""Tier-1 deterministic style linter for mentat skill and agent files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1]
_AGENTS = _LIB.parent
for _p in (_AGENTS, _LIB):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from exits import EX_FAILURE, EX_OK, EX_USAGE  # noqa: E402
from lib.support.frontmatter import parse as _parse_frontmatter  # noqa: E402

BANNED_RE = re.compile(
    r"\b(just|simply|really|basically|actually|obviously|certainly|moreover)\b"
    r"|sure[,!.]|of course|happy to|might want to|feel free to",
    re.IGNORECASE,
)
ARTICLE_RE = re.compile(r"(?<!\w)(a|an|the)\s", re.IGNORECASE)

_STYLE_MD = Path(__file__).resolve().parents[3] / "docs" / "STYLE.md"


def _load_skill_voices(style_path: Path) -> tuple[set[str], set[str]]:
    """Parse thin/full skill sets from the Voice-Mapping Table in docs/STYLE.md.

    A new skill only needs an entry in STYLE.md — no edit to this file required.
    """
    thin: set[str] = set()
    full: set[str] = set()
    if not style_path.exists():
        return thin, full
    in_table = False
    for line in style_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "## Voice-Mapping Table" in line:
            in_table = True
            continue
        if in_table:
            if line.startswith("#"):
                break
            if not line.startswith("|") or "---" in line or "Path pattern" in line:
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) < 2:
                continue
            path_pat = cols[0].strip("`").strip()
            voice_raw = cols[1].lower()
            m = re.search(r"skills/([^/`]+)/SKILL", path_pat)
            if not m:
                continue
            raw = m.group(1)
            if "{" in raw:
                bm = re.match(r"^([^{]*)\{([^}]+)\}(.*)$", raw)
                if bm:
                    prefix, choices, suffix = bm.group(1), bm.group(2), bm.group(3)
                    names: list[str] = [prefix + c.strip() + suffix for c in choices.split(",")]
                else:
                    names = [raw]
            else:
                names = [raw]
            if "thin" in voice_raw:
                thin.update(names)
            elif "full" in voice_raw:
                full.update(names)
    return thin, full


_THIN, _FULL = _load_skill_voices(_STYLE_MD)


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
        return EX_USAGE

    all_errs: list[str] = []
    for a in args:
        p = Path(a)
        if p.is_file():
            all_errs.extend(lint_file(p))

    for e in all_errs:
        print(e, file=sys.stderr)
    return EX_FAILURE if all_errs else EX_OK


if __name__ == "__main__":
    sys.exit(main())
