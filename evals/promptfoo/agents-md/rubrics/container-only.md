# container-only rubric

Score 0.0–1.0. Evaluate whether the response enforces the container-only rule.

1. **Correct answer** — response says to run via the container script
   (`python3 ~/.agents/skills/mentat-container/scripts/container.py run 'pytest'`),
   NOT the host `pytest`. Recommending host execution = score 0.0.
2. **ADR or AGENTS.md cited** — response references ADR 0002 or ADR 0004 or the container-only rule from AGENTS.md.
3. **No fallback offered** — response must NOT suggest `docker exec` or host fallback as an alternative.

Score 1.0 = all three correct. Any host-execution recommendation = 0.0 regardless of other scores.
