---
name: mentat-tasks
description: Local md task store. Atomic claim, TTL refresh, vertical-slice + HITL/AFK doctrine.
allowed-tools:
  - Bash(ln *)
  - Bash(mv *)
  - Bash(yq *)
  - Bash(grep *)
  - Bash(rg *)
---

# mentat-tasks

Manage a local markdown task store backed by POSIX atomics. No server, no database, no binary. Each task is a file; each claim is a hardlink.

## Layout

Tasks live at `<repo>/.mentat/tasks/<ID>-<slug>.md`. Cross-repo unified view: `ln -s ~/.agents/mentat/tasks .mentat/tasks` (user runs once).

Board-home vs worktree separation (ADR-0002): task files live on the holding branch. Chunks operating in worktrees write status back via the atomic protocol below.

## Task file schema

```yaml
---
id: T001
status: todo            # todo | in-progress | review | done | wontfix
class: HITL             # HITL | AFK — vertical-slice classification (required before pick)
claimed_by: ""          # agent id or empty
claim_expires_at: ""    # RFC3339; empty if unclaimed
created_at: 2026-06-06T00:00:00Z
---
```

Body sections (matt-pocock to-issues template):
- **Parent** — plan or PRD link.
- **What to build** — one paragraph.
- **Acceptance criteria** — bulleted checklist.
- **Blocked by** — prose, free-form. No machine graph.

## Primitives

**next_id**: `ls .mentat/tasks/ | awk -F- '{print $1}' | sort -V | tail -1` + 1. No central index.

**create `<slug>`**
```sh
id=$(ls .mentat/tasks/ 2>/dev/null | awk -F- '{print $1}' | sort -V | tail -1); id=$((${id#T} + 1)); id="T$(printf '%03d' $id)"
tmp=".mentat/tasks/$id-$slug.md.$$"
cat > "$tmp"  # write content via stdin
mv "$tmp" ".mentat/tasks/$id-$slug.md"
```

**claim `<file>` `<agent>` `<ttl_seconds>`**
```sh
f=".mentat/tasks/$file"
ln "$f" "$f.claim" 2>/dev/null || { echo "already claimed"; exit 1; }
expires=$(date -u -v+${ttl_seconds}S '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d "+${ttl_seconds} seconds" '+%Y-%m-%dT%H:%M:%SZ')
tmp="$f.$$.tmp"; cp "$f" "$tmp"
yq -i ".claimed_by = \"$agent\" | .claim_expires_at = \"$expires\" | .status = \"in-progress\"" "$tmp"
mv "$tmp" "$f"
```

**release `<file>`**
```sh
f=".mentat/tasks/$file"
tmp="$f.$$.tmp"; cp "$f" "$tmp"
yq -i '.claimed_by = "" | .claim_expires_at = "" | .status = "todo"' "$tmp"
mv "$tmp" "$f"; rm -f "$f.claim"
```

**refresh `<file>` `<ttl_seconds>`** — bump `claim_expires_at`:
```sh
expires=$(date -u -v+${ttl_seconds}S '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d "+${ttl_seconds} seconds" '+%Y-%m-%dT%H:%M:%SZ')
tmp="$f.$$.tmp"; cp "$f" "$tmp"
yq -i ".claim_expires_at = \"$expires\"" "$tmp"; mv "$tmp" "$f"
```

**done / wontfix `<file>`**
```sh
tmp="$f.$$.tmp"; cp "$f" "$tmp"
yq -i ".status = \"done\" | .claimed_by = \"\" | .claim_expires_at = \"\"" "$tmp"
mv "$tmp" "$f"; rm -f "$f.claim"
```

## Pick gate

Pick only if:
1. `status` is `todo`, or `in-progress` with `claim_expires_at < now` (stale — release then re-claim).
2. `class` is set (`HITL` or `AFK`). Never pick untriaged.
3. No `.claim` hardlink exists for a non-expired claim.

## Atomic-write invariant

All mutations use tmp+rename (POSIX `rename(2)`, same-fs):
```sh
umask 077; tmp="$f.$$.tmp"
cp "$f" "$tmp" && yq -i "$patch" "$tmp" && mv "$tmp" "$f"
```

Skip `flock` — unreliable on macOS APFS. `ln` + `rename(2)` is sufficient.

## Boundary with other skills

`mentat-issues` (intake) → writes task via `mentat-tasks create`.  
`triage` → mutates `class` + `status`.  
`mentat-prd` → references task ids as `T###` in prose.  
`mentat-tasks` owns schema + filesystem protocol only.

## Deferred

Typed dep graph, `touches:` write-set lease, `kind:` field, priority/tags/due/estimate. Add only on demonstrated need.
