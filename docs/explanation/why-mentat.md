# Why Mentat

Understanding-oriented. This explains the problem Mentat exists to solve, the
category it belongs to, and when it is — and is not — the right tool. For the
elevator pitch and how the pieces connect, see [what-is-mentat.md](./what-is-mentat.md).

## The problem

A coding agent left to run a long task drifts. Context fills and compacts, so the
agent loses the thread of its own earlier reasoning. Project hooks collide with
sandboxed runs. One bad commit poisons everything that follows in the same agent.

The obvious fix — run many agents in parallel to reclaim wall-clock time — trades
one problem for a worse one. Naive fan-out produces merge conflicts between agents
editing the same tree, half-finished work that never integrates, and a review
burden that grows linearly with the agent count. Throughput goes up; coherence
falls apart.

The second instinct — review the work after it merges, through pull-request
comments — catches problems too late. By the time a human reads the comment, the
code is already on the shared branch, and the agent that wrote it has moved on. The
quality signal arrives after the cost is sunk.

## The shape of the answer

Mentat splits a plan into vertical slices that integrate independently, runs each
slice as an isolated chunk, and lands chunks back one at a time through a gate that
runs *before* the work joins the shared branch.

Two properties make this work:

- **Parallel-out, serial-in.** Slices implement concurrently for throughput;
  landing is single-threaded so the shared branch stays coherent. A ref cannot move
  two ways at once, and serial landing lets each chunk rebase onto the tip the
  previous one left — sibling divergence resolves at land time, not in a tangle.
- **Pre-merge quality gate, not post-merge comments.** Each chunk passes a scored
  gate before it lands. Deterministic checks and reviewer subagents veto bad work
  while it is still isolated in its own worktree. A failure ejects one chunk for
  repair without blocking the rest of the batch.

Isolation is physical: every chunk gets its own git worktree and its own
devcontainer, so project hooks and toolchains run against one chunk's tree without
touching another's.

## The category: a primitive, not a framework

Mentat is a barebones primitive. It composes a small set of tools already on the
machine — git worktrees, a container engine, and a chosen agent CLI — and adds the
one thing those tools do not provide on their own: a scored, serial land queue.

This is a deliberate category choice. Mentat sits with the lean building blocks of
software — the kind a larger system is assembled *from*, not the kind that dictates
how the whole system is shaped. It is not a platform, not a daemon, not a hosted
service, and not a UI. The test every change is held to: a change that exposes a
primitive ships; a change that adds framework weight is refused.

The cost of that choice is real. Mentat does less than a full platform, on purpose.
It expects the user to bring their own editor, their own dashboard, and their own
sense of when to look.

## When to use Mentat

- You want headless, scriptable parallel agents you can drive from the command line.
- You want a quality veto *before* work merges, not review comments after.
- You want a single, consistent audit trail across whichever agent CLI you run.
- You run on local hardware and trust your devcontainer.

## When not to use Mentat

- You want a graphical interface for reviewing diffs and steering agents — reach
  for a desktop agent manager built for that.
- You want agents running on cloud VMs rather than your own machine.
- You want pull-request-comment review without gating the merge.
- You cannot run a container engine. The devcontainer dependency is mandatory and
  has no host-only fallback.

## Honest limitations

These are present-tense facts, not promises of future work:

- **Reviewer thresholds are chosen, not measured.** The pass thresholds for the
  scored reviewers are set by judgment. They are reasonable defaults, not values
  fit to a labeled corpus.
- **Token-usage accounting is partial.** Harness adapters report usage only when the
  underlying CLI emits it; where a CLI emits nothing, Mentat records no usage rather
  than inventing a number.
- **A container engine is required.** Every project-tool invocation runs in a
  devcontainer. Hosts without a container engine cannot run Mentat. This buys
  reproducibility and host-isolation at the cost of that hard dependency.
