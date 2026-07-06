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
└── config.toml                                    # single flat config (user-edited, TOML)
```

`config.toml` keys (layered: `~/.mentat` < repo `.mentat`, repo wins):
```toml
harness = "claude-code"   # claude-code | cursor
# model = "claude-opus-4-8"
# concurrency = 3
# runtime = "docker"      # docker (containerized, default) | host (unsafe — ADR-0004 forfeit)
```
`runtime = "host"` makes `mentat-container` skip bring-up and run project tools on the
host, after a one-time isolation-forfeit warning — the documented opt-out for repos that
cannot containerize.

## Agent/harness-shared (`~/.agents/`)

```
~/.agents/                                         # harness/agent-shared
├── plans/<slug>.md                                # canonical plan path
├── agents/mentat-researcher.md                    # non-gate research agent
├── docs/adr/                                      # symlink → <clone>/docs/adr (shipped by mentat-install)
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
├── skills/mentat-<bin>/                           # dev tree of skills (skill source)
│   ├── SKILL.md                                   # skill manifest + invocation docs
│   └── scripts/                                   # Python source (stdlib only, except tests/)
├── lib/gates/code/                                # deterministic Python gates
│   └── *.py                                       # run(chunk_path) -> (verdict, message)
├── lib/gates/score.py                             # aggregates subagent JSON verdicts (ADR-0003)
├── agents/mentat-*-reviewer.md                    # LLM reviewer subagents (harness-agnostic)
├── lib/                                           # shared host code (tasks/ runs from here)
└── docs/PATHS.md                                  # filesystem layout (harness-internal). Lexicon lives in repo CONTEXT.md + docs/adr/0005-ubiquitous-lexicon.md
```

## Repo user-facing docs (`<repo>/docs/`)

```
<repo>/docs/                                       # user-facing docs (root-level)
├── adr/                                           # Architecture Decision Records
│   ├── README.md                                  # index
│   └── NNNN-<kebab>.md                            # one per decision (canonical location)
├── ARCHITECTURE.md                                # canonical narrative overview
├── STYLE.md                                       # voice + LOC budget
├── PLUGINS.md                                     # plugin API contract
├── EXIT-CODES.md                                  # BSD sysexits convention
└── wiki/                                          # (mirror to GitHub wiki — out-of-repo source)
```

## Evals

```
<repo>/evals/                                      # eval suites
├── <skill>.json                                   # per-skill promptfoo eval config
└── pytest/                                        # pytest harness-replay evals
```

## Stale paths (mentat-install reports for cleanup)

These paths are stale and should not exist on current installs:

| Path | Canonical instead |
|---|---|
| `~/.agents/mentat/logs/` | audit lives in `~/.mentat/logs/` |
| `~/.agents/bin/mentat-*` | only the `mentat-install` wrapper belongs in `~/.agents/bin/` |
| `~/.agents/skills/vendor/` | mentat does not vendor skills |
| `~/.claude/commands/mentat-*.md` | mentat ships skills, not command shims |
| `~/.agents/bin/lib/audit.sh` | audit emits via `mentat-log emit` |
| `~/.agents/bin/lib/audit-schema.jsonc` | schema is `EVENT_CATALOG` in `mentat-log/scripts/log.py` |
| `~/.agents/bin/lib/harness-registry.jsonc` | adapters are Python modules under `mentat-implement/scripts/harness/` |
| `~/.agents/lib/gates/llm/` | rubric content lives in `.agents/agents/mentat-*-reviewer.md` bodies (ADR-0003) |
| `~/.agents/bin/mentat-precommit` | pre-commit runs via lefthook |
| `~/.agents/bin/mentat-config` | user edits `~/.mentat/config.toml` directly |
| `~/.agents/bin/mentat-update` | mentat has no update wrapper |
| `~/.mentatrc.jsonc` | config is `~/.mentat/config.toml` |
