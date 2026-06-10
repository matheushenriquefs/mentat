---
description: Stop the worktree's devcontainer (frees resources, no merge).
---

Run `python3 ~/.agents/skills/mentat-container/scripts/container.py down`. Container respawns on the
next `python3 ~/.agents/skills/mentat-container/scripts/container.py run` or `/mentat-container-up`. Use to
free Docker resources without merging the branch.
