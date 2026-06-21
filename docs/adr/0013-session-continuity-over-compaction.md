# ADR 0013: Session continuity over compaction

Status: Proposed (F4 spike complete — go/no-go: GO)
Date: 2026-06-20

## Context

Long-running AFK chunks can hit the harness context window before all slices are
green. Each harness handles compaction differently: claude-code compacts
in-process; cursor-agent has its own mechanism. Neither is blockable from the
outside. Mentat needs a harness-agnostic way to checkpoint at a slice boundary,
write a session summary, and spawn a fresh seeded session so the chunk continues
without losing critical context.

## F4 spike findings

Two capabilities proved on both adapters:

**1. Usage reporting.**
- `claude-code`: `--output-format stream-json` emits a `{"type": "result", "usage": {...}}` event
  as the last line. `claude_code._parse_usage()` reads `input_tokens + output_tokens` from the
  captured session log. Confirmed: `Result.usage_tokens` is an `int` after a streamed run.
- `cursor-agent`: no CLI usage-reporting equivalent found. `cursor.Result.usage_tokens` returns
  `None`. Mentat's cumulative-count fallback (count slices completed) handles this case.

**2. Seeded fresh spawn.**
Both adapters accept `seed_summary: str | None` in `invoke()`. When set, the summary is
prepended to the prompt before the plan body. The adapter spawns a brand-new session (no
`--resume` / `--continue`) — the harness's own compaction is irrelevant because this is a
fresh session seeded with the summary, not a resumed one. Proved: the summary text arrives
in the prompt stream on both adapters (verified via fake-run test).

**Contract confirmed for F5:**
- `Result.usage_tokens: int | None` — `int` when stream-json log is available (claude-code),
  `None` otherwise (cursor or no session_log).
- `invoke(..., seed_summary: str | None = None)` — both adapters, zero breaking change.
- Mentat owns checkpoint logic: threshold check → write summary → call `invoke` with
  `seed_summary=<summary_text>` on a fresh slug. Adapter agnostic.
- Cumulative-count fallback: if `usage_tokens is None`, mentat counts completed slices
  and uses a configurable slice-count threshold instead of token threshold.

## Decision (pending F5 implementation)

Mentat owns the checkpoint→summary→respawn loop. Harness adapters report usage and accept
a seed summary. The loop runs between slices (in `implement.py`) and between chunks
(in `fan_out.py`). Threshold config lives in `~/.mentat/config.toml`.

## Consequences

`implement.py` calls `invoke()` with `seed_summary` on respawn. `fan_out.py` does the same
between chunks. No new abstract methods on `HarnessProvider` Protocol — both adapters already
implement the extended `invoke()` signature. F5 wires the checkpoint loop.
