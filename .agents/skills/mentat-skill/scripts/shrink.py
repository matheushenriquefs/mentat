"""mentat-skill shrink subcommand."""

from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path


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


_utils = _load_sibling("utils")
_eval = _load_sibling("eval")


def _invoke_shrink_harness(skill_md_content: str) -> str:
    """Invoke harness to propose a leaner SKILL.md. Returns proposed content."""
    # Stub: in real use this calls mentat-implement subprocess
    return skill_md_content


def cmd_shrink(skill_name: str, *, skills_root: Path | None = None, evals_dir: Path | None = None) -> int:
    if skills_root is None:
        skills_root = _utils.default_skills_root()
    if evals_dir is None:
        evals_dir = _utils.default_evals_dir()

    skill_md = skills_root / skill_name / "SKILL.md"
    if not skill_md.exists():
        print(f"mentat-skill: SKILL.md not found: {skill_md}", file=sys.stderr)
        return 1

    proposed = _invoke_shrink_harness(skill_md.read_text())
    if not proposed or proposed == skill_md.read_text():
        print("mentat-skill: no shrink proposed")
        return 0

    if not _eval.run_eval_gate(skill_name, evals_dir=evals_dir):
        print("mentat-skill: eval gate failed after shrink proposal — not applying", file=sys.stderr)
        return 1

    skill_md.write_text(proposed)
    print(f"mentat-skill: shrunk {skill_md}")
    return 0
