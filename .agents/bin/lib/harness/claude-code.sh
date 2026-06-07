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

# HITL detector (ADR-0010, G3-S5): returns 42 iff the session JSONL shows the
# wedge pattern — last assistant turn has no tool_use blocks and its trailing
# text ends with `?`. Gated by MENTAT_INTERACTIVE=0 (AFK chunk only). Any
# other value (interactive default, missing/empty file, non-question end,
# real tool work) returns 0.
harness_claude_code_detect_hitl() {  # $1 = stream-json NDJSON path
  [ "${MENTAT_INTERACTIVE:-1}" = "0" ] || return 0
  local jsonl="$1"
  [ -f "$jsonl" ] || return 0
  local last
  last=$(jq -cs 'map(select(.type == "assistant")) | last // empty' "$jsonl" 2>/dev/null) || return 0
  [ -z "$last" ] && return 0
  # Tool use in the final turn = real work, not a wedge.
  echo "$last" | jq -e '.message.content[]? | select(.type == "tool_use")' >/dev/null 2>&1 && return 0
  local stripped
  stripped=$(echo "$last" | jq -r '[.message.content[]? | select(.type == "text") | .text] | join("\n")' | sed -e 's/[[:space:]]*$//')
  [ -z "$stripped" ] && return 0
  case "$stripped" in
    *\?) return 42 ;;
  esac
  return 0
}
