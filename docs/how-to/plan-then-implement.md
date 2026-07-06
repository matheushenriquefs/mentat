# Plan, then implement a single plan

Task-oriented. Goal: take one plan from written to landed in a single session, with
no fan-out. This is the self-contained loop — useful for a focused change or when
you want to stay in the loop the whole way.

For parallel fan-out across many slices, see
[plan-then-orchestrate](./plan-then-orchestrate.md).

## 1. Write the plan

```
/mentat-plan add-csv-export
```

The planner grills the requirements and writes `~/.agents/plans/add-csv-export.md`,
cut into vertical slices tagged `AFK` or `HITL`.

## 2. Run it self-contained

```
/mentat-implement run --land --holding holding/add-csv-export add-csv-export
```

`--land` makes the run self-contained: after every slice is green, the chunk rebases
onto the holding branch, fast-forwards, and an advisory batch review runs. Without
`--land`, the run stops after the gate and leaves landing to you.

`--holding` sets the target branch (defaults to `main`). `--harness` and `--model`
override the configured harness and model for this run.

What the run does, in order:

1. Creates an isolated worktree and devcontainer for the plan.
2. Implements each slice test-first, one commit per slice.
3. Runs the scored gate ([the review gate](../explanation/why-mentat.md#the-shape-of-the-answer)).
4. Lands onto the holding branch and runs the advisory batch review.

## 3. Handle a stop

- **Gate failure** → the run exits non-zero, the worktree is preserved, and
  `mentat-track doctor` is spawned to write a diagnosis. See [doctor](./doctor.md).
- **A HITL slice** → the run hands control back to your session at the decision
  point rather than guessing. See [hitl-handoff](./hitl-handoff.md).

## 4. Review and merge

```
/mentat-git diff main..holding/add-csv-export
git checkout main && git merge --ff-only holding/add-csv-export
```

## Notes

- One plan slug per `mentat-implement` run. Passing more than one is refused — use
  [orchestrate](./plan-then-orchestrate.md) for multiple plans.
- The run prints `mentat-track track <session>` at the start so you can watch it
  from another session. See [tracking a run](./tracking-a-run.md).
