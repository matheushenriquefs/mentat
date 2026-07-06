# ADR Index

Architecture Decision Records for Mentat.

| ADR | Title | Status |
|---|---|---|
| [0001](./0001-sub-agent-delegation.md) | Sub-agent delegation — cavecrew vs vanilla | Accepted |
| [0002](./0002-holding-branch-over-merge.md) | Holding branch over merge | Accepted |
| [0003](./0003-scored-review-gate.md) | Scored review gate | Accepted |
| [0004](./0004-parallel-orchestration.md) | Parallel orchestration (folds HITL + decomp + harness-registry) | Accepted |
| [0005](./0005-ubiquitous-lexicon.md) | Ubiquitous lexicon (slice/chunk/batch) | Accepted |
| [0006](./0006-soft-readonly-test-enforcement.md) | Soft read-only test enforcement | Accepted |
| [0007](./0007-audit-envelope.md) | Audit envelope — 9-event catalog | Accepted |
| [0008](./0008-python-runtime.md) | Python runtime | Accepted |
| [0009](./0009-plugin-api.md) | Plugin API (Vite-derived, one slot: harness) | Retired |
| [0010](./0010-readonly-test-mount.md) | Read-only test mount (OCP manifest + bind-mount) | Accepted |
| [0011](./0011-compose-aware-container.md) | Compose-aware container bring-up (sidecar detection + dev-service layering + host opt-out) | Accepted |
| [0012](./0012-code-rules-layer.md) | Code-rules layer | Accepted |
| [0013](./0013-session-continuity-over-compaction.md) | Session continuity over compaction — checkpoint + respawn, harness-agnostic | Accepted |
| [0014](./0014-coverage-gate.md) | Coverage gate — 90% unit / e2e journey floor, blocking | Accepted |
| [0015](./0015-auto-recovery.md) | Model-driven auto-recovery — JIT retry/reslice/abandon + storm/budget/attempt caps | Accepted |
| [0016](./0016-mutation-signal.md) | Mutation signal — advisory surviving-mutant hint, never a gate | Accepted |
| [0017](./0017-per-run-isolation.md) | Per-run isolation — chunk-keyed identity, override-config, run-scoped prune, OOM recover | Accepted |
