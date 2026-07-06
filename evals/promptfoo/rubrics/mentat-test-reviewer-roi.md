# mentat-test-reviewer ROI llm-rubric judge

Score 0.0–1.0. The reviewer output is a JSON `ReviewVerdict`
(`asserts_plan`, `veto`, `findings[]`, `surviving_mutants`). Evaluate whether it
applies the ROI lens correctly:

1. **Flags padding** — assertion-free tests, getter/attribute-only tests, and
   "covers-but-checks-nothing" tests appear in `findings[]` with a `file:line` and a
   reason naming the failure (no regression signal / worthless). Missing an obvious
   padding test = score ≤ 0.3.

2. **Passes a lean behavior suite** — a suite that asserts public-API behavior, edge
   cases, and error paths scores high `asserts_plan` (≥ 0.88) with `veto: "clean"` and
   an empty or near-empty `findings[]`. Penalizing a genuinely valuable test = score ≤ 0.3.

3. **Rejects 100%-coverage-but-assertion-free** — a suite that reaches full line
   coverage while asserting nothing real is caught: `findings[]` is non-empty and the
   reviewer does not reward it just for the coverage. Passing it clean = score ≤ 0.2.

4. **Well-formed** — output is a single JSON object parseable without regex; no prose
   wrapper; `veto` is exactly `"clean"` or `"tripped: <reason>"`.

Score 1.0 = all four correct.
