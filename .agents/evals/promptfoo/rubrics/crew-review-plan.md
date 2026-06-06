# crew-review-plan llm-rubric judge

Score 0.0–1.0. Evaluate whether the reviewer output correctly:

1. **must_not_exist veto** — when plan contains drop/remove/replace/must-not lines, and diff retains those entities, reviewer must emit `VETO must_not_exist` with file:line. Missing this veto when entities are present = score ≤ 0.3.

2. **Recall accuracy** — reviewer correctly identifies which planned items are present vs absent from diff.

3. **No inflation** — reviewer does not invent missing items or false vetoes when diff is compliant.

4. **Format** — output follows `PASS | FAIL  score=<x>` with ≤3 lines of evidence.

Score 1.0 = all four correct. Penalize proportionally for each miss.
