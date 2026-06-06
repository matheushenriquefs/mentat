#!/usr/bin/env bash
# audit.sh — global JSONL audit log emitter (locked decision 3)
# Schema: {ts, agent, session, event, payload}
# Payload: verdicts/scores/file:line refs only — never raw diff/file content

: "${MENTAT_LOG_DIR:=$HOME/.agents/mentat/logs}"
: "${MENTAT_REPO:=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")}"
: "${MENTAT_SESSION:=$(date +%s)-$$}"

mentat_audit() {
  local agent="$1" event="$2" payload="${3:-null}"
  local dir="$MENTAT_LOG_DIR/$MENTAT_REPO/$MENTAT_SESSION"
  mkdir -p "$dir"
  chmod 700 "$MENTAT_LOG_DIR" 2>/dev/null || true
  local slug="${MENTAT_SLUG:-$$}"
  local f="$dir/${agent}-${slug}.jsonl"
  jq -cn \
    --arg agent  "$agent" \
    --arg event  "$event" \
    --arg sess   "${MENTAT_SESSION}" \
    --argjson payload "$payload" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:$event, payload:$payload}' >> "$f"
}
