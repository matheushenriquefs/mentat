# ADR 0017: Per-run isolation

Status: Accepted
Date: 2026-07-05

## Context

Parallel AFK agents in the same repo corrupted each other when identity was keyed
only by plan slug: shared holding refs, HEAD flips on the main tree, machine-wide
docker prune reaping live containers, and in-place `devcontainer.json` mutation
blocking rebase. See plan `mentat-run-isolation`.

## Decision

**Chunk-keyed identity.** One derivation `chunk_slug(chunk_id, slug) →
"<chunk_id>/<slug>"` names the holding branch, worktree dir
(`.mentat/worktrees/<chunk_id>/<slug>`), and container label
(`mentat_chunk=<chunk_slug>`). `chunk_id` is a uuid7 minted per chunk execution.

**Non-mutating devcontainer.** Per-chunk config is generated at
`.mentat/config/<chunk_id>/<slug>/devcontainer.json` and passed via
`devcontainer up --override-config`. The tracked worktree `devcontainer.json` is
never written. `workspace_folder_for(worktree_path)` is a pure derivation used at
config-gen and exec time — no JSONC re-parse, no capture.

**Run-scoped teardown.** Orchestrate holds the set of `chunk_slug` values it
minted. Container down and worktree prune iterate that set only; machine-wide
`docker container prune` and cross-run worktree removal are forbidden.

**OOM detect-and-recover.** On container-down eject, read
`docker inspect --format '{{.State.OOMKilled}}'` (exit 137 alone is ambiguous).
OOM-killed chunks eject as `worker-died` with `killed_by: oom` — resource-transient,
handled by the recovery engine (ADR-0015).

**CPU governor declined.** CPU oversubscription is latency-only and self-healing;
memory OOM is the failure that kills work. Recovery handles aggregate pressure
reactively; a machine-wide admission gate would duplicate that.

**`MENTAT_CHUNK_MEMORY`.** Optional per-chunk `--memory` cap injected into
override-config `runArgs` when set (`--memory-swap` equals `--memory`). Default
unset — unmeasured caps false-OOM legitimate work.

## Cross-references

- [ADR-0002](./0002-holding-branch-over-merge.md) — holding branch model
- [ADR-0005](./0005-ubiquitous-lexicon.md) — chunk / slice lexicon
- [ADR-0015](./0015-auto-recovery.md) — transient eject recovery

## Consequences

- `worktree_for_*` raises `GitError` on miss; never `Path.cwd()`.
- `chunk_started` audit records the child's real worktree path.
- Concurrent runs in one repo cannot prune or down each other's resources.
