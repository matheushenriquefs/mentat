# Mentat — Context

Domain glossary for Mentat. For narrative architecture overview, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). For decisions, see [docs/adr/](docs/adr/README.md).

## Language

**Multi-harness orchestrator**
: Mentat's category label. Distinct from a *meta-harness* (outer-loop search over one agent's surrounding code — a different architecture) and a *meta-skill*. Mentat orchestrates parallel coding agents across multiple headless agent CLIs (`claude-code`, `cursor`). _Avoid_: "meta-harness", "the harness" as a self-description of Mentat.

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
: The harness CLI — `cursor-agent` or `claude-code`. What `--harness=` selects; `/mentat-track track` watches it; each harness adapter module under `.agents/skills/mentat-implement/scripts/harness/` declares its `cmd` and `output_format`. _Avoid_: "build" (collides with Docker `build:` in `mentat-container-up`).

**Reviewer gate**
: The six ADR-0003 reviewer subagents — `mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer`, `mentat-rules-reviewer`, `mentat-context-reviewer`, `mentat-smell-reviewer`. Plan and test score against a threshold; bug, rules, and context veto; smell is advisory. They gate each chunk at implement and land time. `mentat-orchestrate` additionally runs them as an advisory end-of-queue batch review over the final tip. _Avoid_: conflating the per-chunk gate with the end-of-queue review.

**Blacklist**
: Set of forbidden reward-hacking moves in `mentat-bug-reviewer`. Any hit → 0.0 veto. Overrides all graded scores. _Avoid_: "denylist" (different mental model — this is a trajectory scan, not an access control).

**must_not_exist veto**
: A veto triggered when `mentat-test-reviewer` finds the implementation asserts behavior the plan did not ask for (hallucination). Inverted polarity: higher hallucination score = worse. _Avoid_: treating this as a threshold to meet.

**Mutation signal**
: The advisory surviving-mutant hint from `task mutation` (mutmut), a `file:line` list scoped to changed shipped-source files. A surviving mutant means a test covered the line but asserted nothing the mutation broke. Advisory only — never in the gate or land re-gate path ([ADR-0016](docs/adr/0016-mutation-signal.md)). _Avoid_: "mutation gate", "mutation score threshold" — it gates nothing.

**ReviewVerdict**
: The typed, validated reviewer output (`.agents/lib/gates/verdict.py`) — a frozen `ReviewVerdict` carrying `asserts_plan`, `veto`, `Finding[]`, and the advisory `surviving_mutants`. The gate parser validates reviewer JSON into it rather than regex-scraping free text; harness-agnostic (any harness that emits the JSON works). _Avoid_: "reviewer text", "scrape the verdict".

**Test ROI**
: The value lens `mentat-test-reviewer` judges by — would a test fail if a real bug were introduced *and* survive a behavior-preserving refactor. Fails the first half → worthless; the second → brittle. Penalizes assertion-free padding and mock-smell (mocking types you don't own). _Avoid_: equating test value with coverage or test count.

**Compaction threshold**
: `compaction_threshold_tokens` in `~/.mentat/config.toml`. When a harness run reports token usage ≥ threshold, mentat writes a checkpoint `summary.md{status: succeeded}` so the next spawn can be seeded with prior context (`MENTAT_SEED_SUMMARY`). Vendor-neutral: adapters report `usage_tokens: int | None`; `None` (cursor) bypasses the threshold check. _Avoid_: confusing this with the harness's own compaction — mentat checkpoints at slice/chunk boundaries, independently of any internal harness compaction.

**Harness tool**
: A MCP/skill resource the orchestration layer uses — `bash`, `grep`, `Read`, `Agent`. Not a target-repo tool. _Avoid_: bare 'tool' when the distinction matters.

**Project tool**
: A target-repo command — linter, test runner, formatter, interpreter. Runs only via `python3 ~/.agents/skills/mentat-container/scripts/container.py run '<cmd>'`, never on the host. _Avoid_: bare 'tool' when the distinction matters.

**Slug**
: A chunk's unique id — also its worktree dirname and `mentat_slug` container label. Format: `mentat-<epoch>-<pid>-<rand>`. _Avoid_: "id", "name", "tag".

**Summary file status vocabulary**
: `summary.md` in the agent log dir carries a `status:` frontmatter field that disambiguates outcome. Canonical values: `succeeded` (plan completed cleanly), `failed` (TDD/gate failure), `blocked` (AFK hit an unresolvable design call — operator must resolve), `hitl-required` (same intent, used in audit payloads). The file is written by the AFK agent (blocked) or by `mentat-track report` (succeeded/failed). _Avoid_: "completed" (hides outcome), custom strings outside this set.

## Relationships

- Slice → chunk: a plan document becomes a running execution.
- Chunk → worktree + devcontainer + branch: each chunk is fully isolated.
- Batch → many chunks → one holding branch: all chunks in a run share one target.
- Chunk → re-gate → land or eject: the merge queue's decision per chunk.
- Reviewer gate → advisory verdict: runs once over the final tip, not per-chunk.

## Flagged ambiguities

**"build" vs "land."** "Build" collides with Docker's `build:` stanza in `mentat-container-up` and with the generic sense of "compile". Mentat uses "land" for the cross-branch move and avoids "build" in orchestration prose.

**"tool" — Mentat-internal vs. target-repo.** A "tool" inside Mentat means a MCP/skill resource (bash, grep, agent). A "tool" in the target repo means its linter/test runner/formatter. Context usually disambiguates; when unclear, say "harness tool" vs. "project tool".

**"agent" — the LLM unit vs. the `agents/` directory.** In prose, **agent** = one harness run audited in the canonical store (`agent_started` … `agent_reaped`). The **supervisor** is the orchestrate agent that schedules slices and fans out chunks. The `agents/` directory holds *prompt files* that define agent personas — not the live runs. Use "agent definition" for the file; "agent" for the live run.

**"Mentat" — system vs. Dune character.** In code and docs, "Mentat" (capitalized) is the harness. The Dune origin is context for the name; it does not appear in technical prose.

## Positioning

Mentat is a barebones primitive, not a framework. It composes git worktrees, a
container engine, and a chosen agent CLI, and adds one thing those do not provide on
their own: a scored, serial land queue. It sits with the lean building blocks of
software — the kind a larger system is assembled from, not the kind that dictates the
system's shape. The test every change is held to: a change that exposes a primitive
ships; a change that adds framework weight is refused.

## Non-goals

Deliberate refusals. A change adding any of these is closed as out of scope.

- **No UI.** Command-line only. Graphical diff-review and agent-steering belong to
  desktop agent managers, not Mentat.
- **No multi-machine.** Single-host concurrency, tuned by the `concurrency` config
  key. Higher counts raise rebase-collision odds at land time.
- **No cloud.** No hosted agents, no platform, no daemon.
- **No cross-repo state.** Compose at the shell level — run independent
  orchestrations per repository; each writes its own namespaced audit log.

## Known limitations

Present-tense facts, not promises of future work.

- **Reviewer thresholds are chosen, not measured.** The pass thresholds are set by
  judgment — reasonable defaults, not values fit to a labeled corpus.
- **Token-usage accounting is partial.** Adapters report usage only when the
  underlying CLI emits it; where it emits nothing, Mentat records no usage rather
  than inventing a number.
- **A container engine is mandatory.** Every project-tool invocation runs in a
  devcontainer ([ADR-0002](docs/adr/0002-holding-branch-over-merge.md),
  [ADR-0004](docs/adr/0004-parallel-orchestration.md)). Hosts without one cannot run
  Mentat — reproducibility traded for that hard dependency.

## ADRs

| # | Title | Summary |
|---|---|---|
| [0001](docs/adr/0001-sub-agent-delegation.md) | Sub-agent delegation | Cavecrew by default; vanilla only for prose/rationale. `mentat-researcher` is procedure, not persona. No hardcoded model. |
| [0002](docs/adr/0002-holding-branch-over-merge.md) | Holding branch over merge | Plain `git worktree` + ff-only merge; no merge commits. Holding branch carries no commits; all lands are ff-only in-container. |
| [0003](docs/adr/0003-scored-review-gate.md) | Scored review gate | Reviewer subagents map to Mastra scorers. Never average; veto > threshold. LLM never self-promotes. |
| [0004](docs/adr/0004-parallel-orchestration.md) | Parallel-slicing orchestration | Fan-out parallel, land serial. Cap 3 chunks. Re-gate after land rebase. Docker required. Driver names no project tool. |
| [0005](docs/adr/0005-ubiquitous-lexicon.md) | Ubiquitous lexicon | Slice/chunk/batch vocabulary. One Laravel borrow (batch, noun only). |
| [0006](docs/adr/0006-soft-readonly-test-enforcement.md) | Soft read-only tests | No kernel mount. Impl-only-after-red contract + runner-redirection blacklist entry. Both agnostic. |
| [0007](docs/adr/0007-audit-envelope.md) | Audit envelope | Flat snake_case catalog (`EVENT_CATALOG`), SQLite canonical store (`mentat.db`), transcript at `~/.mentat/logs/<repo>/<agent_id>/`. |
| [0008](docs/adr/0008-python-runtime.md) | Python runtime | Stdlib-only at the bin layer; uv/ruff/pyright/pytest at the dev layer. Container-required Python 3.11+. |
| [0009](docs/adr/0009-plugin-api.md) | Plugin API | Vite-derived, one slot (harness), entry-point discovery. Mentat core stays minimal. Number reused — the original ADR-0009 (audit envelope) was renumbered to ADR-0007; retired here, not superseded. |
| [0010](docs/adr/0010-readonly-test-mount.md) | Read-only test mount | OCP `<plan>.tests.json` manifest + container bind-mount with `readonly` flag. |
| [0011](docs/adr/0011-compose-aware-container.md) | Compose-aware container | Sidecar detection + dev-service layering; host opt-out forfeits isolation. |
| [0012](docs/adr/0012-code-rules-layer.md) | Code-rules layer | `.agents/rules/` code conventions, enforced by `mentat-rules-reviewer` (veto). |
| [0013](docs/adr/0013-agent-continuity-over-compaction.md) | Agent continuity | Checkpoint at slice boundary, write agent summary, spawn fresh seeded agent — harness-agnostic. "Agent" here means the harness's own conversation, not the `Agent` entity. |
| [0014](docs/adr/0014-coverage-gate.md) | Coverage gate | Unit 90% testable-line floor (amended down from 100% — Goodhart trap, see ADR-0016) + e2e journey floor 45%, both blocking. |
| [0015](docs/adr/0015-auto-recovery.md) | Model-driven auto-recovery | JIT retry/reslice/abandon over transient ejects; storm/budget/attempt caps. Superseded by ADR-0007 v7 (SQLite canonical store) for its audit substrate. |
| [0016](docs/adr/0016-mutation-signal.md) | Mutation signal | Advisory surviving-mutant hint (`task mutation`, mutmut) scoped to changed shipped-source files. Never a gate. |
| [0017](docs/adr/0017-per-run-isolation.md) | Per-run isolation | Chunk-keyed identity, override-config, run-scoped prune, OOM recovery. |
| [0018](docs/adr/0018-skill-modularization.md) | Skill modularization | God-file splits, rename map, `mentat-track`→`mentat-track`, `lib/support/` grouping. ES5 dropped (RI2). |
| [0019](docs/adr/0019-code-organization.md) | Code organization | Domain-not-kind, protocol+registry+adapter, &lt;100 LOC smell, no `utils.py`/`helpers.py`, env/path accessors. |
| [0020](docs/adr/0020-test-craft.md) | Test craft | Tests mirror source, real dep not mock, `real_audit_store` fixture, one-behavior-per-test, `filterwarnings=error`. |

