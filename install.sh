#!/bin/sh
# mentat installer — cloneless bootstrap.
#
# Clones (or updates) the mentat source at ~/.local/share/mentat, then execs the
# Python install script with whatever flags were passed in.
#
# Pass-through flags (forwarded verbatim to mentat-install):
#   --yes / -y          skip confirmation
#   --dry-run           preview only (no filesystem writes)
#   --no-color          disable ANSI colors
#   --skip-companions   skip 3rd-party companion install prompts
#   --help / -h         show installer help
#
# Environment overrides:
#   MENTAT_HOME    clone target           (default: $XDG_DATA_HOME/mentat or ~/.local/share/mentat)
#   MENTAT_BRANCH  branch / tag / sha     (default: main)
#   MENTAT_REPO    git URL                (default: https://github.com/matheushenriquefs/mentat.git)

set -eu

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
MENTAT_HOME="${MENTAT_HOME:-$XDG_DATA_HOME/mentat}"
MENTAT_BRANCH="${MENTAT_BRANCH:-main}"
MENTAT_REPO="${MENTAT_REPO:-https://github.com/matheushenriquefs/mentat.git}"

log()  { printf '[mentat-install] %s\n' "$*" >&2; }
fail() { log "$*"; exit 1; }

command -v git     >/dev/null 2>&1 || fail "git not found. Install git first."
command -v python3 >/dev/null 2>&1 || fail "python3 not found. brew install python3 / apt install python3"

if [ -d "$MENTAT_HOME/.git" ]; then
  log "updating $MENTAT_HOME (branch=$MENTAT_BRANCH)"
  git -C "$MENTAT_HOME" fetch --depth 1 origin "$MENTAT_BRANCH"
  git -C "$MENTAT_HOME" checkout -q "$MENTAT_BRANCH"
  git -C "$MENTAT_HOME" reset --hard "origin/$MENTAT_BRANCH"
else
  log "cloning $MENTAT_REPO → $MENTAT_HOME (branch=$MENTAT_BRANCH)"
  mkdir -p "$(dirname "$MENTAT_HOME")"
  git clone --depth 1 --branch "$MENTAT_BRANCH" "$MENTAT_REPO" "$MENTAT_HOME"
fi

INSTALLER="$MENTAT_HOME/.agents/skills/mentat-install/scripts/install.py"
[ -f "$INSTALLER" ] || fail "installer not found at $INSTALLER (clone failed?)"

log "running mentat-install"
exec python3 "$INSTALLER" "$@"
