#!/usr/bin/env bash
# smells.sh — deterministic code-smell detectors (S3.2, ADR 0008)
# Each detector prints findings to stdout and returns 1 if any found, 0 if clean.
# LLM-only smells (Feature Envy, Shotgun Surgery, etc.) are delegated to mentat-smell-reviewer.

SMELL_LONG_METHOD_LINES="${SMELL_LONG_METHOD_LINES:-30}"
SMELL_LONG_PARAMS_COUNT="${SMELL_LONG_PARAMS_COUNT:-5}"
SMELL_MAGIC_NUMBERS_SKIP="${SMELL_MAGIC_NUMBERS_SKIP:-0|1|2|-1}"
SMELL_NESTED_DEPTH="${SMELL_NESTED_DEPTH:-4}"

smell_long_method() {
  local file="$1" found=0
  # Detect shell functions > SMELL_LONG_METHOD_LINES lines
  awk -v limit="$SMELL_LONG_METHOD_LINES" '
    /^[a-zA-Z_][a-zA-Z0-9_]*[[:space:]]*\(\)/ { fn=$0; fn_line=NR; depth=0 }
    fn_line && /\{/ { depth++ }
    fn_line && /\}/ {
      depth--
      if (depth == 0) {
        len = NR - fn_line
        if (len > limit) print FILENAME ":" fn_line ": long-method: " len " lines (limit " limit "). Extract helper functions."
        fn_line=0
      }
    }
  ' "$file" && return 0 || true
  local out
  out=$(awk -v limit="$SMELL_LONG_METHOD_LINES" '
    /^[a-zA-Z_][a-zA-Z0-9_]*[[:space:]]*\(\)/ { fn=$0; fn_line=NR; depth=0 }
    fn_line && /\{/ { depth++ }
    fn_line && /\}/ {
      depth--
      if (depth == 0) {
        len = NR - fn_line
        if (len > limit) print FILENAME ":" fn_line ": long-method: " len " lines (limit " limit "). Extract helper functions."
        fn_line=0
      }
    }
  ' "$file")
  if [ -n "$out" ]; then
    echo "$out"
    return 1
  fi
  return 0
}

smell_long_params() {
  local file="$1" found=0
  local out
  out=$(grep -nE '^[a-zA-Z_][a-zA-Z0-9_]*\s*\(' "$file" 2>/dev/null | while IFS=: read -r lineno rest; do
    param_count=$(echo "$rest" | tr ',' '\n' | grep -c '[^[:space:]]' || true)
    if [ "$param_count" -gt "$SMELL_LONG_PARAMS_COUNT" ]; then
      echo "$file:$lineno: long-params: $param_count parameters (limit $SMELL_LONG_PARAMS_COUNT). Introduce Parameter Object."
    fi
  done)
  if [ -n "$out" ]; then echo "$out"; return 1; fi
  return 0
}

smell_magic_numbers() {
  local file="$1"
  local skip_pat="\\b(${SMELL_MAGIC_NUMBERS_SKIP})\\b"
  local out
  out=$(grep -nEo '[^a-zA-Z_][0-9]{2,}[^a-zA-Z_0-9]' "$file" 2>/dev/null \
    | grep -vE "$skip_pat" \
    | grep -vE '^\s*#' \
    | sed "s|^|$file:|" \
    | sed 's/$/ magic-number. Extract named constant./')
  if [ -n "$out" ]; then echo "$out"; return 1; fi
  return 0
}

smell_nested_conditional() {
  local file="$1"
  local out
  out=$(awk -v depth=0 -v limit="$SMELL_NESTED_DEPTH" '
    /\bif\b|\bfor\b|\bwhile\b|\bcase\b/ { depth++ }
    /\bfi\b|\bdone\b|\besac\b/ { depth-- }
    depth >= limit { print FILENAME ":" NR ": nested-conditional: depth " depth ". Flatten or extract." }
  ' "$file" 2>/dev/null | head -20)
  if [ -n "$out" ]; then echo "$out"; return 1; fi
  return 0
}

smell_dupe_block() {
  local file="$1"
  # Detect duplicate 4+ line blocks using sort+uniq on 4-line windows
  local out
  out=$(awk 'NR>=4 { print NR-3": "a[1]"\n"a[2]"\n"a[3]"\n"$0 } { a[1]=a[2]; a[2]=a[3]; a[3]=$0 }' "$file" 2>/dev/null \
    | sort | uniq -d | head -5 \
    | while read -r line; do echo "$file: dupe-block: repeated 4-line block. Extract or deduplicate."; done)
  if [ -n "$out" ]; then echo "$out"; return 1; fi
  return 0
}

smells_check() {
  local file="$1" rc=0
  smell_long_method      "$file" || rc=1
  smell_long_params      "$file" || rc=1
  smell_magic_numbers    "$file" || rc=1
  smell_nested_conditional "$file" || rc=1
  smell_dupe_block       "$file" || rc=1
  return $rc
}
