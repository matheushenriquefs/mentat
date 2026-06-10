# ADR 0001: Sub-agent delegation — cavecrew vs vanilla, procedure not persona

Status: Accepted (locked)
Date: 2026-05-31
Amended: 2026-06-09 (Python-era invocations; mentat-researcher stays `.md` agent)

## Context

Commands fan out into sub-agents. Two decisions needed locking: they shape every
command and the global AGENTS.md and are hard to reverse without context.

## Decision

**Cavecrew default, vanilla on demand.** Spawn cavecrew variants (`cavecrew-investigator`,
`cavecrew-builder`, `cavecrew-reviewer`) by default; spawn vanilla (`Explore`,
`Code Reviewer`) only when prose/rationale is the actual goal.

Cross-skill subprocess invocation uses full Python path:
```
subprocess.run(["python3", str(skill_root / "mentat-log/scripts/log.py"), "emit", ...])
```

**`mentat-researcher` is procedure, not persona.** Operating loop + output contract +
primary-source gate. No "you are an expert researcher" preamble. Persona prefixes
damage recall-dependent tasks (PRISM arXiv 2603.18507; Wharton 2512.05858).

**No hardcoded model.** The body says "cheapest capable model the harness offers."
`model` frontmatter omitted; each harness picks. Vendor-coupled aliases (`haiku`,
`sonnet`) not portable across VS Code / JetBrains caps.

The delegation rule lives in global AGENTS.md, not command bodies.

## Consequences

Docs stay TLDR. "Why we rejected X" lives here. AGENTS.md stays one imperative
paragraph. This ADR is index-only in AGENTS.md (title only; body on demand).
