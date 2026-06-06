---
description: Fan out planned chunks in parallel, land each onto the holding branch serially. ADR 0004.
---

$ARGUMENTS

1. Emit start: `source ~/.agents/bin/lib/audit.sh && mentat_audit mentat-orchestrate orchestrate.start "{\"args\":\"$ARGUMENTS\"}"`.
2. Invoke `~/.agents/bin/mentat-orchestrate $ARGUMENTS`. Pass through `--harness=<n>`, `--model=<slug>`, `--dry-run`, `<holding-branch>`, `<plan.md>...`.
3. On non-zero exit: `~/.agents/bin/mentat-doctor --reason=orchestrate-nonzero || true`.
