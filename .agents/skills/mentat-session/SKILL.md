---
name: mentat-session
description: >
  Inspect and diagnose mentat orchestration sessions.
  Use when you want to stream live chunk events, produce a verdict markdown, or kick off a bug-hunt loop.
---

Session inspection toolkit. `list` shows the repo-wide registry — every session under `~/.mentat/logs/<repo>/`, attention-needing ones on top. `track` tails JSONL events live with color-coded output. `doctor` derives a verdict markdown from log events and writes it to `~/.mentat/logs/<repo>/<session>/diagnosis.md`. `report` is its success-side twin — a one-paragraph report-back of what the session implemented, written to `summary.md`. `diagnose` invokes `doctor` for context then enters the `/diagnose` loop.

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

The filesystem *is* the registry — each subdir of `~/.mentat/logs/<repo>/` is one session. There are no push hooks, so status is **pulled**: read the tail row of the session's newest jsonl and classify it against the file's `st_mtime`.

| Status | Marker | Meaning |
|---|---|---|
| `waiting` | `◆` | Needs the operator — `chunk.ejected{reason: hitl-required}`, or a live `AskUserQuestion` in the harness stream. |
| `idle` | `✓` | Terminal event (landed / succeeded / failed / teardown). Done. |
| `?` | `?` | Non-terminal tail but stale `st_mtime` (no activity > 300s) — crashed silently. |
| `working` | `•` | Non-terminal tail, recently active. |

Rows sort attention-to-top by `(rank, age)` — `waiting` (0) > `idle` (1) > `?` (2) > `working` (3). `st_mtime` of the newest file is the free "last-active" timestamp.

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
| `hitl-required` | AFK ambiguity detected. Self-answered-question in session JSONL. |

## track (live multi-AFK navigator)

`track` with **no session** opens the live navigator over the whole repo registry; `track <session>` tails one session's audit events (color-coded, below).

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
- `doctor` writes to `~/.mentat/logs/<repo>/<session>/diagnosis.md`; overwrites on re-run.
- `diagnose` calls `doctor` first, then enters the `/diagnose` loop with the diagnosis as context.
- `diagnose` loop should land a regression test as the first red slice; hand off to `mentat-implement` rather than fixing inline.
- Session ID defaults to latest session for the current repo when not supplied.
- All event reading goes through `mentat-log query`; never reads raw JSONL directly.

## Constraints

- Read-only: `track` and `doctor` never write events or modify plan state.
- `diagnose` is interactive; requires `AskUserQuestion` — do not invoke in AFK class plans.
- Session lookup uses `$MENTAT_SESSION` when set; otherwise latest session in log dir.
