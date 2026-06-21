"""score.py advisory scorers + routing — rules- and context-reviewer (ADR-0012)."""

from __future__ import annotations

import json
from pathlib import Path


def _score_mod():
    from lib.gates import score

    return score


def test_score_rules_advises_never_blocks_when_violations_present():
    score = _score_mod()
    result = score.score_rules({"reviewer": "mentat-rules-reviewer", "violations": [{"rule": "python"}]})
    assert result.verdict == "advise"


def test_score_rules_advises_when_clean():
    score = _score_mod()
    result = score.score_rules({"reviewer": "mentat-rules-reviewer", "violations": []})
    assert result.verdict == "advise"


def test_score_context_advises_never_blocks_when_findings_present():
    score = _score_mod()
    result = score.score_context({"reviewer": "mentat-context-reviewer", "findings": [{"reason": "phase-residue"}]})
    assert result.verdict == "advise"


def test_aggregate_keeps_pass_when_only_advisories_present():
    score = _score_mod()
    results = [
        score.GateResult("pass", 1.0, ""),
        score.score_rules({"violations": [{"rule": "python"}]}),
        score.score_context({"findings": [{"reason": "phase-residue"}]}),
    ]
    out = score.aggregate(results)
    assert out.verdict == "advise"


def test_aggregate_block_still_wins_over_advisory():
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
    assert result.verdict == "advise"


def test_score_context_handles_explicit_null_findings():
    score = _score_mod()
    result = score.score_context({"reviewer": "mentat-context-reviewer", "findings": None})
    assert result.verdict == "advise"


def test_score_from_file_routes_rules_reviewer(tmp_path: Path):
    score = _score_mod()
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({"reviewer": "mentat-rules-reviewer", "violations": []}))
    assert score.score_from_file(p).verdict == "advise"


def test_score_from_file_routes_context_reviewer(tmp_path: Path):
    score = _score_mod()
    p = tmp_path / "context.json"
    p.write_text(json.dumps({"reviewer": "mentat-context-reviewer", "findings": []}))
    assert score.score_from_file(p).verdict == "advise"
