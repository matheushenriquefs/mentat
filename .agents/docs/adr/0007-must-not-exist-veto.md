# ADR 0007: Three-class drift model — must_not_exist veto, non_pytest_gate, design_drift surface

Status: Proposed
Date: 2026-06-05
Amends: ADR 0003 (adds veto + surface; does not alter gate thresholds or existing vetoes)

## Context

Two handoff postmortems exposed gaps in the P4 review gate:

**HANDOFF2 root cause**: `mentat-plan-reviewer` scored 0.96 with 4 plan-specified route removals still present in the diff. The score's recall-weighted math treated absence-of-removal as noise, not as a violation. No veto fired.

**HANDOFF4 root cause**: `mentat-test-reviewer` scored 0.71 on a Taskfile-only diff. Config changes can't be expressed as pytest assertions; the low score was a structural false flag, not evidence of a faithfulness gap.

**Asymmetry**: HIGH findings vetoed; MEDIUM design-scope drift accumulated silently across plan iterations.

Three distinct drift classes emerged:

1. **Recall miss on must-not-exist** — plan says "drop X"; diff keeps X; no veto fires.
2. **Structural false flag** — config-only diffs score low on test faithfulness despite being untestable by pytest.
3. **Severity asymmetry** — only HIGH bugs vetoed; MEDIUM design rot made invisible.

## Decision

### Class 1 — must_not_exist veto (added to mentat-plan-reviewer)

Extract every plan line containing: `drop`, `remove`, `replace`, `no longer`, `must not`, `should not`, `delete`, `eliminate`. These name entities the plan requires to be absent from the diff.

For each entity: grep the diff. Present → VETO `must_not_exist`, `max_sev=HIGH`, hard FAIL. Score computation skipped. This fires **before** scoring and **overrides** the 0.88 threshold.

Rationale: absence-as-evidence is deterministic — either the entity is in the diff or it isn't. An LLM scorer can miss it; a grep cannot. Treat it like the blacklist: deterministic, walk-away-grade.

### Class 2 — non_pytest_gate (added to mentat-test-reviewer)

When **all** changed files are config-only (Taskfile.yml, Dockerfile, .github/workflows/, pyproject.toml, package.json, *.yaml outside src/, etc.), emit `gate_type: non_pytest`, score=N/A, veto=N/A. Defer to the integration check named in the plan (e.g., "task build:test exits 0").

If any source file (src/, lib/, *.py, *.ts, *.js, *.rs, …) is changed, use the standard two-halves gate.

Rationale: pytest can't assert "the CI task runs without error." Scoring config-only diffs as if they had test coverage manufactures false failures. The plan's named integration check is the correct gate.

### Class 3 — design_drift surface (added to mentat-bug-reviewer)

After lenses A–C (blacklist, latent-bug, hallucination): scan MEDIUM findings. Separate:
- MEDIUM items that are design/scope drift → `design_drift[]` (non-vetoing, feeds next plan)
- MEDIUM items that are real bugs → stay in `findings[]`

`design_drift[]` never vetoes the current gate. Items feed back into the next plan iteration so drift accumulates visibly rather than silently.

## Gate expression (updated, extends ADR 0003)

```
gate_pass =
      deterministic_checks_all_green         # tests green / coverage delta >= 0 / no weakened assertion — VETO
  AND must_not_exist_veto_clean              # mentat-plan-reviewer: grep-absent check — VETO (new)
  AND trajectory_blacklist_clean             # mentat-bug-reviewer blacklist — VETO (0.0 kills chunk)
  AND max_latent_bug_sev < high              # mentat-bug-reviewer latent-bug lens — VETO
  AND plan_alignment    >= 0.88              # mentat-plan-reviewer score threshold
  AND test_asserts_plan >= 0.88              # mentat-test-reviewer score threshold (skip if non_pytest_gate)
```

`design_drift` non-empty on a PASS is normal and expected — drift surfaces, does not block.

## Rejected alternatives

- **Score-penalize retained entities instead of veto.** A 0.95 plan score can still pass while 4 removed routes remain. Grep is deterministic; don't route deterministic checks through a probabilistic scorer.
- **Skip mentat-test-reviewer entirely for config diffs.** Loses the reviewer's structural presence in the gate. Better to emit a named gate type and defer to the integration check.
- **Promote MEDIUM design drift to HIGH to force a veto.** Inflation. Real HIGH bugs are already vetoed. Drift that isn't a bug should accumulate into the next plan, not sabotage the current gate.

## Consequences

- `mentat-plan-reviewer.md`: `must_not_exist` section added before scoring.
- `mentat-test-reviewer.md`: `non_pytest_gate` carve-out added before two-halves gate.
- `mentat-bug-reviewer.md`: `design_drift[]` section D added after lenses A–C.
- `mentat/.agents/evals/`: promptfoo + pytest harness added; fixtures for all three drift classes.
- ADR 0003 gate expression extended; existing thresholds and vetoes unchanged.
- Drift that was previously invisible now surfaces via `design_drift[]` on every review.
