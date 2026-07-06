# ADR 0015: Model-driven auto-recovery

Status: Superseded by ADR-0007 v7 (SQLite canonical store)
Date: 2026-07-03

## Context

An AFK orchestrate batch fans chunks out in parallel and lands them serially onto
the holding branch (ADR-0004, ADR-0002). Chunks eject for many reasons, and they
are not equal. A **terminal** eject means the chunk's *code* failed — a red gate,
an implement failure, a design call the agent could not make (`hitl-required`),
a refusal to run. Respawning that unchanged just fails again. A **transient**
eject means the chunk's *environment* failed it, not its code — a wall-deadline or
no-progress kill (`worker-died`), a downed container, or a merge that raced out of
fast-forward (`not-ff`). The work was never proven bad.

Before this ADR, every eject was final. A batch that lost three chunks to a
transient container hiccup handed the operator three dead worktrees to re-run by
hand, even though a rebase-and-retry would have landed them. The four dependency
roots this feature needed — a transient-vs-terminal classification seam and
worker-died marker (runtime), backpressure/breaker/backoff guards, session
inspection (`mentat-track track` / `diagnose`), and a write-set serializer
(land queue) — were landed first; this ADR records the recovery engine built on
top of them.

The hard part is deciding *how* to recover. A fixed heuristic ("always retry
worker-died twice") is brittle: a chunk that timed out because it was doing too
much needs to be re-planned smaller, not retried whole. That decision needs
judgment, and the system already has an agent that can judge.

## Decision

After the drain settles, orchestrate runs a **model-driven recovery pass** over
the batch's transient-ejected **AFK** slugs (`recover.py`, wired via
`orchestrate._run_recovery`). It is serial (one slug at a time), spaced by the
full-jitter backoff helper, and gated by guardrails so it can never make things
worse.

**Transient vs terminal.** `lib.events.TRANSIENT_EJECT_REASONS` is the only set the
engine will act on. Terminal reasons are marked ejected and left for the operator.
HITL chunks are **never** auto-respawned — the operator owns them; an
`upstream_ejected` victim recovers only if its upstream does.

| Reason | Class | Rationale |
|--------|-------|-----------|
| `worker_died` | transient | Worker killed or crashed before a verdict — environment/harness failure. |
| `not_ff` | transient | Holding moved during parallel work; rebase-and-retry may land. |
| `preflight_worktree_failed` | transient | Worktree create/isolation failed before implement ran. |
| `container_oom` | transient | Chunk container OOMKilled; retry with more memory or smaller scope. |
| `implement_failed` | terminal | Child exited non-zero after running — code or harness failure. |
| `gate_failed` | terminal | Post-implement gate blocked — code quality failure. |
| `rebase_conflicted` | terminal | Rebase onto holding conflicted — needs human merge. |
| `hitl_required` | terminal | AFK ambiguity — operator must decide. |
| `main_tree_refused` | terminal | Refused to run in shared main tree — isolation invariant. |
| `upstream_ejected` | terminal | Blocked-by upstream died — cascade victim. |
| `git_error` | terminal | Ambiguous git failure during land — do not blind-retry. |

Transient set: `worker_died`, `not_ff`, `preflight_worktree_failed`, `container_oom`.
Terminal set: all other `CHUNK_EJECT_REASONS` members.

**The JIT decision, not a heuristic.** For each recoverable slug the engine hands
a recovery agent the failure context — `{reason, diagnosis, partial diff, worktree
path, holding tip, attempt#/cap}` — and the agent returns exactly one action:

- **retry** — re-run implement on the SAME preserved worktree, rebased onto the
  live holding tip. For a purely environmental failure.
- **reslice** — re-plan the chunk into smaller vertical-slice plans JIT and re-fan
  them through the staged coordinator. The fix for the chunk that timed out because
  it was too big.
- **abandon** — do not retry; escalate to a human.

An unparseable reply or an unrecognized action degrades to `abandon` — the safe
default is escalation, never a blind retry against an unclassifiable failure.

**Idempotent re-land (Stripe idempotency key).** Recovery reuses the preserved
worktree via `MENTAT_SKIP_PREFLIGHT` (implement skips `worktree create`, which
would exit 65 on the existing branch) and rebases it onto holding before re-running
— a re-land can't double-apply or collide, the same guarantee an idempotency key
gives a retried payment.

**Guardrails — three give-up rungs (Erlang/OTP, OpenHands, Akka/Azure DLQ).**

- **Per-slug attempt cap** — `recovery_attempts` (default 2), replayed from the
  canonical store (`chunk_started{trigger:"recovery", attempt:N}` via `EventDAO`),
  so the count survives a resume.
- **Batch-wide restart-storm cap** — `StormGuard`, the OTP supervisor
  `MaxR`/`MaxT` intensity: at most `recovery_max_restarts` (default 3) respawns per
  `recovery_restart_window` (default 60s). A breach stops the whole pass and
  escalates every not-yet-recovered slug — "give up, don't loop."
- **Budget ceiling** — `Budget`, an OpenHands-style accumulated-cost cap
  (`recovery_budget`, default unlimited). A breach halts recovery and escalates the
  remainder.

**Escalate-to-HITL dead-letter (Akka escalate / Azure dead-letter queue).**
`abandon`, an attempt-cap breach, or a storm/budget breach converts the chunk to a
HITL item (`chunk_ejected{reason:"hitl-required"}` carrying the rationale) and
notifies the operator — never a blind retry, never a silent eject.

**Breaker / backpressure interaction.** Recovery runs only after the fan-out drain
settles, relying on the concurrency-cap clamp so it never respawns into a saturated
box. The circuit breaker (Nygard) still governs the *initial* fan-out; the storm
cap is its recovery-pass analogue. The two are complementary: the breaker
short-circuits spawns against a sick shared backend mid-batch, the storm cap stops
the recovery pass from re-storming it afterward.

**Audit is payload-only (ADR-0007).** A respawn is a `chunk_started` with
`trigger:"recovery"` and the 1-based `attempt` (declared in mentat-log's
`EVENT_OPTIONAL_FIELDS`); the outcome rides the existing `chunk_landed` /
`chunk_ejected` events. No new event type.

Industry grounding: Erlang/OTP supervisor restart intensity, Netflix Zuul
speculative/NNFI re-test, Temporal durable retries, Nygard's circuit breaker,
Stripe idempotency keys, OpenHands cost budgets, Akka supervisor escalation, and
Azure/AMQP dead-letter queues.

## Consequences

A batch that loses chunks to transient infrastructure failures now salvages them
without operator intervention, and a fully-recovered batch exits 0. The recovery
pass cannot itself become a failure amplifier: three independent caps (per-slug,
storm, budget) each convert a runaway into a bounded escalation, and every
give-up is a visible HITL dead-letter, never a silent drop. Recovery depends on a
live agent (the recovery decision is a headless `claude` call); when the agent is
unreachable the decision degrades to `abandon`, so the worst case is the
pre-recovery behavior (operator handles it) plus a notification — never a wedge.
The engine is model-driven, so its retry-vs-reslice judgment improves with the
model rather than with hand-tuned thresholds.
