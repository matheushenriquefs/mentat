# Harness Matrix

Supported headless AI coding harnesses. Each has a corresponding `bin/lib/harness/<name>.sh`
exposing three functions (all required — enforced by `lefthook harness` gate):

- `harness_<name>_cmd <prompt>` — NUL-delimited argv for the headless invocation
- `harness_<name>_output_format` — prints `stream-json`, `text`, or `event-stream`
- `harness_<name>_normalize` — reads stdin (raw harness stdout), writes canonical audit NDJSON `{ts, agent, session, event, payload}` (ADR-0009) to stdout

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

## Normalize contract

`harness_<name>_normalize` must:
- Read raw harness stdout from stdin (line-by-line or slurp per format)
- Write one canonical JSON object per line to stdout: `{ts, agent, session, event, payload}`
- Use `env MENTAT_SESSION` for `session`; never hardcode
- Wrap stderr lines as `{event:"stderr.line", payload:{line:"..."}}`

| Harness | Input format | normalize strategy |
|---|---|---|
| claude-code, amp, cursor, codex | stream-json NDJSON | `jq -c` each line, event=`.type` |
| openhands | event-stream NDJSON | event=`.action // .observation` |
| gemini | single JSON blob | slurp (`jq -cs`), wrap as `gemini.final` |
| aider | plain text | line classifier: `Tokens:*` → usage.line, `[A-Z]*:*` → aider.message |
| copilot | plain text | all lines → `stderr.line` |

`mentat-orchestrate` pipes chunk output through normalize:
```sh
( cd "$wt" && "${cmd[@]}" ) 2>&1 \
  | tee "$stdout_f" \
  | bash -c "source $hfile && $norm_fn" \
  >> "$logf"
```

## Adding a harness

1. Drop `bin/lib/harness/<name>.sh` defining all three functions: `cmd`, `output_format`, `normalize`.
2. `lefthook run pre-commit` validates the contract on commit; no other changes required.
3. Update this table.

No edits to `mentat-orchestrate` core or `config.sh` needed — enum is auto-discovered from `ls bin/lib/harness/*.sh`.
