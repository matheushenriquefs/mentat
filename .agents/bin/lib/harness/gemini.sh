#!/bin/bash
# bin/lib/harness/gemini.sh — gemini headless invocation
# Source this file; do not execute directly.

harness_gemini_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' gemini -p --output-format json "${m[@]}" "$1"
}

harness_gemini_output_format() { printf 'stream-json\n'; }

harness_gemini_normalize() {
  # Gemini emits a single final JSON blob; wrap it once
  jq -cs --arg agent "gemini" --arg sess "${MENTAT_SESSION:-unknown}" \
    '.[0] as $blob | {ts:(now|todate), agent:$agent, session:$sess, event:"gemini.final", payload:$blob}'
}
