"""Gate scoring — parses subagent JSON verdicts, applies ADR-0003 formula."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Verdict = Literal["pass", "block", "advise"]

# ADR-0003 thresholds
PLAN_THRESHOLD = 0.88
TEST_THRESHOLD = 0.88
SMELL_THRESHOLD = 0.85


@dataclass(frozen=True)
class GateResult:
    verdict: Verdict
    score: float
    reason: str


def score_plan(raw: dict) -> GateResult:
    """Plan alignment ≥ PLAN_THRESHOLD → pass; must_not_exist veto overrides."""
    if raw.get("veto") == "must_not_exist":
        return GateResult("block", 0.0, raw.get("veto_detail", "must_not_exist veto"))
    score = float(raw.get("score", 0.0))
    if score >= PLAN_THRESHOLD:
        return GateResult("pass", score, "")
    return GateResult("block", score, f"plan alignment {score:.2f} < {PLAN_THRESHOLD}")


def score_test(raw: dict) -> GateResult:
    """Test faithfulness ≥ TEST_THRESHOLD → pass; deterministic veto overrides."""
    veto = raw.get("veto", "clean")
    if veto and veto != "clean":
        return GateResult("block", 0.0, f"test veto: {veto}")
    score = float(raw.get("asserts_plan", 0.0))
    if score >= TEST_THRESHOLD:
        return GateResult("pass", score, "")
    return GateResult("block", score, f"test alignment {score:.2f} < {TEST_THRESHOLD}")


def score_bug(raw: dict) -> GateResult:
    """Trajectory blacklist, latent-bug sev≥high, and severe hallucination are hard vetoes."""
    if raw.get("blacklist") not in (None, "clean"):
        return GateResult("block", 0.0, f"blacklist: {raw['blacklist']}")
    if raw.get("max_sev") == "high":
        return GateResult("block", 0.0, "latent bug sev=high")
    if raw.get("hallucination") == "severe":
        return GateResult("block", 0.0, "hallucination: severe unplanned behavior")
    return GateResult("pass", 1.0, "")


def score_smell(raw: dict) -> GateResult:
    """Smell review is advisory only — never blocks, never vetoes."""
    score = float(raw.get("score", 1.0))
    if score < SMELL_THRESHOLD:
        return GateResult("advise", score, f"smell score {score:.2f} < {SMELL_THRESHOLD}")
    return GateResult("advise", score, "")


def aggregate(results: list[GateResult]) -> GateResult:
    """Veto > threshold; never average. First block wins."""
    for r in results:
        if r.verdict == "block":
            return r
    advise = [r for r in results if r.verdict == "advise"]
    if advise:
        return advise[0]
    return GateResult("pass", 1.0, "")


def score_from_file(path: Path) -> GateResult:
    """Load subagent JSON output file and route to the correct scorer."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    reviewer = raw.get("reviewer", path.stem)
    if "plan" in reviewer:
        return score_plan(raw)
    if "test" in reviewer:
        return score_test(raw)
    if "bug" in reviewer:
        return score_bug(raw)
    if "smell" in reviewer:
        return score_smell(raw)
    return GateResult("pass", 1.0, f"unknown reviewer {reviewer!r}")
