#!/bin/bash
# bin/lib/harness-codex.sh — codex headless invocation
# Source this file; do not execute directly.

harness_codex_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=("${MODEL:+--model=$MODEL}")
  printf '%s\0' codex exec --json "${m[@]}" "$1"
}
