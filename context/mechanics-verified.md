# Mechanics Verified

Claims from `~/Downloads/mentat-handoff.md` §2 + §7, ground-truthed against ADRs and source.

| Handoff claim | ADR / code citation | Verdict |
|---|---|---|
| "parallel agents on the order of ~3" | `bin/to-orchestrate:49` — `[ "$#" -le 3 ] \|\| { echo "to-orchestrate: max 3 parallel chunks …" }` | **Confirmed.** Hard cap is exactly 3, enforced at invocation. |
| "merge queue re-gates each one" | `bin/to-orchestrate:19` — "re-gate … this land pass is a merge queue"; `:127` — "re-gate catches semantic breakage a sibling's land introduced"; ADR 0004 §Decision | **Confirmed.** Each chunk rebases onto current holding tip, then re-gates before ff-only land. Eject on red (`:167`). |
| "holding branch carries no commits of its own — everything fast-forwards" | ADR 0002:20-25 — "no commits of its own … fast-forward … no `git commit` fires, so no host-side pre-commit fires" | **Confirmed.** Holding branch is a moving pointer only; each land is a `merge --ff-only`. |
| "anti-cheat mechanism" | ADR 0006 §Decision — "enforcement is the agent's, in two layers, both agnostic: implement-contract + trajectory blacklist"; ADR 0003 §Decision — blacklist of forbidden moves → 0.0 veto | **Confirmed (nuanced).** The preventive layer is the implement-contract (agent-held, not a kernel mount — ADR 0006 §The trap we rejected). The detective layer is the trajectory blacklist in `crew-review-bugs` (ADR 0003). Both are agnostic by construction (ADR 0004). |
| "AFK operator goal" | ADR 0004:9 — "tagged AFK (gate clears unattended)"; ADR 0003 §Context — "An orchestrator is only as autonomous as its gate is trustworthy" | **Confirmed.** AFK = gate clears without human input. HITL slices stall until reviewed. The scored gate (ADR 0003) + veto posture is the mechanism that makes AFK trustworthy. |

## Open confirmations

None — all five claims resolved.
