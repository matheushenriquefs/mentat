"""E2E: drive the gate-scoring stack end to end over real inputs.

Exercises ``lib.gates.score`` — the ADR-0003 veto>threshold scoring formula,
each per-reviewer scorer, the aggregate short-circuit, the veto-reviewer
registry check over a real ``.md`` directory, and the ``score_from_file``
JSON-routing entry point reading real files off ``tmp_path``. No mocking of
the module under test.

Imports go through the package (``from lib.gates import score``) rather than
``load_script`` because the module uses package-relative typing / dataclass
conventions and lives under the ``.agents`` tree that the repo's root
``conftest.py`` puts on ``sys.path``, mirroring ``test_code_gates_journey.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _score_mod():
    from lib.gates import score

    return score


# ── _score_gate: advisory vs blocking, below vs at/above threshold ───────────
# Targets score.py lines 36-41 (below flag, advisory advise-branch reason/empty,
# non-advisory block, non-advisory pass).


def test_score_gate_advisory_below_threshold_advises_with_reason():
    score = _score_mod()
    r = score._score_gate(0.50, 0.85, "smell score", advisory=True)
    assert r.verdict == "advise"
    assert r.score == 0.50
    assert "smell score" in r.reason
    assert "0.85" in r.reason


def test_score_gate_advisory_at_or_above_threshold_advises_empty_reason():
    score = _score_mod()
    r = score._score_gate(0.90, 0.85, "smell score", advisory=True)
    assert r.verdict == "advise"
    assert r.score == 0.90
    assert r.reason == ""


def test_score_gate_blocking_below_threshold_blocks_with_reason():
    score = _score_mod()
    r = score._score_gate(0.10, 0.88, "plan alignment")
    assert r.verdict == "block"
    assert r.score == 0.10
    assert "plan alignment" in r.reason
    assert "0.88" in r.reason


def test_score_gate_blocking_at_or_above_threshold_passes_empty_reason():
    score = _score_mod()
    r = score._score_gate(0.88, 0.88, "plan alignment")
    assert r.verdict == "pass"
    assert r.score == 0.88
    assert r.reason == ""


# ── score_plan: must_not_exist veto vs threshold path ────────────────────────
# Targets score.py lines 46-48.


def test_score_plan_must_not_exist_veto_uses_default_detail():
    score = _score_mod()
    r = score.score_plan({"veto": "must_not_exist"})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert r.reason == "must_not_exist veto"


def test_score_plan_must_not_exist_veto_uses_supplied_detail():
    score = _score_mod()
    r = score.score_plan({"veto": "must_not_exist", "veto_detail": "file X forbidden"})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert r.reason == "file X forbidden"


def test_score_plan_passes_at_threshold():
    score = _score_mod()
    r = score.score_plan({"score": 0.88})
    assert r.verdict == "pass"
    assert r.score == 0.88


def test_score_plan_blocks_below_threshold():
    score = _score_mod()
    r = score.score_plan({"score": 0.70})
    assert r.verdict == "block"
    assert "plan alignment" in r.reason


def test_score_plan_absent_score_defaults_to_zero_and_blocks():
    score = _score_mod()
    r = score.score_plan({})
    assert r.verdict == "block"
    assert r.score == 0.0


# ── score_test: fail-closed veto vs threshold path ───────────────────────────
# Targets score.py lines 57-60.


def test_score_test_no_veto_passes_at_threshold():
    score = _score_mod()
    r = score.score_test({"asserts_plan": 0.88})
    assert r.verdict == "pass"
    assert r.score == 0.88


def test_score_test_veto_clean_takes_threshold_path():
    score = _score_mod()
    r = score.score_test({"veto": "clean", "asserts_plan": 0.90})
    assert r.verdict == "pass"
    assert r.score == 0.90


def test_score_test_veto_clean_still_blocks_below_threshold():
    score = _score_mod()
    r = score.score_test({"veto": "clean", "asserts_plan": 0.10})
    assert r.verdict == "block"
    assert "test alignment" in r.reason


def test_score_test_arbitrary_veto_string_blocks():
    score = _score_mod()
    r = score.score_test({"veto": "hallucinated", "asserts_plan": 1.0})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "test veto" in r.reason
    assert "hallucinated" in r.reason


def test_score_test_empty_string_veto_blocks_fail_closed():
    score = _score_mod()
    r = score.score_test({"veto": "", "asserts_plan": 1.0})
    assert r.verdict == "block"
    assert r.score == 0.0


def test_score_test_zero_veto_blocks_fail_closed():
    score = _score_mod()
    r = score.score_test({"veto": 0, "asserts_plan": 1.0})
    assert r.verdict == "block"
    assert r.score == 0.0


# ── score_bug: three independent vetoes + clean pass ─────────────────────────
# Targets score.py lines 65-71.


def test_score_bug_blacklist_veto_blocks():
    score = _score_mod()
    r = score.score_bug({"blacklist": "used forbidden command"})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "blacklist" in r.reason
    assert "used forbidden command" in r.reason


def test_score_bug_max_sev_high_veto_blocks():
    score = _score_mod()
    r = score.score_bug({"blacklist": "clean", "max_sev": "high"})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "sev=high" in r.reason


def test_score_bug_severe_hallucination_veto_blocks():
    score = _score_mod()
    r = score.score_bug({"blacklist": "clean", "max_sev": "low", "hallucination": "severe"})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "hallucination" in r.reason


def test_score_bug_all_clean_passes():
    score = _score_mod()
    r = score.score_bug({"blacklist": "clean", "max_sev": "low", "hallucination": "none"})
    assert r.verdict == "pass"
    assert r.score == 1.0
    assert r.reason == ""


# ── score_smell: advisory only ───────────────────────────────────────────────
# Targets score.py line 76.


def test_score_smell_below_threshold_advises_with_reason():
    score = _score_mod()
    r = score.score_smell({"score": 0.50})
    assert r.verdict == "advise"
    assert r.score == 0.50
    assert "smell score" in r.reason


def test_score_smell_at_or_above_threshold_advises_empty_reason():
    score = _score_mod()
    r = score.score_smell({"score": 0.90})
    assert r.verdict == "advise"
    assert r.score == 0.90
    assert r.reason == ""


def test_score_smell_absent_score_defaults_to_zero_and_advises_below_threshold():
    score = _score_mod()
    r = score.score_smell({})
    assert r.verdict == "advise"
    assert r.score == 0.0
    assert "0.00" in r.reason


# ── score_rules: violations veto vs pass ─────────────────────────────────────
# Targets score.py lines 81-84.


def test_score_rules_with_violations_blocks_with_count():
    score = _score_mod()
    r = score.score_rules({"violations": ["a", "b", "c"]})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "3 violation(s)" in r.reason


def test_score_rules_empty_violations_passes():
    score = _score_mod()
    r = score.score_rules({"violations": []})
    assert r.verdict == "pass"
    assert r.score == 1.0


def test_score_rules_absent_violations_passes():
    score = _score_mod()
    r = score.score_rules({})
    assert r.verdict == "pass"
    assert r.score == 1.0


# ── score_context: findings veto vs pass ─────────────────────────────────────
# Targets score.py lines 89-92.


def test_score_context_with_findings_blocks_with_count():
    score = _score_mod()
    r = score.score_context({"findings": ["residue-1", "residue-2"]})
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "2 residue finding(s)" in r.reason


def test_score_context_empty_findings_passes():
    score = _score_mod()
    r = score.score_context({"findings": []})
    assert r.verdict == "pass"
    assert r.score == 1.0


def test_score_context_absent_findings_passes():
    score = _score_mod()
    r = score.score_context({})
    assert r.verdict == "pass"
    assert r.score == 1.0


# ── aggregate: first block wins, advisory join, all-pass, empty ──────────────
# Targets score.py lines 97-104.


def test_aggregate_first_block_wins():
    score = _score_mod()
    passing = score.GateResult("pass", 1.0, "")
    blocker = score.GateResult("block", 0.0, "the blocker")
    trailing = score.GateResult("pass", 1.0, "")
    r = score.aggregate([passing, blocker, trailing])
    assert r.verdict == "block"
    assert r.reason == "the blocker"


def test_aggregate_no_blocks_joins_advisory_reasons_filtering_empty():
    score = _score_mod()
    advise_with = score.GateResult("advise", 0.5, "smell score 0.50 < 0.85")
    advise_empty = score.GateResult("advise", 0.9, "")
    passing = score.GateResult("pass", 1.0, "")
    r = score.aggregate([advise_with, advise_empty, passing])
    assert r.verdict == "advise"
    # Empty advisory reason filtered out of the join; score taken from first advise.
    assert r.reason == "smell score 0.50 < 0.85"
    assert r.score == 0.5


def test_aggregate_advisory_all_empty_reasons_falls_back_to_advisory():
    score = _score_mod()
    a1 = score.GateResult("advise", 0.9, "")
    a2 = score.GateResult("advise", 1.0, "")
    r = score.aggregate([a1, a2])
    assert r.verdict == "advise"
    assert r.reason == "advisory"


def test_aggregate_all_pass_returns_clean():
    score = _score_mod()
    r = score.aggregate([score.GateResult("pass", 1.0, ""), score.GateResult("pass", 1.0, "")])
    assert r.verdict == "pass"
    assert r.score == 1.0
    assert r.reason == "clean"


def test_aggregate_empty_list_returns_clean():
    score = _score_mod()
    r = score.aggregate([])
    assert r.verdict == "pass"
    assert r.score == 1.0
    assert r.reason == "clean"


# ── VETO_KEYWORDS / missing_veto_reviewers over a real .md directory ─────────
# Targets score.py lines 110, 119-124.


def test_missing_veto_reviewers_returns_sorted_missing_only(tmp_path: Path):
    score = _score_mod()
    agents = tmp_path / "agents"
    agents.mkdir()
    # Register only some of the required veto reviewers as real .md files.
    (agents / "mentat-plan-reviewer.md").write_text("plan reviewer\n")
    (agents / "mentat-bug-reviewer.md").write_text("bug reviewer\n")
    # A non-veto reviewer present but irrelevant to the check.
    (agents / "mentat-smell-reviewer.md").write_text("smell reviewer\n")

    missing = score.missing_veto_reviewers(agents)

    # Every VETO_KEYWORDS entry without a matching .md, sorted, and nothing else.
    assert missing == ["mentat-context-reviewer", "mentat-rules-reviewer", "mentat-test-reviewer"]
    assert missing == sorted(missing)


def test_missing_veto_reviewers_all_present_returns_empty(tmp_path: Path):
    score = _score_mod()
    agents = tmp_path / "agents"
    agents.mkdir()
    for kw in score.VETO_KEYWORDS:
        (agents / f"mentat-{kw}-reviewer.md").write_text(f"{kw} reviewer\n")

    assert score.missing_veto_reviewers(agents) == []


# ── score_from_file: JSON routing by reviewer key and stem fallback ──────────
# Targets score.py lines 129-143.


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_score_from_file_routes_plan(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-plan-reviewer", "score": 0.95})
    r = score.score_from_file(f)
    assert r.verdict == "pass"
    assert r.score == 0.95


def test_score_from_file_routes_test(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-test-reviewer", "asserts_plan": 0.95})
    r = score.score_from_file(f)
    assert r.verdict == "pass"
    assert r.score == 0.95


def test_score_from_file_routes_bug(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-bug-reviewer", "blacklist": "clean"})
    r = score.score_from_file(f)
    assert r.verdict == "pass"
    assert r.score == 1.0


def test_score_from_file_routes_smell(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-smell-reviewer", "score": 0.40})
    r = score.score_from_file(f)
    assert r.verdict == "advise"
    assert "smell score" in r.reason


def test_score_from_file_routes_rules(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-rules-reviewer", "violations": ["v1"]})
    r = score.score_from_file(f)
    assert r.verdict == "block"
    assert "1 violation(s)" in r.reason


def test_score_from_file_routes_context(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-context-reviewer", "findings": ["f1"]})
    r = score.score_from_file(f)
    assert r.verdict == "block"
    assert "1 residue finding(s)" in r.reason


def test_score_from_file_unknown_reviewer_blocks(tmp_path: Path):
    score = _score_mod()
    f = _write_json(tmp_path / "out.json", {"reviewer": "mentat-weird-reviewer"})
    r = score.score_from_file(f)
    assert r.verdict == "block"
    assert r.score == 0.0
    assert "unknown reviewer" in r.reason
    assert "mentat-weird-reviewer" in r.reason


def test_score_from_file_falls_back_to_stem_when_reviewer_absent(tmp_path: Path):
    score = _score_mod()
    # No "reviewer" key → routing uses path.stem ("mentat-plan-reviewer").
    f = _write_json(tmp_path / "mentat-plan-reviewer.json", {"score": 0.95})
    r = score.score_from_file(f)
    assert r.verdict == "pass"
    assert r.score == 0.95
