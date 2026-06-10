#!/usr/bin/env python3
"""mentat-skill — eval / shrink / scaffold."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parents[2]


def _default_skills_root() -> Path:
    return _SKILL_ROOT / ".agents" / "skills"


def _default_evals_dir() -> Path:
    return _SKILL_ROOT / "evals"


def cmd_eval(skill_name: str, *, evals_dir: Path | None = None) -> int:
    if evals_dir is None:
        evals_dir = _default_evals_dir()
    eval_file = evals_dir / f"{skill_name}.json"
    if not eval_file.exists():
        print(f"mentat-skill: eval file not found: {eval_file}", file=sys.stderr)
        raise SystemExit(1)
    if shutil.which("promptfoo") is None:
        print(
            "mentat-skill: promptfoo not found on PATH. Install: npm install -g promptfoo",
            file=sys.stderr,
        )
        raise SystemExit(1)
    result = subprocess.run(["promptfoo", "eval", "--config", str(eval_file)])
    return result.returncode


def _invoke_shrink_harness(skill_md_content: str) -> str:
    """Invoke harness to propose a leaner SKILL.md. Returns proposed content."""
    # Stub: in real use this calls mentat-implement subprocess
    return skill_md_content


def _run_eval_gate(skill_name: str, *, evals_dir: Path) -> bool:
    """Run eval gate against current. Returns True if passes."""
    eval_file = evals_dir / f"{skill_name}.json"
    if not eval_file.exists():
        return True
    if shutil.which("promptfoo") is None:
        return True
    result = subprocess.run(["promptfoo", "eval", "--config", str(eval_file)], capture_output=True)
    return result.returncode == 0


def cmd_shrink(skill_name: str, *, skills_root: Path | None = None, evals_dir: Path | None = None) -> int:
    if skills_root is None:
        skills_root = _default_skills_root()
    if evals_dir is None:
        evals_dir = _default_evals_dir()

    skill_md = skills_root / skill_name / "SKILL.md"
    if not skill_md.exists():
        print(f"mentat-skill: SKILL.md not found: {skill_md}", file=sys.stderr)
        return 1

    proposed = _invoke_shrink_harness(skill_md.read_text())
    if not proposed or proposed == skill_md.read_text():
        print("mentat-skill: no shrink proposed")
        return 0

    if not _run_eval_gate(skill_name, evals_dir=evals_dir):
        print("mentat-skill: eval gate failed after shrink proposal — not applying", file=sys.stderr)
        return 1

    skill_md.write_text(proposed)
    print(f"mentat-skill: shrunk {skill_md}")
    return 0


def cmd_scaffold(skill_name: str, *, skills_root: Path | None = None, evals_dir: Path | None = None) -> int:
    if skills_root is None:
        skills_root = _default_skills_root()
    if evals_dir is None:
        evals_dir = _default_evals_dir()

    skill_dir = skills_root / skill_name
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    evals_dir.mkdir(parents=True, exist_ok=True)

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        skill_md.write_text(
            f"---\nname: {skill_name}\ndescription: >\n  {skill_name} skill.\n"
            f"metadata:\n  version: \"0.1.0\"\n---\n\n# {skill_name}\n\n"
            f"## How to invoke\n\n```\npython3 ~/.agents/skills/{skill_name}/scripts/{skill_name}.py\n```\n"
        )

    init = scripts_dir / "__init__.py"
    if not init.exists():
        init.write_text("")

    main_script = scripts_dir / f"{skill_name}.py"
    if not main_script.exists():
        main_script.write_text(
            f'#!/usr/bin/env python3\n"""mentat-{skill_name}."""\n\nfrom __future__ import annotations\n\nimport sys\n\n\ndef main() -> None:\n    print("mentat-{skill_name}: not yet implemented")\n    sys.exit(1)\n\n\nif __name__ == "__main__":\n    main()\n'
        )

    evals_file = evals_dir / f"{skill_name}.json"
    if not evals_file.exists():
        evals_file.write_text(json.dumps({
            "skill_name": skill_name,
            "description": f"{skill_name} skill",
            "evals": [],
            "eval_queries": [],
        }, indent=2) + "\n")

    print(f"mentat-skill: scaffolded {skill_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-skill")
    sub = p.add_subparsers(dest="cmd", required=True)

    eval_p = sub.add_parser("eval", help="Run evals for a skill")
    eval_p.add_argument("skill_name", nargs="?", default=None)

    shrink_p = sub.add_parser("shrink", help="Propose leaner SKILL.md")
    shrink_p.add_argument("skill_name", nargs="?", default=None)

    scaffold_p = sub.add_parser("scaffold", help="Scaffold a new skill")
    scaffold_p.add_argument("skill_name")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "eval":
        sys.exit(cmd_eval(args.skill_name or Path.cwd().name))
    elif args.cmd == "shrink":
        sys.exit(cmd_shrink(args.skill_name or Path.cwd().name))
    elif args.cmd == "scaffold":
        sys.exit(cmd_scaffold(args.skill_name))


if __name__ == "__main__":
    main()
