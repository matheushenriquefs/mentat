# Mentat

A lean, agnostic **multi-harness orchestrator** for parallel coding agents.

## What this is

Mentat cuts planned work into vertical slices, runs each slice as an isolated chunk (worktree + devcontainer + its own branch), lands them serially onto a holding branch via a merge queue, and gates each land deterministically.

**Parallel-out / serial-in.** Chunks implement concurrently. Landing is serial — one ref can't move concurrently, and serial landing lets sibling divergence resolve by rebasing onto the tip the previous chunk left (ADR 0004). Hard cap: 3 parallel chunks.

**Holding-branch invariant.** The holding branch (`branch/<feature>`) carries no commits of its own. Each land is a `merge --ff-only` — no `git commit` fires, so no host-side pre-commit fires (ADR 0002).

**Merge queue / re-gate.** Per chunk: rebase onto current holding tip in-container, re-gate using the target repo's own quality gates, then ff-only. A red gate ejects the chunk; the queue continues. This catches semantic breakage a sibling's land introduced (ADR 0004).

**Deterministic gating + anti-cheat.** Two enforcement layers, both agnostic (ADR 0006): (1) impl-only-after-red contract — agent writes implementation code only after a failing test; (2) trajectory blacklist in `mentat-bug-reviewer` — forbidden reward-hacking moves → hard 0.0 veto (ADR 0003). The driver names no project tool.

**AFK operator.** AFK-tagged slices gate and land without human input. HITL-tagged slices stall for review. The scored gate (ADR 0003) — never average, veto > threshold — is what makes AFK trustworthy.

**No-framework thesis.** Bash + jq + prompts. No language toolchain on the host. Any Unix, any harness (`cursor-agent` | `claude-code`), any target language. Docker required (ADR 0004).

## Language

**Multi-harness orchestrator**
: Mentat's category label. Contrast with *meta-harness* (Lee et al. arxiv 2603.28052 — a different architecture) and *meta-skill* (revfactory/harness). Mentat orchestrates parallel coding agents across multiple headless agent CLIs (`cursor-agent`, `claude-code`). _Avoid_: "meta-harness", "the harness" as a self-description of Mentat.

**Vendor skill**
: A third-party skill vendored via `bin/mentat-update` (wraps `vendir sync`) from `vendir.yml`. Installed under `.agents/skills/vendor/<user>/<repo>/`. Attributions recorded in `CREDITS.md`. _Avoid_: treating vendor skills as first-party; always check `vendir.yml` before modifying.

**Vendor pins**
: `vendir.lock.yml` — SHA-pinned lockfile written by `vendir sync`. Track in git. Check staleness with `vendir sync --diff`. _Avoid_: editing the lockfile manually.

**Mentat (system)**
: The harness itself — the `bin/`, `.agents/`, and orchestration contracts. Not a person, not an agent. _Avoid_: "the Mentat", "the AI", "the bot".

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
: Docker container for a chunk's target repo — where all project tools run. `mentat-container-up` brings it up; `mentat-container-run` executes commands inside. _Avoid_: "the container", "the Docker".

**Headless agent CLI**
: The harness CLI — `cursor-agent` or `claude-code`. What `--harness=` selects; `mentat-track` watches it; each harness file self-declares its output format via `harness_<name>_output_format`. _Avoid_: "build" (collides with Docker `build:` in `mentat-container-up`).

**Reviewer gate**
: The three ADR-0003 reviewers (`mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer`) run once at end-of-queue over the final landed tip. Advisory (inspect-after) until they earn a false-pass record. _Avoid_: conflating this with the per-chunk land gate.

**Blacklist**
: Set of forbidden reward-hacking moves in `mentat-bug-reviewer`. Any hit → 0.0 veto. Overrides all graded scores. _Avoid_: "denylist" (different mental model — this is a trajectory scan, not an access control).

**must_not_exist veto**
: A veto triggered when `mentat-test-reviewer` finds the implementation asserts behavior the plan did not ask for (hallucination). Inverted polarity: higher hallucination score = worse. _Avoid_: treating this as a threshold to meet.

**Harness tool**
: A MCP/skill resource the orchestration layer uses — `bash`, `grep`, `Read`, `Agent`. Not a target-repo tool. _Avoid_: bare 'tool' when the distinction matters.

**Project tool**
: A target-repo command — linter, test runner, formatter, interpreter. Runs only via `mentat-container-run`, never on the host. _Avoid_: bare 'tool' when the distinction matters.

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

**"agent" — the LLM unit vs. the `agents/` directory.** In prose, "agent" = the running LLM instance executing a chunk. The `agents/` directory holds *prompt files* that define crew-agent personas — not the agents themselves. Use "crew-agent definition" for the file; "agent" for the live run.

**"Mentat" — system vs. Dune character.** In code and docs, "Mentat" (capitalized) is the harness. The Dune origin is context for the name; it does not appear in technical prose.

## ADRs

| # | Title | Summary |
|---|---|---|
| 0001 | Sub-agent delegation | Cavecrew by default; vanilla only for prose/rationale. `/mentat-researcher` is procedure, not persona. No hardcoded model. |
| 0002 | Holding branch + `/mentat-rebase` | Use plain `git worktree` + ff-only merge; no merge commits. Holding branch carries no commits; all lands are ff-only in-container. |
| 0003 | Scored review gate | Three reviewers map to Mastra scorers. Never average; veto > threshold. LLM never self-promotes. |
| 0004 | Parallel-slicing orchestration | Fan-out parallel, land serial. Cap 3 chunks. Re-gate after land rebase. Docker required. Driver names no project tool. |
| 0005 | Ubiquitous lexicon | Slice/chunk/batch vocabulary. One Laravel borrow (batch, noun only). |
| 0006 | Soft read-only tests | No kernel mount. Impl-only-after-red contract + runner-redirection blacklist entry. Both agnostic. |

