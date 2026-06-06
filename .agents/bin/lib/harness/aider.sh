#!/bin/bash
# bin/lib/harness/aider.sh — aider headless invocation
# Source this file; do not execute directly.

harness_aider_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' aider --message "$1" --yes "${m[@]}"
}

harness_aider_output_format() { printf 'text\n'; }

harness_aider_normalize() {
  # Aider emits plain text; classify each line by prefix
  local sess="${MENTAT_SESSION:-unknown}"
  while IFS= read -r line; do
    local event="stderr.line"
    case "$line" in
      Tokens:*) event="usage.line" ;;
      [A-Z]*:*) event="aider.message" ;;
    esac
    jq -cn --arg agent "aider" --arg sess "$sess" \
      --arg event "$event" --arg line "$line" \
      '{ts:(now|todate), agent:$agent, session:$sess, event:$event, payload:{line:$line}}'
  done
}
