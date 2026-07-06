# adr-cross-ref rubric

Score 0.0–1.0. Evaluate whether the response correctly cross-references ADRs.

1. **Correct ADR** — response cites ADR 0002 (Holding branch over merge; in-container ff-only rebase). Citing only ADR 0004 or unrelated ADRs without 0002 = score ≤ 0.5.
2. **Rule stated accurately** — holding branch carries no commits of its own; all lands are ff-only (`merge --ff-only`); no `git commit` fires; no host pre-commit fires.
3. **No invented ADR numbers** — response does not cite ADR numbers outside the 0001–0018 index.

Score 1.0 = all three correct. Penalize proportionally.
