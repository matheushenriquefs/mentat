"""S3 grep-gate: zero ``session`` token repo-wide outside ADR history."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SESSION_RE = re.compile(r"\bsessions?\b", re.IGNORECASE)
_MENTAT_SESSION_RE = re.compile("MENTAT_" + "SESSION")
_SKIP = {
    REPO_ROOT / "tests" / "test_retire_session_s1.py",
    REPO_ROOT / "tests" / "test_retire_session_s2.py",
    REPO_ROOT / "tests" / "test_retire_session_s3.py",
}
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mentat"}


def _iter_text_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path in _SKIP:
            continue
        if path.suffix not in {".py", ".md", ".json", ".jsonc", ".toml", ".yml", ".yaml"}:
            continue
        if "docs/adr/" in str(path):
            continue
        out.append(path)
    return sorted(out)


def test_repo_has_zero_session_token_outside_adr_history() -> None:
    offenders: list[str] = []
    for path in _iter_text_files():
        text = path.read_text()
        rel = path.relative_to(REPO_ROOT)
        if _SESSION_RE.search(text):
            offenders.append(str(rel))
        if _MENTAT_SESSION_RE.search(text):
            offenders.append(f"{rel} (MENTAT_SESSION)")
    assert offenders == [], f"session token remains outside ADR history: {offenders}"
