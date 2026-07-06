# Plan brief: add config loader to mentat-orchestrate

## Goal

Wire `~/.mentat/config.toml` into `mentat-orchestrate` so users stop passing `--harness` and `--model` flags every invocation. All work touches a single call chain.

## Slices

- write `lib/config.py` — `load_config()` reads `~/.mentat/config.toml` via stdlib `tomllib`
- write `lib/config_validate.py` — validates schema, raises `ConfigError` on bad value; calls `load_config()`
- update `skills/mentat-orchestrate/scripts/orchestrate.py` — replace flag parse loop with `load_config()` calls; import `config`; import `config_validate`
- write `~/.mentat/config.toml.example` — comments documenting every key

## Dependencies

`config_validate.py` blocked by `config.py` (calls `load_config`).
`orchestrate.py` blocked by `config_validate.py` (validates on startup).
`config.toml.example` blocked by `config_validate.py` (documents the same keys).

All slices write to `.agents/lib/`, `.agents/skills/mentat-orchestrate/scripts/`, or `~/.mentat/` — one write-set, one chain.
