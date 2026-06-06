#!/bin/bash
# bin/lib/harness-openhands.sh — openhands headless invocation
# Source this file; do not execute directly.

harness_openhands_cmd() {  # $1 = prompt string; prints NUL-delimited argv
  local m=("${MODEL:+--model=$MODEL}")
  printf '%s\0' openhands -t "${m[@]}" "$1"
}
