# AGENTS.md

## Sub-agent delegation

Want the finding in ~1/3 the tokens → spawn a cavecrew variant
(`cavecrew-investigator` to locate repo code, `cavecrew-builder` for ≤2-file
edits, `cavecrew-reviewer` for diffs, `mentat-researcher` for external facts).
Want prose — rationale, alternatives, architecture — → spawn vanilla
(`Explore`, `Code Reviewer`) or use the main thread.

`skill-creator` stays vanilla. `mentat-researcher` runs on the cheapest capable
model the harness offers.

## Run project tools in the container, never the host

The project's interpreters, formatters, linters, hooks, and test runner —
whatever this repo uses — run only via `mentat-container-run '<cmd>'`, never on the
host. The host pins no interpreter (asdf shim aborts in a bare worktree) and host
commits fire pre-commit where container-only tools aren't installed (ADR 0002).
If `mentat-container-run` fails, fix bring-up — don't fall back to host or
`docker exec`. Why: ADR 0004.

## Land gate (orchestrated runs)

`mentat-orchestrate`'s serial land pass is a merge queue. Per chunk it rebases onto
the live holding tip, then re-gates by spawning a `cavecrew-builder` that reads
this repo's own docs and runs its quality gates — the driver names no tool, so it
stays project-agnostic. A red gate ejects that chunk (left up for repair). When the
whole batch lands green, one end-of-queue agent pass runs the ADR-0003 reviewers
over the final tip (advisory — inspect-after). (slice = planned cut; chunk = its
running execution; batch = all chunks in the run — ADR 0005.) Why: ADR 0004.

## ADRs

System decisions live in `~/.agents/docs/adr/`. Project decisions live in that
repo's `<repo>/docs/adr/`. "Check ADRs in the
area you're touching" means both — system ADRs always, repo ADRs when working
in a repo. Index (titles only; read on demand):

- **0001** sub-agent delegation — cavecrew vs vanilla, procedure not persona.
- **0002** holding branch over Merge — own-branch + `/to-rebase`, commits in-container.
- **0003** scored review gate — Mastra-mapped reviewers, veto > threshold.
- **0004** parallel-slicing orchestration — fan-out parallel, land serial, Docker-required.
- **0005** ubiquitous lexicon — slice/chunk/batch, one Laravel borrow (batch, noun only).
- **0006** soft read-only tests — impl-only-after-red contract + blacklist, driver agnostic.

## Comment Hygiene

- Comment *why*, not *what*. Code names explain what; comments explain motivation.
- No commented-out code. Delete it.
- No TODO comments. File an ADR or an issue.
- Docstring/header for public entry points only. No narrative essays inside functions.
- Remove duplicate comment blocks. One canonical statement per fact.

## Quality Gates

Every modified file must pass its class checker before commit.
Run locally: `mentat-gate $(git diff --name-only "$base")`.
Wired into `mentat-orchestrate` pre-land step (host-side; harness tools only — ADR 0004).

<!-- BEGIN generated: mentat-gate --print-policy -->
| Class | Glob | Check |
|-------|------|-------|
| ADR | docs/adr/*.md | All three sections present: ## Context, ## Decision, ## Consequences |
| Skill/agent | agents/*.md | YAML frontmatter present (first 10 lines contain ---) |
| Command | commands/*.md | YAML frontmatter present (first 10 lines contain ---) |
| Workflow doc | AGENTS.md,CONTEXT.md,STYLE.md,README.md | Cross-ref links present ([text](*.md) syntax) |
| Shell | bin/**/*,lib/**/*.sh | bash -n + shellcheck (advisory if absent) |
| Config | *.jsonc | sed | jq -e validates JSON structure |
| Harness | bin/lib/harness/*.sh | harness_<name>_cmd and harness_<name>_output_format both defined |
<!-- END generated -->

Unknown file classes pass silently (gate is additive, not a whitelist).

See [bin/lib/gates.sh](bin/lib/gates.sh) for checker implementations and [bin/mentat-gate](bin/mentat-gate) for the driver.

## Test-when-modified

Modifying certain file classes requires additional checks before commit:

| Trigger | Required action |
|---|---|
| `agents/*.md` or `skills/*/SKILL.md` modified | Run `mentat-gate <file>` + skill's promptfoo eval (`npx promptfoo eval --filter-providers <skill-name>`) |
| `docs/adr/*.md` modified | File must include `**Decided:** <YYYY-MM-DD>` and `**Author:** <handle>` lines |
| `agents/mentat-*-reviewer.md` modified | Must bump ADR-0003 weight rationale (add/update reasoning for any changed dimension weight) |

These are enforced by convention during review, not by a pre-commit hook. `mentat-gate` flags structural violations; the LLM reviewer flags missing promptfoo eval evidence in the PR diff.

## Project docs

- [../README.md](../README.md) — public overview, quickstart, no-framework thesis.
- [../CONTEXT.md](../CONTEXT.md) — glossary (slice/chunk/batch/land/eject/…) + ADR index + flagged ambiguities.
- [../STYLE.md](../STYLE.md) — frontmatter shapes, body structure, forbidden words, voice rules per file class.
- [../AGENTS.md](../AGENTS.md) — repo-level agent guidelines (constraints, naming conventions, workflow rules).
