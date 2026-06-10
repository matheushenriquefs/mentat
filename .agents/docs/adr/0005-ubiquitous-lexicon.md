# ADR 0005: Ubiquitous lexicon — slice/chunk/batch + gate/smell/verdict

Status: Accepted (locked)
Date: 2026-06-03
Amended: 2026-06-09 (v2 — expanded with gate machinery vocabulary)

## Context

The system's terms grew across ADRs 0001–0004 and the `to-*`/`mentat-container-*`
scripts — consistent in spirit but never collected. Two gaps bit: `slice` and `chunk`
used interchangeably; no noun for the whole set of chunks in one run. Gate machinery
(ADR-0003 v2) adds its own vocabulary; collected here.

## Decision — the lexicon

**Orchestration:**
- **slice** — a *planned* vertical tracer-bullet cut. INPUT: a `plan.md`.
- **chunk** — the *running execution* of one slice: worktree + container + branch.
- **batch** — the full set of chunks in one `mentat-orchestrate run`.
- **slug** — chunk's unique id; worktree dirname; `mentat_slug` container label.
- **holding branch** — `branch/<feature>`, no own commits; chunks FF onto it.
- **land** — FF-merge a chunk's tip onto the holding branch after all gates pass.
- **eject** — preserve a chunk's worktree for repair on gate-fail or conflict.
- **plan class** — `AFK` (headless, `--disallowedTools AskUserQuestion`) | `HITL` (interactive).

**Review machinery (expanded for ADR-0003 v2):**
- **gate** — anything that evaluates a chunk and emits a verdict (umbrella).
- **code gate** — deterministic Python gate. Lives in `.agents/lib/gates/code/`.
- **reviewer subagent** — LLM reviewer spawned via Agent tool. Source: `.agents/agents/mentat-*-reviewer.md`; installed via harness symlinks. Replaces `llm/*.md` gate files.
- **smell** — Fowler code smell. Advisory by default.
- **severity** — per-gate: `info` / `low` / `med` / `high` / `critical`.
- **threshold** — (reviewer subagents) numeric score above which advisory flips blocking.
- **verdict** — typed gate output: `pass` / `block` / `advise`.

slice : chunk :: plan : process. If about the cut → slice; about the execution → chunk;
about all of them together in one run → batch.

`batch` borrowed from Laravel job batching (parallel group), noun only — NOT Laravel's
independent `then()`/`catch()`/`finally()` semantics. Landing is serial; each chunk
rebases onto the tip the previous one left.

## Consequences

Every command, ADR, and script speaks one vocabulary. New terms join this table.
ADRs/AGENTS.md use slice/chunk/batch/gate/verdict per the layers above. This ADR is
index-only in AGENTS.md (title only; body on demand — ADR 0001's budget).
