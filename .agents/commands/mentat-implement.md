---
description: Implement a plan using TDD inside the devcontainer. Score-gate the review, then rebase the holding branch.
---

$ARGUMENTS

1. Emit start: `source ~/.agents/bin/lib/audit.sh && mentat_audit mentat-implement implement.start "{\"plan\":\"$ARGUMENTS\"}"`.
2. **Pre-flight artifact check (mandatory).** Parse the plan's slice list. For each slice derive its artifact predicate (file exists / file absent / grep returns N hits). Run predicates as bash one-liners. Emit `implement.preflight` audit event with `{slices:[{id,status,predicate}]}` table. Refuse to implement slices already marked DONE. Refuse to skip slices unless table marks DONE.
3. `/caveman ultra`.
4. `~/.agents/bin/mentat-container-up`.
5. Use `/tdd`. Run each test via `~/.agents/bin/mentat-container-run '<test command>'`. Discover the test command from CLAUDE.md or AGENTS.md.
6. **Rename/delete discipline.** When plan says "rename X → Y" or "drop X": run `git mv`/`git rm` first in its own commit. Post-commit: `git ls-files | grep <old>` must return 0. Emit `rename.complete {old, new}` audit event.
7. **Stale-ref sweep pre-commit.** After any rename/delete slice, run the plan's verification `rg` lines. Non-zero hit = abort commit. Emit `staleref.sweep {terms, hits}`.
8. After each green slice, `/mentat-commit` scoped to that slice's files.
9. When the plan is fully implemented, spawn `mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer` in parallel, each given the plan path + the cumulative diff (and mentat-bug-reviewer the slice trajectory if available). Gate (ADR 0003 — never average, veto > threshold):

   ```
   gate_pass =
         deterministic_checks_all_green     # tests green / coverage delta >= 0 / no weakened-or-deleted assertion — VETO
     AND trajectory_blacklist_clean         # mentat-bug-reviewer blacklist — VETO (0.0 kills the chunk)
     AND max_latent_bug_sev < high          # mentat-bug-reviewer latent-bug lens — VETO
     AND plan_alignment    >= 0.88          # mentat-plan-reviewer — LLM threshold
     AND test_asserts_plan >= 0.88          # mentat-test-reviewer — LLM threshold
   ```

   `gate_pass` → continue. Any veto tripped or either threshold below 0.88 → fix the cited miss, re-commit, re-spawn the three. Don't rebase on a FAIL. Never average a threshold against a veto — a clean code read can't buy back a deleted test. To dismiss a reviewer finding, emit `review.dismiss {reviewer, score, reason}` with reason enumerating each refuted finding and the artifact check that disproved it — prose-only dismissal is forbidden.
10. Emit complete: `mentat_audit mentat-implement implement.complete "{\"plan\":\"$ARGUMENTS\",\"outcome\":\"success\"}"`.
11. `/mentat-rebase <holding-branch>`. Ask the user for the holding-branch name if not specified in $ARGUMENTS.
12. `~/.agents/bin/mentat-container-down`.
