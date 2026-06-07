# delegation-routing rubric

Score 0.0–1.0. Evaluate whether the response correctly routes a code-location query.

1. **Correct subagent** — response recommends `cavecrew-investigator` (or equivalent read-only locator). Recommending a write-capable agent (`cavecrew-builder`) or vanilla `Explore` without cavecrew = score ≤ 0.4.
2. **Reason cited** — response explains why: token savings (~1/3) or "locate repo code" purpose.
3. **No hallucination** — response does not invent subagent names not present in AGENTS.md.

Score 1.0 = all three correct. Penalize proportionally for each miss.
