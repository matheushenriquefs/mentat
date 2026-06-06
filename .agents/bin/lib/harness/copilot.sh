#!/bin/bash
# bin/lib/harness/copilot.sh — copilot headless invocation
# Source this file; do not execute directly.

harness_copilot_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' copilot -p "${m[@]}" "$1"
}

harness_copilot_output_format() { printf 'text\n'; }

harness_copilot_normalize() {
  # Copilot emits plain text; wrap each line as stderr.line
  local sess="${MENTAT_SESSION:-unknown}"
  while IFS= read -r line; do
    jq -cn --arg agent "copilot" --arg sess "$sess" --arg line "$line" \
      '{ts:(now|todate), agent:$agent, session:$sess, event:"stderr.line", payload:{line:$line}}'
  done
}
