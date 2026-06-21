# Plan, then orchestrate parallel chunks

Task-oriented. Goal: fan several slices out as parallel chunks and land them back
serially onto one holding branch.

For a single plan in one session, see [plan-then-implement](./plan-then-implement.md).

## 1. Write the plans

```
/mentat-plan checkout-flow
```

When slices form groups with disjoint write-sets and no chain between them, the
planner emits sibling plans plus a parent index. Orchestrate expands the parent into
its siblings and fans them out; passing the parent is equivalent to passing every
sibling.

## 2. Run orchestrate

```
/mentat-orchestrate run holding/checkout-flow checkout-flow
```

The first positional is the holding branch; the rest are plan refs. The run:

1. Topologically sorts plans by their `blocked_by` dependencies.
2. Fans independent plans out as parallel chunks — each its own worktree,
   devcontainer, and branch (up to the `concurrency` cap, default 3).
3. Implements and gates each chunk in parallel.
4. Lands chunks **serially** through the merge queue: per chunk, rebase onto the
   live holding tip, re-gate the rebased tree, fast-forward or eject.
5. Runs one advisory batch review over the final landed tip.

`--harness` and `--model` override the configured defaults; `--dry-run` prints the
schedule without spawning anything.

## 3. Watch it

Orchestrate prints a track command at the start. See
[orchestrate with tracking](./orchestrate-with-tracking.md) for the live view.

## 4. Handle ejected chunks

A chunk that fails to rebase cleanly or fails the re-gate is **ejected**: its
worktree is left up for repair and the queue continues with the rest of the batch.
Diagnose an ejected chunk with [doctor](./doctor.md), fix the slice, and re-run.

A chunk that hits a decision an unattended agent cannot resolve wedges for a human —
see [hitl-handoff](./hitl-handoff.md).

## 5. Review and merge

```
/mentat-git diff main..holding/checkout-flow
git checkout main && git merge --ff-only holding/checkout-flow
```

## Notes

- Tune parallelism with the `concurrency` key in `~/.mentat/config.toml`. Higher
  counts raise the chance of rebase collisions at land time — raise it deliberately.
- Landing is serial by construction; only implementation runs in parallel. This is
  the [parallel-out, serial-in](../explanation/why-mentat.md#the-shape-of-the-answer)
  property.
