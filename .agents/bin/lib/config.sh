#!/bin/bash
# bin/lib/config.sh — load + validate .mentat.jsonc (nested schema)
# Source this file; do not execute directly.

_MENTAT_HARNESSES="claude-code cursor aider codex copilot gemini openhands amp"

_mentat_config_file() {
  # Allow test injection via MENTAT_CONFIG_PATH
  if [ -n "${MENTAT_CONFIG_PATH:-}" ] && [ -f "$MENTAT_CONFIG_PATH" ]; then
    echo "$MENTAT_CONFIG_PATH"; return
  fi
  for f in "$PWD/.mentat.jsonc" "$HOME/.mentat.jsonc"; do
    [ -f "$f" ] && { echo "$f"; return; }
  done
}

mentat_config() {  # $1 = dot-path (harness.name, agents.max_concurrent)
  local f; f="$(_mentat_config_file)"
  [ -n "$f" ] || return 0
  sed 's|//.*||g' "$f" | jq -r ".${1} // empty"
}

mentat_config_validate() {
  local f; f="$(_mentat_config_file)"
  if [ -z "$f" ]; then
    echo "[mentat-config] no .mentat.jsonc found — using defaults" >&2; return 0
  fi
  local parsed; parsed="$(sed 's|//.*||g' "$f")" || { echo "[mentat-config] JSONC parse error" >&2; return 2; }

  local name; name="$(echo "$parsed" | jq -r '.harness.name // empty')"
  local valid=0
  for h in $_MENTAT_HARNESSES; do [ "$name" = "$h" ] && valid=1 && break; done
  [ "$valid" -eq 1 ] || { echo "[mentat-config] .harness.name '$name' invalid (${_MENTAT_HARNESSES})" >&2; return 2; }

  echo "$parsed" | jq -e '.harness.model | type == "string"' >/dev/null 2>&1 \
    || { echo "[mentat-config] .harness.model must be string" >&2; return 2; }

  local cap; cap="$(echo "$parsed" | jq -r '.agents.max_concurrent // empty')"
  echo "$parsed" | jq -e '.agents.max_concurrent | type == "number" and . >= 1 and . <= 10' >/dev/null 2>&1 \
    || { echo "[mentat-config] .agents.max_concurrent must be int 1-10, got: $cap" >&2; return 2; }

  for key in '.diff.tool' '.editor.name'; do
    echo "$parsed" | jq -e "${key} | type == \"string\"" >/dev/null 2>&1 \
      || { echo "[mentat-config] ${key} must be string" >&2; return 2; }
  done

  echo "$parsed" | jq -e '.plugins | type == "array"' >/dev/null 2>&1 \
    || { echo "[mentat-config] .plugins must be array" >&2; return 2; }
}
