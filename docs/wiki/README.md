# Mentat

Parallel-slicing orchestration harness. Fan out planned chunks across worktrees + devcontainers, land each serially through a scored gate.

## Reference

- [Architecture](../ARCHITECTURE.md) — narrative overview.
- [Glossary](../../CONTEXT.md) — slice / chunk / batch / land / eject / AFK / HITL.
- [ADRs](../adr/README.md) — architecture decision records.
- [Filesystem layout](../../.agents/docs/PATHS.md) — every path Mentat reads or writes.
- [Style guide](../STYLE.md) — voice classes, LOC budgets, banned words.
- [Plugin API](../PLUGINS.md) — rubric + gate extension slots.
- [Exit codes](../EXIT-CODES.md) — BSD sysexits convention.
