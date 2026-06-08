#!/bin/bash
# bin/lib/land-queue.sh — verdict-reason classification for mentat-land-queue.
# Source this file; do not execute directly.
#
# ADR-0010 §2-§3: a harness adapter that detects HITL ambiguity in an AFK
# chunk exits with code 42. mentat-land-queue maps that exit code to
# `reason: hitl-ambiguity` on the `land.complete` audit row — distinct from
# generic gate-fail (other nonzero) and from implement-fail (orchestrate
# upstream). Drift guard: HITL_EXIT constant is the single source within
# this script tree; ADR-0010 owns the canonical value.

HITL_EXIT=42

# Map a re-gate spawn's exit code to the verdict `reason` string.
# Echoes:
#   ""               (rc=0 — re-gate green, continue to ff-merge)
#   "hitl-ambiguity" (rc=42 — adapter refused to guess at ambiguity, ADR-0010)
#   "gate-fail"      (any other nonzero — generic red gate)
_classify_gate_rc() {  # $1 = exit code; echoes reason on stdout
  case "$1" in
    0) ;;
    "$HITL_EXIT") printf '%s' "hitl-ambiguity" ;;
    *) printf '%s' "gate-fail" ;;
  esac
}
