"""Stdlib-only spec_from_file_location loader. Shared by every skill."""

from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path
from types import ModuleType

from lib import paths


def _load_cached(key: str, path: Path) -> ModuleType:
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, path)
    mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def load_sibling(caller_file: str, name: str) -> ModuleType:
    here = Path(caller_file).resolve().parent
    return _load_cached(f"{here.parent.name}.{name}", here / f"{name}.py")


def load_skill(skill: str, module: str) -> ModuleType:
    return _load_cached(f"{skill}.{module}", paths.SKILLS_DIR / skill / "scripts" / f"{module}.py")
