"""Stdlib-only spec_from_file_location loader. Shared by every skill."""

from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path
from types import ModuleType

from lib import paths


def load_sibling(caller_file: str, name: str) -> ModuleType:
    here = Path(caller_file).resolve().parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def load_skill(skill: str, module: str) -> ModuleType:
    path = paths.SKILLS_DIR / skill / "scripts" / f"{module}.py"
    key = f"{skill}.{module}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, path)
    mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod
