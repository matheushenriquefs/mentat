"""score.py veto scorers + routing — rules- and context-reviewer (ADR-0012 v2)."""

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
