---
description: Implement a plan using TDD inside the devcontainer. Score-gate the review, then rebase the holding branch.
---

$ARGUMENTS

1. `/caveman ultra`.
2. `~/.agents/bin/mentat-container-up`.
3. Use `/tdd`. Run each test via `~/.agents/bin/mentat-container-run '<test command>'`. Discover the test command from CLAUDE.md or AGENTS.md.
4. After each green slice, `/mentat-commit` scoped to that slice's files.
5. When the plan is fully implemented, spawn `mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer` in parallel, each given the plan path + the cumulative diff (and mentat-bug-reviewer the slice trajectory if available). Gate (ADR 0003 — never average, veto > threshold):

   ```
   gate_pass =
         deterministic_checks_all_green     # tests green / coverage delta >= 0 / no weakened-or-deleted assertion — VETO
     AND trajectory_blacklist_clean         # mentat-bug-reviewer blacklist — VETO (0.0 kills the chunk)
     AND max_latent_bug_sev < high          # mentat-bug-reviewer latent-bug lens — VETO
     AND plan_alignment    >= 0.88          # mentat-plan-reviewer — LLM threshold
     AND test_asserts_plan >= 0.88          # mentat-test-reviewer — LLM threshold
   ```

   `gate_pass` → continue. Any veto tripped or either threshold below 0.88 → fix the cited miss, re-commit, re-spawn the three. Don't rebase on a FAIL. Never average a threshold against a veto — a clean code read can't buy back a deleted test.
6. `/mentat-rebase <holding-branch>`. Ask the user for the holding-branch name if not specified in $ARGUMENTS.
7. `~/.agents/bin/mentat-container-down`.
