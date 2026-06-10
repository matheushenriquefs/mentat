# ADR 0010: Read-only test mount (OCP manifest + bind-mount)

Status: Accepted
Date: 2026-06-10

## Context

ADR-0006 rejected kernel-level read-only mounts because the driver would need
per-repo test path knowledge — breaking ADR-0004's language agnosticism. That
blocker is resolved by a plan-adjacent manifest (`<slug>.tests.json`) written by
plan-phase enumeration, not the driver.

SWE-bench's `PASS_TO_PASS` semantic (existing tests that must stay green) maps
directly onto this manifest's `closed` array. Using OCP vocabulary (`closed` /
`open`) makes the design legible across the dev audience without introducing a
new naming scheme.

## Decision

**Manifest** — `~/.agents/plans/<slug>.tests.json` written at plan phase:

```json
{
  "closed": ["tests/test_foo.py", "spec/bar_spec.rb"],
  "open":   ["tests/test_new_feature.py"]
}
```

- `closed` — existing test files, enumerated by `cavecrew-investigator` at plan
  phase. Default: every test file discovered in the repo.
- `open` — plan author overrides; these files may be modified during impl.
- Unlisted files — unconstrained (new test files freely creatable, per OCP
  extension principle).

**Sub-agent prompt for enumeration** (Pocock voice, language-agnostic):

> List test files in this repo. Return absolute paths only. Skip generated tests
> and vendored dependencies.

**Mechanism** — 4 steps:

1. **Plan phase.** `/mentat-plan` spawns `cavecrew-investigator` with the prompt
   above. Output populates `closed`. Plan author edits `open` allowlist for slices
   that intentionally modify existing tests.

2. **Memory.** `/mentat-plan` writes `~/.agents/plans/<slug>.tests.json` adjacent
   to the plan body.

3. **Impl phase.** `/mentat-implement` reads the manifest before
   `/mentat-container-up`. For each `path in closed - open`, container spawn
   appends:
   ```
   --mount type=bind,source=<host>/<path>,target=<container>/<path>,readonly
   ```

4. **TDD escape.** `/mentat-implement` supports `mark-test-writable <path>`
   subcommand (audited as `test.writable.requested`) for the red-test-write step.
   Flips back to `ro,bind` after red commits via `/mentat-commit`.

## Consequences

- ADR-0004 agnosticism preserved: driver reads the manifest, infers no test paths
  itself.
- ADR-0006 soft layer retained; hard mount is additive, not a replacement.
- `/mentat-plan` gains `cavecrew-investigator` spawn + manifest write step.
- `/mentat-implement` gains manifest read + `--mount` injection + `mark-test-writable`.
- Container scripts untouched beyond accepting extra `--mount` flags.
- Manifest absent (old plans, quick runs) → no mounts added; ADR-0006 soft
  layer still applies.
