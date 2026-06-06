# ADR 0001: Sub-agent delegation — cavecrew vs vanilla, procedure vs persona

Status: Accepted (locked)
Date: 2026-05-31

## Context

Commands fan out into sub-agents. Two decisions needed locking because they're
hard to reverse (they shape every command and the global AGENTS.md), surprising
without context, and the result of real trade-offs we evaluated against primary
sources.

## Decision 1 — cavecrew default, vanilla on demand

Spawn cavecrew variants by default; spawn vanilla (`Explore`, `Code Reviewer`)
only when prose/rationale is the actual goal.

Rejected: "always cavecrew, never vanilla." cavecrew output is structured and
sometimes cryptic; when you want architecture commentary or alternatives, the
compression destroys the thing you asked for. The win is real but conditional —
across ~20 delegations in a session, compressed tool-results are the difference
between finishing and context exhaustion (cavecrew's own benchmark), but that's
a context-budget argument, not a quality one.

The delegation rule lives in global AGENTS.md, not command bodies, so it holds
across Claude Code / Codex / Cursor and changes in one place.

## Decision 2 — `/mentat-researcher` is procedure, not persona

`/mentat-researcher` is operating loop + output contract + primary-source gate. No
"you are an expert researcher" preamble.

Rejected: persona-based research agents. Primary sources are consistent that
role prefixes don't improve accuracy and actively damage recall-dependent tasks
(PRISM arXiv 2603.18507: persona prefixes activate instruction-following mode at
the expense of factual recall; Wharton 2512.05858; Zheng/Pei ACL 2024). Research
is recall-dependent, so a persona would hurt the one thing the agent is for.

## Decision 3 — no hardcoded model

`/mentat-researcher` omits the `model` frontmatter field; the body says "cheapest
capable model the harness offers."

Rejected: `model: haiku`. It's vendor-coupled (Anthropic alias) and not even
portable in meaning — VS Code/Copilot cap subagent model at the parent's cost
tier and silently fall back. Omitting the field lets each harness pick, which is
the harness-agnostic goal. `tools` is kept (it's the read-only guarantee and
inherits-all if omitted, which we don't want for a research agent).

## Consequences

Docs stay TLDR — the delegation rule is one imperative paragraph in AGENTS.md,
commands say nothing about which agent to spawn. The "why we rejected X"
reasoning lives here, not scattered as defensive prose across setup/skills/docs.
