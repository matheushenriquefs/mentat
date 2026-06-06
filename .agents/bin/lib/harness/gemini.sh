#!/bin/bash
# bin/lib/harness/gemini.sh — gemini headless invocation
# Source this file; do not execute directly.

harness_gemini_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=(); [ -n "${MODEL:-}" ] && m=("--model=$MODEL")
  printf '%s\0' gemini -p --output-format json "${m[@]}" "$1"
}

harness_gemini_output_format() { printf 'stream-json\n'; }
