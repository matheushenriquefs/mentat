# What is Mentat

Understanding-oriented. This is the elevator pitch and the shape of the system. For
the problem it solves and where it fits, see [why-mentat.md](./why-mentat.md). For
the full narrative, see [ARCHITECTURE.md](../ARCHITECTURE.md).

## In one line

Mentat is a merge-queue for parallel coding agents: it fans a plan out across
isolated agents, then rebases, re-gates, scores, and lands each one back onto a
holding branch.

## The pitch

A plan is cut into vertical slices. Each slice fans out as a chunk — its own git
worktree, its own devcontainer, its own branch — running a coding agent unattended.
When a chunk's work passes its gate, it joins a serial land queue. The queue takes
one chunk at a time: it rebases the chunk onto the live holding-branch tip, re-runs
the target repository's quality gates on the rebased tree, and fast-forwards the
holding branch if everything is green. A chunk that fails to rebase cleanly or fails
the re-gate is ejected — its worktree left up for repair — while the queue moves on
to the next chunk.

The result is a holding branch that only ever advances through green, integrated
work. When the whole batch has landed, a human merges the holding branch into the
mainline from outside the loop.

## How the pieces fit

```
plan ──split──▶ slices ──fan out──▶ chunks (worktree + devcontainer + branch)
                                       │
                                       ▼ implement + gate, in parallel
                                    land queue (serial)
                                       │  rebase ▶ re-gate ▶ fast-forward
                                       ▼
                                 holding branch ──human merge──▶ mainline
```

- A **slice** is a planned vertical cut, written as a `plan.md`.
- A **chunk** is one slice running: a worktree, a devcontainer, and a branch.
- A **batch** is every chunk in one orchestration run.
- The **holding branch** carries no commits of its own; chunks fast-forward onto it.
- **Landing** is the rebase → re-gate → fast-forward move. A failed land is an
  **eject**, not a merge conflict left in the tree.

Each of these terms is defined precisely in the [glossary](../../CONTEXT.md).

## Single agent or a whole batch

Mentat scales down as cleanly as it scales out. One plan can run start-to-finish in
a single agent — implement, gate, land — without any fan-out at all. The same
primitives drive both: the land queue with one chunk in it behaves exactly like the
land queue with ten.

## The name

Mentat takes its name from Frank Herbert's *Dune*, where a Mentat is a human trained
to think with the rigor once delegated to machines. The name is framing only; it
carries no meaning in the system's technical behavior.
