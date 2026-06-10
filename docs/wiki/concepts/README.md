# Concepts

Core vocabulary (ADR 0005 — ubiquitous lexicon).

| Term | Definition |
|---|---|
| **slice** | A planned unit of work cut from a plan file |
| **chunk** | A running execution of a slice |
| **batch** | All chunks in a single orchestrate run |
| **holding branch** | Shared branch chunks land on serially after green gate |
| **worktree** | Isolated git worktree; one per chunk |
| **land gate** | Review pass (plan + test + bug + smell + context reviewers) before merge |
| **HITL** | Human-in-the-loop — pause for user confirmation before proceeding |
| **AFK** | Can proceed without user; no confirmation pause |

See `docs/adr/` for architecture decisions.
