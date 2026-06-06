---
description: Stage and commit. Route through devcontainer if one exists.
---

1. Stage the files to commit.
2. Invoke `/caveman-commit`. Strip the ``` fences from its output.
3. Commit. For multi-line messages, use a temp file:

   ```
   printf '%s\n' "<message>" > .commit-msg
   # With .devcontainer/ (container-side pre-commit):
   ~/.agents/bin/mentat-container-run "git commit -F .commit-msg && rm .commit-msg"
   # Otherwise:
   git commit -F .commit-msg && rm .commit-msg
   ```

4. If pre-commit modified files, re-stage and re-commit.
