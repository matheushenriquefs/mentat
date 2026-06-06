---
description: Ensure this worktree's devcontainer is running.
---

Run `~/.agents/bin/mentat-container-up`. Safe to call any time —
idempotent. The `worktree_created` hook usually does this in the
background on `n`; the slash command is for manual top-ups or when
the hook didn't fire.
