# ADR 0003: Scored review gate (folds ADR-0007 must-not-exist + ADR-0008 smell)

Status: Accepted (locked)
Date: 2026-05-31
Amended: 2026-06-09 (v2 — folds 0007 + 0008; Python gate runner; gate filesystem layout)
Amended: 2026-06-10 (v3 — reviewers promoted to `.agents/agents/` subagents; `score.py` added; install-time symlinks; old LLM rubric dir retired)
Amended: 2026-06-20 (v4 — `mentat-rules-reviewer` + `mentat-context-reviewer` join the gate as advisory; ADR-0012 code-rules layer)
Amended: 2026-06-21 (v5 — both reviewers promoted from advisory to veto; full-tree scan confirmed clean)

## Context

Four reviewers evaluate each chunk. Without scored thresholds + veto tiers the gate
can't be trusted unattended. Mastra eval scorers (source-verified) provide the math.
Three prior ADRs (0003 + 0007 + 0008) covered overlapping ground; folded here.

## Decision

Gate pass formula (never average; veto > threshold):

```
gate_pass =
      deterministic_checks_all_green     # tests green / coverage ≥ 0 / no weakened assertion — VETO
  AND trajectory_blacklist_clean         # forbidden reward-hacking moves — VETO (0.0 kills chunk)
  AND max_latent_bug_sev < high          # latent-bug lens — VETO
  AND no_severe_hallucination            # impl asserts unplanned behavior — VETO (inverted polarity)
  AND plan_alignment    >= 0.88          # Prompt Alignment (user mode) — LLM threshold
  AND test_asserts_plan >= 0.88          # Faithfulness scorer (plan-as-context) — LLM threshold
  AND smell_score       >= 0.85          # code-smell advisory — no max-sev veto
  AND rules_violations  == 0             # code-rule conformance — VETO (promoted v5)
  AND context_findings  == 0             # prose/prompt residue — VETO (promoted v5)
```

Gate filesystem layout:
- `.agents/lib/gates/code/*.py` — Python callables `run(chunk_path: Path) -> tuple[str, str]`
  returning `(verdict, message)` where `verdict ∈ {"pass", "block", "advise"}`.
- `.agents/agents/mentat-*-reviewer.md` — reviewer subagent source (harness-agnostic).
  Installed via symlink: `~/.claude/agents/`, `~/.cursor/agents/` etc. per detected harness.
- `.agents/lib/gates/score.py` — parses subagent JSON verdicts, applies thresholds, aggregates.

Severity per gate: `code/precommit.py` = blocking; `code/smells.py` = advisory;
`mentat-bug-reviewer` = blocking with threshold; `mentat-smell-reviewer` = advisory.

Enforcing reviewers (promoted v5, folded from ADR-0012): `mentat-rules-reviewer`
(code-rule conformance against `.agents/rules/` + lexicon contradictions) and
`mentat-context-reviewer` (prose/prompt residue + self-containment) are both veto gates —
`score.py` routes them through `score_rules` / `score_context`, which return `block` on
any finding (zero tolerance). Full-tree scan confirmed clean before promotion. Their
verdict bases do not overlap: rules-reviewer owns code rules and lexicon, context-reviewer
owns prose residue.

Must-not-exist veto (folded from ADR-0007): `code/precommit.py` emits `block` on
forbidden file/path patterns (e.g. test-file writes during impl phase).

Smell review (folded from ADR-0008): `mentat-smell-reviewer` runs refactoring.guru 22-smell
catalog. Advisory; severity escalation at callsite. Threshold 0.85.

HITL exit `42` (`hitl-ambiguity`) is NOT a blacklist hit — it's a separate axis
owned by ADR-0004 (HITL routing contract folded there).

## Consequences

Three overlapping ADRs → one. Old 0007 and 0008 archived. Gate runner iterates
`gates/code/*.py` (deterministic), then spawns reviewer subagents (`mentat-plan-reviewer`,
`mentat-test-reviewer`, `mentat-bug-reviewer`, `mentat-smell-reviewer`) via Agent tool;
`score.py` aggregates verdicts per ADR-0003 formula. New subagent reviewer: add file to
`.agents/agents/`, run `mentat-install` for harness symlinks. Old LLM rubric content
moved into subagent bodies; retired directory cleaned up by `mentat-install` (ADR-0003 v3).
