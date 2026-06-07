---
description: Emit cumulative diff of holding branch vs main (or fork point).
---

Holding branch (optional): $ARGUMENTS

1. Resolve holding branch: arg > `git symbolic-ref --short HEAD` > error.
2. Compute base: `git merge-base main <branch>` (or `--since=<sha>` override).
3. Emit audit: `mentat_audit mentat-diff diff.emit '{"base":"…","tip":"…","branch":"…","files":N}'`.
4. Print header block (branch / base / tip / files).
5. Print diff: `rtk git diff <base>..<tip> --stat` then full diff.
   Flags: `--stat-only` (stat only), `--name-only` (names only), `--since=<sha>` (custom base).
