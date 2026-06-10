---
description: Fan out planned chunks in parallel, land each onto the holding branch serially. ADR 0004.
---

$ARGUMENTS

1. Emit start: `python3 ~/.agents/skills/mentat-log/scripts/log.py emit mentat-orchestrate orchestrate.start "{\"args\":\"$ARGUMENTS\"}"`.
2. Invoke `python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py run $ARGUMENTS`. Pass through `--harness=<n>`, `--model=<slug>`, `--dry-run`, `<holding-branch>`, `<plan.md>...`.
3. On non-zero exit: `python3 ~/.agents/skills/mentat-session/scripts/session.py doctor --reason=orchestrate-nonzero || true`.
