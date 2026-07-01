# Architecture

Canonical narrative overview of Mentat. Pointers to ADRs for rationale; this file states the *what* and *how* in prose.

For the domain glossary, see [CONTEXT.md](../CONTEXT.md). For decisions, see [docs/adr/](./adr/README.md). For filesystem layout, see [.agents/docs/PATHS.md](../.agents/docs/PATHS.md).

---

## What Mentat does

Mentat is a multi-harness orchestrator for AI coding agents. It cuts a plan into independent vertical slices, fans them out into parallel devcontainer-isolated chunks, and lands each one back onto a holding branch through a serial merge queue. Each land is gated. Failures eject without blocking the queue. Surfaces stay swappable (multiplexer, harness, model, OS, arch, container engine, shell, editor, target-repo toolchain) — see `AGENTS.md` for the agnosticism mantra.

The core property: **parallel-out, serial-in.** Implementation parallelism amplifies throughput; serial landing keeps the holding branch coherent.

## Parallel fan-out, serial land

Slices run as chunks: one worktree + one devcontainer + one branch off `main`, each running its own coding agent session. The orchestrator spawns chunks concurrently (default 3; tunable via `~/.mentat/config.toml` `concurrency` key). Once all gates clear inside a chunk, it queues for landing.

Landing is single-threaded by construction: one ref can't move concurrently, and serial landing lets sibling divergence resolve by rebasing onto the tip the previous chunk left. See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Holding branch over merge

A holding branch (`branch/<feature>`) carries no commits of its own. Each chunk's land is `git merge --ff-only` against the holding tip — no merge commits, no host-side `git commit` invocations, so no host pre-commit hook fires (which would fail in repos where pre-commit tooling lives only in the container). When the whole batch lands green, the human merges holding into `main` from outside the loop.

This sidesteps a class of host/container tooling-divergence failures common in team repos where pre-commit hooks live only inside the container. See [ADR-0002](./adr/0002-holding-branch-over-merge.md).

## Re-gate merge queue

Per chunk at land time: rebase onto the live holding tip in-container, re-gate using the target repo's own quality gates, then ff-only. The re-gate catches semantic breakage a sibling's earlier land introduced. A red re-gate ejects the chunk — its worktree is left up for repair, the queue continues with the rest of the batch.

See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Scored review gate

Six reviewer subagents live in `.agents/agents/`:

- `mentat-plan-reviewer` — does the diff cover the plan? *Threshold.*
- `mentat-test-reviewer` — does the implementation earn its green tests, or game them? *Threshold.*
- `mentat-bug-reviewer` — does the diff introduce new bugs, and does the trajectory hit the anti-cheat blacklist? *Veto.*
- `mentat-rules-reviewer` — does the code follow the rules layer? *Veto.*
- `mentat-context-reviewer` — does the prose stay self-contained (no plan/slice/round refs)? *Veto.*
- `mentat-smell-reviewer` — Fowler smells. *Advisory.*

Each emits a JSON verdict over the chunk; `score.py` aggregates per ADR-0003 rules: never average, veto > threshold. A single veto blocks; threshold reviewers must each clear their bar; the advisory smell pass never blocks. The LLM never self-promotes.

This is the per-chunk gate that runs at implement and land time. Separately, `mentat-orchestrate` runs an end-of-queue batch review over the final landed tip — an advisory, inspect-after pass, distinct from the per-chunk gate.

See [ADR-0003](./adr/0003-scored-review-gate.md) and [ADR-0012](./adr/0012-code-rules-layer.md).

## Deterministic gating + anti-cheat

Two enforcement layers, both project-tool-agnostic:

1. **Impl-only-after-red contract.** The coding agent writes implementation code only after a failing test exists in the commit log. The container test-mount enforces this softly: tests in the manifest's `closed` list are mounted read-only until the agent emits `mark-test-writable`.
2. **Trajectory blacklist** in `mentat-bug-reviewer`. Forbidden reward-hacking moves (runner redirection, test deletion, asserting the inverse) → hard 0.0 veto, no threshold mediation.

See [ADR-0006](./adr/0006-soft-readonly-test-enforcement.md) and [ADR-0010](./adr/0010-readonly-test-mount.md).

## Coverage gate

Coverage is a blocking gate, run by `task coverage`, in two branch-coverage passes: the fast unit suite (`-m "not e2e"`) over `.agents/lib`, `.agents/skills`, and `tasks` must hit **100% testable-line** (floor in `pyproject.toml` `fail_under`), and the `e2e`-marked journeys over `.agents` must hit **99%**. Entrypoints, `TYPE_CHECKING` blocks, and the stdlib-only `sys.path` bootstrap idiom are omit-listed; raw-tty I/O shells are covered through their extracted pure helpers, not by driving the terminal. A branch that drops below its floor fails the land the same way a red test does.

See [ADR-0014](./adr/0014-coverage-gate.md).

## AFK vs HITL routing

Each slice carries a `class:` tag in its plan frontmatter:

- **AFK** — headless, no interactive user-prompt tool allowed. Ambiguity at runtime is ejection, not a question. The harness adapter disables its interactive-prompt tool (e.g. Claude Code's `AskUserQuestion`, Cursor's equivalent) and adds a system clause forbidding self-answer.
- **HITL** — interactive. Stalls for review at decision points.

The orchestrator routes plans accordingly. AFK depends on the scored gate (ADR-0003) — that's what makes trusting unattended runs possible.

See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Audit envelope

Commands emit events through `mentat-log emit`. Nine canonical event types — `plan.started`, `plan.succeeded`, `plan.failed`, `chunk.spawned`, `chunk.landed`, `chunk.ejected`, `gate.evaluated`, `review.submitted`, `batch.reviewed` — written NDJSON to `~/.mentat/logs/<repo>/<session>/<agent>-<slug>.jsonl`. Raw harness stdout goes to a sibling `.stdout` file (opaque). Subprocess stderr goes to `.stderr/<...>.stderr`. The catalog is defined once in `mentat-log/scripts/log.py` as `EVENT_CATALOG`.

`mentat-session track` watches the live JSONL. `mentat-session doctor` writes a per-session diagnosis markdown after the batch.

See [ADR-0007](./adr/0007-audit-envelope.md).

## Plugin API

The formal plugin surface is one slot: **harness**. A plugin package registers
through a `mentat-plugin` entry point and fills the `harness` slot with a
`HarnessProvider`; resolution is first-wins, with the built-in adapters as the
last-resort fallback. Declare the active harness via `~/.mentat/config.toml`
`harness`. Built-in: `claude-code`, `cursor`.

Two more surfaces extend by filesystem convention rather than the plugin registry:

- **Reviewers** — drop a reviewer subagent body into `.agents/agents/<name>-reviewer.md`.
- **Code gates** — drop a Python module exposing `run(chunk_path) -> (verdict, message)` into `.agents/lib/gates/code/`.

Diff rendering is not a slot: set `diff_tool` in `~/.mentat/config.toml` and Mentat
prints that command as the review suggestion at run end.

Mentat core stays minimal; project-specific concerns extend through these surfaces
without forking.

See [ADR-0009](./adr/0009-plugin-api.md) and [docs/PLUGINS.md](./PLUGINS.md).

## Python runtime

User-facing bin layer (`.agents/skills/mentat-*/scripts/`): stdlib-only Python 3.11+. No third-party imports — installs work on bare Python without pip.

Dev layer (`tests/`, `evals/`): pinned dependencies via `uv`. Linting via `ruff`, type checking via `pyright`, tests via `pytest`. Driven from `pyproject.toml`.

See [ADR-0008](./adr/0008-python-runtime.md). Target-repo tool routing lives in the [Devcontainer-first](#devcontainer-first) section below.

## Sub-agent delegation

Cavecrew variants (`cavecrew-investigator`, `cavecrew-builder`, `cavecrew-reviewer`) for compressed findings — main context eats ~60% fewer tokens. Vanilla (`Explore`, code reviewer) for prose-heavy work where rationale matters. `mentat-researcher` for external facts (papers, docs, repos). Rule lives in `.agents/AGENTS.md`, not in command bodies — every harness reads it the same way.

See [ADR-0001](./adr/0001-sub-agent-delegation.md).

## Harness-agnostic adapters

Headless agent CLIs are pluggable. Built-in adapters:

| Harness | Module |
|---|---|
| `claude-code` | `.agents/skills/mentat-implement/scripts/harness/claude_code.py` |
| `cursor` | `.agents/skills/mentat-implement/scripts/harness/cursor.py` |

Adding a harness: drop a module exposing `cmd()`, `output_format()`, `normalize()` into the harness dir. The orchestrator auto-discovers and the implementation skill picks it up. No core changes needed.

Config is resolved as a layered stack (highest precedence first):

| Layer | Source | Precedence |
|---|---|---|
| CLI flag | `--harness <n>`, `--model <s>` | highest |
| Repo overlay | `<repo-root>/.mentat/config.toml` | over global |
| Global | `~/.mentat/config.toml` | base |

Merge is shallow (`{**global, **repo}`); repo wins per top-level key. Plugin lists are NOT merged — a repo `plugins` key replaces the global list. Scaffold with `mentat-install --repo`.

## Devcontainer-first

Docker is required. Every project-tool invocation routes through `mentat-container run '<cmd>'`. The driver names no specific language, test framework, or build tool — the container provides them. This is the agnosticism contract.

The container exposes the worktree at `/workspaces/<slug>`. Git resolution into the worktree is fixed up via `--mount type=bind,source=$ROOT/.git,target=$ROOT/.git` and `GIT_DIR`/`GIT_WORK_TREE` remote env vars. The host's uid owning `.git` gets a `safe.directory` post-up.

See [ADR-0004](./adr/0004-parallel-orchestration.md).

## Layout pointer

For the full filesystem layout — user state at `~/.mentat/`, harness-shared at `~/.agents/`, repo dev tree at `<repo>/.agents/`, repo user-facing docs at `<repo>/docs/` — see [.agents/docs/PATHS.md](../.agents/docs/PATHS.md).
