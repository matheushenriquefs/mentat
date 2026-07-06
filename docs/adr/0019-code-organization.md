# ADR 0019: Code organization

Status: Accepted
Date: 2026-07-06

## Context

ADR-0012 introduced `.agents/rules/architecture.md` with group-by-function and
no-`utils.py` guidance, but the conventions were scattered across architecture
prose, ADR-0008 runtime notes, and reviewer judgment. Contributors still reach
for artifact-type filenames (`helpers.py`, `handlers.py`) and grow modules past
the point where a split is obvious. A single ADR must lock the organization
model so `mentat-rules-reviewer` and pre-commit gates share one authority.

## Decision

**Organize by domain, not by kind.** A module belongs with the concept it
models (`agent.py`, `chunk.py`, `worktrees.py`), not with a structural bucket
(`models.py`, `types.py`, `utils.py`, `helpers.py`). A generic artifact filename
is a smell — rename for the work the file does.

**Protocol + registry + adapter at boundaries.** When a surface must stay
swappable (gates, harness adapters, emit backends), define a `Protocol` for the
contract, a registry that discovers implementations, and thin adapters that wire
one implementation. Do not hide the seam behind a god-module.

**<100 LOC smell.** A shipped-runtime module over ~100 lines is a split
candidate — not a hard gate, but a signal to extract by sub-concept (see
`lib/gates/` as the reference layout: `engine.py`, `score.py`, `code/precommit.py`).

**No `utils.py` / `helpers.py`.** Banned at review time. Two similar lines beat
a misnamed grab-bag. Skill `scripts/` entrypoints stay thin shells; logic lives
in named submodules per ADR-0018.

**Env and path single change-points.** Raw `os.environ` reads for
`MENTAT_CHUNK_ID` and `MENTAT_CONFIG` route through `lib/chunk` and
`lib/config` accessors. Duplicate path constants live in `lib/support/paths.py`
only.

## Consequences

- New modules have a named home in ADR-0019 and `.agents/rules/code-organization.md`.
- Reviewers veto generic filenames and god-files without debating preference.
- Env/path drift is grep-testable — accessors are the only allowed read sites.
