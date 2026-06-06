# Harness Matrix

Supported headless AI coding harnesses. Each has a corresponding `bin/lib/harness/<name>.sh`
exposing `harness_<name>_cmd <prompt>` (NUL-delimited argv) and `harness_<name>_output_format`
(prints `stream-json`, `text`, or `event-stream`).

| Name | Binary | Headless flag | Stream output | Auth model |
|---|---|---|---|---|
| `claude-code` | `claude` | `-p` | `--output-format stream-json` | `ANTHROPIC_API_KEY` |
| `cursor` | `cursor-agent` | `-p` | `--output-format stream-json` | Cursor account / OAuth |
| `aider` | `aider` | `--message --yes` | text stream | `OPENAI_API_KEY` or LiteLLM |
| `codex` | `codex` | `exec` | `--json` | `OPENAI_API_KEY` |
| `copilot` | `copilot` | `-p` | text stream | GitHub token / OAuth |
| `gemini` | `gemini` | `-p` | `--output-format json` | `GOOGLE_API_KEY` |
| `openhands` | `openhands` | `-t` | event-stream JSON | `LLM_API_KEY` |
| `amp` | `amp` | `-x` | `--stream-json` | `ANTHROPIC_API_KEY` |

Cline/Roo/Continue/Cody: IDE-only or deprecated — not in enum.

## Adding a harness

1. Drop `bin/lib/harness/<name>.sh` defining `harness_<name>_cmd <prompt>` and `harness_<name>_output_format`.
2. `lefthook run pre-commit` validates the contract on commit; no other changes required.
3. Update this table.

No edits to `mentat-orchestrate` core or `config.sh` needed — enum is auto-discovered from `ls bin/lib/harness/*.sh`.
