# ADR 0003: Scored review gate — Mastra-mapped reviewers, veto > threshold

Status: Accepted (locked)
Date: 2026-05-31
Amended: 2026-06-04 — scorer mappings re-confirmed against source (not docs);
`both`-mode reason corrected to "unfinished stub"; hallucination veto added to
mentat-bug-reviewer; blacklist set gains runner-redirection (see ADR 0006).
Amended: 2026-06-06 — mentat-smell-reviewer added as 4th reviewer, advisory,
threshold 0.85, no max-sev veto.
Amended: 2026-06-07 (G3-S10) — HITL axis added as a fourth eject reason
alongside score-veto / not-ff / rebase-conflict. Distinct from blacklist
veto and from scored-review threshold; canonical contract in ADR-0010.

## Context

The four reviewers (`mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer`, `mentat-smell-reviewer`)
emitted `PASS|FAIL` — LLM judgment, not a number. An orchestrator is only as
autonomous as its gate is trustworthy, and a binary verdict with no false-pass
record can't be trusted to reject unattended. We ground-truthed Mastra's eval
scorers (docs + pasted source) and the RAG-faithfulness convention to upgrade
the gate to numbers. Hard-to-reverse: shapes every reviewer and the
`/mentat-implement` step-5 gate, so it's locked here.

## Decision

Each reviewer maps to a specific Mastra scorer; we **reimplement the math in
the reviewer prompts, no code dependency** on Mastra. Scores are [0,1].

- **mentat-plan-reviewer → Prompt Alignment, `user` mode.** Weights
  intent .40 / requirements .30 / completeness .20 / appropriateness .10.
  `requirements[].isFulfilled` = per-planned-item checklist; `missingElements[]`
  = FAIL detail. Owns the **recall** axis. Threshold ≥ 0.88.
- **mentat-test-reviewer → Faithfulness (tests-assert-plan) + deterministic veto.**
  context = plan behaviors, claims = test assertions, `score = yes / total`
  (`no` and `unsure` both drag). Threshold ≥ 0.88. Veto half: tests green /
  coverage delta ≥ 0 / no weakened-or-deleted assertion.
- **mentat-bug-reviewer → trajectory blacklist veto + latent-bug veto.** Blacklist
  of forbidden moves → 0.0, overrides all. Latent-bug single finding at
  **sev ≥ high** → hard veto.
- **mentat-smell-reviewer → advisory code-smell reviewer.** Runs refactoring.guru
  22-smell catalog. No veto authority. Threshold ≥ 0.85 (lower than plan/test —
  smell findings are fuzzier, rarely justify hard halt). Score-only gate.

Gate (verbatim posture): **never average; veto > threshold; LLM never
self-promotes.**

```
gate_pass =
      deterministic_checks_all_green     # tests/coverage/assertions — VETO
  AND trajectory_blacklist_clean         # reward-hacking moves — VETO (0.0 kills)
  AND max_latent_bug_sev < high          # latent-bug lens — VETO
  AND no_severe_hallucination            # impl asserts unplanned behavior — VETO (inverted polarity)
  AND plan_alignment    >= 0.88          # Prompt Alignment (user) — LLM threshold
  AND test_asserts_plan >= 0.88          # Faithfulness scorer (plan-as-context) — LLM threshold
  AND smell_score       >= 0.85          # code-smell advisory — no max-sev veto
```

mentat-bug-reviewer now carries THREE vetoes (blacklist, latent-bug, hallucination),
all min/veto, never averaged. The hallucination term has INVERTED polarity vs the
LLM thresholds: Mastra's Hallucination scorer scores higher = worse
(`verdict==='yes'` means IS-a-hallucination; `generateScore` = contradicted/total).
So it is wired as `severe-unsupported-assertion → 0.0`, a low-ceiling veto, NEVER a
`>= 0.88` threshold. Mapping: context = plan behaviors, claims = impl output —
"does the impl assert behavior the plan never specified." Fires only on a SEVERE
unsupported assertion (same high bar as latent-bug sev≥high), so reasonable-but-
unplanned implementation detail does not trip it.
```

## Locked sub-decisions

1. **Latent-bug veto severity = high+.** A single finding at sev ≥ high
   (unhandled throw on reachable path, resource leak, race, injection/secret,
   data-loss/corruption) is a hard veto. Medium/low do not veto alone.
2. **Prompt Alignment `user` mode, never `both`.** Source-confirmed (re-read of
   `prompt-alignment/index.ts` generateScore): `both` mode is an UNFINISHED STUB,
   not a designed collapse. The both-branch literally does
   `const systemScore = userScore; // This will be updated when we modify the
   analysis structure`, then `userScore*0.7 + systemScore*0.3` = userScore. The
   analyze prompt asks for combined user+system requirements, but the score math
   discards the system half and reuses userScore. Outcome is the same (both →
   user score) but the *reason* is a placeholder TODO, not an intentional
   `systemScore = userScore` assignment — so depending on `both` means depending
   on half-built code. The plan is the user prompt; we have no system layer to
   audit. `both` is banned.
3. **Faithfulness framing = tests-assert-plan** (context = plan behaviors,
   claims = test assertions). The RAG convention judges-the-artifact against
   the-context, and this reviewer's artifact IS the test suite. Faithfulness
   does not measure recall — coverage gaps live in mentat-plan-reviewer's
   `missingElements[]`. The two reviewers are complementary; don't make
   tests-reviewer chase coverage.
4. **Blacklist set for mentat-bug-reviewer** (the reward-hacking veto, highest-value
   deterministic piece). **Moves** (single forbidden action): test-file deletion/
   emptying; harness monkey-patch/stub; early-return-before-assert; hardcoded-
   fixture-matching-expected; assertion-weakening (incl. skip/xfail); **runner
   redirection to a writable test copy** (point the runner at a duplicated/relocated
   test tree or set config/env so tests resolve from a writable path — NEW, added
   2026-06-04, ADR 0006: the soft no-edit-tests contract creates this incentive).
   **Sequences** (ordered subsequence): edit-assertion→commit; touch-test→touch-
   impl-to-match. Any hit → 0.0. **No entry was retired:** there is no kernel
   read-only mount (ADR 0006 rejected it for breaking agnosticism), so nothing is
   "fully covered" by prevention — the blacklist is the actual enforcement, kept
   whole.
5. **Reimplement the math, don't mirror Mastra's `createScorer` API.** No code
   dependency; the scorers are pattern + arithmetic in the reviewer prompts.
   Both optional code .ts (`code/tool-call-accuracy`, `code/trajectory`) are now
   in hand — used as spec, not imported.

## Source-confirmed details (from pasted .ts, folded into the defs)

**Faithfulness (`llm/faithfulness/index.ts`) — now confirmed by SOURCE, not docs.**
`generateScore` = `supportedClaims / totalClaims` where supported = `verdict==='yes'`;
`no` and `unsure` both drag; `totalClaims === 0 → 0`; rounds to 2dp. Identical to
mentat-test-reviewer' formula — the mapping stands unchanged, the prior "confirmed by
docs" caveat is lifted. **Footgun (record, not bitten):** the scorer's default
context source `getToolInvocationContext` reads ONLY `toolInvocations[]` (V1), NOT
V2 `content.parts[].toolInvocation` — the exact #17297 shape. mentat-test-reviewer
overrides context with the plan, so it dodges this; but any trajectory/claims scan
that trusts the scorer's default context inherits the V1-only blind spot. (Contrast:
`code/tool-call-accuracy`'s `extractToolCalls` reads BOTH shapes — it has the
explicit #17297 regression test. The two Mastra utils are asymmetric.)

**Hallucination (`llm/hallucination/index.ts`) — inverted polarity, source-confirmed.**
`generateScore` = `contradicted / total` where contradicted = `verdict==='yes'` and
`yes` means IS-a-hallucination. HIGHER = WORSE. This is why the gate term is a
low-ceiling veto (`severe → 0.0`), not a `>=0.88` threshold. Wiring it as a threshold
would invert the gate and pass only fully-hallucinated impls.

**`code/tool-call-accuracy/index.ts`** — deterministic event-ordering shape for
mentat-test-reviewer' veto: binary 1/0, never graded.
- **strict** = full-sequence equality (`JSON.stringify` compare), no extra events.
- **relaxed** = all expected present, strictly increasing relative order, extras allowed.
- Empty events → 0; `state: 'call'` (unresolved) still counts as called.
- **Trajectory-parse footgun (Mastra #17297):** events live in legacy
  `toolInvocations[]` OR V2 `content.parts[].toolInvocation` (observable-memory).
  mentat-bug-reviewer MUST read both or the veto scans empty and passes silently.

**`code/trajectory/index.ts`** — blacklist veto backbone for mentat-bug-reviewer.
`checkTrajectoryBlacklist` matches two kinds: **blacklistedTools** (forbidden step
*names*) and **blacklistedSequences** (forbidden ordered *subsequences*, e.g.
`['escalate','admin']`). Either → `blacklist.score === 0`. In `generateScore` a
0 blacklist returns 0 **before any weighting** — overrides accuracy/efficiency/
toolFailures entirely, and recursively (a nested-child violation hard-fails the
whole run). We use the blacklist dimension only; the graded .4/.3/.2/.1 dimensions
are not part of our gate — reward-hacking is binary, not scored.

## Staged trust (unchanged posture)

Deterministic checks + blacklist + latent-bug vetoes are **walk-away-grade**.
The two LLM thresholds (plan-alignment, test-faithfulness) are **on probation
until they earn a false-pass record** — build the scorer now, but for
feature-dev fan-out treat a clear as "inspect-after," not "done." skill-opt's
numeric gate stays the first true walk-away target.

## Rejected

- **Mirror Mastra's `createScorer` API in-harness.** Adds a code dependency for
  math we can state in a prompt. Reimplement.
- **Prompt Alignment `both` mode.** Unfinished stub — never implemented. Banned.
- **Answer-relevancy as the new mentat-bug-reviewer lens.** Source-confirmed
  (`llm/answer-relevancy/index.ts` generateScore: yes=1, unsure=0.3, no=0 over
  output-statements-vs-input): it measures does-the-answer-address-the-question —
  which IS mentat-plan-reviewer's intent/Prompt-Alignment axis. Adopting it double-
  covers intent and adds no new lens. Hallucination (impl-asserts-unplanned) was
  chosen instead — a genuinely new axis. Rejected.
- **Averaging vetoes with thresholds, or blending good-thing + bad-thing scores.**
  A 0.92 plan-alignment can't buy back a deleted test. Veto dominates; min/floor
  posture, LLM never self-promotes.
- **impl-claims-vs-plan for Faithfulness.** That judges the implementation —
  mentat-plan-reviewer's and mentat-bug-reviewer' job, not the tests-reviewer's.

## HITL axis (ADR-0010 cross-reference) — added 2026-06-07 by G3-S10

The gate above governs *scored review*. A HITL exit (harness adapter refused to
guess at ambiguity in an AFK chunk — ADR-0010) is a **fourth, orthogonal axis**.
It must NOT be collapsed into the scored-review veto, into the reward-hacking
blacklist, or into `implement-fail`.

**Three orthogonal mechanisms — never substitutable:**

| Axis | Signal | Owned by |
|---|---|---|
| Scored-review veto | reviewer score below threshold (plan/test ≥ 0.88) | this ADR (ADR-0003) |
| Reward-hacking blacklist | LLM-judge score `0.0` on forbidden move/sequence | ADR-0006 + this ADR §blacklist |
| HITL | process exit code `42` + audit reason `hitl-ambiguity` | ADR-0010 |

A `0.92` plan-alignment cannot buy back a `hitl-ambiguity` exit. A blacklist
veto and a HITL exit do not substitute for each other — the blacklist is a
reviewer judgment over the diff, HITL is a runtime signal from the adapter that
no diff was produced because the agent refused to fabricate one. Future reviewers
MUST keep them separate; the gate expression above does not include HITL because
HITL terminates *before* the gate runs.

**Four eject reasons in `mentat-land-queue` verdict inventory (ADR-0011):**

1. `rebase-conflict` — chunk could not rebase onto holding tip.
2. `gate-fail` — re-gate red after rebase (covers scored-review veto + blacklist).
3. `not-ff` — chunk would not fast-forward into holding branch.
4. `hitl-ambiguity` — adapter exited `42` per ADR-0010 (HITL axis). Distinct
   from `gate-fail`; distinct from `implement-fail` (which is an orchestrate-
   upstream verdict, not a land-queue eject reason).

The `hitl-ambiguity` reason is NOT a blacklist hit, NOT a scored-review veto,
and NOT collapsible into `implement-fail`. See ADR-0010 §"Axis discipline" for
the canonical three-way table.

## Consequences

Reviewer defs emit `PASS|FAIL score=…` with a veto field. `/mentat-implement` step 5
gates on the full expression above. Provenance for the mapping lives in the
VERIFIED reviewers↔Mastra handoff; this ADR is the locked decision-of-record.
