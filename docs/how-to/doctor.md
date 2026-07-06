# Diagnose a chunk with doctor

Task-oriented. Goal: understand why a chunk ejected or failed, using the doctor.

## What doctor is

`mentat-track doctor` reads a chunk's audit events and prints a verdict to stdout —
what the chunk attempted, what happened, and the suspected cause. It is the
death-side counterpart to `report`, which writes the success-side summary to
`summary.md`. Doctor itself writes no file; its output is the printed verdict.

## When it is spawned

Doctor runs automatically when a run ends on a diagnosable exit code — a gate or
implementation failure, a HITL wedge, a container or configuration error, or an
unhandled exception. Signal-interrupt exits are skipped. So an ejected or failed
chunk usually has its verdict printed to the run output already; you rarely invoke
doctor by hand.

## 1. Find the chunk

List the repository's agents and their statuses:

```
/mentat-track list
```

An ejected or failed chunk stands out by its status.

## 2. Read the diagnosis

```
/mentat-track doctor <agent-id>
```

With no id, doctor falls back to the most recent agent in the repository. It prints
the verdict to stdout.

## 3. Diagnose interactively

For a guided loop that runs doctor first and walks the evidence:

```
/mentat-track diagnose <agent-id>
```

## 4. Act on the verdict

- **Gate or implementation failure** → the worktree is preserved. Fix the slice in
  place and re-run the plan.
- **Needs a human** → the chunk wedged; resume it per [hitl-handoff](./hitl-handoff.md).

## Notes

- Doctor is read-only: it derives the verdict from stored audit events each time and
  prints it. Re-running is safe and always reflects the latest events.
- To read the success side of a clean run instead, use `/mentat-track report`, which
  writes `summary.md` beside the run's transcript.
