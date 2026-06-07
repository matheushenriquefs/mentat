# adr-citation rubric

Score 0.0–1.0. Evaluate whether the response correctly cites ADRs for the container-only rule.

1. **Correct ADR(s) cited** — response cites ADR 0002 and/or ADR 0004. Citing only ADR 0001 or unrelated ADRs = score ≤ 0.4.
2. **Reason accurate** — response explains: host has no pinned interpreter; host commits fire pre-commit without container tools; OR parallel-slicing requires Docker (ADR 0004).
3. **No invented ADRs** — response does not fabricate ADR numbers not in the index.

Score 1.0 = all three correct. Penalize proportionally.
