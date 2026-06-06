#!/usr/bin/env bash
# bin/lib/strict.sh — enable strict mode + ERR trap for sourcing scripts.
# Source this at the top of every bin/ entry point.
set -Eeuo pipefail
trap 'echo "[err] $BASH_COMMAND on line $LINENO (exit $?)" >&2' ERR
