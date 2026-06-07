#!/bin/bash
# bin/lib/harness/claude-code.sh — claude-code headless invocation
# Source this file; do not execute directly.
#
# AFK seam (ADR-0010): when MENTAT_INTERACTIVE=0, append
#   --disallowedTools AskUserQuestion
# and prepend the system-prompt clause to the user prompt. Any other value
# (unset, 1, "", "maybe") leaves invocation unchanged — fail-closed default.

harness_claude_code_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local model="${MODEL:-sonnet}"
  local prompt="$1"
  local afk_args=()
  if [ "${MENTAT_INTERACTIVE:-1}" = "0" ]; then
    afk_args=(--disallowedTools AskUserQuestion)
    prompt="AFK mode: do not ask the user questions. On ambiguity, exit nonzero with a HITL audit reason instead of guessing.

$1"
  fi
  printf '%s\0' claude -p --output-format stream-json --verbose \
    --permission-mode acceptEdits \
    --allowedTools "Bash,Read,Edit,Write,Agent" \
    ${afk_args[@]+"${afk_args[@]}"} \
    --model "$model" "$prompt"
}

harness_claude_code_output_format() { printf 'stream-json\n'; }

harness_claude_code_normalize() {
  # stdin: stream-json NDJSON; stdout: canonical audit NDJSON
  jq -c --arg agent "claude-code" --arg sess "${MENTAT_SESSION:-unknown}" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown" | tostring), payload:(del(.type))}'
}
