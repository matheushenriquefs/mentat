---
name: mentat-session
description: >
  Inspect and diagnose mentat orchestration sessions.
  Use when you want to stream live chunk events, produce a verdict markdown, or kick off a bug-hunt loop.
metadata:
  version: "0.1.0"
---

Session inspection toolkit. `track` tails JSONL events live with color-coded output. `doctor` derives a verdict markdown from log events and writes it to `~/.mentat/logs/<repo>/<session>/diagnosis.md`. `diagnose` invokes `doctor` for context then enters the `/diagnose` loop.

## How to invoke

```
python3 ~/.agents/skills/mentat-session/scripts/session.py track [<session>]
python3 ~/.agents/skills/mentat-session/scripts/session.py doctor [<session>]
python3 ~/.agents/skills/mentat-session/scripts/session.py diagnose
```

## Doctor markdown structure (B10 design)

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

## Track colors

| Event pattern | Color |
|---|---|
| `*.started` | blue |
| `*.succeeded` / `*.landed` | green |
| `*.failed` / `*.ejected` | red |
| `*.evaluated` / `*.reviewed` / `*.submitted` | cyan |
| `*.spawned` | yellow |
