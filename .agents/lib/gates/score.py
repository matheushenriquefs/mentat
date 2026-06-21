"""Gate scoring — parses subagent JSON verdicts, applies ADR-0003 formula."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Verdict = Literal["pass", "block", "advise"]

# ADR-0003 thresholds
PLAN_THRESHOLD = 0.88
TEST_THRESHOLD = 0.88
SMELL_THRESHOLD = 0.85

# An advisory verdict never gates, so its numeric score is informational only.
ADVISORY_SCORE = 1.0


@dataclass(frozen=True)
class GateResult:
    verdict: Verdict
    score: float
    reason: str


def _score_gate(
    score: float,
    threshold: float,
    label: str,
    *,
    advisory: bool = False,
) -> GateResult:
    """Threshold check. advisory=True always returns 'advise'; False blocks below threshold."""
    below = score < threshold
    if advisory:
        return GateResult("advise", score, f"{label} {score:.2f} < {threshold}" if below else "")
    if below:
        return GateResult("block", score, f"{label} {score:.2f} < {threshold}")
    return GateResult("pass", score, "")


def score_plan(raw: dict[str, Any]) -> GateResult:
    """Plan alignment ≥ PLAN_THRESHOLD → pass; must_not_exist veto overrides."""
    if raw.get("veto") == "must_not_exist":
        return GateResult("block", 0.0, raw.get("veto_detail", "must_not_exist veto"))
    return _score_gate(float(raw.get("score", 0.0)), PLAN_THRESHOLD, "plan alignment")


def score_test(raw: dict[str, Any]) -> GateResult:
    """Test faithfulness ≥ TEST_THRESHOLD → pass; deterministic veto overrides.

    Veto is fail-closed: only an absent key or the exact string "clean" is safe.
    Falsy values ("", 0, False) and any other value block.
    """
    veto = raw.get("veto")
    if veto is not None and veto != "clean":
        return GateResult("block", 0.0, f"test veto: {veto!r}")
    return _score_gate(float(raw.get("asserts_plan", 0.0)), TEST_THRESHOLD, "test alignment")


def score_bug(raw: dict[str, Any]) -> GateResult:
    """Trajectory blacklist, latent-bug sev≥high, and severe hallucination are hard vetoes."""
    if raw.get("blacklist") not in (None, "clean"):
        return GateResult("block", 0.0, f"blacklist: {raw['blacklist']}")
    if raw.get("max_sev") == "high":
        return GateResult("block", 0.0, "latent bug sev=high")
    if raw.get("hallucination") == "severe":
        return GateResult("block", 0.0, "hallucination: severe unplanned behavior")
    return GateResult("pass", 1.0, "")


def score_smell(raw: dict[str, Any]) -> GateResult:
    """Smell review is advisory only — never blocks, never vetoes."""
    return _score_gate(float(raw.get("score", 1.0)), SMELL_THRESHOLD, "smell score", advisory=True)


def score_rules(raw: dict[str, Any]) -> GateResult:
    """Code-rule conformance (ADR-0012). Veto — zero violations required (promoted 2026-06-21)."""
    violations: list[Any] = raw.get("violations") or []
    if violations:
        return GateResult("block", 0.0, f"rules: {len(violations)} violation(s)")
    return GateResult("pass", 1.0, "")


def score_context(raw: dict[str, Any]) -> GateResult:
    """Prose/prompt residue (ADR-0012). Veto — zero findings required (promoted 2026-06-21)."""
    findings: list[Any] = raw.get("findings") or []
    if findings:
        return GateResult("block", 0.0, f"context: {len(findings)} residue finding(s)")
    return GateResult("pass", 1.0, "")


def aggregate(results: list[GateResult]) -> GateResult:
    """Veto > threshold; never average. First block wins."""
    for r in results:
        if r.verdict == "block":
            return r
    advise = [r for r in results if r.verdict == "advise"]
    if advise:
        return advise[0]
    return GateResult("pass", 1.0, "")


# Routing keywords from score_from_file that map to blocking (veto) scorers.
# "smell" is excluded — its scorer is advisory-only. Extend here when promoting a
# new scorer to veto so preflight_veto_reviewers auto-extends the check.
VETO_KEYWORDS: frozenset[str] = frozenset({"plan", "test", "bug", "rules", "context"})


def missing_veto_reviewers(agents_dir: Path) -> list[str]:
    """Return names of veto reviewers not registered as .md files in agents_dir.

    Derives the required set from VETO_KEYWORDS, matching score_from_file's routing,
    so adding a keyword to VETO_KEYWORDS auto-extends the check.
    """
    missing: list[str] = []
    for kw in sorted(VETO_KEYWORDS):
        name = f"mentat-{kw}-reviewer"
        if not (agents_dir / f"{name}.md").exists():
            missing.append(name)
    return missing


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
    if "rules" in reviewer:
        return score_rules(raw)
    if "context" in reviewer:
        return score_context(raw)
    return GateResult("pass", 1.0, f"unknown reviewer {reviewer!r}")
