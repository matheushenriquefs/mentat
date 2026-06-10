"""mentat-skill scaffold subcommand."""

from __future__ import annotations

import importlib.util as _ilu
import json
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


def cmd_scaffold(skill_name: str, *, skills_root: Path | None = None, evals_dir: Path | None = None) -> int:
    if skills_root is None:
        skills_root = _utils.default_skills_root()
    if evals_dir is None:
        evals_dir = _utils.default_evals_dir()

    skill_dir = skills_root / skill_name
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    evals_dir.mkdir(parents=True, exist_ok=True)

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        skill_md.write_text(
            f"---\nname: {skill_name}\ndescription: >\n  {skill_name} skill.\n"
            f"---\n\n"
            f"<!-- Voice, LOC budget, and frontmatter spec: docs/STYLE.md -->\n\n"
            f"## How to invoke\n\n```\npython3 ~/.agents/skills/{skill_name}/scripts/{skill_name}.py\n```\n"
        )

    init = scripts_dir / "__init__.py"
    if not init.exists():
        init.write_text("")

    main_script = scripts_dir / f"{skill_name}.py"
    if not main_script.exists():
        lines = [
            "#!/usr/bin/env python3",
            f'"""mentat-{skill_name}."""',
            "",
            "from __future__ import annotations",
            "",
            "import sys",
            "",
            "",
            "def main() -> None:",
            f'    print("mentat-{skill_name}: not yet implemented")',
            "    sys.exit(1)",
            "",
            "",
            'if __name__ == "__main__":',
            "    main()",
            "",
        ]
        main_script.write_text("\n".join(lines))

    evals_file = evals_dir / f"{skill_name}.json"
    if not evals_file.exists():
        evals_file.write_text(
            json.dumps(
                {
                    "skill_name": skill_name,
                    "description": f"{skill_name} skill",
                    "evals": [],
                    "eval_queries": [],
                },
                indent=2,
            )
            + "\n"
        )

    print(f"mentat-skill: scaffolded {skill_dir}")
    return 0
