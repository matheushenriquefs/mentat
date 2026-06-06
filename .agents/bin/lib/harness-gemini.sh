#!/bin/bash
# bin/lib/harness-gemini.sh — gemini headless invocation
# Source this file; do not execute directly.

harness_gemini_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=("${MODEL:+--model=$MODEL}")
  printf '%s\0' gemini -p --output-format json "${m[@]}" "$1"
}
