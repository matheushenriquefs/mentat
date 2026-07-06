# Track a run live

Task-oriented. Goal: watch chunks implement and land in real time, and inspect any
one chunk's activity.

## List the agents

```
/mentat-track list
```

A repo-wide registry: one row per agent, with a status marker, the agent name,
how long ago its last event fired, and that event. Agents needing attention sort
to the top. Use this for a quick snapshot.

## Open the live navigator

```
/mentat-track track
```

With no argument, `track` opens a live navigator over every agent in the
repository, re-scanning on a short interval. Keys:

| Key | Action |
|---|---|
| `j` / `k` (or arrows) | Move the cursor between agents. |
| `enter` | Focus the selected agent (and return). |
| `x` | Tear down the focused agent's worktree. |
| `q` / `esc` | Quit. |

The list pane shows every chunk; the preview pane shows the selected chunk's recent
activity. Focusing a chunk zooms into a deeper view of that one agent.

When stdin is not a terminal (piped or in CI), `track` prints the list once and
exits instead of opening the interactive navigator.

## Follow one agent

To watch a single chunk directly, pass its agent id — the runs print it at start:

```
/mentat-track track <agent-id>
```

## After the run

- **Ejected or failed** → [doctor](./doctor.md) for the diagnosis.
- **Wedged** → [hitl-handoff](./hitl-handoff.md) to resume.
- **Landed clean** → `/mentat-track report` for the success summary.

## Notes

- The navigator is read-only except for the `x` teardown key.
- Status for each agent is derived from its newest audit event, so a chunk that
  stops advancing keeps the status of its last event — that stall is the signal to
  inspect it.
