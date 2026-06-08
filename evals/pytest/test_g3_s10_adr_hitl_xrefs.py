"""G3-S10: ADR-0003 + ADR-0006 cross-reference HITL three-way axis distinction.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S10):
  - Add cross-reference: HITL exit code from S3 is distinct from
    reward-hacking blacklist (ADR-0006) and from scored-review veto
    (ADR-0003). Document the three-way distinction so future reviewers
    do not collapse them.
  - Verify: ADR-0006 explicitly names the HITL code as not-a-blacklist-hit.
    ADR-0003 lists HITL as a fourth eject reason alongside score-veto /
    not-ff / rebase-conflict.

Three orthogonal mechanisms (ADR-0010 §"Axis discipline"):
  - HITL                       — exit 42 + `hitl-ambiguity` audit reason
  - Reward-hacking blacklist   — score 0.0 veto (ADR-0006 + ADR-0003 §blacklist)
  - Scored-review veto         — score < 0.88 (ADR-0003)

This test locks the cross-ref text so removing or renaming any of the
three labels in either ADR breaks the gate. S10 also requires the four
eject-reason inventory in ADR-0003 to include HITL — covering all four
verdicts that mentat-land-queue emits per ADR-0011.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / ".agents" / "docs" / "adr"
ADR_0003 = ADR_DIR / "0003-scored-review-gate.md"
ADR_0006 = ADR_DIR / "0006-soft-readonly-test-enforcement.md"
ADR_0010 = ADR_DIR / "0010-hitl-routing.md"

HITL_REASON = "hitl-ambiguity"
HITL_EXIT = "42"
EJECT_REASONS = ("rebase-conflict", "gate-fail", "not-ff", HITL_REASON)


# -- File-existence preconditions --------------------------------------------


def test_adr_0003_file_exists():
    assert ADR_0003.is_file(), f"ADR-0003 missing: {ADR_0003}"


def test_adr_0006_file_exists():
    """Plan refers to ADR-0006 as `0006-soft-readonly-tests.md`; the actual
    file is `0006-soft-readonly-test-enforcement.md`. Lock the real path."""
    assert ADR_0006.is_file(), f"ADR-0006 missing: {ADR_0006}"


def test_adr_0010_file_exists():
    assert ADR_0010.is_file(), f"ADR-0010 (HITL routing) missing: {ADR_0010}"


# -- ADR-0003: HITL named as a fourth eject reason ---------------------------


def test_adr_0003_references_hitl_ambiguity():
    """ADR-0003 must name the HITL reason — that's the cross-link to ADR-0010.
    Without this anchor a reviewer reading ADR-0003 cannot tell that HITL is
    a distinct axis."""
    text = ADR_0003.read_text()
    assert HITL_REASON in text, (
        f"ADR-0003 must reference {HITL_REASON!r} (cross-ref to ADR-0010)"
    )


def test_adr_0003_references_adr_0010():
    """Explicit ADR-0010 citation — a textual back-link operators can follow.
    Mere mention of `hitl-ambiguity` is not enough; the canonical contract
    lives in ADR-0010 and must be named."""
    text = ADR_0003.read_text()
    assert re.search(r"ADR[-\s]?0010|0010-hitl-routing", text), (
        "ADR-0003 must cite ADR-0010 (canonical HITL contract)"
    )


def test_adr_0003_lists_four_eject_reasons():
    """Plan S10 verify: ADR-0003 lists HITL as a fourth eject reason
    alongside score-veto / not-ff / rebase-conflict. All four labels from
    mentat-land-queue's verdict inventory must appear in the doc — the
    four-way map is the whole point of the slice."""
    text = ADR_0003.read_text()
    for reason in EJECT_REASONS:
        assert reason in text, (
            f"ADR-0003 must list eject reason {reason!r} — full inventory: "
            f"{EJECT_REASONS}"
        )


def test_adr_0003_distinguishes_hitl_from_blacklist():
    """The three-way distinction must be in the prose, not just the label
    set. Anchor: somewhere in ADR-0003 the words `hitl` and `blacklist` (or
    `reward-hacking`) must co-occur within a short window, asserting they
    are NOT the same thing — otherwise a future reviewer can read the doc
    and collapse them. Window = 400 chars (typical paragraph)."""
    text = ADR_0003.read_text().lower()
    for match in re.finditer(r"hitl", text):
        window = text[max(0, match.start() - 200): match.end() + 200]
        if "blacklist" in window or "reward-hack" in window:
            return
    raise AssertionError(
        "ADR-0003 must co-locate `hitl` with `blacklist` or `reward-hack` "
        "(within ±200 chars) to assert the axis distinction explicitly"
    )


def test_adr_0003_distinguishes_hitl_from_scored_veto():
    """Same anchor pattern: HITL must be co-located with the scored-review
    veto language so the doc names all three axes near each other."""
    text = ADR_0003.read_text().lower()
    for match in re.finditer(r"hitl", text):
        window = text[max(0, match.start() - 200): match.end() + 200]
        if "scored" in window or "threshold" in window or "veto" in window:
            return
    raise AssertionError(
        "ADR-0003 must co-locate `hitl` with `scored` / `threshold` / `veto` "
        "(within ±200 chars) to assert the axis distinction"
    )


# -- ADR-0006: HITL named as NOT a blacklist hit -----------------------------


def test_adr_0006_references_hitl_ambiguity():
    """ADR-0006 must name the HITL reason. Plan verify: ADR-0006 names HITL
    code as not-a-blacklist-hit — that requires naming it in the first place."""
    text = ADR_0006.read_text()
    assert HITL_REASON in text, (
        f"ADR-0006 must reference {HITL_REASON!r} to anchor the not-blacklist claim"
    )


def test_adr_0006_references_adr_0010():
    """Back-link to the canonical HITL contract."""
    text = ADR_0006.read_text()
    assert re.search(r"ADR[-\s]?0010|0010-hitl-routing", text), (
        "ADR-0006 must cite ADR-0010 (canonical HITL contract)"
    )


def test_adr_0006_says_hitl_is_not_a_blacklist_hit():
    """Plan S10 verify (verbatim): 'ADR-0006 explicitly names the HITL code
    as not-a-blacklist-hit.' The negation must be explicit — not implied by
    table headers. Acceptable phrasings: 'not a blacklist hit',
    'not a blacklist veto', 'HITL is distinct from blacklist', etc."""
    text = ADR_0006.read_text().lower()
    patterns = [
        r"hitl[^.]{0,200}not\s+a?\s*blacklist",
        r"not\s+a?\s*blacklist[^.]{0,200}hitl",
        r"hitl[^.]{0,200}distinct\s+from[^.]{0,80}blacklist",
        r"blacklist[^.]{0,200}distinct\s+from[^.]{0,80}hitl",
        r"hitl[^.]{0,200}≠[^.]{0,80}blacklist",
        r"blacklist[^.]{0,200}≠[^.]{0,80}hitl",
    ]
    for pat in patterns:
        if re.search(pat, text, re.DOTALL):
            return
    raise AssertionError(
        "ADR-0006 must explicitly state HITL is NOT a blacklist hit — "
        f"none of these patterns matched: {patterns}"
    )


def test_adr_0006_references_hitl_exit_code():
    """Plan verify: 'names the HITL code as not-a-blacklist-hit'. The exit
    code 42 must be named — the code IS the HITL signature at the OS level
    and is what disambiguates HITL from a blacklist score of 0.0."""
    text = ADR_0006.read_text()
    assert HITL_EXIT in text, (
        f"ADR-0006 must reference HITL exit code {HITL_EXIT} per plan verify"
    )


# -- Three-way axis label inventory ------------------------------------------


def test_adr_0003_inventories_three_axes():
    """The three-way axis distinction is the load-bearing claim of S10.
    ADR-0003 must name all three:
      1. HITL (or hitl-ambiguity)
      2. blacklist (reward-hacking) — already there as part of the gate
      3. scored-review (threshold / Prompt Alignment / Faithfulness)
    """
    text = ADR_0003.read_text().lower()
    assert "hitl" in text, "ADR-0003 missing axis 1: HITL"
    assert "blacklist" in text, "ADR-0003 missing axis 2: blacklist"
    assert any(k in text for k in ("threshold", "scored", "alignment")), (
        "ADR-0003 missing axis 3: scored-review veto"
    )


def test_adr_0006_inventories_three_axes():
    """ADR-0006 too — the cross-reference must be reciprocal. A reader
    landing in ADR-0006 must see the same three-axis map."""
    text = ADR_0006.read_text().lower()
    assert "hitl" in text, "ADR-0006 missing axis 1: HITL"
    assert "blacklist" in text, "ADR-0006 missing axis 2: blacklist"
    assert any(k in text for k in ("scored", "threshold", "alignment")), (
        "ADR-0006 missing axis 3: scored-review veto"
    )


# -- Reciprocal cross-references ---------------------------------------------


def test_adr_0010_already_references_g3_s10():
    """Sanity: ADR-0010 (the canonical HITL doc) already names the S10
    amendment. Drift guard: if a future edit removes the back-reference
    from ADR-0010, this test fails and forces it to be re-added."""
    text = ADR_0010.read_text()
    assert "G3-S10" in text or "g3-s10" in text.lower(), (
        "ADR-0010 must reference G3-S10 (this slice) — drift guard"
    )


def test_adr_0010_references_both_target_adrs():
    """ADR-0010's three-way axis table cites ADR-0003 and ADR-0006 as the
    other two axes. Lock that pair so the canonical doc stays anchored."""
    text = ADR_0010.read_text()
    assert "ADR-0003" in text, "ADR-0010 must cite ADR-0003 (scored-review axis)"
    assert "ADR-0006" in text, "ADR-0010 must cite ADR-0006 (blacklist axis)"


# -- Forbidden collapse: ADR-0003 must not equate HITL with implement-fail ---


def test_adr_0003_does_not_collapse_hitl_into_implement_fail():
    """ADR-0010 §3 + plan S8 already forbid collapsing HITL into
    implement-fail. ADR-0003, as the gate-defining doc, must not undo that
    by treating HITL and implement-fail as equivalent eject buckets."""
    text = ADR_0003.read_text()
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "implement-fail" in line and HITL_REASON in line:
            assert "not" in line.lower() or "distinct" in line.lower() or "≠" in line, (
                f"ADR-0003 line co-locates hitl-ambiguity and implement-fail "
                f"without negation: {line!r}"
            )
