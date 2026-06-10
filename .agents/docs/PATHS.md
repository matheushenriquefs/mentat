# PATHS — Mentat filesystem layout

Single source of truth for every path mentat reads or writes.

## User state (`~/.mentat/`)

```
~/.mentat/                                         # user state root
├── logs/<repo>/<session>/                         # per-session audit
│   ├── <agent>-<slug>.jsonl                       # canonical event stream
│   ├── <agent>-<slug>.stdout                      # raw harness output (opaque)
│   ├── .stderr/<agent>-<slug>.stderr              # subprocess stderr sidecar
│   └── diagnosis.md                               # per-session diagnosis (mentat-session doctor output)
└── config.jsonc                                   # single flat config (user-edited)
```

`config.jsonc` defaults:
```json
{"harness": "claude-code", "diff_tool": null}
```

## Agent/harness-shared (`~/.agents/`)

```
~/.agents/                                         # harness/agent-shared
├── plans/<slug>.md                                # canonical plan path
├── agents/mentat-researcher.md                    # non-gate research agent
└── skills/mentat-<bin>/                           # canonical skill location (clone-or-copy from repo)
```

## Per-harness symlinks

```
~/.<harness>/skills/mentat-<bin>                   # per-harness symlink → ~/.agents/skills/mentat-<bin>
                                                   # created by mentat-install per detected harness
```

Detected harnesses: `claude-code` (`~/.claude/`), `cursor` (`~/.cursor/`).

## Repo dev tree (`<repo>/.agents/`)

```
<repo>/.agents/                                    # repo dev tree
├── skills/mentat-<bin>/                           # dev tree of skills (where rewrite happens)
│   ├── SKILL.md                                   # skill manifest + invocation docs
│   └── scripts/                                   # Python source (stdlib only, except tests/)
├── lib/gates/{code,llm}/                          # filesystem-as-registry for gates
│   ├── code/*.py                                  # deterministic gates: run(chunk_path) -> Verdict
│   └── llm/*.md                                   # LLM reviewer prompts (system prompt body)
├── lib/                                           # shared host code (tasks/ runs from here)
└── docs/                                          # CONTEXT, PATHS, mentat-architecture, ADRs
```

## Evals

```
<repo>/evals/                                      # eval suites
├── <skill>.json                                   # per-skill promptfoo eval config
└── pytest/                                        # pytest harness-replay evals
```

## Stale paths (mentat-install reports for cleanup)

These paths are from the shell era and should not exist on a post-rewrite install:

| Path | Reason stale |
|---|---|
| `~/.agents/mentat/logs/` | OLD audit location — canonical is `~/.mentat/logs/` |
| `~/.agents/bin/mentat-*` | OLD shell-era symlink farm (all except thin `mentat-install` wrapper) |
| `~/.agents/skills/vendor/` | vendored skills removed (vendir dropped) |
| `~/.claude/commands/mentat-*.md` | OLD shell-era slash command shims |
| `~/.agents/bin/lib/audit.sh` | shell emitter replaced by `mentat-log emit` |
| `~/.agents/bin/lib/audit-schema.jsonc` | schema moved into `mentat-log/scripts/log.py` as `EVENT_CATALOG` |
| `~/.agents/bin/lib/harness-registry.jsonc` | adapters hard-coded as Python modules in `mentat-implement` |
| `~/.agents/agents/mentat-*-reviewer.md` | moved to `.agents/lib/gates/llm/` |
| `~/.agents/bin/mentat-precommit` | replaced by lefthook snippet |
| `~/.agents/bin/mentat-config` | user edits `~/.mentat/config.jsonc` directly |
| `~/.agents/bin/mentat-update` | vendir wrapper removed |
| `~/.mentatrc.jsonc` | never canonical; some old plans referenced this by mistake |
