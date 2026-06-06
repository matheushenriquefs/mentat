# Skills

Skills are organized by bucket. Install via `bin/mentat-update` or Claude Code's skill manager.

See [AGENTS.md](../AGENTS.md) for workflow rules and [vendir.yml](../../vendir.yml) for vendored sources.

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

Skills from external upstreams (mattpocock/skills, juliusbrussee/caveman, mastra-ai/mastra) are vendored via
[`bin/mentat-update`](../bin/mentat-update) (wraps `vendir sync`). See [vendir.yml](../../vendir.yml) for pins.
