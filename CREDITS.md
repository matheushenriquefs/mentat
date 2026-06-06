<!-- AUTO-GENERATED header and Vendored section by bin/mentat-update — do not edit those sections -->
# Credits

## Vendored

Upstreams managed by [vendir](https://carvel.dev/vendir/). Regenerate: `bin/mentat-update`.

| Name | URL | Pin | Description |
|------|-----|-----|-------------|
| juliusbrussee/caveman | https://github.com/JuliusBrussee/caveman | (run mentat-update to populate) | Token-optimized terse communication mode skill |
| mattpocock/skills | https://github.com/mattpocock/skills | (run mentat-update to populate) | Engineering and productivity skills for Claude Code |
| mastra-ai/mastra | https://github.com/mastra-ai/mastra | (run mentat-update to populate) | Mastra eval scorers used in ADR-0003 review gate |

## Inspired by

- **[mattpocock/skills](https://github.com/mattpocock/skills)** — Engineering and productivity skills for Claude Code. Backbone of `mentat-tasks`: to-issues template, voice, LOC discipline, HITL/AFK classification, and vertical-slice doctrine.
- **[antopolskiy/kanban-md](https://github.com/antopolskiy/kanban-md)** — (no upstream description available). Flavor of `mentat-tasks`: `allowed-tools:` frontmatter whitelist, atomic `pick --claim` + `claim_timeout` refresh, `review`-as-waiting-room status, board-home/worktree separation.
- **[Purple-Horizons/tick-md](https://github.com/Purple-Horizons/tick-md)** — (no upstream description available). Reference for dep-graph + auto-unblock + filename convention. Acknowledged, not adopted; revisit when real pain hits.

## Runtime tool dependencies

| Tool | URL | License | Used for |
|------|-----|---------|---------|
| vendir | https://github.com/carvel-dev/vendir | Apache-2.0 | Declarative vendoring (S3) |
| lefthook | https://github.com/evilmartians/lefthook | MIT | Pre-commit quality gates |
| yq | https://github.com/mikefarah/yq | MIT | Task md frontmatter mutation (mentat-tasks) |
| jq | https://github.com/jqlang/jq | MIT | Bash+jq pipelines across bin/ |
