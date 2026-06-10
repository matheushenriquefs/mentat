<h1 align="center">Mentat</h1>

<h3 align="center">Parallel agents with vertical slices, devcontainers, and a serial merge queue</h3>

<p align="center">
  Fan out coding agents across isolated git worktrees + devcontainers.<br/>
  Land each slice back onto a holding branch through a scored, serial gate.
</p>

<p align="center">
  <a href="./docs/ARCHITECTURE.md"><strong>Architecture</strong></a> &nbsp;&middot;&nbsp;
  <a href="./CONTEXT.md"><strong>Glossary</strong></a> &nbsp;&middot;&nbsp;
  <a href="./docs/adr/README.md"><strong>ADRs</strong></a> &nbsp;&middot;&nbsp;
  <a href="https://github.com/matheushenriquefs/mentat/issues"><strong>Issues</strong></a>
</p>

---

> "It is by will alone I set my mind in motion. It is by the juice of sapho that thoughts acquire speed, the lips acquire stains, the stains become a warning. It is by will alone I set my mind in motion."
>
> — *The Mentat Mantra*, Frank Herbert, **Dune**

---

## Install

Mentat needs Python 3.11+ and Docker. Everything else runs inside the devcontainer.

```bash
# clone
git clone https://github.com/matheushenriquefs/mentat && cd mentat

# dev install
task install                            # uv sync

# user install (idempotent — sets up ~/.mentat/ + ~/.agents/ + harness symlinks)
.agents/bin/mentat-install              # interactive
.agents/bin/mentat-install --yes        # skip confirmation
.agents/bin/mentat-install --dry-run    # preview only
```

Dev commands:

```bash
task check   # lint + format + typecheck
task test    # pytest tests/
```

## Quick Start

```bash
# 1. create a plan (interactive grilling session)
python3 ~/.agents/skills/mentat-plan/scripts/plan.py write my-feature /tmp/body.md

# 2. orchestrate — fan slices out as parallel chunks, land serial
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py run \
    branch/my-feature my-feature

# 3. watch the batch land
python3 ~/.agents/skills/mentat-session/scripts/session.py track

# 4. inspect ejected chunks (if any)
python3 ~/.agents/skills/mentat-session/scripts/session.py doctor

# 5. merge holding into main when green
git checkout main && git merge --ff-only branch/my-feature
```

## What it does

- **Vertical-slice plans** — break work into tracer-bullet `plan.md` files, each independently landable.
- **Parallel fan-out** — each slice becomes a chunk: worktree + devcontainer + branch, up to 3 concurrent.
- **Serial land queue** — rebase onto holding tip in-container, re-gate, fast-forward. No merge commits, no host pre-commit collisions.
- **Scored review gate** — 5 reviewer subagents (plan/test/bug/smell/context) emit JSON verdicts; never average, veto > threshold.
- **Anti-cheat blacklist** — trajectory scanner in `mentat-bug-reviewer` hard-vetoes forbidden moves (test-runner redirection, asserting the inverse). No threshold mediation.
- **AFK vs HITL** — slice-level tags control whether agents stall for human review or proceed unattended. AFK depends on the scored gate.
- **Audit envelope** — every command emits start + complete events. NDJSON to `~/.mentat/logs/<repo>/<session>/`.
- **Harness-agnostic** — pluggable headless-agent CLIs (`claude-code`, `cursor` today). Drop a module to add another.
- **Plugin API** — extend rubrics and gates without forking core.
- **Stdlib-only bin layer** — installs without pip. Dev layer uses `uv`/`ruff`/`pyright`/`pytest`.

## How it compares

| | Mentat | dmux [^1] | swarm [^2] | claude-flow [^3] |
|---|---|---|---|---|
| Parallel fan-out | ✓ | ✓ [^4] | ✓ [^5] | ✓ [^6] |
| Serial land queue | ✓ | — | — | — |
| Deterministic gate | ✓ | — | — | partial [^7] |
| Anti-cheat blacklist | ✓ | — | — | — |
| Host toolchain required | python3 | none [^8] | python | node [^10] |
| Harness agnostic | ✓ | — [^11] | — | — [^12] |
| Docker required | ✓ | — | — | — |

[^1]: dmux — tmux-based Claude Code pane manager. Runs multiple Claude Code sessions in parallel tmux panes. No merge queue or quality gate. <https://github.com/formkit/dmux>
[^2]: OpenAI Swarm — "lightweight, highly controllable, and easily testable" multi-agent coordination via `Agent`s and handoffs. Deprecated in favour of [OpenAI Agents SDK](https://github.com/openai/openai-agents-python). <https://github.com/openai/swarm>
[^3]: claude-flow (now Ruflo) — "Multi-agent AI harness for Claude Code and Codex." Orchestrates swarms via `npx ruflo init`. <https://github.com/ruvnet/claude-flow>
[^4]: dmux spawns one Claude Code pane per task; panes run concurrently inside tmux.
[^5]: Swarm routes between agents via handoffs; concurrent calls possible via Python async.
[^6]: Ruflo: "Orchestrate 100+ specialized AI agents across machines, teams, and trust boundaries."
[^7]: Ruflo includes a routing layer and autopilot loop but no deterministic scored gate or veto system equivalent to ADR-0003.
[^8]: dmux is a shell script + tmux; no language runtime required on the host beyond tmux and a terminal.
[^10]: Ruflo README: "One `npx ruflo init` gives Claude Code a nervous system." Requires Node.js/npm for `npx`.
[^11]: dmux is tightly coupled to Claude Code; it reads `.dmux.config.json` and launches `claude` sessions directly.
[^12]: Ruflo targets Claude Code and Codex explicitly; README badge: "Claude Code — Plugin".

## Documentation

- **[Architecture](./docs/ARCHITECTURE.md)** — narrative overview, 15 sections, ADR pointers.
- **[Glossary](./CONTEXT.md)** — domain lexicon (slice / chunk / batch / land / eject / AFK / HITL).
- **[ADRs](./docs/adr/README.md)** — 10 architecture decision records, 0001-0010.
- **[Filesystem layout](./.agents/docs/PATHS.md)** — every path Mentat reads or writes.
- **[Style guide](./docs/STYLE.md)** — voice classes, LOC budgets, banned words.
- **[Plugin API](./docs/PLUGINS.md)** — rubric + gate extension slots.
- **[Exit codes](./docs/EXIT-CODES.md)** — BSD sysexits convention.
- **[Installer design](./docs/INSTALLER.md)** — TUI flows.

## License

MIT. See [CREDITS.md](./CREDITS.md) for attributions and inspirations.
