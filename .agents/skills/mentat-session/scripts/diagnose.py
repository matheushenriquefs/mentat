"""Diagnose loop: doctor-first context, then /diagnose interactive."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

_doctor = load_sibling(__file__, "doctor")


def _call_doctor(session_dir: Path) -> str:
    diag = _doctor.write_diagnosis(session_dir)
    return diag.read_text()


def _run_diagnose_loop(context: str) -> None:
    """Entry point for the /diagnose interactive loop with context pre-loaded."""
    print("=== diagnose context ===")
    print(context)
    print("=== enter diagnose loop (reproduce → minimize → hypothesize → red test) ===")


def run_diagnose(session_dir: Path) -> None:
    context = _call_doctor(session_dir)
    _run_diagnose_loop(context)
