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
