#!/usr/bin/env bash
# bin/lib/log.sh — logging helpers: log / warn / die.
# Source after strict.sh.

log()  { printf '[%s] %s\n'    "${_LOG_PREFIX:-mentat}" "$*" >&2; }
warn() { printf '[%s] WARN %s\n' "${_LOG_PREFIX:-mentat}" "$*" >&2; }
die()  { printf '[%s] ERROR %s\n' "${_LOG_PREFIX:-mentat}" "$*" >&2; exit 1; }
