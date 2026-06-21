# Diagnose a chunk with doctor

Task-oriented. Goal: understand why a chunk ejected or failed, using the doctor.

## What doctor is

`mentat-session doctor` reads a session's audit log and writes a `diagnosis.md`
into that session's log directory — a verdict on what the chunk attempted, what
happened, and the suspected cause. It is the death-side counterpart to `report`,
which writes the success-side summary.

## When it is spawned

Doctor runs automatically when a run ends on a diagnosable exit code — a gate or
implementation failure, a HITL wedge, a container or configuration error, or an
unhandled exception. Signal-interrupt exits are skipped. So an ejected or failed
chunk usually already has a `diagnosis.md` waiting; you rarely invoke doctor by hand.

## 1. Find the chunk

List the repository's sessions and their statuses:

```
/mentat-session list
```

An ejected or failed chunk stands out by its status.

## 2. Read the diagnosis

```
/mentat-session doctor <session-id>
```

With no session id, doctor falls back to the most recent session in the repository.
It prints the diagnosis and leaves `diagnosis.md` in the session's log directory for
later reading.

## 3. Diagnose interactively

For a guided loop that runs doctor first and walks the evidence:

```
/mentat-session diagnose <session-id>
```

## 4. Act on the verdict

- **Gate or implementation failure** → the worktree is preserved. Fix the slice in
  place and re-run the plan.
- **Needs a human** → the chunk wedged; resume it per [hitl-handoff](./hitl-handoff.md).

## Notes

- One diagnosis per session — re-running doctor overwrites it.
- The diagnosis lives beside the events it explains (`diagnosis.md` next to the
  session's audit log), so one directory holds both verdict and evidence.
- To read the success side of a clean run instead, use `/mentat-session report`.
