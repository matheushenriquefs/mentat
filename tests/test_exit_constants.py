"""S14 — adopt the BSD sysexits constants; no bare-integer exit codes remain.

Every exit code carrying a sysexits meaning (or EX_HITL_REQUIRED) must reference
a named constant from lib/exits.py, not a bare integer literal — in `sys.exit()`,
`raise SystemExit(...)`, or a `return <code>` that becomes an exit code. Generic
0/1/2 (not sysexits values) and passthrough variables are exempt.

mentat-container is out of scope here — it belongs to the container sibling plan's
write-set; its exit sites convert there.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / ".agents/skills"

# sysexits values + the mentat-specific HITL code. 0/1/2 are generic, not sysexits.
SYSEXITS = {42, 64, 65, 66, 67, 68, 69, 70, 71, 73, 74, 75, 76, 77, 78}

_CALL = re.compile(r"(?:sys\.exit|SystemExit)\(\s*(\d+)\s*\)")
_RETURN = re.compile(r"^\s*return\s+(\d+)\s*$", re.M)

# Files converted in S14 — must import the constants.
CONVERTED = [
    "mentat-git/scripts/commit.py",
    "mentat-git/scripts/worktree.py",
    "mentat-implement/scripts/implement.py",
    "mentat-install/scripts/install.py",
    "mentat-orchestrate/scripts/orchestrate.py",
]


def _core_scripts() -> list[Path]:
    # Production scripts only — skill-local tests/ legitimately assert exit values.
    return [
        p
        for p in SKILLS_DIR.rglob("scripts/*.py")
        if "__pycache__" not in p.parts and "mentat-container" not in p.parts
    ]


def test_no_bare_sysexits_literal_in_exit_or_return() -> None:
    offenders: list[str] = []
    for p in _core_scripts():
        text = p.read_text()
        for rx in (_CALL, _RETURN):
            for m in rx.finditer(text):
                if int(m.group(1)) in SYSEXITS:
                    line = text[: m.start()].count("\n") + 1
                    offenders.append(f"{p.relative_to(REPO_ROOT)}:{line} -> {m.group(1)}")
    assert offenders == [], f"bare sysexits literals remain: {offenders}"


def test_converted_files_import_exits() -> None:
    for rel in CONVERTED:
        text = (SKILLS_DIR / rel).read_text()
        assert "lib.exits" in text, f"{rel} does not import from lib.exits"


def test_doctor_exit_set_uses_constants() -> None:
    """S2's death-detection set is expressed in constant names, not bare ints."""
    text = (SKILLS_DIR / "mentat-implement/scripts/implement.py").read_text()
    m = re.search(r"_DOCTOR_EXIT_CODES\s*=\s*frozenset\(\s*\{([^}]*)\}", text)
    assert m, "_DOCTOR_EXIT_CODES frozenset not found"
    body = m.group(1)
    assert "EX_HITL_REQUIRED" in body, f"set should reference constants, got: {body}"
    assert not re.search(r"\b(42|64|65|66|69|70|78)\b", body), f"bare sysexits int in set: {body}"
