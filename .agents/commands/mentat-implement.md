---
description: Implement a plan using TDD inside the devcontainer. Score-gate the review, then rebase the holding branch.
---

$ARGUMENTS

AFK contract + harness adapters: see ADR-0004 (folded) and `.agents/lib/harness/registry.py`.

0. **Worktree preflight.** `pwd` must match `$MENTAT_WORKTREE`, `.*/\.mentat/worktrees/[^/]+/?$`, or `.*/worktrees/[^/]+/?$` (parent-harness fallback). Else halt + emit `log.py emit mentat-implement implement.preflight.fail "{\"cwd\":\"$(pwd)\"}"`.
1. Emit start: `python3 ~/.agents/skills/mentat-log/scripts/log.py emit mentat-implement implement.start "{\"plan\":\"$ARGUMENTS\"}"`.
2. **Pre-flight artifact check.** Parse slice list; derive each artifact predicate (exists/absent/grep N) as bash one-liner. Emit `implement.preflight {slices:[{id,status,predicate}]}`. Refuse DONE slices; refuse skips not marked DONE.
3. `/caveman ultra` then `python3 ~/.agents/skills/mentat-container/scripts/container.py up`.
4. `/tdd`. Run each test via `python3 ~/.agents/skills/mentat-container/scripts/container.py run '<test cmd>'`. Discover test cmd from CLAUDE.md/AGENTS.md.
5. **Rename/delete discipline.** "rename X → Y" / "drop X": `git mv`/`git rm` first in own commit. Post-commit `git ls-files | grep <old>` must return 0. Emit `rename.complete {old,new}`.
6. **Stale-ref sweep pre-commit.** After rename/delete, run plan's `rg` lines. Non-zero = abort. Emit `staleref.sweep {terms,hits}`.
7. After each green slice, `/mentat-commit` scoped to that slice.
8. When fully implemented, spawn `mentat-plan-reviewer`, `mentat-test-reviewer`, `mentat-bug-reviewer`, `mentat-smell-reviewer` in parallel with plan path + cumulative diff (bug-reviewer also gets slice trajectory). Gate (ADR-0003 — never average, veto > threshold):
   ```
   gate_pass =
         deterministic_checks_all_green     # tests / coverage delta >= 0 / no weakened-or-deleted assertion — VETO
     AND trajectory_blacklist_clean         # mentat-bug-reviewer blacklist — VETO
     AND max_latent_bug_sev < high          # mentat-bug-reviewer latent-bug lens — VETO
     AND plan_alignment    >= 0.88          # mentat-plan-reviewer — LLM threshold
     AND test_asserts_plan >= 0.88          # mentat-test-reviewer — LLM threshold
     AND smell_findings.hard_tier == []     # mentat-smell-reviewer — hard-tier deterministic veto
     AND smell_findings.soft_tier[sev=high] == []  # mentat-smell-reviewer — soft-tier LLM sev=high veto
   ```
   Any veto/threshold fail → fix, re-commit, re-spawn. Don't rebase on FAIL. Dismiss only via `review.dismiss {reviewer, score, reason}` enumerating refuted findings + disproof — prose-only forbidden.
9. Emit complete (`implement.complete`), `/mentat-rebase <holding-branch>` (ask user if not in $ARGUMENTS), then `python3 ~/.agents/skills/mentat-container/scripts/container.py down`.
