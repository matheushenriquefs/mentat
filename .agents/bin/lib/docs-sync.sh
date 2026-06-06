#!/usr/bin/env bash
# bin/lib/docs-sync.sh — check that renamed/deleted bin or commands files have
# no stale references in docs. Called by lefthook docs-sync hook.
# Usage: docs-sync.sh <staged-file> [...]
set -euo pipefail

DOCS=(README.md AGENTS.md CONTEXT.md CREDITS.md)
fail=0

for f in "$@"; do
  [ -f "$f" ] && continue  # file still exists — not renamed/deleted
  base=$(basename "$f")
  for doc in "${DOCS[@]}"; do
    [ -f "$doc" ] || continue
    hits=$(grep -cE "\b${base}\b" "$doc" 2>/dev/null || true)
    if [ "$hits" -gt 0 ]; then
      echo "docs-sync: '$base' removed but still referenced in $doc ($hits hit(s))" >&2
      fail=1
    fi
  done
done

exit "$fail"
