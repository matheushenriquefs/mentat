#!/bin/bash
# bin/lib/harness/copilot.sh — copilot headless invocation
# Source this file; do not execute directly.

harness_copilot_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' copilot -p "${m[@]}" "$1"
}

harness_copilot_output_format() { printf 'text\n'; }
