"""S2 grep-gate: zero ``session`` token in ``.agents/skills/``."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

_SESSION_RE = re.compile(r"session", re.IGNORECASE)
_MENTAT_SESSION_RE = re.compile(r"MENTAT_SESSION")


def _skill_files() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.rglob("*") if p.is_file() and p.suffix in {".py", ".md"})


def test_skills_have_zero_session_token() -> None:
    offenders: list[str] = []
    for path in _skill_files():
        text = path.read_text()
        rel = path.relative_to(REPO_ROOT)
        if _SESSION_RE.search(text):
            offenders.append(str(rel))
        if _MENTAT_SESSION_RE.search(text):
            offenders.append(f"{rel} (MENTAT_SESSION)")
    assert offenders == [], f"session token remains in skills: {offenders}"
