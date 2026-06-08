#!/usr/bin/env bash
# .agents/bin/lib/container-state.sh — single source of truth for the three
# invariants the four `mentat-container-*` scripts repeatedly re-derive:
# workspaceFolder, safe.directory, slug-from-$PWD. Design doc:
# .agents/docs/container-state-design.md (G2-S1 HITL).
#
# Convention (locked in S1 HITL): values on stdout, success via exit 0,
# failure via nonzero exit + stderr message. No silent fallback.
#
# MENTAT_DOCKER override: tests inside the dev container do not have a real
# docker CLI; setting MENTAT_DOCKER=<path/to/fake> lets the unit tests drive
# the lib's logic against scripted responses without changing call shape.

: "${MENTAT_DOCKER:=docker}"

# Slug derived from $PWD. Canonical site; replaces inline
# `basename "$PWD"` and `basename "$WT"` duplicated across the four scripts.
container_slug_for_cwd() {
  basename "$PWD"
}

# Resolve a running container's ID by mentat_slug label.
# Stdout: 12-char (or longer) docker container ID.
# Exit 0 on hit, 1 on miss (stderr stays empty — caller decides fatality),
# 2 on missing argument.
container_id_for() {
  local slug="${1:-}"
  if [ -z "$slug" ]; then
    echo "container_id_for: missing slug arg" >&2
    return 2
  fi
  local cid
  cid="$("$MENTAT_DOCKER" ps -q --filter "label=mentat_slug=$slug" 2>/dev/null | head -1)"
  if [ -z "$cid" ]; then
    return 1
  fi
  printf '%s\n' "$cid"
}

# Assert the workspaceFolder path exists inside the container for $PWD's slug.
# Stdout: empty. Exit 0 on hit; nonzero with explicit stderr on miss.
ensure_workspace_folder() {
  local ws="${1:-}"
  if [ -z "$ws" ]; then
    echo "ensure_workspace_folder: missing ws arg" >&2
    return 2
  fi
  local slug cid
  slug="$(container_slug_for_cwd)"
  if ! cid="$(container_id_for "$slug")"; then
    echo "ensure_workspace_folder: no container for slug=$slug (run mentat-container-up)" >&2
    return 1
  fi
  if ! "$MENTAT_DOCKER" exec "$cid" test -d "$ws" >/dev/null 2>&1; then
    echo "ensure_workspace_folder: missing inside container: $ws" >&2
    return 1
  fi
}

# Assert git safe.directory contains $ws inside the container.
# Stdout: empty. Exit 0 on hit; nonzero with explicit stderr on miss.
# Match is full-line + fixed-string (grep -Fxq) — `/foo` does not match
# `/foobar`; only exact entries count.
assert_safe_directory() {
  local ws="${1:-}"
  if [ -z "$ws" ]; then
    echo "assert_safe_directory: missing ws arg" >&2
    return 2
  fi
  local slug cid
  slug="$(container_slug_for_cwd)"
  if ! cid="$(container_id_for "$slug")"; then
    echo "assert_safe_directory: no container for slug=$slug" >&2
    return 1
  fi
  if ! "$MENTAT_DOCKER" exec "$cid" git config --global --get-all safe.directory 2>/dev/null \
       | grep -Fxq "$ws"; then
    echo "assert_safe_directory: $ws not in git safe.directory" >&2
    return 1
  fi
}

# Idempotent: if .devcontainer/devcontainer.json exists, return 0 immediately.
# Otherwise delegate to compose-synth.sh (which expects WT + SLUG env vars).
# Exit 1 + stderr if neither compose nor Dockerfile is present.
synthesize_compose_if_absent() {
  local wt="$PWD"
  if [ -f "$wt/.devcontainer/devcontainer.json" ]; then
    return 0
  fi
  local has_compose=0 has_dockerfile=0
  if [ -f "$wt/docker-compose.yml" ] || [ -f "$wt/docker-compose.yaml" ]; then
    has_compose=1
  fi
  if ls "$wt"/Dockerfile* >/dev/null 2>&1; then
    has_dockerfile=1
  fi
  if [ "$has_compose" = 0 ] && [ "$has_dockerfile" = 0 ]; then
    echo "synthesize_compose_if_absent: no compose / Dockerfile in $wt; cannot synthesize devcontainer" >&2
    return 1
  fi
  local lib_dir
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  export WT="$wt"
  export SLUG
  SLUG="$(container_slug_for_cwd)"
  # shellcheck source=/dev/null
  . "$lib_dir/compose-synth.sh"
  mkdir -p "$wt/.devcontainer"
  # Atomic write: synthesize_* `exit 3`s mid-jq on zero/multiple compose
  # services or missing Dockerfile. Bash opens+truncates the redirect target
  # BEFORE the fn runs, so a naked `synthesize_x > final` would leave an
  # empty .devcontainer/devcontainer.json that the guard above re-greenlights
  # on next run (data-poisoning). Write to a sibling tmp (same dir as the
  # final target → mv is an atomic rename(2), not a cross-fs copy) then mv
  # on success; on exit-3 the caller dies before mv runs and the real
  # target stays untouched. An orphan `<dcj>.XXXXXX` may persist in
  # .devcontainer/ on repeated failures — cosmetic; cleanup is a follow-up.
  local dcj="$wt/.devcontainer/devcontainer.json"
  local tmp
  tmp="$(mktemp "${dcj}.XXXXXX")"
  if [ "$has_compose" = 1 ]; then
    synthesize_devcontainer > "$tmp" && mv "$tmp" "$dcj"
  else
    synthesize_devcontainer_from_dockerfile > "$tmp" && mv "$tmp" "$dcj"
  fi
}
