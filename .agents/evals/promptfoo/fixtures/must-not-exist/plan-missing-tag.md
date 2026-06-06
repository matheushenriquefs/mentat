# Purge legacy bin

## S1.1 — Remove devcontainer-down [AFK]

- `rm .agents/bin/devcontainer-down`
- Create `mentat-container-down` with strict.sh header.
- Sed-sweep cross-refs.
- Verify: devcontainer-down must not exist after this slice.
