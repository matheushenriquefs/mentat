---
name: mentat-implement
description: >
  Execute a single mentat plan atomically in the current session.
  Use when you want to implement one plan slice-by-slice with TDD, gates, and per-slice commits.
metadata:
  version: "0.1.0"
---

Atomic single-plan executor. ONE job: execute one plan in the calling session. No routing, no worktree spawning, no multi-plan dispatch — those are orchestrate concerns.

## How to invoke

```
python3 ~/.agents/skills/mentat-implement/scripts/implement.py <plan-ref> [--harness <name>]
```

`plan-ref`: bare slug (`my-plan`) or path (`~/.agents/plans/my-plan.md` or `/abs/path/plan.md`).

Multi-slug → exit 1 with "use mentat-orchestrate for multi-plan".

## Atomic contract (B4 design)

```
mentat-implement <single-plan-slug>

1. Read plan frontmatter: id, class.
2. If class == AFK:
     harness adapter invoked with --disallowedTools AskUserQuestion
     + system clause forbidding self-answer.
3. If class == HITL:
     harness adapter invoked normally (AskUserQuestion allowed).
4. TDD loop over plan slices:
     red test → impl → gate → commit per slice.
5. On AFK ambiguity (self-answered-question detected in session JSONL):
     emit chunk.ejected{reason: hitl-required} + exit 42.
6. On success → exit 0.
7. On TDD/gate failure → exit 1.
8. On signals → standard signal exit codes.
```

## Decisions

- One plan slug per invocation. Multi-plan → use `mentat-orchestrate`.
- No `MENTAT_BATCH_CLASS` env var. Class lives in plan frontmatter (source of truth).
- HITL exit code = `42` (sentinel; clear from 0 / 1 / signal codes).
- Harness: default from `~/.mentat/config.jsonc` `harness:` key; override via `--harness`.
- Gate runner: iterates `.agents/lib/gates/code/*.py` (`run(chunk_path)`) and `.agents/lib/gates/llm/*.md` (subprocess to harness).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All slices green, plan complete |
| 1 | TDD or gate failure |
| 42 | AFK ambiguity — HITL required |
| ≥2 | Tool/config error |
