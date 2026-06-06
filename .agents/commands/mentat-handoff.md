---
description: Snapshot current session state into a handoff doc — worktrees, orchestration, stash, HITL blockers, next steps.
---

$ARGUMENTS

Produce a markdown handoff document. Run each probe and embed the output verbatim.

## Probes to run

```bash
# 1. Git state
git log --oneline -8
git stash list
git status --short

# 2. Active worktrees (chunk agents still alive)
git worktree list | grep -v dmux

# 3. Latest orchestrate session + outcome
ls -t ~/.agents/mentat/logs/$(basename $(git rev-parse --show-toplevel 2>/dev/null || pwd))/*/mentat-orchestrate*.jsonl 2>/dev/null | head -1 | xargs tail -5 2>/dev/null

# 4. Any leftover diagnoses
ls -t ~/.agents/mentat/diagnoses/*.md 2>/dev/null | head -5

# 5. Pending HITL (stash[0] description)
git stash list | head -3
```

## Handoff doc format

```markdown
# Handoff — <date> <worktree>

## What just happened
<1-3 sentence summary: what was being worked on, last action taken>

## Git state
<log + stash + status output>

## Active worktrees / orchestrate session
<worktree list + orchestrate tail>

## Stashed work to review
<stash list, what each stash contains, which to cherry-pick vs discard>

## HITL blockers open
<numbered list — what needs human decision before proceeding>

## Recommended next steps
<ordered list — what to do first in the next session>

## Plans in flight
<list any plan files being worked, their status>
```

Print the completed doc. Do not commit it. If $ARGUMENTS names a file path, write the doc there instead of printing.
