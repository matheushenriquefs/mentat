---
name: mentat-implement
description: Execute a single mentat plan atomically in the current session. Use when you want to implement one plan slice-by-slice with TDD, gates, and per-slice commits.
---

Atomic single-plan executor. ONE job: execute one plan in the calling session. No routing, no worktree spawning, no multi-plan dispatch — those are orchestrate concerns.

## How to invoke

```
/mentat-implement <plan-ref> [--harness <name>]
/mentat-implement run --land [--holding <branch>] <plan-ref>
```

`plan-ref`: bare slug (`my-plan`) or path. Multi-slug → exit 1 (use mentat-orchestrate).

Subcommands (peers): `run` (default), `mark-test-writable <slug> <path>`.

`--land`: after all slices green, rebase onto `<holding>` (default `main`), fast-forward merge, spawn advisory batch review — no `mentat-orchestrate` needed. Use for a single plan start→finish in one session. `--holding` order is intentionally swapped vs. `orchestrate run <branch> <plan>+`.

## Preflight

1. **Worktree.** Main worktree → create sibling via `mentat-git worktree create <slug>` + chdir. Already in sibling → skipped. Not in repo → skipped. `MENTAT_SKIP_PREFLIGHT=1` → skipped.
2. **Failure** → emit `chunk.ejected{reason: preflight-worktree-failed}` + exit rc (65/66/70).
3. **Slice artifacts.** Skip already-passing predicates; refuse re-run on DONE slices.
4. **Container** auto-ups via `mentat-container up`; second miss → exit 69.

## Gate formula

After all slices green, spawn four reviewers in parallel (ADR-0003, veto-style):

```
gate_pass =
      deterministic_checks_all_green     # VETO — tests / coverage / no weakened assertion
  AND trajectory_blacklist_clean         # VETO — bug-reviewer blacklist
  AND max_latent_bug_sev < high          # VETO — bug-reviewer latent-bug lens
  AND plan_alignment    ≥ 0.88           # plan-reviewer
  AND test_asserts_plan ≥ 0.88           # test-reviewer
  AND smell_findings.hard_tier == []     # VETO
  AND smell_findings.soft_tier[sev=high] == []  # VETO
```

Fail → fix, re-commit, re-spawn. No rebase on FAIL. Dismissals require refuted findings + disproof; prose-only forbidden.

## Execution flow

1. Read `kind` from plan frontmatter.
2. AFK: adapter invoked `--disallowedTools AskUserQuestion`; unresolvable call → write `summary.md{status: blocked}`, stop.
3. HITL: adapter invoked normally (`AskUserQuestion` allowed).
4. TDD loop: red test → impl → gate → commit per slice.
5. AFK wedge detected → emit `chunk.ejected{hitl-required}` + exit 42, preserve worktree.
6. Success → exit 0. TDD/gate failure → exit 1.

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
| 78 | `~/.mentat/config.toml` missing or invalid |

## Rules

- One plan slug per invocation. Refuse multi-slug input with exit 64.
- Container required (ADR-0004). Exit 69 if container down at preflight.
- AFK: no interactive prompts. Ambiguity → `summary.md{status: blocked}` → `chunk.ejected{hitl-required}` exit 42.
- HITL: `AskUserQuestion` allowed at any phase.
- Rename/delete: `git mv`/`git rm` first in own commit; post-commit `git ls-files | grep <old>` must be empty.
- Stale-ref sweep: after rename/delete, non-zero rg hits → abort the slice.
- One commit per slice via `/mentat-commit`. No squash.
- All emit calls route through `mentat-log emit`; never write JSONL directly.
- Session id from `$MENTAT_SESSION` (`<role>-<slug>-<pid>` format).

## Read-only test mount (ADR-0010)

When `~/.agents/plans/<slug>.tests.json` exists, reads it before `/mentat-container-up`:

```json
{ "closed": ["tests/test_foo.py"], "open": ["tests/test_new.py"] }
```

`closed - open` → mounted `readonly`. `open` → writable. Absent manifest → no extra mounts.

`mark-test-writable <slug> <path>` flips a closed path writable for the red-test step.
Audited as `test.writable.requested`.
