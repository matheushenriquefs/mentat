# CONTEXT — Mentat domain lexicon

Domain vocabulary for mentat. Canonical definitions; ADRs are the source of authority for decisions.

## Lexicon — review machinery

- **gate** — anything that evaluates a chunk and emits a verdict (umbrella).
- **code gate** — gate implemented in Python (deterministic). Lives in `.agents/lib/gates/code/`.
- **llm gate** — gate implemented as a reviewer agent prompt. Lives in `.agents/lib/gates/llm/`.
- **smell** — Fowler code smell. Advisory by default. Both code and llm gates can emit smells.
- **severity** — per-gate: `info` / `low` / `med` / `high` / `critical`.
- **threshold** — (llm gates only) numeric score above which advisory flips to blocking.
- **verdict** — typed gate output: `pass` / `block` / `advise`.

## Lexicon — orchestration

- **slice** — planned cut (a discrete unit of work in a plan file).
- **chunk** — slice's running execution (worktree + harness session).
- **batch** — all chunks in one orchestrate run.
- **plan class** — `AFK` (headless, no `AskUserQuestion`) | `HITL` (anchored, interactive).
- **holding branch** — `branch/<feature>` with no commits of its own; chunks fast-forward onto it.
- **land** — fast-forward a chunk's worktree tip onto the holding branch after all gates pass.
- **eject** — preserve a chunk's worktree for repair when a gate fails or conflict occurs.
