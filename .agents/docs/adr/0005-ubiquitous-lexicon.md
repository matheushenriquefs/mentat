# ADR 0005: Ubiquitous lexicon — slice/chunk/batch, one Laravel borrow

Status: Accepted (locked)
Date: 2026-06-03

## Context

The system's terms (`slice`, `chunk`, `slug`, holding branch, land) grew across
ADRs 0001-0004 and the `to-*`/`devcontainer-*` scripts. They were *consistent
in spirit* but never collected, and two gaps bit: (1) `slice` and `chunk` were
used near-interchangeably in prose though they name different layers; (2) there
was no noun for "the whole set of chunks in one `to-orchestrate` run" — code
said `SLUGS[@]`, prose said "the queue" / "the whole run". One word imported
from Laravel (`batch`) closes that gap; nothing else there maps. Locked here so
every command, ADR, and script speaks one vocabulary.

## Decision — the lexicon

- **slice** — a *planned* vertical tracer-bullet cut. An INPUT artifact: a
  `plan.md`. Taxonomy owned by `/to-plan` + `/to-issues` (AFK/HITL tags theirs).
- **chunk** — the *running execution* of one slice: worktree + devcontainer +
  its own branch off `main`, running `/to-implement`. One slice → one chunk.
- **batch** — the full set of chunks in one `to-orchestrate` run. The parallel
  fan-out group; lands when all-green, ejects per-chunk on red.
- **slug** — a chunk's unique id; also its worktree dirname and `dmux_slug`
  container label. (`dmux-<epoch>-<pid>-<rand>`.)
- **harness** — the headless agent CLI (`cursor-agent` | `claude`). The thing
  `--harness=` selects, `to-track-harness` watches, `harness-map.jq` normalizes,
  and `harness_cmd()` builds an invocation of. Never "build" (collides with
  Docker `build:` in `devcontainer-up`).
- **holding branch** (`$HOLDING`, `branch/<feature>`) — own-branch land target
  with no commits of its own (ADR 0002).
- **land** — the cross-branch move: rebase the chunk onto `$HOLDING`
  in-container, re-gate, host `merge --ff-only` (ADR 0004). Never "merge"
  (dmux's Merge is the rejected thing — ADR 0002).

slice : chunk :: plan : process. If a sentence is about the cut, say slice; if
it's about the worktree/container/branch doing the work, say chunk; if it's
about all of them together in one run, say batch.

## The one Laravel borrow — `batch`, noun only

`batch` is taken from Laravel's job batching (parallel group, monitor
completion, act when all done / on first failure) because it's idiomatic and
ground-truthable against their docs. **We adopt the noun, NOT the semantics.**
Laravel batch jobs are independent and order-free; our chunks are not — landing
is serial and each chunk rebases onto the tip the previous one left (ADR 0004's
merge queue). So `batch` names the group; it does NOT imply `then()`/`catch()`/
`finally()` independence or any dispatch/handle/worker model. Read "batch" as
"the run's chunks," nothing more.

## Rejected

- **`chunk(s)` for the group.** Plural of the execution unit is a pile of
  chunks, never a name for the group-as-a-unit — can't say "re-gate the batch"
  or "the batch lands all-green". Different layer, needs its own noun.
- **Laravel `Job` for chunk.** Imports serialize→store→pop→worker; our chunk is
  a live worktree+container, not a serialized payload. Keep `chunk`.
- **Laravel `Chain` for the land pass.** Chain = sequential, skip-rest-on-fail.
  Ours ejects-and-continues. Close enough to mislead. Keep "land pass / merge
  queue" — git vocabulary, already correct.
- **Laravel `dispatch`/`handle`/`release`/`tries`.** Queue-backend verbs with no
  worktree analog.
- **`run` / `wave` for the group.** Fine, but not ground-truthable; `batch` is
  the idiomatic pick.

## Terse file-style — confirmed, not changed

Sanity-checked: the in-house `to-*` style (dense, telegraphic, imperative) is
consistent across AGENTS.md and the ADRs. No edits. The rule, stated once: that
terseness is for FILES (ADRs, AGENTS.md/CLAUDE.md, command bodies, script
comments) — prose with a human in chat is exempt.

## Consequences

`harness_cmd` replaces `build_cmd` in `to-orchestrate` (this lexicon's rename).
ADRs and AGENTS.md use slice/chunk/batch per the layers above. New terms join
this table rather than drifting in inline. This ADR is index-only in AGENTS.md
(titles-only; body on demand — ADR 0001's context budget).
