#!/usr/bin/env bash
# bin/lib/gates.sh — per-class deterministic file checkers for mentat-gate

gate_adr() {
  local ok=1
  grep -q '^## Context'      "$1" || { echo "$1: missing '## Context'";      ok=0; }
  grep -q '^## Decision'     "$1" || { echo "$1: missing '## Decision'";     ok=0; }
  grep -q '^## Consequences' "$1" || { echo "$1: missing '## Consequences'"; ok=0; }
  return $((1 - ok))
}

gate_skill() {
  head -10 "$1" | grep -q '^---$' || { echo "$1: missing YAML frontmatter"; return 1; }
}

gate_command() {
  head -10 "$1" | grep -q '^---$' || { echo "$1: missing YAML frontmatter"; return 1; }
}

gate_workflow() {
  grep -q '\[.\+\](.\+\.md)' "$1" || { echo "$1: no cross-ref links found"; return 1; }
}

gate_shell() {
  bash -n "$1" || return 1
  command -v shellcheck >/dev/null && shellcheck "$1" || true
}

gate_jsonc() {
  sed 's|//.*||g' "$1" | jq -e '.' >/dev/null || { echo "$1: jq parse fail"; return 1; }
}

mentat_gate() {
  local f="$1"
  case "$f" in
    */docs/adr/*.md)    gate_adr      "$f" ;;
    */agents/*.md)      gate_skill    "$f" ;;
    */commands/*.md)    gate_command  "$f" ;;
    AGENTS.md|CONTEXT.md|STYLE.md|README.md|\
    */AGENTS.md|*/CONTEXT.md|*/STYLE.md|*/README.md)
                        gate_workflow "$f" ;;
    *.sh|*/bin/mentat-*|*/bin/lib/*)
                        gate_shell    "$f" ;;
    *.jsonc)            gate_jsonc    "$f" ;;
    *)                  return 0 ;;
  esac
}
