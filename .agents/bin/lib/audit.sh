#!/usr/bin/env bash
# audit.sh — global JSONL audit log emitter (see docs/adr/0009-audit-envelope.md)
# Schema: {ts, agent, session, event, payload}
# Payload: verdicts/scores/file:line refs only — never raw diff/file content
#
# Validation (G1-S2): every emit goes through schema gate at
# .agents/bin/lib/audit-schema.jsonc. Reject + sidecar (no .jsonl row) on:
#   - non-JSON payload
#   - unknown event (not in schema's events map)
#   - missing required field for that event
# Sidecar: $base/.stderr/${agent}-${slug}.stderr (created on first reject).

# Deprecation shim — one release; remove after all callers migrated.
if [ -n "${MENTAT_LOG_DIR:-}" ] && [ -z "${MENTAT_LOG_PATH:-}" ]; then
  echo "WARN: MENTAT_LOG_DIR is deprecated; use MENTAT_LOG_PATH" >&2
  export MENTAT_LOG_PATH="$MENTAT_LOG_DIR"
fi

# Path defaults are safe to compute — no identity semantics.
: "${MENTAT_LOG_PATH:=$HOME/.agents/mentat/logs}"
: "${MENTAT_REPO:=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")}"

# Session is identity. Never invent under the real-work namespace.
# Unset session => loose emit. Route to manual/ namespace with manual- prefix.
if [ -z "${MENTAT_SESSION:-}" ]; then
  _LOOSE=1
  MENTAT_SESSION="manual-$(date +%s)-$$"
else
  _LOOSE=0
fi
# Not exported — keeps local so children of a loose caller don't inherit.

# Schema path resolution: prefer the audit.sh-adjacent file (rsync target),
# fall back to repo source when sourced from elsewhere during development.
_mentat_audit_schema_path() {
  local self_dir
  self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ -f "$self_dir/audit-schema.jsonc" ]; then
    printf '%s\n' "$self_dir/audit-schema.jsonc"
    return 0
  fi
  local repo_root
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
  if [ -n "$repo_root" ] && [ -f "$repo_root/.agents/bin/lib/audit-schema.jsonc" ]; then
    printf '%s\n' "$repo_root/.agents/bin/lib/audit-schema.jsonc"
    return 0
  fi
  return 1
}

# Strip `//` line comments (naive — assumes no `//` inside JSON strings, which
# holds for audit-schema.jsonc). Mirrors python loader convention.
_mentat_audit_strip_comments() {
  sed 's|//.*$||' "$1"
}

# Cache: schema JSON loaded once per shell. Caller may unset MENTAT_AUDIT_SCHEMA
# to force reload (useful in tests).
_mentat_audit_load_schema() {
  if [ -n "${MENTAT_AUDIT_SCHEMA:-}" ]; then
    return 0
  fi
  local path
  path="$(_mentat_audit_schema_path)" || return 1
  MENTAT_AUDIT_SCHEMA="$(_mentat_audit_strip_comments "$path" | jq -c '.' 2>/dev/null)" || return 1
  [ -n "$MENTAT_AUDIT_SCHEMA" ] || return 1
  return 0
}

_mentat_audit_sidecar() {
  local base="$1" agent="$2" slug="$3"
  local dir="$base/.stderr"
  mkdir -p "$dir"
  printf '%s\n' "$dir/${agent}-${slug}.stderr"
}

_mentat_audit_reject() {
  local base="$1" agent="$2" slug="$3" event="$4" reason="$5" raw="$6"
  local sidecar
  sidecar="$(_mentat_audit_sidecar "$base" "$agent" "$slug")"
  printf '%s  reject event=%s reason=%s raw=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$reason" "$raw" >> "$sidecar"
  printf 'audit: reject event=%s reason=%s (sidecar=%s)\n' "$event" "$reason" "$sidecar" >&2
}

mentat_audit() {
  local agent="$1" event="$2" raw="${3:-null}"
  local base
  if [ "${_LOOSE:-0}" = 1 ]; then
    base="$MENTAT_LOG_PATH/manual/$MENTAT_REPO/$MENTAT_SESSION"
  else
    base="$MENTAT_LOG_PATH/$MENTAT_REPO/$MENTAT_SESSION"
  fi
  mkdir -p "$base"
  chmod 700 "$MENTAT_LOG_PATH" 2>/dev/null || true
  local slug="${MENTAT_SLUG:-manual-$$}"
  local f="$base/${agent}-${slug}.jsonl"

  if ! _mentat_audit_load_schema; then
    _mentat_audit_reject "$base" "$agent" "$slug" "$event" "schema-unreadable" "$raw"
    return 1
  fi

  local event_def
  event_def="$(printf '%s' "$MENTAT_AUDIT_SCHEMA" | jq -c --arg e "$event" '.events[$e] // empty' 2>/dev/null)"
  if [ -z "$event_def" ] || [ "$event_def" = "null" ]; then
    _mentat_audit_reject "$base" "$agent" "$slug" "$event" "unknown-event" "$raw"
    return 1
  fi

  local payload
  if ! payload="$(printf '%s' "$raw" | jq -c '.' 2>/dev/null)"; then
    _mentat_audit_reject "$base" "$agent" "$slug" "$event" "non-json-payload" "$raw"
    return 1
  fi

  local missing
  missing="$(printf '%s' "$event_def" | jq -r --argjson p "$payload" '
    (.required // []) - (
      if ($p | type) == "object" then ($p | keys) else [] end
    ) | .[]
  ' 2>/dev/null)"
  if [ -n "$missing" ]; then
    local joined
    joined="$(printf '%s' "$missing" | tr '\n' ',' | sed 's/,$//')"
    _mentat_audit_reject "$base" "$agent" "$slug" "$event" "missing-required:$joined" "$raw"
    return 1
  fi

  jq -cn \
    --arg agent  "$agent" \
    --arg event  "$event" \
    --arg sess   "${MENTAT_SESSION}" \
    --argjson payload "$payload" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:$event, payload:$payload}' >> "$f"
}
