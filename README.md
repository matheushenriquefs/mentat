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

> "Once men turned their thinking over to machines in the hope that this would set them free. But that only permitted other men with machines to enslave them."
>
> — *Dune*, Frank Herbert

---

## Install

Mentat needs Python 3.11+ and Docker. Everything else runs inside the devcontainer.

```bash
git clone https://github.com/matheushenriquefs/mentat && cd mentat

# idempotent — sets up ~/.mentat/ + ~/.agents/ + harness symlinks
.agents/bin/mentat-install              # interactive
.agents/bin/mentat-install --yes        # skip confirmation
.agents/bin/mentat-install --dry-run    # preview only
```

## Quick Start

```
# 1. plan — agent grills requirements, writes ~/.agents/plans/add-csv-export-plan.md
/mentat-plan add-csv-export-plan

# 2. orchestrate — fan slices out as parallel chunks, land serial onto holding branch
/mentat-orchestrate run feat/add-csv-export add-csv-export-plan

# 3. watch the batch land
/mentat-session track

# 4. inspect ejected chunks (if any)
/mentat-session doctor

# 5. review what landed on holding before merging upstream
/mentat-git diff main..holding/add-csv-export
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

## Development

Contributing to Mentat itself (not running it on a target repo):

```bash
task install   # uv sync — dev dependencies (ruff, pyright, pytest)
task check     # lint + format + typecheck
task test      # pytest tests/
```

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
