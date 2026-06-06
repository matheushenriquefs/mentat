# Mentat

> "Once men turned their thinking over to machines in the hope that this would set them free. But that only permitted other men with machines to enslave them."
> — *Dune*, Frank Herbert

Agents can work unattended *because* the harness keeps them honest — isolated chunks, deterministic gates, an anti-cheat blacklist.

A lean, agnostic harness for orchestrating parallel coding agents.

## How it works

1. **Cut.** `/to-plan` slices a feature into vertical tracer-bullet cuts — each a `plan.md`. AFK slices gate and land unattended; HITL slices pause for review.
2. **Fan out.** `bin/to-orchestrate` launches each slice as a chunk: isolated worktree, devcontainer, and branch off `main`. Up to 3 run in parallel.
3. **Re-gate on land.** The serial land pass is a merge queue. Per chunk: rebase onto the live holding-branch tip inside the container, re-gate with the target repo's own quality gates, then `merge --ff-only`. Semantic breakage from a sibling's land is caught here. Red → eject; queue continues.
4. **Hold, don't merge.** The holding branch (`branch/<feature>`) carries no commits of its own — every land is a fast-forward. No host-side pre-commit ever fires.

Anti-cheat is structural: the impl-only-after-red contract (agents write implementation only after a failing test) plus a trajectory blacklist in the reviewer gate (forbidden reward-hacking moves → hard veto). The driver names no project tool and holds no project knowledge — agents read the target repo's own docs and run its gates.

See [CONTEXT.md](CONTEXT.md) for the full glossary and ADR index.

## Quickstart

```bash
# Bring up the devcontainer for a worktree
bin/devcontainer-up

# Run a command inside the container
bin/devcontainer-run 'npm test'

# Fan out planned slices onto a holding branch
bin/to-orchestrate branch/my-feature plan1.md plan2.md plan3.md
```

## Requirements

- git
- jq
- Docker

No language toolchain on the host. Mentat declares no interpreter, formatter, linter, or test runner — those run inside the target repo's devcontainer.

## No-framework thesis

Bash + jq + prompts.

No SDK, no orchestration framework, no platform lock. The driver (`to-orchestrate`) is ~260 lines of shell. The gate logic is in reviewer prompt files. The harness abstraction (`to-track-harness`, `harness-map.jq`) normalizes `cursor-agent` and `claude-code` stream-json — swapping harnesses is a config change, not a rewrite.

The constraint is Docker. Everything else is a text file.
