#!/bin/bash
# bin/lib/harness-claude-code.sh — claude-code headless invocation
# Source this file; do not execute directly.

harness_claude_code_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local model="${MODEL:-sonnet}"
  printf '%s\0' claude -p --output-format stream-json --verbose \
    --permission-mode acceptEdits \
    --allowedTools "Bash,Read,Edit,Write,Agent" \
    --model "$model" "$1"
}
