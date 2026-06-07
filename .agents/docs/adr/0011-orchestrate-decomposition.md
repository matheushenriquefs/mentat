# ADR 0011 — Orchestrate decomposition: fan-out / land-queue / final-review

Status: Accepted
Date: 2026-06-07
Author: matheussantosh

## Context

`mentat-orchestrate` is a 317-LOC bash driver that conflates five
responsibilities behind one entrypoint:

1. fan-out — spawn parallel chunks, one worktree + devcontainer per slice
2. land-queue — serial rebase-onto-tip → re-gate → `merge --ff-only` or eject
3. eject — leave the worktree intact when a chunk fails its rebase or re-gate
4. final-review — one ADR-0003 reviewer pass over the drained tip
5. session bookkeeping — `MENTAT_SESSION`, `$LOGDIR`, `$HOLDING` globals

Every failure path is observable only through whole-script side effects:
log lines, audit rows, and the worktree state left on disk. Production
telemetry over the last batch run: 27 implement-fail / 23 rebase-conflict /
2 gate-fail / 2 not-ff. Each failure class is a distinct eject reason but
the driver currently emits them through the same shared code path with
weakly-typed `{"reason":"..."}` strings.

ADR-0004 locks the *shape* (fan-out parallel, land serial, one holding branch,
re-gate after rebase, reviewers run once at end-of-queue). G1-S4 routed
`final_review` through the typed audit emit. This ADR locks how that shape
*decomposes* into separately invocable tools, so that each tool is testable in
isolation and reusable inside `mentat-implement`'s solo path.

## Decision

Split the driver into three independent CLI tools plus a thin dispatcher.

### Tools

```
mentat-fan-out      reads:  newline-delimited slice plan paths on stdin
                    writes: newline-delimited chunk slugs on stdout
                    side:   spawns one worktree + devcontainer per path,
                            emits one `chunk.spawn` audit row per spawn

mentat-land-queue   reads:  newline-delimited chunk slugs on stdin
                    writes: JSONL verdicts on stdout, one per chunk:
                            {slug, outcome, tip?, reason?, conflicted_files?,
                             resume_cmd?, findings?}
                            outcome ∈ {"success", "eject"}            (audit schema)
                            reason  ∈ {"rebase-conflict", "gate-fail",
                                       "not-ff", "implement-fail"}   (eject only)
                    side:   per chunk — rebase onto live $HOLDING tip,
                            re-gate via cavecrew-builder, `merge --ff-only` or
                            eject (worktree left intact). Emits one
                            `land.complete` audit row per chunk.

mentat-final-review <base-sha> <tip-sha>
                    reads:  nothing on stdin
                    writes: JSONL verdict on stdout (single line):
                            {reviewer, score, veto, findings, base, tip,
                             stdout?, stderr_path?}
                            (`findings` required by audit schema;
                             stdout-verdict shape duplicates the audit row.)
                    side:   spawns the ADR-0003 reviewer set against
                            (base..tip), captures stdout into the audit field
                            (tail -c 4000) and stderr into the sidecar at
                            `$LOGDIR/.stderr/mentat-final-review.stderr`.
                            Emits one `review.final` audit row.
```

Empty stdin → zero chunks → tools exit 0 with zero verdict lines. Zero-slice
batches are a legitimate no-op (e.g., a plan whose preflight finds every
slice already DONE), not an argv error.

Outcome / reason enums above are the canonical land-verdict vocabulary that
`audit-schema.jsonc::land.complete` already locks. S7 implementers wire
plan-stated failure classes (27 implement-fail / 23 rebase-conflict / 2 gate-fail /
2 not-ff) onto the `reason` field; no new enum values are introduced here.

`mentat-orchestrate` becomes a ≤60-LOC dispatcher: parse a batch spec, pipe
the slice paths into fan-out, pipe the chunk slugs into land-queue, pluck the
landed tip from the last successful verdict, hand it to final-review.

### I/O convention

- **Inputs that are lists**: newline-delimited records on stdin.
- **Inputs that are single refs**: positional argv.
- **Verdicts out**: JSONL (one JSON object per line) on stdout.
- **Audit log**: all telemetry routes through `audit.sh::mentat_audit`. Tools
  emit rows themselves; stdout verdicts duplicate the same facts so downstream
  tools never have to re-read the audit log to act.
- **Stderr**: subprocess stderr tee'd to
  `$LOGDIR/.stderr/<agent>-<slug>.stderr` per ADR-0009 sidecar policy. Never
  in `.jsonl`.

### Exit-code contract (hybrid)

Each tool reports two orthogonal facts: *did the tool itself complete*, and
*did every chunk land*.

- Exit `0` — tool ran to completion AND every chunk in this invocation landed.
- Exit `1` — tool ran to completion BUT ≥1 chunk ejected (partial success;
  verdicts on stdout enumerate which). Shell-idiom: lets `&&`-chains halt the
  pipeline when any chunk needs operator attention.
- Exit `≥2` — tool-level failure: bad argv, schema-unreadable, worktree-spawn
  failed, etc. No useful per-chunk verdicts produced.

`mentat-fan-out` follows the same convention: exit 1 if ≥1 worktree failed to
spawn, exit ≥2 on argv/setup errors.

### Reusability — solo path

`mentat-implement`'s `/mentat-rebase` self-no-ops onto its own branch
(ADR-0004) — solo runs never reach `mentat-land-queue`. But the **rebase + re-gate
+ ff-only** cycle inside `mentat-land-queue` is exactly what a hypothetical
"land this single chunk onto $HOLDING" command would need. Locking the
N-chunk-on-stdin interface means N=1 is the solo case for free — pipe one slug
in, read one verdict out, exit 0 or 1.

### Audit verbs

Existing verbs reused as-is:

- `chunk.spawn` — emitted by `mentat-fan-out` per worktree spawn
- `land.complete` — emitted by `mentat-land-queue` per chunk
- `review.final` — emitted by `mentat-final-review` over the drained tip

No new event types. S6/S7/S8 fix the *origin* of these emits, not their shape.
Schema in `.agents/bin/lib/audit-schema.jsonc` (single source-of-truth) does
not need to change.

### Eject layout

When `mentat-land-queue` ejects a chunk:

- worktree left intact (ADR-0004)
- verdict line on stdout includes `conflicted_files: [...]` and
  `resume_cmd: "cd <worktree> && git rebase --continue"` (S10)
- `RESUME.md` dropped at worktree root with chunk slug, holding tip SHA,
  conflicted files, exact resume command (S11)

These three are mechanical S10/S11 fills against the verdict schema locked
here. The verdict schema is forward-compatible: `conflicted_files` and
`resume_cmd` are optional keys defined now; consumers may ignore them until
S10/S11 ship.

## Cross-check against ADR-0004

ADR-0004 locks the orchestration shape. This decomposition is conformant if
and only if each behavior survives the split.

| ADR-0004 invariant                                | How the split preserves it                                                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Fan-out parallel, land serial                     | `mentat-fan-out` spawns concurrently; `mentat-land-queue` reads slugs sequentially. The pipe enforces ordering; no shared state required.       |
| Each chunk holds its OWN branch                   | `mentat-fan-out` creates per-chunk worktrees with their own branches; nothing in this ADR couples chunks to a shared ref except `$HOLDING`.    |
| Re-gate after the land rebase (merge queue)       | `mentat-land-queue` re-gates inside its per-chunk loop before `merge --ff-only`. Same agent-spawn pattern as today; no driver names a project tool. |
| Eject on any red, never loop-retry one chunk      | Verdict schema has a closed set of `outcome` values; once emitted, the chunk is done. `mentat-land-queue` moves on to the next slug.            |
| Reviewers run once at end-of-queue, only all-green | `mentat-final-review` runs after `mentat-land-queue` exits 0 (all-green). On exit 1 (partial), the dispatcher skips final-review per ADR-0004. The review is advisory (warns, never rolls back the landed ref) — `mentat-final-review`'s `veto` bit on stdout flags miss-detection but the dispatcher does not act on it. |
| Language- and harness-agnostic; Docker required   | None of the three tools name a project tool. `mentat-container-run` and `cavecrew-builder` already abstract that. Docker remains a hard dep (ADR-0004): `mentat-fan-out` calls `mentat-container-up` per chunk; absence of a container runtime is a tool-level failure (exit ≥2), not an eject. |
| Project tools run in-container, never host        | Inherited — these tools shell out to `mentat-container-run` exactly where the current driver does.                                              |
| Cap 3 parallel chunks                             | Cap lives in `mentat-fan-out` (a single number that gates its spawn loop). Same place it lives today, just relocated.                          |

No ADR-0004 invariant is broken. No new invariant is added.

## Rejected

- **Argv-only inputs (no stdin).** Loses the `|`-pipe composability that
  makes the solo path free. A driver would have to re-assemble the slug list
  into argv tokens.
- **Audit log as the only output channel.** Forces downstream tools to
  re-read JSONL to learn what just happened, coupling every consumer to the
  audit schema for control flow. Stdout verdicts are cheap and explicit.
- **Typed exit codes per eject class (10=rebase, 11=gate, 12=not-ff, 13=impl).**
  N>1 verdicts can't fit in one exit code anyway, so the per-chunk verdict
  must live on stdout. Once it's there, encoding it twice (exit code +
  stdout) is duplication that drifts.
- **Single combined binary with subcommands** (e.g.,
  `mentat-orchestrate fan-out | mentat-orchestrate land-queue`). Removes the
  testability win — each subcommand still shares state through the same
  process and source tree.
- **Inferring `<base-sha>` from HEAD..tip merge-base in `mentat-final-review`.**
  Hidden coupling to the caller's git state. Explicit two-arg avoids
  "which base did the reviewer actually use" forensic work.

## Consequences

- S6, S7, S8 (extracts) and S9 (driver rewrite) can land independently in
  any order — each is a pure relocation against the interface locked here.
- `mentat-implement` solo path gains a clean "land just this chunk" verb by
  piping one slug into `mentat-land-queue`. No new code, no new ADR.
- Eject verdict schema is closed now; S10 + S11 fill optional keys defined
  here. Consumers written before S10 ignore the new keys without crashing.
- The 60-LOC dispatcher target in S9 is achievable: parse argv, three pipes,
  propagate exit code, done.
- Adding a fifth tool later (e.g., `mentat-doctor` over the drained tip)
  costs one entry in the dispatcher and one ADR amendment — no schema
  migration.
