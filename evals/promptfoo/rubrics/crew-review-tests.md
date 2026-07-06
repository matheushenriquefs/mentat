# mentat-test-reviewer llm-rubric judge

Score 0.0–1.0. Evaluate whether the reviewer output correctly:

1. **config_only_gate detection** — when all changed files are config-only (Taskfile, Dockerfile, .github/workflows, pyproject.toml, package.json, *.yaml outside src/), reviewer must emit `gate_type=config_only` and skip score/veto. Failing to detect this on a config-only diff = score ≤ 0.2.

2. **No false penalty** — reviewer does not penalize for missing test assertions on config-only changes.

3. **Source-file accuracy** — when diff contains source files, reviewer correctly scores test faithfulness against plan behaviors.

4. **Format** — config-only: `gate_type=config_only  score=N/A  veto=N/A`. Source: `PASS | FAIL  asserts_plan=<x>  veto=<clean|tripped:reason>`.

Score 1.0 = all four correct.
