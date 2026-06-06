#!/bin/bash
# bin/lib/harness-aider.sh — aider headless invocation
# Source this file; do not execute directly.

harness_aider_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' aider --message "$1" --yes "${m[@]}"
}
