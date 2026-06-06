# Plan brief: add config loader to mentat-orchestrate

## Goal

Wire `.mentat.jsonc` config into `mentat-orchestrate` so users stop passing `--harness` and `--model` flags every invocation. All work touches a single call chain.

## Slices

- S1: write `bin/lib/config.sh` — `mentat_config()` reads `.mentat.jsonc` via `sed | jq`
- S2: write `bin/lib/config-validate.sh` — validates schema, exits 2 on bad value; calls `mentat_config()`
- S3: update `bin/mentat-orchestrate` — replace flag parse loop with `mentat_config` calls; source `config.sh`; source `config-validate.sh`
- S4: write `.agents/.mentat.jsonc` default — sane starter config; validated by S2 checker
- S5: write `.agents/.mentat.jsonc.example` — inline `//` comments documenting every key; references S4

## Dependencies

S2 blocked by S1 (calls `mentat_config`).
S3 blocked by S2 (validates on startup).
S4 blocked by S2 (must validate clean).
S5 blocked by S4 (documents the same keys).

All slices write to `.agents/bin/` or `.agents/` root — one write-set, one chain.
