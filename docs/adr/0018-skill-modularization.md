# ADR 0018: Skill modularization boundaries + rename map

Status: Accepted
Date: 2026-07-06

## Context

Several skill `scripts/` modules grew into god-files (`orchestrate.py` ~1300 LOC,
`track.py` ~600, `container.py` ~670 with `override.py`). `lib/` is already
well-factored. The owner wants each skill's `scripts/` to be a private workspace of
scoped submodules with factories and sub-packages — bebop-level internal structure —
and every module/class/function renamed per [`.agents/rules/naming.md`](../../.agents/rules/naming.md).
Behaviour is preserved; public entrypoints (`orchestrate.py`, `container.py`,
`track.py` CLIs) stay stable.

## Decision

### Orchestrate (`mentat-orchestrate/scripts/`)

| Submodule | Responsibility | Source today |
|---|---|---|
| `orchestrate.py` | CLI entry, `run_orchestrate`, argparse | thin shell over submodules |
| `scheduler.py` | Plan graph, readiness, `Plan` type | unchanged |
| `plans.py` | Plan load, gate runner, config read | unchanged |
| `spawn.py` | AFK fan-out, subprocess spawn | `fan_out.py` (rename) |
| `landing.py` | Serial land-queue, rebase + gate + ff-merge | `land_queue.py` (rename) |
| `recover.py` | Auto-recovery drain, respawn, reslice | unchanged |
| `supervise.py` | Async chunk supervision, circuit breaker, stall | extracted from `orchestrate.py` |
| `batch.py` | Batch coordinator loop, prune, recovery wire-up | extracted from `orchestrate.py` |

Test layout mirrors source: `test_spawn.py`, `test_landing.py`, `test_supervise.py`,
`test_batch.py` — split from `test_orchestrate.py` monolith.

### Container (`mentat-container/scripts/`)

| Submodule | Responsibility | Source today |
|---|---|---|
| `container.py` | CLI entry, argparse | thin shell |
| `client.py` | `ContainerService` — docker/devcontainer exec | `client.py` (rename) |
| `override.py` | RI2 override-config generation | `override.py` (rename) |
| `lifecycle.py` | `cmd_up`, `cmd_down`, safe-directory, identity | extracted from `container.py` |
| `runtime.py` | Host-vs-container runtime select, env scrub | extracted from `container.py` |
| `doctor.py` | `cmd_doctor` sections | extracted from `container.py` |

### Track skill (`mentat-track/` → `mentat-track/`)

| Submodule | Responsibility | Source today |
|---|---|---|
| `track.py` | CLI entry (`track`, `list`, `status`) | thin shell |
| `render.py` | TUI render, transcript coloring | extracted from `track.py` |
| `registry.py` | Agent list/filter, `AgentDAO` wire-up | extracted from `sessions.py` |
| `panes.py` | Pane layout, viewport | extracted from `track.py` |
| `agent.py` | Id mint (`make_agent_id`), agent resolution | `session.py` + `sessions.py` |

Entity rename during split: `view_session`→`view_agent`, `SessionRecord`→`Agent`,
`SessionStatus`→`AgentStatus = Literal[...]`, `_resolve_session`→`_resolve_agent`.
Skill dir `mentat-track/` → `mentat-track/`; install symlinks and evals follow.

### Shared lib moves

| Current | Target | Rule |
|---|---|---|
| `lib/harness_stream.py` | `lib/harness/schema.py` | package supplies context |
| `mentat-implement/scripts/harness_utils.py` | `mentat-implement/scripts/harness/utils.py` | scoped under existing package |
| `mentat-install/scripts/render.py` | `mentat-install/scripts/report.py` | skill scopes it |
| `lib/{backoff,paths,frontmatter}.py` | `lib/support/{backoff,paths,frontmatter}.py` | pure helpers grouped |

### File rename map (scope-noun, no prefix)

| Current | → |
|---|---|
| `fan_out.py` | `spawn.py` |
| `land_queue.py` | `landing.py` |
| `override.py` | `override.py` |
| `client.py` | `client.py` (`ContainerService`) |
| `harness_stream.py` | `lib/harness/schema.py` |
| `harness_utils.py` | `harness/utils.py` |
| install `render.py` | `report.py` |
| skill `mentat-track/` | `mentat-track/` |

Function-level renames are owned by their feature plans and are **not** duplicated
here: `mentat-log query`→`list` (drift-guardrail), `next_ready`→`list_ready_slices`
(fail-loud), `partition_by_outcome` (eject-reasons), `make_recovery_seed` /
`make_recovery_prompt` (track-storage V3).

### Domain-model promotions

Frozen `@dataclass` types to introduce or consolidate (evidence-checked):

| Type | Source | Notes |
|---|---|---|
| `Config` | `config.py:81` | dict read by 8+ modules — highest leverage |
| `LandVerdict` | `landing.py:84` | land-queue return shape |
| `BatchResult` | `orchestrate.py:531` | renamed from positional fan-out tuple |
| `RebaseResult` | `git.py:97` | ff-rebase outcome |
| `RecoveryOutcome` | `recover.py:319+` | recovery drain result |

Held-state resources become `<Thing>Service`: `ContainerService`, `GitService`,
`WorktreeService`. Pure helpers stay functions.

### ES5 dropped

`.worktreeinclude` local-file seed is **out of scope**. RI2
([ADR-0017](./0017-per-run-isolation.md)) fixes devcontainer dirt at the root via
`--override-config`; no concrete non-devcontainer dirt source remains.

## Consequences

- Public CLI paths unchanged; importers update to new module names.
- `test_orchestrate.py` and `test_implement.py` monoliths split to mirror modules.
- `mentat-track` skill name retires; docs, install symlinks, and evals reference
  `mentat-track` only.
- `lib/support/` is optional grouping — core subsystems (`git`, `events`, `store`)
  stay top-level `lib/` modules.
