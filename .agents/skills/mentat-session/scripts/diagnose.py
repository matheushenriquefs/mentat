"""Diagnose loop: doctor-first context, then /diagnose interactive."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

import importlib.util as _ilu


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_doctor = _load_sibling("doctor")


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
