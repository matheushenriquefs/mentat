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
whatever this repo uses — run only via the container script:

```bash
python3 ~/.agents/skills/mentat-container/scripts/container.py run '<cmd>'
```

Never on the host. The host pins no interpreter (host interpreters may be
unset in bare worktrees) and host commits fire pre-commit where
container-only tools aren't installed (ADR 0002). If `container.py run`
fails, fix bring-up (`python3 ~/.agents/skills/mentat-container/scripts/container.py up`)
— don't fall back to host or `docker exec`. Why: ADR 0004.

## Land gate (orchestrated runs)

`mentat-orchestrate`'s serial land pass is a merge queue. Per chunk it rebases onto
the live holding tip, then re-gates by spawning a `cavecrew-builder` that reads
this repo's own docs and runs its quality gates — the driver names no tool, so it
stays project-agnostic. A red gate ejects that chunk (left up for repair). When the
whole batch lands green, one end-of-queue agent pass runs the ADR-0003 reviewers
over the final tip (advisory — inspect-after). (slice = planned cut; chunk = its
running execution; batch = all chunks in the run — ADR 0005.) Why: ADR 0004.

## ADRs

System decisions live in mentat's `docs/adr/`. Project decisions live in that
repo's own `docs/adr/`. "Check ADRs in the area you're touching" means both
— system ADRs always, repo ADRs when working in a repo. Index (titles only;
read on demand):

- **0001** sub-agent delegation — cavecrew vs vanilla, procedure not persona.
- **0002** holding branch over merge — own-branch + ff-only rebase, commits in-container.
- **0003** scored review gate — Mastra-mapped reviewers, veto > threshold.
- **0004** parallel-slicing orchestration — fan-out parallel, land serial, Docker-required.
- **0005** ubiquitous lexicon — slice/chunk/batch, one Laravel borrow (batch, noun only).
- **0006** soft read-only tests — impl-only-after-red contract + blacklist, driver agnostic.
- **0007** audit envelope — 9-event NDJSON catalog, per-session log dir.
- **0008** python runtime — stdlib-only bin layer; uv/ruff/pyright/pytest dev layer.
- **0009** plugin API — Vite-derived 2-slot extension (rubric, gate).
- **0010** read-only test mount — OCP manifest + container bind-mount.

