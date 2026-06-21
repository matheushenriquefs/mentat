# ADR 0004: Parallel orchestration (folds ADR-0010 HITL + ADR-0011 decomp + ADR-0012 harness-registry)

Status: Accepted (locked)
Date: 2026-05-31
Amended: 2026-06-09 (v2 — hybrid 1-bin+3-modules shape; Python ProcessPoolExecutor;
folds 0010 hitl-routing + 0011 decomp + 0012 harness-registry)
Amended: 2026-06-11 (v3 — cross-chunk dep gating via scheduler.py; upstream-HITL
promotion; eject cascade payload on chunk.ejected)

## Context

Orchestration shape evolved through ADRs 0010, 0011, 0012. Shell-era 3-bin pattern
(`mentat-fan-out`, `mentat-land-queue`, `mentat-final-review`) maps naturally to
Python stage modules under one bin. HITL routing contract and harness registry
folded here.

## Decision

**Shape: one bin + three stage modules + four subcommands.**

- `mentat-orchestrate run [--harness=<n>] [--model=<s>] [--dry-run] <holding> <plan-ref>+`
- `mentat-orchestrate fan-out <plan-ref>+` — debug: spawn N plans headless; stdout = chunk slugs
- `mentat-orchestrate land-queue <holding-branch>` — debug: stdin = slugs; stdout = verdict JSONL
- `mentat-orchestrate batch-review <session>` — debug: re-run batch review

Stage modules under `scripts/`: `fan_out.py`, `land_queue.py`, `batch_review.py`.

**Routing partition (HITL contract folded from ADR-0010):**

Read each plan's `class: AFK|HITL` frontmatter. Topological sort by `blocked_by`.
- `HITL` plans → anchored in current interactive session.
- `AFK` plans with no HITL anywhere in the dep chain → auto-spawned headless.
- `AFK` plans with a downstream HITL → anchored (HITL must complete first).
- `AFK` plans with an upstream HITL → anchored (caller must drive the
  upstream HITL in-session before the downstream AFK can spawn — its
  worktree can't safely auto-spawn against the pre-batch base).

The walks live in `scheduler.py` (`_has_downstream_hitl`, `_has_upstream_hitl`).
`routing.py` is a backward-compat shim that re-exports from `scheduler`.

AFK headless contract: harness adapter invoked with `--disallowedTools AskUserQuestion`
+ system clause forbidding self-answer. Exit `42` = `hitl-ambiguity` (AFK adapter
detected ambiguity). HITL: interactive, normal.

**Concurrency:** `concurrent.futures.ProcessPoolExecutor` — subprocess per chunk = isolation.

**Harness registry (folded from ADR-0012):** claude-code + cursor hard-coded as
Python adapters in `mentat-implement/scripts/harness/`. No JSONC file.
Selection: `~/.mentat/config.toml` `harness:` key; `--harness` flag overrides.

**v4 amendment — layered config + per-repo overlay:**

Config is now resolved as a layered stack (highest precedence first):

| Layer | Source | Precedence |
|---|---|---|
| CLI flag | `--harness <n>`, `--model <s>` | highest |
| Repo overlay | `<repo-root>/.mentat/config.toml` | over global |
| Global | `~/.mentat/config.toml` | base |

Merge: shallow `{**global, **repo}` — repo wins per top-level key. Plugin
lists are NOT merged; a repo `plugins` key replaces the global list entirely
to avoid accidental activation of globally-installed plugins in scoped repos.

Repo root resolved via `git rev-parse --show-toplevel` in each skill entry
(not memoized; called once per invocation). Non-zero rc (outside git repo)
falls back to global only. Malformed repo JSONC is swallowed; global config
is kept.

`mentat-install --repo` scaffolds `<repo>/.mentat/config.toml` with a
commented-out template and appends `.mentat/` to `.gitignore`.

**Verdict JSONL shape:**
```
{slug, status, tip, reason?, conflicted_files?, resume_cmd?, findings?}
  status ∈ {success, eject}
  reason ∈ {rebase-conflict, gate-fail, not-ff, implement-fail, hitl-ambiguity}
```

Exit codes: 0 all-landed; 1 partial; ≥2 tool error.

**Cross-chunk dependency gating (v3 amendment):**

`land_queue.drain` accepts an optional `Scheduler` (`scheduler.py`). With one,
the drain pulls the next-ready chunk via `Scheduler.next_ready(pending)` — a
chunk lands only when every slug in its `blocked_by` is already in
`scheduler.landed`. `B(blocked_by=[A])` waits for `A.landed` even if B's
chunk arrived first; rebase-at-land then carries A's commits underneath B.

Eject cascade: when a chunk ejects (gate-failed, rebase-conflicted, not-ff),
`Scheduler.mark_ejected` walks the reverse-dep graph and returns every
downstream slug. `land_queue.drain` emits one `chunk.ejected` per cascaded
slug with payload `{reason:"upstream_ejected", upstream:<X>}` — payload-only
extension per ADR-0007 (no new event name) — and skips the cascaded slugs
without rebase or gate. Sibling chunks (no dep on the ejected one) keep
flowing.

Cycle / missing upstream → drain returns a single `status:"stalled"` verdict
with the pending list; orchestrate exits 1.

## Consequences

Shell bins `mentat-fan-out`, `mentat-land-queue`, `mentat-batch-review` replaced by
debug subcommands. Old ADRs 0010, 0011, 0012 archived. Docker required per worktree.
Track prompt prints immediately after spawn (not at end) so user can monitor while
anchored plans run. `mentat-session track` remains the live view.
