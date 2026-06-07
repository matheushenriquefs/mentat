#!/usr/bin/env bash
# bin/lib/plan-validate.sh — AFK class + blocked_by dep check for orchestrate plans.
# Source-only. Exposes: mentat_plan_check <plan.md>. Returns 2 on rejection.
# Frontmatter parser is pure awk so we don't drag a yq dependency into the container.

# Extract a scalar frontmatter field. $1=plan path, $2=field name.
_mpv_scalar() {
  awk -v key="$2" '
    /^---[[:space:]]*$/ { fm = !fm; if (!fm) exit; next }
    fm && $0 ~ "^" key ":" {
      sub("^" key ":[[:space:]]*", "")
      gsub(/^["\x27]|["\x27][[:space:]]*$/, "")
      print; exit
    }
  ' "$1"
}

# Extract a list frontmatter field. $1=plan path, $2=field name. One item per line.
# Supports both inline `key: [a, b]` and YAML block `key:\n  - a\n  - b`.
_mpv_list() {
  awk -v key="$2" '
    /^---[[:space:]]*$/ { fm = !fm; if (!fm) exit; next }
    !fm { next }
    in_list && /^[[:space:]]+-[[:space:]]+/ {
      v = $0; sub(/^[[:space:]]+-[[:space:]]+/, "", v)
      gsub(/^["\x27]|["\x27][[:space:]]*$/, "", v)
      if (v != "") print v
      next
    }
    in_list && /^[^[:space:]]/ { in_list = 0 }
    $0 ~ "^" key ":" {
      line = $0; sub("^" key ":[[:space:]]*", "", line)
      if (line == "" || line == "[]") { in_list = 1; next }
      if (substr(line, 1, 1) == "[") {
        gsub(/^\[|\][[:space:]]*$/, "", line)
        n = split(line, arr, /[[:space:]]*,[[:space:]]*/)
        for (i = 1; i <= n; i++) {
          v = arr[i]; gsub(/^["\x27]|["\x27]$/, "", v)
          if (v != "") print v
        }
        exit
      }
      in_list = 1; next
    }
  ' "$1"
}

mentat_plan_check() {
  local p="$1" class id dep dep_path dep_status
  [ -f "$p" ] || { echo "plan not found: $p" >&2; return 2; }
  class="$(_mpv_scalar "$p" class)"
  id="$(_mpv_scalar "$p" id)"
  [ "$class" = AFK ] || { echo "plan '$p' is class=${class:-missing}; orchestrate runs AFK only — run via mentat-implement" >&2; return 2; }
  [ -n "$id" ] || { echo "plan '$p' missing frontmatter id" >&2; return 2; }
  [ "${id}.md" = "$(basename "$p")" ] || { echo "plan '$p' id mismatch (id=$id vs file=$(basename "$p"))" >&2; return 2; }
  while IFS= read -r dep; do
    [ -z "$dep" ] && continue
    dep_path="$(dirname "$p")/${dep}.md"
    [ -f "$dep_path" ] || { echo "plan '$p' blocked_by '$dep' missing: $dep_path" >&2; return 2; }
    dep_status="$(_mpv_scalar "$dep_path" status)"
    [ "$dep_status" = done ] || { echo "plan '$p' blocked_by '$dep' status=$dep_status (must be done)" >&2; return 2; }
  done < <(_mpv_list "$p" blocked_by)
}
