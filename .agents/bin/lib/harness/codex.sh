#!/bin/bash
# bin/lib/harness/codex.sh — codex headless invocation
# Source this file; do not execute directly.

harness_codex_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' codex exec --json "${m[@]}" "$1"
}

harness_codex_output_format() { printf 'stream-json\n'; }

harness_codex_normalize() {
  # Codex emits cumulative usage totals; normalize same as stream-json
  jq -c --arg agent "codex" --arg sess "${MENTAT_SESSION:-unknown}" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown" | tostring), payload:(. - {type})}'
}
