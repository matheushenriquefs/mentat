---
name: mentat-session
description: >
  Inspect and diagnose mentat orchestration sessions.
  Use when you want to stream live chunk events, produce a verdict markdown, or kick off a bug-hunt loop.
---

Session inspection toolkit. `list` shows the repo-wide agent registry from `mentat.db` (attention-needing agents on top). `track` tails canonical audit events and the harness transcript live. `doctor` prints a verdict markdown from store events to stdout. `report` is its success-side twin — a one-paragraph report-back written to `summary.md`. `diagnose` renders the verdict from the store, then enters the `/diagnose` loop.

## How to invoke

Terminal tool — run on PATH (no slash form; this is not a harness slash command):

```
mentat-session list
mentat-session track [<session>]
mentat-session doctor [<session>]
mentat-session report [<session>]
mentat-session diagnose
```

## list (repo-wide registry)

`list` reads agents from the canonical store (`lib/store.list_track_entries`), scoped to agents with a log dir under `~/.mentat/logs/<repo>/`. Status is derived from the agent projection and the latest audit event.

| Status | Marker | Meaning |
|---|---|---|
| `waiting` | `◆` | Needs the operator — `chunk.ejected{reason: hitl-required}` (AFK wrote `summary.md{status: blocked}`), or a live `AskUserQuestion` in the harness stream. |
| `idle` | `✓` | Terminal event (landed / succeeded / failed / teardown). Done. |
| `?` | `?` | Non-terminal tail but stale `st_mtime` (no activity > 300s) — crashed silently. |
| `working` | `•` | Non-terminal tail, recently active. |

Rows sort attention-to-top by `(rank, age)` — `waiting` (0) > `idle` (1) > `?` (2) > `working` (3). Last event timestamp drives age.

## Doctor markdown structure

```markdown
## Verdict
- Reason: <chunk.landed | chunk.ejected.reason>
- Phase: <last event type>
- First failed event: <event-type> @ <ts>
- Suspect: <human-readable hypothesis from last event payload>

## Expected vs actual
- Expected: <from plan.started or chunk.spawned payload>
- Actual:   <from chunk.ejected.reason + tail of assistant transcript>

## Regression
- Last known good commit: <from chunk.landed payload if any prior chunk, else "unknown">
- Is regression: <yes | no | unknown>
```

## Per-reason Suspect formatters

| `chunk.ejected.reason` | Hypothesis |
|---|---|
| `implement-failed` | TDD/gate fail mid-implementation. Check `<chunk>.stdout`. |
| `gate-failed` | Code/LLM gate `<gate>` returned `block`. See payload `message:`. |
| `rebase-conflicted` | Conflict against holding tip. Worktree preserved at `<where>`. |
| `not-ff` | Non-fast-forward state. Holding moved while chunk worked. |
| `hitl-required` | AFK hit a design call the plan didn't resolve; wrote a blocker to `summary.md` instead of guessing. Payload `summary` carries it; worktree preserved. |

## track (live multi-AFK navigator)

`track` with **no agent id** opens the live navigator over the whole repo registry; `track <agent-id>` tails one agent's audit events (from the store) and transcript (color-coded, below).

The navigator timer-polls the registry (~1s, no daemon — there are no push hooks) so newly-spawned AFKs appear without restart. A **list pane** shows one row per session (status dot in the rank palette + name + last event); a **preview pane** tails the selected session's recent harness tool calls under a `│` gutter, each under a `── [session] ──` rule. ASCII/house glyphs only — no emoji.

| Key | Action |
|---|---|
| `j` / `↓`, `k` / `↑` | Move the selection (clamped) |
| `enter` | Toggle the focused single-session zoom (deeper tool tail); `enter`/`esc` returns |
| `x` | Kill bind — tear down the session's worktree, re-emit the list |
| `q` / `esc` | Quit |

Glyphs (shared with `lib/tui.py`): tool calls `Read ·` `Edit ~` `Write +` `Bash $` `Grep //` `Task »`; lifecycle `spawned +` `landed ✓` `ejected ✗` `hitl ◆` `commit ●`. Status dots reuse the list palette — waiting yellow, idle green, working red, `?` dim. Non-tty stdin (CI / piped) → one-shot list print, no raw-tty.

## Track colors (single-session tail)

| Event pattern | Color |
|---|---|
| `*.started` | blue |
| `*.succeeded` / `*.landed` | green |
| `*.failed` / `*.ejected` | red |
| `*.evaluated` / `*.reviewed` / `*.submitted` | cyan |
| `*.spawned` | yellow |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 64 | CLI arg parse error / unknown subcommand |
| 66 | Session ID not found in log path |
| 70 | Unhandled Python exception |

## Rules

- `track` uses `tail -F` semantics: follows new events as they arrive.
- `doctor` prints verdict markdown to stdout (no `diagnosis.md` artifact).
- `diagnose` renders the verdict from the canonical store, then enters the `/diagnose` loop with it as context.
- `diagnose` loop should land a regression test as the first red slice; hand off to `mentat-implement` rather than fixing inline.
- Agent id defaults to latest agent for the current repo when not supplied.
- Audit reads go through `lib/store.list_events`; transcript reads use `transcript.jsonl`.

## Constraints

- Read-only: `track` and `doctor` never write events or modify plan state.
- `diagnose` is interactive; requires `AskUserQuestion` — do not invoke in AFK class plans.
- Session lookup uses `$MENTAT_AGENT` (or legacy `$MENTAT_SESSION`) when set; otherwise latest agent in log dir.
