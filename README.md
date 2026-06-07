# Mentat

> _Parallel-out, serial-in. Agents work unattended because the harness keeps them honest._

<!-- TL;DR ----------------------------------------------------------------- -->

## What it is

<!-- 3–5 lines: what + why + diff vs dmux/swarm -->

## Demo

<!-- Hero asciicast — land C3 first -->
![demo](docs/assets/demo.cast.gif)

<!-- Install --------------------------------------------------------------- -->

## Install

```bash
# one-liner
curl -fsSL https://raw.githubusercontent.com/matheushenriquefs/mentat/main/bin/mentat-install | sh

# or clone and run directly
git clone https://github.com/matheushenriquefs/mentat
bin/mentat-install
```

<!-- Quickstart ------------------------------------------------------------ -->

## Quickstart

```bash
# 1. create a plan
/mentat-plan "add OAuth endpoint"

# 2. fan out: each slice gets its own worktree + container + branch
bin/mentat-orchestrate branch/oauth plan-oauth.md

# 3. watch the batch land
/mentat-track

# 4. review any ejected chunks
bin/mentat-worktree-list

# 5. merge when green
git checkout main && git merge --ff-only branch/oauth
```

<!-- Concepts -------------------------------------------------------------- -->

## Concepts

| Term | Meaning |
|------|---------|
| **slice** | A planned tracer-bullet cut — a `plan.md` |
| **chunk** | The running execution of one slice (worktree + container + branch) |
| **batch** | All chunks in one `mentat-orchestrate` run |
| **holding branch** | `branch/<feature>` — a moving pointer, no commits of its own |
| **land** | Rebase chunk onto holding tip → re-gate → ff-only |
| **eject** | Gate failed — chunk left up for repair, queue continues |
| **AFK / HITL** | Away-from-keyboard (unattended) vs. human-in-the-loop (stalls for review) |

Full glossary and ADR index: [CONTEXT.md](CONTEXT.md)

<!-- Comparison ------------------------------------------------------------ -->

## How it compares

| | Mentat | dmux [^1] | swarm [^2] | claude-flow [^3] |
|---|---|---|---|---|
| Parallel fan-out | ✓ | ✓ [^4] | ✓ [^5] | ✓ [^6] |
| Serial land queue | ✓ | — | — | — |
| Deterministic gate | ✓ | — | — | partial [^7] |
| Anti-cheat blacklist | ✓ | — | — | — |
| Host toolchain required | none | none [^8] | python [^9] | node [^10] |
| Harness agnostic | ✓ | — [^11] | — | — [^12] |
| Docker required | ✓ | — | — | — |

[^1]: dmux — tmux-based Claude Code pane manager. Runs multiple Claude Code sessions in parallel tmux panes. No merge queue or quality gate. <https://github.com/matheushenriquefs/mentat/tree/main/.dmux>
[^2]: OpenAI Swarm — "lightweight, highly controllable, and easily testable" multi-agent coordination via `Agent`s and handoffs. Deprecated in favour of [OpenAI Agents SDK](https://github.com/openai/openai-agents-python). <https://github.com/openai/swarm>
[^3]: claude-flow (now Ruflo) — "Multi-agent AI harness for Claude Code and Codex." Orchestrates swarms via `npx ruflo init`. <https://github.com/ruvnet/claude-flow>
[^4]: dmux spawns one Claude Code pane per task; panes run concurrently inside tmux.
[^5]: Swarm routes between agents via handoffs; concurrent calls possible via Python async. README: "powerful enough to express rich dynamics between tools and networks of agents."
[^6]: Ruflo: "Orchestrate 100+ specialized AI agents across machines, teams, and trust boundaries." Swarm plugin coordinates agents as a team.
[^7]: Ruflo includes a routing layer and autopilot loop but no deterministic scored gate or veto system equivalent to ADR 0003.
[^8]: dmux is a shell script + tmux; no language runtime required on the host beyond tmux and a terminal.
[^9]: Swarm README: "Requires Python 3.10+". Install via `pip install git+https://github.com/openai/swarm.git`.
[^10]: Ruflo README: "One `npx ruflo init` gives Claude Code a nervous system." Requires Node.js/npm for `npx`.
[^11]: dmux is tightly coupled to Claude Code; it reads `.dmux.config.json` and launches `claude` sessions directly.
[^12]: Ruflo targets Claude Code and Codex explicitly; README badge: "Claude Code — Plugin".

<!-- Docs ------------------------------------------------------------------ -->

## Docs

Full documentation lives in the [wiki](../../wiki).

<!-- Status ---------------------------------------------------------------- -->

## Status

<!-- Honest bounds: what works, what is on probation, what is not yet done -->

<!-- License --------------------------------------------------------------- -->

## License & credits

MIT. Third-party skills vendored via [`vendir.yml`](vendir.yml) — attributions in [CREDITS.md](CREDITS.md).
