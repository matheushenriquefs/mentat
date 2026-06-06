# mentat-bug-reviewer llm-rubric judge

Score 0.0–1.0. Evaluate whether the reviewer output correctly:

1. **design_drift separation** — MEDIUM findings that are scope/design drift (plan excluded them, not runtime bugs) must appear in `design_drift[]`, not `findings[]`. Mixing them = score ≤ 0.4.

2. **No veto inflation** — design_drift items must NOT trigger a veto. Only sev≥high real bugs veto. Vetoing on drift = score 0.0.

3. **Correct HIGH/MEDIUM split** — real bugs with sev=high remain in `findings[]` and trigger veto correctly.

4. **Format** — `PASS | FAIL  blacklist=...  max_sev=...  hallucination=...` with optional `design_drift: [...]` line.

Score 1.0 = all four correct.
