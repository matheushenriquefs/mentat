#!/usr/bin/env bash
# bin/lib/compose-synth.sh — synthesize .devcontainer/devcontainer.json from
# docker-compose.yml or a bare Dockerfile when no .devcontainer/ exists.
# Source from mentat-container-up; requires WT and SLUG to be set by the caller.

# Infer workspace service from docker-compose.yml and write devcontainer.json.
# Exits 3 if zero or multiple buildable/cwd-mounted services are found.
synthesize_devcontainer() {
  local compose="$WT/docker-compose.yml"

  local candidates
  candidates=$(awk '
    /^services:[[:space:]]*$/ { in_svc=1; next }
    in_svc && /^[^ \t]/ { in_svc=0 }
    in_svc && /^  [a-zA-Z0-9._-]+:[[:space:]]*$/ {
      if (cur && (has_build || has_cwd)) print cur
      s=$0; gsub(/^  /, "", s); gsub(/:.*/, "", s)
      cur=s; has_build=0; has_cwd=0; next
    }
    in_svc && cur && /build:/ { has_build=1 }
    in_svc && cur && (/\.\.:/ || /\.\/:/ || /\$\{PWD\}/ || /\$PWD/) { has_cwd=1 }
    END { if (cur && (has_build || has_cwd)) print cur }
  ' "$compose")

  local count=0
  [ -n "$candidates" ] && count=$(printf '%s\n' "$candidates" | grep -c '[^[:space:]]')

  if [ "$count" -ne 1 ]; then
    local how="${candidates:-none}"
    echo "mentat-container-up: cannot infer workspace service from docker-compose.yml (buildable/cwd-mounted: $how)." >&2
    echo "Add a .devcontainer/devcontainer.json naming the \`service\` + \`workspaceFolder\`." >&2
    exit 3
  fi

  local service
  service=$(printf '%s\n' "$candidates" | head -1)

  local ws="/workspaces/$SLUG"
  local mt
  mt=$(awk -v svc="$service" '
    /^  / && $0 ~ ("^  "svc":") { in_svc=1; next }
    in_svc && /^  [a-zA-Z0-9]/ { in_svc=0 }
    in_svc { print }
  ' "$compose" | grep -oE ':[/][^[:space:]:\x27"]*' | tail -1 | sed 's/^://')
  [ -n "$mt" ] && ws="$mt"

  mkdir -p "$WT/.devcontainer"
  jq -n --arg name "$SLUG" --arg svc "$service" --arg ws "$ws" '{
    name: $name,
    dockerComposeFile: ["../docker-compose.yml"],
    service: $svc,
    workspaceFolder: $ws
  }' > "$WT/.devcontainer/devcontainer.json"
}

# Write devcontainer.json for a bare Dockerfile (no compose, no .devcontainer/).
# Exits 3 if no Dockerfile is found.
synthesize_devcontainer_from_dockerfile() {
  local dockerfile=""
  for cand in Dockerfile dockerfile; do
    [ -f "$WT/$cand" ] && dockerfile="$cand" && break
  done
  if [ -z "$dockerfile" ]; then
    local first
    first=$(ls "$WT"/Dockerfile* 2>/dev/null | head -1)
    [ -n "$first" ] && dockerfile="$(basename "$first")"
  fi
  [ -n "$dockerfile" ] || { echo "mentat-container-up: no Dockerfile found in worktree." >&2; exit 3; }

  local ws="/workspaces/$SLUG"
  local last_workdir
  last_workdir=$(grep -iE '^\s*WORKDIR\s+/\S+' "$WT/$dockerfile" | tail -1 | awk '{print $NF}')
  [ -n "$last_workdir" ] && ws="$last_workdir"

  mkdir -p "$WT/.devcontainer"
  jq -n --arg name "$SLUG" --arg df "../$dockerfile" --arg ws "$ws" '{
    name: $name,
    build: {dockerfile: $df, context: ".."},
    workspaceFolder: $ws,
    workspaceMount: ("source=${localWorkspaceFolder},target=" + $ws + ",type=bind")
  }' > "$WT/.devcontainer/devcontainer.json"
}
