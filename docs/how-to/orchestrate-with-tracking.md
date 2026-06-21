# Orchestrate with live tracking

Task-oriented. Goal: run an orchestration and watch its chunks implement and land in
real time.

## 1. Start the run

```
/mentat-orchestrate run holding/feature feature-plan
```

At startup the run prints a track command for the whole run, and each fanned-out
chunk prints its own track command as it spawns. Copy one and run it in a second
session.

## 2. Track the run

```
/mentat-session track
```

With no session argument, `track` opens the live navigator over every session in the
current repository — one row per chunk, with status and last event. From there:

- `j` / `k` — move between chunks.
- `enter` — focus one chunk and watch its activity.
- `x` — tear down the focused chunk's worktree.
- `q` — quit.

To follow one chunk directly, pass its session id:

```
/mentat-session track <session-id>
```

See [tracking a run](./tracking-a-run.md) for the full view reference.

## 3. Read the statuses

Each chunk reports a status derived from its latest event: implementing, waiting,
landed, or ejected. A chunk that stops advancing is the one to inspect.

## 4. Follow up after landing

- **Ejected chunk** → diagnose with [doctor](./doctor.md).
- **Wedged chunk** (needs a human) → resume per [hitl-handoff](./hitl-handoff.md).
- **All green** → review and merge the holding branch:

```
/mentat-git diff main..holding/feature
```

## Notes

- Tracking is read-only except for the `x` teardown key — watching a run never
  changes what it does.
- The registry the navigator reads is repo-wide, so one tracker shows every
  concurrent chunk in the batch at once.
