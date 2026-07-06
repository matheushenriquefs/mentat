# Mix AFK and HITL plans in one run

Task-oriented. Goal: drive a set of plans where some run unattended (`AFK`) and some
need a human at a decision point (`HITL`), without one blocking the other.

## How kind routing works

Every plan carries a `kind:` in its frontmatter:

- **AFK** — the gate clears unattended. The agent never stops to ask; an ambiguity
  it cannot resolve is an ejection, not a question.
- **HITL** — the run drives in your calling session so a human can answer at the
  decision points. It is never spawned headless.

Orchestrate routes by kind. AFK plans fan out as parallel chunks. A HITL plan is
not spawned headless — it is handed to your session to drive directly.

## 1. Fan out the AFK plans

Run orchestrate over the AFK plans against a holding branch:

```
/mentat-orchestrate run holding/feature afk-plan-a afk-plan-b
```

These land through the serial merge queue as usual. See
[plan-then-orchestrate](./plan-then-orchestrate.md).

## 2. Drive the HITL plan in session

Run the HITL plan with `mentat-implement` in your interactive session, landing onto
the same holding branch so it joins the rest:

```
/mentat-implement run --land --holding holding/feature hitl-plan-c
```

Because the plan is `HITL`, the run stays in your session and stops at each decision
point for your answer instead of guessing.

## 3. Handle a wedge from an AFK chunk

An AFK chunk that hits an unresolvable decision wedges rather than guessing: it
writes a blocker to `summary.md` and ejects with a hitl-required reason, preserving
its worktree. Resume it as a HITL run once you have made the call — see
[hitl-handoff](./hitl-handoff.md).

## 4. Review and merge

Once both the fanned-out chunks and the in-session plan have landed:

```
/mentat-git diff main..holding/feature
git checkout main && git merge --ff-only holding/feature
```

## Notes

- Kind lives in plan frontmatter and is never overridden at runtime — there is no
  environment flag that flips a plan's kind.
- Landing onto a shared holding branch is what lets AFK and HITL work converge:
  whoever lands next rebases onto the tip the previous one left.
