#!/usr/bin/env bash
# bin/lib/here.sh — sets HERE to the sourcing script's own directory.
# Source this early; requires BASH_SOURCE to be set (bash only).
HERE="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
