#!/bin/bash
# bin/lib/harness/cursor.sh — cursor headless invocation
# Source this file; do not execute directly.

harness_cursor_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' cursor-agent -p --output-format stream-json --force "${m[@]}" "$1"
}

harness_cursor_output_format() { printf 'stream-json\n'; }

harness_cursor_normalize() {
  jq -c --arg agent "cursor" --arg sess "${MENTAT_SESSION:-unknown}" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown" | tostring), payload:(. - {type})}'
}
