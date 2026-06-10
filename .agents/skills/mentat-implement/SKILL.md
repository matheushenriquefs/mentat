---
name: mentat-implement
description: >
  Execute a single mentat plan atomically in the current session.
  Use when you want to implement one plan slice-by-slice with TDD, gates, and per-slice commits.
---

Atomic single-plan executor. ONE job: execute one plan in the calling session. No routing, no worktree spawning, no multi-plan dispatch — those are orchestrate concerns.

## How to invoke

```
python3 ~/.agents/skills/mentat-implement/scripts/implement.py <plan-ref> [--harness <name>]
```

`plan-ref`: bare slug (`my-plan`) or path (`~/.agents/plans/my-plan.md` or `/abs/path/plan.md`).

Multi-slug → exit 1 with "use mentat-orchestrate for multi-plan".

## Preflight

1. **Worktree.** If `pwd` doesn't match `$MENTAT_WORKTREE` or `.*/worktrees/[^/]+/?$`, invoke `mentat-git worktree create <plan-slug>` and cd into the new worktree.
2. **Worktree-create failure** → emit `chunk.ejected{reason: preflight}` and halt.
3. **Slice artifacts.** Derive a bash predicate per slice (exists / absent / `grep -c <pattern> <file> -ge N`). Skip slices whose predicate already passes; refuse to re-run DONE slices.
4. **Container** auto-ups via `mentat-container up`; second miss → exit 69.

## Gate formula

After all slices green, spawn `mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer`, `mentat-smell-reviewer` in parallel. Per ADR-0003 (never average, veto-style):

```
gate_pass =
      deterministic_checks_all_green     # VETO — tests / coverage delta ≥ 0 / no weakened assertion
  AND trajectory_blacklist_clean         # VETO — bug-reviewer blacklist
  AND max_latent_bug_sev < high          # VETO — bug-reviewer latent-bug lens
  AND plan_alignment    ≥ 0.88           # plan-reviewer threshold
  AND test_asserts_plan ≥ 0.88           # test-reviewer threshold
  AND smell_findings.hard_tier == []     # VETO — smell-reviewer hard tier
  AND smell_findings.soft_tier[sev=high] == []  # VETO — soft tier sev=high
```

Any veto/threshold fail → fix, re-commit, re-spawn. Do not rebase on FAIL. Dismissals enumerate refuted findings + disproof in `review.submitted.payload.reason`; prose-only dismissal forbidden.

## Execution flow

```
mentat-implement <single-plan-slug>

1. Read plan frontmatter: id, class.
2. If class == AFK:
     harness adapter invoked with --disallowedTools AskUserQuestion
     + system clause forbidding self-answer.
3. If class == HITL:
     harness adapter invoked normally (AskUserQuestion allowed).
4. TDD loop over plan slices via /tdd:
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
- Gate runner: iterates `.agents/lib/gates/code/*.py` (`run(chunk_path)`); spawns reviewer subagents (`mentat-{plan,test,bug,smell}-reviewer`) via Agent tool; `score.py` aggregates.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All slices green, plan complete |
| 1 | TDD or gate failure |
| 42 | AFK ambiguity — HITL required |
| 64 | CLI arg parse error / missing plan slug |
| 65 | Malformed plan frontmatter |
| 66 | Plan slug not found |
| 69 | Container down at preflight |
| 70 | Unhandled Python exception |
| 78 | `~/.mentat/config.jsonc` missing or invalid |

## Rules

- One plan slug per invocation. Refuse multi-slug input with exit 64.
- Container required (ADR-0004). Exit 69 if container down at preflight.
- AFK class forbids `AskUserQuestion`; ambiguity → emit `chunk.ejected`, exit 42.
- Rename/delete: `git mv`/`git rm` first in own commit; post-commit `git ls-files | grep <old>` must be empty.
- Stale-ref sweep: after any rename/delete, run the plan's `rg` lines; non-zero hits → abort the slice.
- One commit per slice via `/mentat-commit`. No squash.
- All emit calls route through `mentat-log emit`; never write JSONL directly.
- Read-only test mount enforced per `<slug>.tests.json` manifest when present.

## Read-only test mount (ADR-0010)

When `~/.agents/plans/<slug>.tests.json` exists, `mentat-implement` reads it before
`/mentat-container-up`:

```json
{ "closed": ["tests/test_foo.py"], "open": ["tests/test_new.py"] }
```

- `closed - open` paths → mounted `readonly` via `--mount type=bind,...,readonly`.
- `open` paths → writable (plan author declared intent to modify them).
- Absent manifest → no extra mounts; ADR-0006 soft layer still applies.

`mark-test-writable <path>` subcommand flips a closed path writable for the red-test
step; reverts to `ro,bind` after red commits. Audited as `test.writable.requested`.

## Constraints

- HITL class: `AskUserQuestion` allowed at any phase.
- AFK class: no interactive prompts. Ambiguity is ejection, not a question.
- Harness selection from `~/.mentat/config.jsonc`; `--harness` flag overrides.
- Plan class read from frontmatter only; no env var override.
- Session id from `$MENTAT_SESSION` (`<epoch>-<pid>` format).
- Gate pass required for each slice before proceeding to next.
