# ADR 0008: Python runtime — rewrite, skill layout, stdlib-only

Status: Accepted (locked)
Date: 2026-06-09
Parent plan: mentat-python-rewrite-v2

## Context

Shell era hit testability and concurrency ceilings. Bug-class recurrence (env
pollution, chdir, placeholders) traced to shell-specific patterns. 2,751 LOC shell
with zero tests; 8 harness adapters of which only 2 had real traffic (claude-code +
cursor). Pydantic runtime dep in `lib/audit_schema.py` violated SSOT.

## Decision

**Python 3.11+ runtime.** `requires-python = ">=3.11"` in `pyproject.toml`.

**Stdlib only for user-runtime.** `scripts/<bin>.py` + `.agents/lib/*.py` use no
third-party imports. Pydantic, PyYAML allowed in `[dependency-groups] dev` (tests only).

**Dev tooling:** uv (env), ruff (lint+format, target py311), pyright (strict), pytest.

**Skill layout** (Anthropic skill-creator pattern):
```
.agents/skills/mentat-<bin>/
├── SKILL.md             # manifest + invocation docs
└── scripts/
    ├── __init__.py
    ├── <bin>.py         # main entry point
    └── utils.py         # within-skill helpers (not shared across skills)
```

Invocation via full path:
```
python3 ~/.agents/skills/mentat-<bin>/scripts/<bin>.py <subcommand> <args>
```

No `~/.agents/bin/` symlink farm. SKILL.md documents full path.

**Cross-skill calls:** subprocess with full path. `SKILL_ROOT` resolved as:
```python
SKILL_ROOT = Path(__file__).resolve().parents[2]
```
Works for clone (`<repo>/.agents/skills/`) and installed (`~/.agents/skills/`).

**Conventions:** PEP 8, type hints all fns, `X | None` (3.10+), f-strings except
logging, no `print` in library code, no commented-out code, no TODO comments.

**Test pairing:** each bin slice ships paired pytest under `tests/`.

## Consequences

`python3` hard dep on user box (already via devcontainer feature). Bash dropped
from user-facing surface. Test suite established (~1,000 LOC target).
Old `.agents/bin/mentat-*` + `.agents/bin/lib/*.sh` + `.agents/bin/lib/harness/*.sh`
deleted in bins-v2 B13. Exception: `.agents/bin/mentat-install` thin shell
bootstrap wrapper kept (parent plan §J).
