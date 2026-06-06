#!/bin/bash
# bin/lib/harness/openhands.sh — openhands headless invocation
# Source this file; do not execute directly.

harness_openhands_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' openhands -t "${m[@]}" "$1"
}

harness_openhands_output_format() { printf 'text\n'; }

harness_openhands_normalize() {
  # OpenHands emits event-stream NDJSON; event = .action or .observation
  jq -c --arg agent "openhands" --arg sess "${MENTAT_SESSION:-unknown}" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:(.action // .observation // "unknown" | tostring), payload:(. - {action,observation})}'
}
