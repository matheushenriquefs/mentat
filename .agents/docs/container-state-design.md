# container-state.sh — interface design (G2-S1)

Status: Designed (G2-S1 HITL). Implementation: G2-S2.
Plan: [mentat-architecture-revamp-g2-container-quartet](../../../.agents/plans/mentat-architecture-revamp-g2-container-quartet.md)
(index: [mentat-architecture-revamp](../../../.agents/plans/mentat-architecture-revamp.md)).
Owner: `.agents/bin/lib/container-state.sh` (to be created by S2).

## Why this exists

C4 in the architecture report: 13 OCI `chdir to /workspaces/...` failures, 4
fix commits, still recurring. Each of the four `mentat-container-*` scripts
re-derives the same three invariants — `workspaceFolder`, `safe.directory`,
slug-from-`$PWD` — with subtle divergence. Whack-a-mole survives because
there is no single source of truth.

S1 produces this design doc; S2 implements; S3–S6 collapse the call sites.

## Signature convention

User decision during G2-S1 HITL: bash-idiomatic, **values on stdout, success
via exit 0 / failure via nonzero exit**.

- Helpers that produce a value (e.g. `container_id_for`) write it to stdout
  and exit `0` on success. Diagnostics go to stderr.
- Helpers that assert (e.g. `assert_safe_directory`) emit nothing on stdout
  on success; on failure they print the exact missing precondition to stderr
  and exit nonzero. **No silent fallback** — every failure mode is loud.
- All helpers are pure shell functions sourced from `container-state.sh`. No
  `set -e` reliance for branching; callers check `$?` or use `if ! helper`.

Rationale: stdout-capture (`x=$(helper "$arg")`) is the most common shape in
the existing four scripts. Keeping that shape lets S3–S6 swap inline blocks
for one-line calls without restructuring control flow.

## Invariant inventory

The three things currently re-derived across the four scripts. The lib must
absorb every site listed below — `grep -c 'workspaceFolder\|safe.directory\|basename "\$PWD"' .agents/bin/mentat-container-*`
returns 10 hits at design time (up=7, run=2, down=1, doctor=0). The doctor
script reads no invariant directly today; S6 wires it into the lib.

| # | Invariant | Today's call sites | Lib owner |
|---|-----------|---------------------|-----------|
| 1 | `workspaceFolder` — resolved from `.devcontainer/devcontainer.json` (`.workspaceFolder` field, fallback `/workspaces/<slug>`) | `mentat-container-up:20,33,41,60,145`, `mentat-container-run:23,27` | `ensure_workspace_folder` |
| 2 | `safe.directory` — `git config --global --add safe.directory <ws>` inside the container | `mentat-container-up:23,27,33,41,145` | `assert_safe_directory` |
| 3 | Slug — `basename "$PWD"`, matched to container label `mentat_slug=<slug>` | `mentat-container-down:10` (explicit `basename "$PWD"`); implicit in `mentat-container-up:11` (`SLUG=$(basename "$WT")`) and every `--filter label=mentat_slug=...` call | `container_slug_for_cwd` |

Cross-script divergence the lib closes: container-up uses `$WT=$PWD` then
`basename "$WT"`; container-down uses `basename "$PWD"` directly; future
helpers must not invent a third form.

## Helpers

Five helpers. Each section: signature, behavior, failure mode (single,
explicit — no silent fallback).

### `container_id_for`

Signature: `container_id_for <slug>` → stdout: container ID (12-char or
full). Exit `0` if a running container with `label=mentat_slug=<slug>` is
found; exit `1` if none. Stderr empty on miss (let caller decide whether
absence is fatal).

Behavior: `docker ps -q --filter "label=mentat_slug=<slug>"`, single-line
output via `head -1` (multiple matches are a separate failure — the lib
returns the first and emits a stderr warning).

Failure mode: no running container for slug → exit `1`. No silent fallback
to "search by name" or "use first running container" — those are the bugs
that caused the OCI chdir incidents.

### `ensure_workspace_folder`

Signature: `ensure_workspace_folder <ws>` (where `<ws>` is an absolute path).
Stdout: empty. Exit `0` if the container has the directory; nonzero
otherwise.

Behavior: requires `container_id_for "$slug"` upstream. Runs `docker exec
<cid> test -d <ws>`. On miss, stderr names the exact path that is missing.

Failure mode: `<ws>` does not exist inside the container → exit nonzero,
stderr: `ensure_workspace_folder: missing inside container: <ws>` (the
literal path the test asserted). No silent fallback to `--workdir /` —
explicit failure is the whole point.

### `assert_safe_directory`

Signature: `assert_safe_directory <ws>`. Stdout: empty. Exit `0` if
`safe.directory` is configured for `<ws>` inside the container; nonzero
otherwise.

Behavior: `docker exec <cid> git config --global --get-all safe.directory |
grep -Fxq "<ws>"`. The current scripts blindly re-add the entry on every
invocation (handoff Issue 4); this helper *checks* and lets the caller
choose whether to re-add.

Failure mode: `safe.directory` is unset or does not include `<ws>` → exit
nonzero, stderr: `assert_safe_directory: <ws> not in git safe.directory`.

### `synthesize_compose_if_absent`

Signature: `synthesize_compose_if_absent`. Stdout: empty. Exit `0` if a
`.devcontainer/devcontainer.json` exists OR was just synthesized; nonzero if
none of `docker-compose.yml`, `docker-compose.yaml`, or `Dockerfile*`
present.

Behavior: wraps the existing `compose-synth.sh` logic. Calls
`synthesize_devcontainer` or `synthesize_devcontainer_from_dockerfile` as
the source file dictates.

Failure mode: worktree has no compose file and no Dockerfile → exit `1`,
stderr: `synthesize_compose_if_absent: no compose / Dockerfile in
<worktree>; cannot synthesize devcontainer`. Loud, not silent — today's
behavior is to die in container-up:55 with the same message; the lib
preserves that.

### `container_slug_for_cwd`

Signature: `container_slug_for_cwd`. Stdout: slug string (one line). Exit
`0` always (a slug is always derivable from `$PWD`).

Behavior: `basename "$PWD"`. Sole canonical site. S3–S6 replace every local
`SLUG=$(basename "$PWD")` (and `SLUG=$(basename "$WT")` shape) with a call
into this helper, so future shape changes (e.g. handling worktree paths
with trailing slashes) land in one file.

Failure mode: none functional — `basename` of any non-empty path returns a
slug. The exit-0-always shape is intentional: this is the one helper that
cannot fail, and S2 tests must lock that.

## Cross-references

- **S2** (`lib/container-state.sh`) implements these signatures. Tests live
  in `evals/pytest/test_g2_s2_*.py`.
- **S3** (`mentat-container-up`), **S4** (`mentat-container-run`), **S5**
  (`mentat-container-down`), **S6** (`mentat-container-doctor`) collapse
  inline duplication into calls into this lib.
- **ADR 0004** (parallel-slicing orchestration, Docker-required) — the lib
  must stay agnostic across harnesses: it reads `$PWD` and docker labels,
  not harness-specific names.
- **handoff Issue 4** — `safe.directory` must fire every path. This design
  preserves that by exposing `assert_safe_directory` as a check-only
  predicate; callers that need re-add behavior call `git config --add`
  themselves after a failed assert.

## Out of scope for S1

- Tests for the helpers — those land in S2 alongside the implementation.
- Driver-script edits — S3 through S6.
- ADR write-up — this design lives as a free-standing doc, not an ADR
  (G2-S1 HITL choice). If a future slice promotes any decision here to
  ADR status, the ADR cross-references back to this file.
