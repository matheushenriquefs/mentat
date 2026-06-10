# Skill shape rubric — applies to all mentat-* SKILL.md files

Per docs/STYLE.md and ADR-0003:

## Frontmatter

- `name:` key present
- `description:` key present
- No `metadata:` or `version:` key
- No extra keys beyond `name` + `description`

## Voice class: Full Pocock skill

- LOC ≥ 75 and ≤ 120
- No banned headers: `## Toolchain discovery`, `## Atomic contract`, `## Invariants`
- No banned words: just, simply, really, basically, actually

## Voice class: Thin skill

- LOC ≤ 40
- Numbered action list delegates to Python script

## Crew agent (agents/ dir)

- LOC ≥ 60 and ≤ 100
- `tools:` frontmatter key present
- No standalone articles (a/an/the) in prose

## Verdict format

```
PASS | FAIL
<one line per violation: path:line: <rule>>
```
