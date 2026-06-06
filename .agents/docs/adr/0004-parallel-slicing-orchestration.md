# ADR 0004: Parallel-slicing orchestration — fan-out parallel, land serial

Status: Accepted (locked)
Date: 2026-06-03

## Context

`/mentat-plan` and `/mentat-issues` already cut work into tracer-bullet vertical
slices, tagged AFK (gate clears unattended) or HITL. That taxonomy is theirs.
Undocumented: how `mentat-orchestrate` *executes* slices — many in parallel, onto
one holding branch — and the hard-to-reverse choices in the driver and the
`mentat-container-*` scripts. Locked here. One plan → many slices → many parallel
chunks → one holding branch.

## Decision

- **The slice is the unit because vertical cuts compose.** Two thin end-to-end
  cuts touch disjoint code and rebase cleanly; two horizontal cuts fight over
  the same files. "Many thin over few thick" is the precondition for safe
  fan-out, not an aesthetic. Un-sliceable plan → babysit one `/mentat-implement`.
- **Fan-out parallel, land serial.** Chunks implement concurrently, each in its
  own worktree + devcontainer. Land one at a time — can't move one ref
  concurrently, and serial landing lets sibling divergence resolve by rebasing
  onto the tip the previous chunk left. Break-even ≥ 2 AFK chunks; cap 3.
- **Each chunk holds its OWN branch.** `/mentat-implement`'s `/mentat-rebase` self-no-ops
  (ff-to-self, no host commit, no holding-branch prompt to stall headless). The
  cross-branch land is the driver's: rebase onto `$HOLDING` *in-container*
  (pre-commit fires where tools live — ADR 0002), re-gate, host `merge --ff-only`.
  A real ff creates no commit object → no host pre-commit, ever.
- **Re-gate after the land rebase — this is a merge queue.** The land loop is a
  merge queue: rebase each chunk onto the *current* tip (siblings already landed
  are in it), re-validate, then ff-only — the standard fix for "two PRs pass CI
  alone, main breaks together" (semantic clash, not a textual conflict). The
  driver names **no project tool**: it re-gates by spawning a `cavecrew-builder`
  that reads the repo's own CLAUDE.md/AGENTS.md and runs that project's quality
  gates in-container on the rebased tree (same command the implementer already
  knew — agnostic by construction). Deterministic *where it counts* (the agent's
  exit code gates the land) without the driver knowing any tool name. **On any red
  (rebase conflict OR gate fail): eject** — leave the worktree up, log the sibling
  tip it rebased onto, continue the queue with the rest. **Never loop-retry one
  chunk** — same commits onto same tip reproduce the same break; repair needs an
  agent or human against the new base.
- **Reviewers run once, at end-of-queue, only when all-green.** The full ADR-0003
  reviewer gate is expensive and there is no point spending tokens on a tree a
  later chunk will change, or on a partial result where a sibling is mid-repair.
  So per-chunk landing runs only the project's own gates (via the agent above);
  the three reviewers run *once*, after the whole queue drains green, over the
  final landed tip. Advisory per ADR 0003's staged-trust posture (reviewers are
  inspect-after until they earn a false-pass record) — a red end-of-queue review
  warns, it does not roll back a landed ref.
- **Language- and harness-agnostic; Docker required.** Any Unix, `cursor` or
  `claude-code` (one stream-json model via `mentat-track`, format self-declared per harness),
  any language. NOT runtime-agnostic. `mentat-container-up` prefers authored
  `.devcontainer/`, else synthesizes over `docker-compose.yml`/`.yaml`, else over
  a bare `Dockerfile`. None of those → abort loud.
- **Project tools run in-container, never host** (imperative in AGENTS.md). The
  driver and the rule name no specific tool — whatever interpreters, linters,
  hooks, or test runner a repo uses, they run via `mentat-container-run`. Two
  unconflated failures drove this: (1) the *agent* reaching for host project tools
  — already container work per ADR 0002, fixed by a reliable `mentat-container-run` +
  the rule; (2) the *scripts'* own `python3`, which parses `devcontainer.json` on
  the host before any container exists and gets hijacked by an asdf shim in a
  `.tool-versions`-less worktree — fixed by resolving a real non-shim `python3`
  for that parsing only.

## Rejected

- **`.tool-versions` per worktree.** Wrong layer — accommodates host work that
  belongs in-container, and litters the worktree (untracked). Bypass the shim for
  the scripts' own parsing instead.
- **Host-side N-way merge of chunks.** Fires host pre-commit (ADR 0002's whole
  point); turns divergence into planner-pane conflict resolution.
- **Trust the chunk's pre-rebase green.** Says nothing about the rebased tree.
- **`@`-import ADRs into AGENTS.md/CLAUDE.md.** Always-loading bodies defeats the
  on-demand design (ADR 0001's context budget). Titles-only index; bodies on demand.
- **Container-runtime abstraction (Podman/nerdctl).** Real cost for a
  single-dev arm64-macOS-Docker setup. Docker is a hard dep by decision.
- **> 3 parallel chunks.** Conflict surface + host RAM/port pressure outrun cheap
  serial landing.
- **Speculative land execution (deferred, not rejected).** Merge queues at scale
  re-gate chunk N against the *hypothetical* tip "holding + all predecessors still
  in the queue" before they land, so the queue moves at gate-speed not serially —
  at the cost of testing a tip that doesn't exist yet and discarding if a
  predecessor ejects. At the 3-chunk cap the serial cost is trivial and the
  complexity isn't worth it. Revisit only if the cap lifts.

## Consequences

`mentat-orchestrate` stays a thin driver over slices others produce — no planning, no
grilling. `mentat-container-*` own runtime-shape detection and host-`python3` hygiene.
New harness = extend the stream-json map, not the control flow.
