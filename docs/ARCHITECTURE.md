# Architecture

Canonical narrative overview of Mentat. Pointers to ADRs for rationale; this file states the *what* and *how* in prose.

For the domain glossary, see [CONTEXT.md](../CONTEXT.md). For decisions, see [docs/adr/](./adr/README.md). For filesystem layout, see [.agents/docs/PATHS.md](../.agents/docs/PATHS.md).

---

## What Mentat does

Mentat is a multi-harness orchestrator for AI coding agents. It cuts a plan into independent vertical slices, fans them out into parallel devcontainer-isolated chunks, and lands each one back onto a holding branch through a serial merge queue. Each land is gated. Failures eject without blocking the queue. Surfaces stay swappable (multiplexer, harness, model, OS, arch, container engine, shell, editor, target-repo toolchain) — see `AGENTS.md` for the agnosticism mantra.

The core property: **parallel-out, serial-in.** Implementation parallelism amplifies throughput; serial landing keeps the holding branch coherent.

## Parallel fan-out, serial land

Slices run as chunks: one worktree + one devcontainer + one branch off `main`, each running its own coding agent session. The orchestrator spawns chunks concurrently (default 3; tunable via `~/.mentat/config.jsonc` `concurrency` key). Once all gates clear inside a chunk, it queues for landing.

Landing is single-threaded by construction: one ref can't move concurrently, and serial landing lets sibling divergence resolve by rebasing onto the tip the previous chunk left. See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Holding branch over merge

A holding branch (`branch/<feature>`) carries no commits of its own. Each chunk's land is `git merge --ff-only` against the holding tip — no merge commits, no host-side `git commit` invocations, so no host pre-commit hook fires (which would fail in repos where pre-commit tooling lives only in the container). When the whole batch lands green, the human merges holding into `main` from outside the loop.

This sidesteps a class of host/container tooling-divergence failures common in team repos where pre-commit hooks live only inside the container. See [ADR-0002](./adr/0002-holding-branch-over-merge.md).

## Re-gate merge queue

Per chunk at land time: rebase onto the live holding tip in-container, re-gate using the target repo's own quality gates, then ff-only. The re-gate catches semantic breakage a sibling's earlier land introduced. A red re-gate ejects the chunk — its worktree is left up for repair, the queue continues with the rest of the batch.

See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Scored review gate

Five reviewer subagents live in `.agents/agents/`:

- `mentat-plan-reviewer` — does the diff cover the plan?
- `mentat-test-reviewer` — does the implementation earn its green tests, or game them?
- `mentat-bug-reviewer` — does the diff introduce new bugs?
- `mentat-smell-reviewer` — Fowler smells, advisory.
- `mentat-context-reviewer` — does the prose stay self-contained (no plan/slice/round refs)?

Each emits a JSON verdict over the chunk; `score.py` aggregates per ADR-0003 rules: never average, veto-on-blacklist-hit > threshold. LLM never self-promotes. The reviewer pass runs once at end-of-queue over the final landed tip (advisory — inspect-after — until each reviewer earns a false-pass record).

See [ADR-0003](./adr/0003-scored-review-gate.md).

## Deterministic gating + anti-cheat

Two enforcement layers, both project-tool-agnostic:

1. **Impl-only-after-red contract.** The coding agent writes implementation code only after a failing test exists in the commit log. The container test-mount enforces this softly: tests in the manifest's `closed` list are mounted read-only until the agent emits `mark-test-writable`, audited via `test.writable.requested`.
2. **Trajectory blacklist** in `mentat-bug-reviewer`. Forbidden reward-hacking moves (runner redirection, test deletion, asserting the inverse) → hard 0.0 veto, no threshold mediation.

See [ADR-0006](./adr/0006-soft-readonly-test-enforcement.md) and [ADR-0010](./adr/0010-readonly-test-mount.md).

## AFK vs HITL routing

Each slice carries a `class:` tag in its plan frontmatter:

- **AFK** — headless, no interactive user-prompt tool allowed. Ambiguity at runtime is ejection, not a question. The harness adapter disables its interactive-prompt tool (e.g. Claude Code's `AskUserQuestion`, Cursor's equivalent) and adds a system clause forbidding self-answer.
- **HITL** — interactive. Stalls for review at decision points.

The orchestrator routes plans accordingly. AFK depends on the scored gate (ADR-0003) — that's what makes trusting unattended runs possible.

See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Audit envelope

Every command emits start + complete events through `mentat-log emit`. Nine canonical event types — `plan.started`, `plan.succeeded`, `plan.failed`, `chunk.started`, `chunk.ejected`, `chunk.landed`, `batch.started`, `batch.succeeded`, `test.writable.requested` — written NDJSON to `~/.mentat/logs/<repo>/<session>/<agent>-<slug>.jsonl`. Raw harness stdout goes to a sibling `.stdout` file (opaque). Subprocess stderr goes to `.stderr/<...>.stderr`.

`mentat-session track` watches the live JSONL. `mentat-session doctor` writes a per-session diagnosis markdown after the batch.

See [ADR-0007](./adr/0007-audit-envelope.md).

## Plugin API

Four extension surfaces, all swap-in / no-fork:

- **Rubric slot** — drop a reviewer subagent body into `.agents/agents/<name>-reviewer.md`. Auto-discovered.
- **Gate slot** — drop a Python module exposing `run(chunk_path) -> (verdict, message)` into `.agents/lib/gates/code/`. Auto-discovered.
- **Diff provider** — implement `DiffProvider.render(base, head) -> str`. Built-in: `git`. Declare in `~/.mentat/config.jsonc` `diff_tool`.
- **Harness adapter** — implement `HarnessProvider.spawn(prompt, **opts)`. Built-in: `claude-code`, `cursor`. Declare in `~/.mentat/config.jsonc` `harness`.

Mentat core stays minimal; project-specific concerns extend through slots without forking.

See [ADR-0009](./adr/0009-plugin-api.md) and [docs/PLUGINS.md](./PLUGINS.md).

## Python runtime

User-facing bin layer (`.agents/skills/mentat-*/scripts/`): stdlib-only Python 3.11+. No third-party imports — installs work on bare Python without pip.

Dev layer (`tests/`, `evals/`): pinned dependencies via `uv`. Linting via `ruff`, type checking via `pyright`, tests via `pytest`. Driven from `pyproject.toml`.

See [ADR-0008](./adr/0008-python-runtime.md). Target-repo tool routing lives in the [Devcontainer-first](#devcontainer-first) section below.

## Sub-agent delegation

Cavecrew variants (`cavecrew-investigator`, `cavecrew-builder`, `cavecrew-reviewer`) for compressed findings — main context eats ~60% fewer tokens. Vanilla (`Explore`, code reviewer) for prose-heavy work where rationale matters. `mentat-researcher` for external facts (papers, docs, repos). Rule lives in `.agents/AGENTS.md`, not in command bodies — every harness reads it the same way.

See [ADR-0001](./adr/0001-sub-agent-delegation.md).

## Harness-agnostic adapters

Headless agent CLIs are pluggable. Current Python-era adapters:

| Harness | Module | Status |
|---|---|---|
| `claude-code` | `.agents/skills/mentat-implement/scripts/harness/claude_code.py` | landed |
| `cursor` | `.agents/skills/mentat-implement/scripts/harness/cursor.py` | landed |

Adding a harness: drop a module exposing `cmd()`, `output_format()`, `normalize()` into the harness dir. The orchestrator auto-discovers and the implementation skill picks it up. No core changes needed.

Config is resolved as a layered stack (highest precedence first):

| Layer | Source | Precedence |
|---|---|---|
| CLI flag | `--harness <n>`, `--model <s>` | highest |
| Repo overlay | `<repo-root>/.mentat/config.jsonc` | over global |
| Global | `~/.mentat/config.jsonc` | base |

Merge is shallow (`{**global, **repo}`); repo wins per top-level key. Plugin lists are NOT merged — a repo `plugins` key replaces the global list. Scaffold with `mentat-install --repo`.

## Devcontainer-first

Docker is required. Every project-tool invocation routes through `mentat-container run '<cmd>'`. The driver names no specific language, test framework, or build tool — the container provides them. This is the agnosticism contract.

The container exposes the worktree at `/workspaces/<slug>`. Git resolution into the worktree is fixed up via `--mount type=bind,source=$ROOT/.git,target=$ROOT/.git` and `GIT_DIR`/`GIT_WORK_TREE` remote env vars. The host's uid owning `.git` gets a `safe.directory` post-up.

See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Layout pointer

For the full filesystem layout — user state at `~/.mentat/`, harness-shared at `~/.agents/`, repo dev tree at `<repo>/.agents/`, repo user-facing docs at `<repo>/docs/` — see [.agents/docs/PATHS.md](../.agents/docs/PATHS.md).
