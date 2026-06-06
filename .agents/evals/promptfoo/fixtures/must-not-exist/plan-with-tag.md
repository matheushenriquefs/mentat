# Purge legacy bin

## S1.1 — Remove devcontainer-down [AFK]

[must-not-exist: .agents/bin/devcontainer-down]

- `rm .agents/bin/devcontainer-down`
- Create `mentat-container-down` with strict.sh header.
- Sed-sweep cross-refs.

## Must-not-exist

- `.agents/bin/devcontainer-down`
