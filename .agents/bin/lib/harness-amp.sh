#!/bin/bash
# bin/lib/harness-amp.sh — amp headless invocation
# Source this file; do not execute directly.

harness_amp_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=("${MODEL:+--model=$MODEL}")
  printf '%s\0' amp -x --stream-json "${m[@]}" "$1"
}
