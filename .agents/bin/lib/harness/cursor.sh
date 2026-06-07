#!/bin/bash
# bin/lib/harness/cursor.sh — cursor headless invocation
# Source this file; do not execute directly.
#
# AFK seam (ADR-0010): when MENTAT_INTERACTIVE=0, prepend the system-prompt
# clause to the user prompt. Cursor lacks a --disallowedTools equivalent
# (registry row stores disallowed_tools_arg=""), so enforcement is
# prompt-bound only — a warning is emitted to stderr so operators know.
# Any other env value (unset, 1, "", "maybe") leaves invocation unchanged.

harness_cursor_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  local prompt="$1"
  if [ "${MENTAT_INTERACTIVE:-1}" = "0" ]; then
    echo "warning: cursor AFK enforced via system prompt only (no --disallowedTools equivalent)" >&2
    prompt="AFK mode: do not ask the user questions. On ambiguity, exit nonzero with a HITL audit reason instead of guessing.

$1"
  fi
  printf '%s\0' cursor-agent -p --output-format stream-json --force \
    ${m[@]+"${m[@]}"} "$prompt"
}

harness_cursor_output_format() { printf 'stream-json\n'; }

harness_cursor_normalize() {
  jq -c --arg agent "cursor" --arg sess "${MENTAT_SESSION:-unknown}" \
    '{ts:(now|todate), agent:$agent, session:$sess, event:(.type // "unknown" | tostring), payload:(del(.type))}'
}

# HITL detector (ADR-0010, G3-S6): mirrors claude-code's detector — returns
# 42 iff the session JSONL shows the wedge pattern (last assistant turn has
# no tool_use blocks and its trailing text ends with `?`). Gated by
# MENTAT_INTERACTIVE=0 (AFK chunk only). Any other value (interactive
# default, missing/empty file, non-question end, real tool work) returns 0.
harness_cursor_detect_hitl() {  # $1 = stream-json NDJSON path
  [ "${MENTAT_INTERACTIVE:-1}" = "0" ] || return 0
  local jsonl="$1"
  [ -f "$jsonl" ] || return 0
  local last
  last=$(jq -cs 'map(select(.type == "assistant")) | last // empty' "$jsonl" 2>/dev/null) || return 0
  [ -z "$last" ] && return 0
  echo "$last" | jq -e '.message.content[]? | select(.type == "tool_use")' >/dev/null 2>&1 && return 0
  local stripped
  stripped=$(echo "$last" | jq -r '[.message.content[]? | select(.type == "text") | .text] | join("\n")' | sed -e 's/[[:space:]]*$//')
  [ -z "$stripped" ] && return 0
  case "$stripped" in
    *\?) return 42 ;;
  esac
  return 0
}
