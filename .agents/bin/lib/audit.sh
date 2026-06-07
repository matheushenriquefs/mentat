#!/usr/bin/env bash
# audit.sh — global JSONL audit log emitter (see docs/adr/0009-audit-log-format.md)
# Schema: {ts, agent, session, event, payload}
# Payload: verdicts/scores/file:line refs only — never raw diff/file content

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
  # Validate payload is JSON; fall back to null to avoid silent jq crash on bad input
  local payload
  payload="$(echo "$raw" | jq -c '.' 2>/dev/null)" || payload="null"
  jq -cn \
    --arg agent  "$agent" \
    --arg event  "$event" \
    --arg sess   "${MENTAT_SESSION}" \
    --argjson payload "$payload" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:$event, payload:$payload}' >> "$f"
}
