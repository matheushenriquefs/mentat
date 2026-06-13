# ADR 0008: Python runtime — layout, bootstrap, stdlib-only

Status: Accepted (locked)
Date: 2026-06-09 (revised 2026-06-13)
Parent plan: mentat-python-rewrite-v2 / mentat-rehome-layout

## Context

Shell era hit testability and concurrency ceilings. Bug-class recurrence (env
pollution, chdir, placeholders) traced to shell-specific patterns. 2,751 LOC shell
with zero tests; 8 harness adapters of which only 2 had real traffic (claude-code +
cursor). Pydantic runtime dep in `lib/audit_schema.py` violated SSOT.

Post-shell-port audit (2026-06-13) surfaced two additional issues:

1. **Namespace pollution under `~/.agents/`.** `mentat-install` was planting
   `bin/`, `lib/`, `docs/` under `~/.agents/`. Ground-truth search (mentat-researcher
   2026-06-13) found no published convention for `~/.agents/{bin,lib,docs}/`. The only
   contested convention is `~/.agents/skills/`. Shipping mentat-private dirs there
   risks collision with any future shared-tooling spec that adopts `~/.agents/`.

2. **`_load_sibling` chicken-egg.** Canonical `lib/loader.py::load_sibling` cannot be
   imported until `sys.path` includes the lib root — so 17 scripts re-implemented the
   bootstrap inline (~240 LOC of `_AGENTS_ROOT = parents[N]` boilerplate). The helper
   designed to eliminate that boilerplate couldn't be reached without the boilerplate.

## Decision

**Python 3.11+ runtime.** `requires-python = ">=3.11"` in `pyproject.toml`.

**Stdlib only for user-runtime.** `scripts/<bin>.py` + `lib/*.py` use no third-party
imports. Pydantic, PyYAML allowed in `[dependency-groups] dev` (tests only).

**Dev tooling:** uv (env), ruff (lint+format, target py311), pyright (strict), pytest.

### User-state layout

```
~/.agents/                  # harness/community surface
├── AGENTS.md               # symlink → <repo>/.agents/AGENTS.md
├── agents/<reviewer>.md    # per-harness reviewer prompts
├── plans/<slug>.md         # plan files
└── skills/<skill>/         # installed skill trees

~/.mentat/                  # mentat-private surface
├── bin/                    # CLI wrappers (symlink → <repo>/bin)
├── lib/                    # shared Python library (symlink → <repo>/lib)
├── docs/                   # ARCHITECTURE, ADRs, PATHS.md (symlinks)
├── logs/<repo>/<session>/  # audit NDJSON (per ADR-0007)
├── config.jsonc            # user config
└── worktrees/<slug>/       # chunk worktrees (per ADR-0002)
```

`~/.agents/` is the harness-shared surface. Only `skills/`, `plans/`, `agents/`, and
`AGENTS.md` live there. Everything mentat-private lives under `~/.mentat/`.

### Source-tree layout

```
<repo>/
├── bin/                    # CLI wrappers (was .agents/bin/)
├── lib/                    # shared Python library (was .agents/lib/)
├── docs/                   # user-facing docs, ADRs, PATHS.md
├── .agents/
│   ├── AGENTS.md
│   ├── agents/<reviewer>.md
│   └── skills/<skill>/
```

`<repo>/.agents/` keeps only `skills/`, `agents/`, `AGENTS.md`. Skill invocation path
unchanged: `python3 ~/.agents/skills/mentat-<bin>/scripts/<bin>.py`.

### Bootstrap

Every skill script that imports from `lib/` starts with:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".mentat"))
```

After that one line, `from lib.foo import ...` resolves (`~/.mentat/lib/` is a symlink
into the source tree). No `parents[N]` arithmetic required.

Canonical sibling-module loader: `from lib.loader import load_sibling`. Usage:

```python
_utils = load_sibling(__file__, "utils")
```

### Skill layout (unchanged)

```
.agents/skills/mentat-<bin>/
├── SKILL.md
└── scripts/
    ├── __init__.py
    ├── <bin>.py
    └── utils.py
```

### Cross-skill calls (updated)

Use `lib.paths` constants; do not compute `SKILL_ROOT` inline:

```python
from lib import paths
# paths.SKILLS_DIR / "mentat-<bin>" / "scripts" / "<bin>.py"
```

### Conventions

PEP 8, type hints all fns, `X | None` (3.10+), f-strings except logging, no `print`
in library code, no commented-out code, no TODO comments.

**Test pairing:** each bin slice ships paired pytest under `tests/`.

## Consequences

`python3` hard dep on user box (already via devcontainer feature). Bash dropped from
user-facing surface. Test suite established (~1,000 LOC target).

**Migration:** `mentat-install` stale-paths sweep (S4 of `mentat-rehome-layout`)
removes old `~/.agents/{bin,lib,docs}` symlinks and plants new ones at
`~/.mentat/{bin,lib,docs}`. Existing chunk worktrees at `<repo>/../<slug>` stay in
place; new ones land under `<repo>/.mentat/worktrees/`. Contributors with patches
against `.agents/{bin,lib,docs}` paths rebase after `mentat-rehome-repo-flatten` lands.

Exception: `bin/mentat-install` is the canonical install wrapper path post-flatten.
