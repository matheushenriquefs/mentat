---
name: mentat-skill
description: >
  Evaluate, shrink, or scaffold mentat skills.
  Use when you want to run promptfoo evals, propose a leaner SKILL.md, or create a new skill skeleton.
---

SKILL.md lifecycle workflows: functional + cognitive eval against promptfoo, propose a leaner SKILL.md guarded by a pass-rate + token-ratio gate, and scaffold a new skill directory from template with promptfoo wiring and live symlink.

## How to invoke

```
python3 ~/.agents/skills/mentat-skill/scripts/skill.py eval [<skill-name>]
python3 ~/.agents/skills/mentat-skill/scripts/skill.py shrink [<skill-name>]
python3 ~/.agents/skills/mentat-skill/scripts/skill.py scaffold <new-skill-name>
```

`eval` and `shrink` require `promptfoo` binary on PATH (`npm install -g promptfoo`).

## Eval flow

1. Functional pass: `python3 .agents/skills/<skill>/eval/run.py` (skill-specific harness; non-zero → abort).
2. Cognitive current: `npx promptfoo eval --output /tmp/<skill>-current.json --no-progress-bar`.
3. Cognitive main: extract `main`'s SKILL.md to a temp path, re-run promptfoo with `--prompts file:///tmp/<skill>-main.md`.
4. Report delta table:

   | Metric | main | current | Δ |
   |---|---|---|---|
   | pass rate | … | … | … |
   | prompt tokens | … | … | … |
   | $/run | … | … | … |

5. Include top 3 failing cases with judge reasoning + per-provider breakdown (does Haiku clear 0.88?).
6. Do not edit the skill — eval is read-only.

## Shrink flow

1. Identify the 3 highest-token sections in the current SKILL.md (examples, edge-case enumerations, redundant phrasing).
2. Rewrite each preserving intent in fewer tokens — same voice class, same LOC budget.
3. Run the eval flow above. Gate: `pass_rate ≥ 0.88 AND prompt_tokens ≤ 1.10 × main`.
4. Pass → commit via `mentat-git commit`, then `mentat-git rebase <holding-branch>`.
5. Fail → revert SKILL.md to HEAD and report which axis failed (pass-rate or token-ratio).

## Scaffold flow

1. Spawn `skill-creator` subagent to draft `.agents/skills/<new-skill-name>/SKILL.md`.
2. Copy `.agents/lib/templates/promptfooconfig.yaml` into the new skill dir.
3. Derive 10 diverse test inputs from the new SKILL.md and seed `promptfooconfig.yaml`.
4. Symlink the directory into `~/.claude/skills/<new-skill-name>` so the harness picks it up live.
5. Do not run evals — scaffolding and evaluation are separate invocations.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Shrink gate failed (pass-rate or token-ratio) |
| 64 | CLI arg parse error / unknown subcommand |
| 66 | Skill not found |
| 70 | Unhandled Python exception |
| 127 | `promptfoo` binary missing on PATH |

## Rules

- Eval is read-only — never mutates `SKILL.md`. Shrink is the only mutating subcommand.
- Shrink gate is veto-style: both axes must pass. No averaging across metrics.
- Scaffold never runs evals; users invoke `eval` separately after first commit.
- Symlink target is `~/.claude/skills/<name>` — Claude Code's skill discovery root.
- Promptfoo template lives at `.agents/lib/templates/promptfooconfig.yaml`; do not inline.
- Script body is stdlib-only; `npx promptfoo` is invoked via `subprocess`.

## Constraints

- `eval` and `shrink` require a `main` branch ref to extract baseline SKILL.md.
- Skill name must match a directory under `.agents/skills/`; `mentat-` prefix optional.
- Shrink rewrites must respect the skill's voice class LOC budget (see `docs/STYLE.md`).
- Token counts come from promptfoo's reported `prompt_tokens` per case — averaged across cases.
- All audit emissions route through `mentat-log emit` — never write JSONL directly.
