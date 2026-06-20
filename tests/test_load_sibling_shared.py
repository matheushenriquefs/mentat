"""S15 — one shared `load_sibling`, zero local `_load_sibling` copies.

Asserts the sibling-loader dedup: the only definition lives in `lib/loader.py`,
no skill script re-defines a local `_load_sibling`, and every converted
entrypoint still imports cleanly (smoke `--help`).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / ".agents/skills"
LOADER = REPO_ROOT / ".agents/lib/loader.py"

_DEF_LOAD_SIBLING = re.compile(r"^def load_sibling\b", re.M)
_DEF_LOCAL = re.compile(r"^def _load_sibling\b", re.M)


def _skill_scripts() -> list[Path]:
    return [p for p in SKILLS_DIR.rglob("*.py") if "__pycache__" not in p.parts]


def test_exactly_one_load_sibling_definition() -> None:
    """`load_sibling` is defined once, in lib/loader.py."""
    defs = [
        p for p in REPO_ROOT.rglob("*.py") if "__pycache__" not in p.parts and _DEF_LOAD_SIBLING.search(p.read_text())
    ]
    assert defs == [LOADER], f"load_sibling must be defined only in {LOADER}, found: {defs}"


def test_no_local_load_sibling_remains() -> None:
    """No skill script defines a local `_load_sibling`."""
    offenders = [str(p.relative_to(REPO_ROOT)) for p in _skill_scripts() if _DEF_LOCAL.search(p.read_text())]
    assert offenders == [], f"local _load_sibling copies remain: {offenders}"


def test_no_local_load_sibling_call_sites() -> None:
    """No script calls the removed `_load_sibling(` helper."""
    offenders = [
        str(p.relative_to(REPO_ROOT)) for p in _skill_scripts() if re.search(r"_load_sibling\(", p.read_text())
    ]
    assert offenders == [], f"_load_sibling call sites remain: {offenders}"


ENTRYPOINTS = [
    "mentat-git/scripts/git.py",
    "mentat-implement/scripts/implement.py",
    "mentat-install/scripts/install.py",
    "mentat-session/scripts/session.py",
    "mentat-skill/scripts/skill.py",
    "mentat-tasks/scripts/tasks.py",
]


@pytest.mark.parametrize("rel", ENTRYPOINTS)
def test_entrypoint_help_still_resolves(rel: str) -> None:
    """Each converted entrypoint imports cleanly via the shared loader."""
    result = subprocess.run(
        ["python3", str(SKILLS_DIR / rel), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{rel} --help failed: {result.stderr}"
