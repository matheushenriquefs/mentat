"""score.py veto scorers + routing — rules- and context-reviewer (ADR-0012 v2).

Slice 1 (G3): score_test veto fail-closed — falsy veto must block.
Slice 2 (G4): aggregate preserves all advisory reasons; clean pass has marker.
"""

from __future__ import annotations

import json
from pathlib import Path


def _score_mod():
    from lib.gates import score

    return score


def test_score_rules_blocks_when_violations_present():
    score = _score_mod()
    result = score.score_rules({"reviewer": "mentat-rules-reviewer", "violations": [{"rule": "python"}]})
    assert result.verdict == "block"


def test_score_rules_passes_when_clean():
    score = _score_mod()
    result = score.score_rules({"reviewer": "mentat-rules-reviewer", "violations": []})
    assert result.verdict == "pass"


def test_score_context_blocks_when_findings_present():
    score = _score_mod()
    result = score.score_context({"reviewer": "mentat-context-reviewer", "findings": [{"reason": "phase-residue"}]})
    assert result.verdict == "block"


def test_score_context_passes_when_clean():
    score = _score_mod()
    result = score.score_context({"reviewer": "mentat-context-reviewer", "findings": []})
    assert result.verdict == "pass"


def test_aggregate_blocks_when_rules_violations_present():
    score = _score_mod()
    results = [
        score.GateResult("pass", 1.0, ""),
        score.score_rules({"violations": [{"rule": "python"}]}),
        score.score_context({"findings": []}),
    ]
    out = score.aggregate(results)
    assert out.verdict == "block"


def test_aggregate_blocks_when_context_findings_present():
    score = _score_mod()
    results = [
        score.GateResult("pass", 1.0, ""),
        score.score_rules({"violations": []}),
        score.score_context({"findings": [{"reason": "phase-residue"}]}),
    ]
    out = score.aggregate(results)
    assert out.verdict == "block"


def test_aggregate_block_wins_over_rules_veto():
    score = _score_mod()
    results = [
        score.score_rules({"violations": [{"rule": "python"}]}),
        score.GateResult("block", 0.0, "real veto"),
    ]
    out = score.aggregate(results)
    assert out.verdict == "block"


def test_score_rules_handles_explicit_null_violations():
    score = _score_mod()
    result = score.score_rules({"reviewer": "mentat-rules-reviewer", "violations": None})
    assert result.verdict == "pass"


def test_score_context_handles_explicit_null_findings():
    score = _score_mod()
    result = score.score_context({"reviewer": "mentat-context-reviewer", "findings": None})
    assert result.verdict == "pass"


def test_score_from_file_routes_rules_reviewer(tmp_path: Path):
    score = _score_mod()
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"reviewer": "mentat-rules-reviewer", "violations": []}))
    assert score.score_from_file(p).verdict == "pass"


def test_score_from_file_routes_context_reviewer(tmp_path: Path):
    score = _score_mod()
    p = tmp_path / "context.json"
    p.write_text(json.dumps({"reviewer": "mentat-context-reviewer", "findings": []}))
    assert score.score_from_file(p).verdict == "pass"


# ── Slice 1 (G3): score_test veto fail-closed ────────────────────────────────


def test_score_test_empty_string_veto_blocks():
    score = _score_mod()
    result = score.score_test({"veto": "", "asserts_plan": 0.99})
    assert result.verdict == "block"


def test_score_test_zero_veto_blocks():
    score = _score_mod()
    result = score.score_test({"veto": 0, "asserts_plan": 0.99})
    assert result.verdict == "block"


def test_score_test_false_veto_blocks():
    score = _score_mod()
    result = score.score_test({"veto": False, "asserts_plan": 0.99})
    assert result.verdict == "block"


def test_score_test_absent_veto_passes_on_high_score():
    score = _score_mod()
    result = score.score_test({"asserts_plan": 0.99})
    assert result.verdict == "pass"


def test_score_test_clean_veto_passes_on_high_score():
    score = _score_mod()
    result = score.score_test({"veto": "clean", "asserts_plan": 0.99})
    assert result.verdict == "pass"


# ── Slice 2 (G4): aggregate preserves all advisory reasons ──────────────────


def test_aggregate_advisory_joins_all_reasons():
    score = _score_mod()
    results = [
        score.GateResult("advise", 0.9, "smell-a"),
        score.GateResult("advise", 0.8, "smell-b"),
        score.GateResult("advise", 0.7, "smell-c"),
    ]
    out = score.aggregate(results)
    assert out.verdict == "advise"
    assert "smell-a" in out.reason
    assert "smell-b" in out.reason
    assert "smell-c" in out.reason


def test_aggregate_advisory_single_empty_reason_gets_fallback():
    score = _score_mod()
    results = [score.GateResult("advise", 1.0, "")]
    out = score.aggregate(results)
    assert out.verdict == "advise"
    assert out.reason  # non-empty fallback


def test_aggregate_clean_pass_has_nonempty_reason():
    score = _score_mod()
    results = [score.GateResult("pass", 1.0, "")]
    out = score.aggregate(results)
    assert out.verdict == "pass"
    assert out.reason  # "clean" marker, not ""
