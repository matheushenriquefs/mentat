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

| | Mentat | dmux | swarm | claude-flow |
|---|---|---|---|---|
| Parallel fan-out | ✓ | ✓ | ✓ | ✓ |
| Serial land queue | ✓ | — | — | — |
| Deterministic gate | ✓ | — | — | partial |
| Anti-cheat blacklist | ✓ | — | — | — |
| Host toolchain required | none | none | varies | node |
| Harness agnostic | ✓ | — | — | — |
| Docker required | ✓ | — | — | — |

<!-- Docs ------------------------------------------------------------------ -->

## Docs

Full documentation lives in the [wiki](../../wiki).

<!-- Status ---------------------------------------------------------------- -->

## Status

<!-- Honest bounds: what works, what is on probation, what is not yet done -->

<!-- License --------------------------------------------------------------- -->

## License & credits

MIT. Third-party skills vendored via [`vendir.yml`](vendir.yml) — attributions in [CREDITS.md](CREDITS.md).
