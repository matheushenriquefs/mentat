# Credits

## Inspired by

- **[mattpocock/skills](https://github.com/mattpocock/skills)** — Engineering and productivity skills for Claude Code. Backbone of `mentat-tasks`: to-issues template, voice, LOC discipline, HITL/AFK classification, and vertical-slice doctrine.
- **[antopolskiy/kanban-md](https://github.com/antopolskiy/kanban-md)** — (no upstream description). Flavor of `mentat-tasks`: `allowed-tools:` frontmatter whitelist, atomic `pick --claim` + `claim_timeout` refresh, `review`-as-waiting-room status, board-home/worktree separation.
- **[Purple-Horizons/tick-md](https://github.com/Purple-Horizons/tick-md)** — (no upstream description). Reference for dep-graph + auto-unblock + filename convention. Acknowledged, not adopted; revisit when real pain hits.
- **bebop** (sibling project, no public URL) — "Personal news briefing pipeline — local editorial, LLM-rendered prose." Source of mentat's code-rules layer: path-scoped `.agents/rules/` files gated by a `rules-reviewer` subagent (ADR-0012). The prose-voice rules fold into `docs/STYLE.md`.

## Runtime tool dependencies

| Tool | URL | License | Used for |
|------|-----|---------|---------|
| lefthook | https://github.com/evilmartians/lefthook | MIT | Pre-commit quality gates |
