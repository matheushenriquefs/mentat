#!/usr/bin/env bash
# bin/lib/gates.sh — per-class deterministic file checkers for mentat-gate

# @class: ADR  # @glob: docs/adr/*.md  # @check: All three sections present: ## Context, ## Decision, ## Consequences
gate_adr() {
  local ok=1
  grep -q '^## Context'      "$1" || { echo "$1: missing '## Context'";      ok=0; }
  grep -q '^## Decision'     "$1" || { echo "$1: missing '## Decision'";     ok=0; }
  grep -q '^## Consequences' "$1" || { echo "$1: missing '## Consequences'"; ok=0; }
  return $((1 - ok))
}

# @class: Skill/agent  # @glob: agents/*.md  # @check: YAML frontmatter present (first 10 lines contain ---)
gate_skill() {
  head -10 "$1" | grep -q '^---$' || { echo "$1: missing YAML frontmatter"; return 1; }
}

# @class: Command  # @glob: commands/*.md  # @check: YAML frontmatter present (first 10 lines contain ---)
gate_command() {
  head -10 "$1" | grep -q '^---$' || { echo "$1: missing YAML frontmatter"; return 1; }
}

# @class: Workflow doc  # @glob: AGENTS.md,CONTEXT.md,README.md  # @check: Cross-ref links present ([text](*.md) syntax)
gate_workflow() {
  grep -qE '\[.+\]\(.+\.md\)' "$1" || { echo "$1: no cross-ref links found"; return 1; }
}

# @class: Shell  # @glob: bin/**/*,lib/**/*.sh  # @check: bash -n + shellcheck (advisory if absent)
gate_shell() {
  bash -n "$1" || return 1
  command -v shellcheck >/dev/null && shellcheck "$1" || true
}

# @class: Config  # @glob: *.jsonc  # @check: sed | jq -e validates JSON structure
gate_jsonc() {
  # Delete pure // comment lines only — avoids breaking https:// URLs in string values
  sed '/^[[:space:]]*\/\//d' "$1" | jq -e '.' >/dev/null || { echo "$1: jq parse fail"; return 1; }
}

# @class: Harness  # @glob: bin/lib/harness/*.sh  # @check: harness_<name>_cmd and harness_<name>_output_format both defined
gate_harness() {
  local name; name="$(basename "$1" .sh | tr - _)"
  bash -c "source $(printf %q "$1"); declare -f harness_${name}_cmd >/dev/null" \
    || { echo "$1: missing harness_${name}_cmd"; return 1; }
  bash -c "source $(printf %q "$1"); declare -f harness_${name}_output_format >/dev/null" \
    || { echo "$1: missing harness_${name}_output_format"; return 1; }
}

mentat_gate() {
  local f="$1"
  case "$f" in
    */docs/adr/*.md)    gate_adr      "$f" ;;
    */agents/*.md)      gate_skill    "$f" ;;
    */commands/*.md)    gate_command  "$f" ;;
    AGENTS.md|CONTEXT.md|README.md|\
    */AGENTS.md|*/CONTEXT.md|*/README.md)
                        gate_workflow "$f" ;;
    */bin/lib/harness/*.sh)
                        gate_harness  "$f" ;;
    *.sh|*/bin/mentat-*|*/bin/lib/*)
                        gate_shell    "$f" ;;
    *.jsonc)            gate_jsonc    "$f" ;;
    *)                  return 0 ;;
  esac
}
