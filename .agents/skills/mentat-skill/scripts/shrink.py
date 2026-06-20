"""mentat-skill shrink subcommand."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

_utils = load_sibling(__file__, "utils")
_eval = load_sibling(__file__, "eval")


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
