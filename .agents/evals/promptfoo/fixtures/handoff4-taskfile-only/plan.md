# Plan: Fix CI Taskfile test invocation

## Goal
Fix the `build:test` task so it runs pytest with the correct working directory and passes in CI.

## Required changes
- Update `Taskfile.yml` `build:test` task: set `dir: /workspaces/mentat`
- Add `--tb=short` flag to pytest invocation
- Ensure task exits 0 on a clean run

## Verification
`task build:test` exits 0 in under 60 seconds in devcontainer.
No source file changes required.
