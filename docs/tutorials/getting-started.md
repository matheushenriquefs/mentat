# Getting started

Learning-oriented. This walks one complete first run end to end: plan a small
change, implement it in an isolated worktree, gate it, land it onto a holding
branch, and review what landed. By the end you will have seen every stage of the
core loop on a real change.

This tutorial runs a **single plan, self-contained** — no fan-out yet. Once the loop
is familiar, [plan-then-orchestrate](../how-to/plan-then-orchestrate.md) shows how to
fan several slices out in parallel.

## Before you start

- Mentat installed (see [installation](../how-to/installation.md)).
- A container engine running.
- A git repository you can experiment in, with a `main` branch.

Open your agent harness inside that repository. Every `/command` below is run from
the harness prompt.

## 1. Plan the change

Pick something small and self-contained for the first run — one function, one new
flag, one bug fix. Start the planner:

```
/mentat-plan hello-mentat
```

The planner grills you about the change, then writes a plan file to
`~/.agents/plans/hello-mentat.md`. The plan is cut into vertical slices, each tagged
`AFK` (gate clears unattended) or `HITL` (needs a human decision). For a first run,
aim for a single AFK slice.

Open the plan and read it before continuing. It is plain markdown — edit it directly
if a slice is wrong.

## 2. Implement and land

Run the plan start to finish in one agent:

```
/mentat-implement run --land --holding holding/hello-mentat hello-mentat
```

What happens:

1. **Worktree.** Mentat creates an isolated worktree under
   `.mentat/worktrees/hello-mentat` and a devcontainer for it. Your main working
   tree is untouched.
2. **Implement.** The agent writes a failing test, then the implementation, and
   commits one commit per slice.
3. **Gate.** The scored review gate runs: deterministic checks plus reviewer
   subagents. A veto or a failed check stops the run for repair.
4. **Land.** Once green, the chunk rebases onto `holding/hello-mentat` and
   fast-forwards onto it.

If a slice was tagged `HITL`, the run hands control back to you at the decision
point instead of landing unattended.

## 3. Watch it run

In a second harness agent, watch progress live:

```
/mentat-track track
```

This streams the run's events and the agent's activity. Leave it open while the
implement run works.

## 4. Review what landed

When the run finishes, review the holding branch before merging:

```
/mentat-git diff main..holding/hello-mentat
```

Mentat also prints a review suggestion at the end of the run, using your configured
diff command.

## 5. Merge

The holding branch only advances through green, gated work. When you are satisfied,
merge it into `main` yourself, from outside the loop:

```
git checkout main && git merge --ff-only holding/hello-mentat
```

## What you did

You took a change from plan to merged code through the full loop: isolated worktree,
test-first implementation, a scored gate, and a serial land onto a holding branch.

Next steps:

- [Plan then implement](../how-to/plan-then-implement.md) — the single-plan loop in
  reference detail.
- [Plan then orchestrate](../how-to/plan-then-orchestrate.md) — fan several slices
  out as parallel chunks.
- [What is Mentat](../explanation/what-is-mentat.md) — the model behind the loop.
