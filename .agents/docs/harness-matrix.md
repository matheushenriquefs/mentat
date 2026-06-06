# Harness Matrix

Supported headless AI coding harnesses. Each has a corresponding `bin/lib/harness-<name>.sh`
exposing `harness_<name>_cmd <prompt>` that prints the NUL-delimited argv.

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

1. Add a `bin/lib/harness-<name>.sh` file defining `harness_<name>_cmd <prompt>`.
2. Add `<name>` to the `_MENTAT_HARNESSES` list in `bin/lib/config.sh`.
3. Update this table.

No edits to `mentat-orchestrate` core needed.
