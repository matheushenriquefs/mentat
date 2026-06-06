# Skills

Skills are organized by bucket. Install via `bin/mentat-sync-upstream` or Claude Code's skill manager.

See [AGENTS.md](../AGENTS.md) for workflow rules and [upstreams.jsonc](../../upstreams.jsonc) for vendored sources.

## Buckets

| Bucket | Purpose |
|--------|---------|
| [engineering/](engineering/) | Code review, TDD, diagnosis, architecture |
| [productivity/](productivity/) | Triage, handoff, planning |
| [misc/](misc/) | Uncategorized |
| [personal/](personal/) | User-specific workflows |
| [in-progress/](in-progress/) | Drafts not yet ready |
| [deprecated/](deprecated/) | Retired skills — kept for reference |

## Upstream skills

Skills from external upstreams (mattpocock/skills, vercel-labs/skills) are installed via
[`bin/mentat-sync-upstream`](../bin/mentat-sync-upstream). See [upstreams.jsonc](../../upstreams.jsonc) for pins.
