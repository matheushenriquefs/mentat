# Mentat — Context

Domain glossary for Mentat. For narrative architecture overview, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). For decisions, see [docs/adr/](docs/adr/README.md).

## Language

**Multi-harness orchestrator**
: Mentat's category label. Contrast with *meta-harness* (Lee et al. arxiv 2603.28052 — a different architecture) and *meta-skill* (revfactory/harness). Mentat orchestrates parallel coding agents across multiple headless agent CLIs (`cursor-agent`, `claude-code`). _Avoid_: "meta-harness", "the harness" as a self-description of Mentat.

**Mentat (system)**
: The harness itself — the `.agents/` tree, Python skills, and orchestration contracts. Not a person, not an agent. _Avoid_: "the Mentat", "the AI", "the bot".

**Slice**
: A *planned* vertical tracer-bullet cut. An input artifact: a `plan.md`. Taxonomy owned by `/mentat-plan` and `/mentat-issues`; AFK/HITL tags are theirs. _Avoid_: using "slice" for the running execution.

**Chunk**
: The *running execution* of one slice — worktree + devcontainer + its own branch off `main`, running `/mentat-implement`. One slice → one chunk. _Avoid_: "chunk" for the plan document or the group.

**Batch**
: The full set of chunks in one `mentat-orchestrate` run. Borrowed from Laravel (noun only — not their semantics; landing is serial, not independent). _Avoid_: `batch` to imply parallel independence or Laravel's `then()`/`catch()` pattern.

**Holding branch**
: `branch/<feature>` — a moving pointer with no commits of its own. All chunks fast-forward onto it. _Avoid_: "merge branch", "integration branch".

**Land**
: The cross-branch move — rebase the chunk onto `$HOLDING` in-container, re-gate, host `merge --ff-only`. _Avoid_: "merge" (plain `git merge` is the rejected mechanism — ADR 0002).

**Merge queue**
: The serial land pass in `mentat-orchestrate`. Per chunk: rebase onto live holding tip → re-gate → ff-only or eject. _Avoid_: "CI queue", "build queue".

**Re-gate**
: Running the target repo's quality gates on the rebased tree after landing. Distinct from the chunk's own gate during implementation. _Avoid_: "re-test", "re-check".

**Eject**
: When re-gate fails — the chunk's worktree is left up for repair, the queue continues with remaining chunks. _Avoid_: "reject", "fail", "rollback".

**AFK / HITL**
: Away-from-keyboard (gate clears unattended) vs. human-in-the-loop (stalls for review). Tags on slices in a plan. _Avoid_: "automatic", "manual".

**Target repo**
: The codebase a batch implements against. Mentat is agnostic to its toolchain; all target-repo commands run in-container. _Avoid_: "the project" (ambiguous between Mentat and target).

**Devcontainer**
: Docker container for a chunk's target repo — where all project tools run. `python3 ~/.agents/skills/mentat-container/scripts/container.py up` brings it up; `... container.py run '<cmd>'` executes commands inside. _Avoid_: "the container", "the Docker".

**Headless agent CLI**
: The harness CLI — `cursor-agent` or `claude-code`. What `--harness=` selects; `/mentat-session track` watches it; each harness adapter module under `.agents/skills/mentat-implement/scripts/harness/` declares its `cmd` and `output_format`. _Avoid_: "build" (collides with Docker `build:` in `mentat-container-up`).

**Reviewer gate**
: The three ADR-0003 reviewers (`mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer`) run once at end-of-queue over the final landed tip. Advisory (inspect-after) until they earn a false-pass record. _Avoid_: conflating this with the per-chunk land gate.

**Blacklist**
: Set of forbidden reward-hacking moves in `mentat-bug-reviewer`. Any hit → 0.0 veto. Overrides all graded scores. _Avoid_: "denylist" (different mental model — this is a trajectory scan, not an access control).

**must_not_exist veto**
: A veto triggered when `mentat-test-reviewer` finds the implementation asserts behavior the plan did not ask for (hallucination). Inverted polarity: higher hallucination score = worse. _Avoid_: treating this as a threshold to meet.

**Harness tool**
: A MCP/skill resource the orchestration layer uses — `bash`, `grep`, `Read`, `Agent`. Not a target-repo tool. _Avoid_: bare 'tool' when the distinction matters.

**Project tool**
: A target-repo command — linter, test runner, formatter, interpreter. Runs only via `python3 ~/.agents/skills/mentat-container/scripts/container.py run '<cmd>'`, never on the host. _Avoid_: bare 'tool' when the distinction matters.

**Slug**
: A chunk's unique id — also its worktree dirname and `mentat_slug` container label. Format: `mentat-<epoch>-<pid>-<rand>`. _Avoid_: "id", "name", "tag".

## Relationships

- Slice → chunk: a plan document becomes a running execution.
- Chunk → worktree + devcontainer + branch: each chunk is fully isolated.
- Batch → many chunks → one holding branch: all chunks in a run share one target.
- Chunk → re-gate → land or eject: the merge queue's decision per chunk.
- Reviewer gate → advisory verdict: runs once over the final tip, not per-chunk.

## Flagged ambiguities

**"build" vs "land."** "Build" collides with Docker's `build:` stanza in `mentat-container-up` and with the generic sense of "compile". Mentat uses "land" for the cross-branch move and avoids "build" in orchestration prose.

**"tool" — Mentat-internal vs. target-repo.** A "tool" inside Mentat means a MCP/skill resource (bash, grep, agent). A "tool" in the target repo means its linter/test runner/formatter. Context usually disambiguates; when unclear, say "harness tool" vs. "project tool".

**"agent" — the LLM unit vs. the `agents/` directory.** In prose, "agent" = the running LLM instance executing a chunk. The `agents/` directory holds *prompt files* that define agent personas — not the agents themselves. Use "agent definition" for the file; "agent" for the live run.

**"Mentat" — system vs. Dune character.** In code and docs, "Mentat" (capitalized) is the harness. The Dune origin is context for the name; it does not appear in technical prose.

## ADRs

| # | Title | Summary |
|---|---|---|
| [0001](docs/adr/0001-sub-agent-delegation.md) | Sub-agent delegation | Cavecrew by default; vanilla only for prose/rationale. `mentat-researcher` is procedure, not persona. No hardcoded model. |
| [0002](docs/adr/0002-holding-branch-over-merge.md) | Holding branch over merge | Plain `git worktree` + ff-only merge; no merge commits. Holding branch carries no commits; all lands are ff-only in-container. |
| [0003](docs/adr/0003-scored-review-gate.md) | Scored review gate | Reviewer subagents map to Mastra scorers. Never average; veto > threshold. LLM never self-promotes. |
| [0004](docs/adr/0004-parallel-orchestration.md) | Parallel-slicing orchestration | Fan-out parallel, land serial. Cap 3 chunks. Re-gate after land rebase. Docker required. Driver names no project tool. |
| [0005](docs/adr/0005-ubiquitous-lexicon.md) | Ubiquitous lexicon | Slice/chunk/batch vocabulary. One Laravel borrow (batch, noun only). |
| [0006](docs/adr/0006-soft-readonly-test-enforcement.md) | Soft read-only tests | No kernel mount. Impl-only-after-red contract + runner-redirection blacklist entry. Both agnostic. |
| [0007](docs/adr/0007-audit-envelope.md) | Audit envelope | 9-event canonical catalog, NDJSON envelope, `~/.mentat/logs/<repo>/<session>/` layout. |
| [0008](docs/adr/0008-python-runtime.md) | Python runtime | Stdlib-only at the bin layer; uv/ruff/pyright/pytest at the dev layer. Container-required Python 3.11+. |
| [0009](docs/adr/0009-plugin-api.md) | Plugin API | Vite-derived 2-slot extension surface (rubric, gate). Mentat core stays minimal. |
| [0010](docs/adr/0010-readonly-test-mount.md) | Read-only test mount | OCP `<plan>.tests.json` manifest + container bind-mount with `readonly` flag. |

