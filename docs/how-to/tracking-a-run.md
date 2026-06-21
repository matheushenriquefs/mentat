# Track a run live

Task-oriented. Goal: watch chunks implement and land in real time, and inspect any
one chunk's activity.

## List the sessions

```
/mentat-session list
```

A repo-wide registry: one row per session, with a status marker, the session name,
how long ago its last event fired, and that event. Sessions needing attention sort
to the top. Use this for a quick snapshot.

## Open the live navigator

```
/mentat-session track
```

With no argument, `track` opens a live navigator over every session in the
repository, re-scanning on a short interval. Keys:

| Key | Action |
|---|---|
| `j` / `k` (or arrows) | Move the cursor between sessions. |
| `enter` | Focus the selected session (and return). |
| `x` | Tear down the focused session's worktree. |
| `q` / `esc` | Quit. |

The list pane shows every chunk; the preview pane shows the selected chunk's recent
activity. Focusing a chunk zooms into a deeper view of that one session.

When stdin is not a terminal (piped or in CI), `track` prints the list once and
exits instead of opening the interactive navigator.

## Follow one session

To watch a single chunk directly, pass its session id — the runs print it at start:

```
/mentat-session track <session-id>
```

## After the run

- **Ejected or failed** → [doctor](./doctor.md) for the diagnosis.
- **Wedged** → [hitl-handoff](./hitl-handoff.md) to resume.
- **Landed clean** → `/mentat-session report` for the success summary.

## Notes

- The navigator is read-only except for the `x` teardown key.
- Status for each session is derived from its newest audit event, so a chunk that
  stops advancing keeps the status of its last event — that stall is the signal to
  inspect it.
