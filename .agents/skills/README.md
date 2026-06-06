# Skills

Skills are organized by bucket. Install via `bin/mentat-install` or Claude Code's skill manager.

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

Vendored skills from external upstreams are declared in [`vendir.yml`](../../vendir.yml) and materialized under
`vendor/<user>/<repo>/` by `bin/mentat-update` (wraps `vendir sync`). Pins are in `vendir.lock.yml`.
