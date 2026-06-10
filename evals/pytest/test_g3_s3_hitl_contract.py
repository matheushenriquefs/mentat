"""G3-S3: AFK seam contract — ADR-0010 codifies the four-tuple.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S3):
  - Signal: env var `MENTAT_INTERACTIVE=0` for AFK chunks (env over arg
    because it survives sub-invocations).
  - HITL exit code: `42` (distinct from 0/success, 1/general fail, 2/tool
    error per ADR-0011; distinct from ADR-0006 blacklist axis).
  - HITL audit reason: `"hitl-ambiguity"` (typed event field).
  - System prompt clause: explicit text the adapter prepends in AFK mode
    forbidding question-asking; directs exit-with-HITL on ambiguity.
  - Verify: design doc cites every existing exit code in `lib/harness/*.sh`
    + `mentat-orchestrate` and confirms `42` collision-free. ADR-0006
    blacklist axis identified and excluded.

ADR-0010 was reserved at the numbering gap (0001-0009, [skip 0010], 0011,
0012). ADR-0012 forward-references it; S3 fills the slot.

Blocked-by: none (G1 done; S3 is internally unblocked HITL design).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")


import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / ".agents" / "docs" / "adr"
ADR = ADR_DIR / "0010-hitl-routing.md"

ENV_VAR = "MENTAT_INTERACTIVE"
HITL_EXIT = "42"
HITL_REASON = "hitl-ambiguity"

# Exit codes used elsewhere — design doc must enumerate to prove 42 is free.
EXISTING_EXIT_CODES = ("0", "1", "2")


# -- File existence -----------------------------------------------------------


def test_adr_0010_file_exists():
    assert ADR.is_file(), f"S3: {ADR.name} must exist (HITL routing slot reserved at numbering gap)"


def test_only_one_adr_0010():
    matches = sorted(p.name for p in ADR_DIR.glob("0010-*.md"))
    assert matches == ["0010-hitl-routing.md"], f"exactly one 0010-* ADR expected, got {matches}"


# -- Four-tuple contract: env / exit / reason / clause -----------------------


def test_adr_names_env_var_mentat_interactive():
    src = ADR.read_text()
    assert f"`{ENV_VAR}=0`" in src or f"`{ENV_VAR}`" in src, f"ADR must name the AFK signal env var `{ENV_VAR}`"


def test_adr_states_env_survives_subinvocations():
    """Plan S3: env chosen over arg flag because it survives sub-invocations.
    ADR must record the why, not just the what."""
    src = ADR.read_text().lower()
    assert "sub-invocation" in src or "subinvocation" in src or "survives" in src, (
        "ADR must explain why env over arg flag — survives sub-invocations"
    )


def test_adr_names_hitl_exit_code_42():
    src = ADR.read_text()
    assert re.search(rf"\b{HITL_EXIT}\b", src), f"ADR must name HITL exit code {HITL_EXIT}"


def test_adr_names_hitl_audit_reason():
    src = ADR.read_text()
    assert HITL_REASON in src, f"ADR must name HITL audit reason `{HITL_REASON}`"


def test_adr_contains_system_prompt_clause():
    """The clause text is a verbatim contract; the registry S2 already
    seeded it for claude-code + cursor rows. ADR-0010 owns the canonical
    text — S2 rows must match."""
    src = ADR.read_text()
    assert "AFK mode" in src, "ADR must contain the system-prompt clause text"
    assert "do not ask" in src.lower(), "ADR clause must forbid question-asking in plain text"
    assert "exit" in src.lower() and "ambigu" in src.lower(), "ADR clause must direct exit-on-ambiguity"


# -- Collision check: enumerate existing exit codes --------------------------


def test_adr_enumerates_existing_exit_codes():
    """Plan S3 verify clause: ADR must cite every existing exit code in
    lib/harness/*.sh + mentat-orchestrate. Codes in use: 0 / 1 / 2."""
    src = ADR.read_text()
    for code in EXISTING_EXIT_CODES:
        assert re.search(rf"\b{code}\b", src), f"ADR must cite existing exit code `{code}` in collision audit"


def test_adr_cites_mentat_orchestrate():
    src = ADR.read_text()
    assert "mentat-orchestrate" in src, "ADR must cite mentat-orchestrate as source of existing exit codes"


def test_adr_cites_harness_adapters_or_states_no_exits():
    """lib/harness/*.sh have no `exit N` (verified at preflight). ADR must
    either cite harness adapters in the collision audit or state explicitly
    that adapters define no exits of their own."""
    src = ADR.read_text()
    cites_harness = "lib/harness" in src or "harness/" in src
    assert cites_harness, (
        "ADR must reference lib/harness/* in the collision audit, even if only to note adapters define no exits"
    )


def test_adr_states_42_collision_free():
    src = ADR.read_text().lower()
    assert "collision-free" in src or "collision free" in src or "no collision" in src or "free of collision" in src, (
        "ADR must explicitly state `42` is collision-free against existing codes"
    )


# -- Axis discipline: HITL vs ADR-0006 blacklist vs ADR-0003 score-veto ------


def test_adr_distinguishes_hitl_from_adr_0006_blacklist():
    """Plan S3 verify clause: ADR-0006 blacklist code identified and excluded.
    ADR-0006 blacklist is an LLM-judge score veto (0.0), not a process exit
    code. ADR-0010 must explicitly state the distinction so they cannot be
    collapsed."""
    src = ADR.read_text()
    assert "0006" in src, "ADR must cross-reference ADR-0006 (blacklist axis)"
    src_lower = src.lower()
    assert "blacklist" in src_lower, "ADR must name the ADR-0006 blacklist axis"
    # Distinction must be explicit, not just two separate mentions
    assert (
        "axis" in src_lower
        or "distinct" in src_lower
        or "different" in src_lower
        or "not a blacklist" in src_lower
        or "orthogonal" in src_lower
    ), "ADR must explicitly state HITL exit ≠ blacklist (axis discipline)"


def test_adr_distinguishes_hitl_from_adr_0003_score_veto():
    """G3-S10 will amend ADR-0003 with cross-ref; this ADR must already name
    ADR-0003 scored-review veto as the third axis."""
    src = ADR.read_text()
    assert "0003" in src, "ADR must cross-reference ADR-0003 (scored-review axis)"


# -- ADR-0011 grounding (tool-level exit semantics) --------------------------


def test_adr_cross_references_adr_0011():
    """Exit code 2 semantics live in ADR-0011 (1=partial, >=2=tool-level).
    ADR-0010 must cite 0011 so the collision audit is anchored, not asserted."""
    src = ADR.read_text()
    assert "0011" in src, "ADR must cross-reference ADR-0011 (exit-code semantics: 1/partial, >=2/tool-level)"


# -- Cross-references to G3 consumers (S4-S10) -------------------------------


def test_adr_cross_references_g3_consumers():
    """S3 is the contract; S4-S10 are the consumers. ADR must enumerate
    each consumer slice so future readers can trace the seam."""
    src = ADR.read_text()
    for slice_id in ("S4", "S5", "S6", "S7", "S8", "S9", "S10"):
        assert re.search(rf"G3-{slice_id}(?!\d)", src), f"ADR must reference G3-{slice_id} as a downstream consumer"


# -- ADR-0012 cross-reference (registry consumes supports_afk) ---------------


def test_adr_cross_references_adr_0012_registry():
    """ADR-0012 `supports_afk` rows declare which adapters honor this
    contract. The reference must be bidirectional."""
    src = ADR.read_text()
    assert "0012" in src, "ADR must cross-reference ADR-0012 (registry that declares supports_afk)"
    assert "supports_afk" in src, "ADR must name the supports_afk field that flags compliant adapters"


# -- ADR-0012 row clause matches ADR-0010 clause (no drift) ------------------


def test_adr_0010_clause_matches_registry_rows():
    """G3-S2 wrote the clause verbatim into claude-code + cursor rows of
    harness-registry.jsonc. ADR-0010 is the canonical source. They must
    agree token-for-token to prevent drift."""
    import json

    registry_path = ROOT / ".agents" / "bin" / "lib" / "harness-registry.jsonc"
    raw = registry_path.read_text()
    parsed = json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))
    clause_claude = parsed["harnesses"]["claude-code"]["system_prompt_template"]
    clause_cursor = parsed["harnesses"]["cursor"]["system_prompt_template"]
    # Both rows must carry the same clause
    assert clause_claude == clause_cursor, f"S2 rows drifted: claude-code != cursor clause"
    # And that clause must appear verbatim in the ADR
    adr_src = ADR.read_text()
    assert clause_claude in adr_src, (
        f"ADR-0010 must contain the canonical clause verbatim — registry rows "
        f"reference it. Missing from ADR: {clause_claude!r}"
    )


# -- Reason string usable in audit row ---------------------------------------


def test_hitl_reason_is_kebab_lowercase():
    """audit-schema.jsonc (G1-S1) reason field is kebab-lowercase. The HITL
    reason must conform so mentat-land-queue can emit it directly."""
    assert HITL_REASON == HITL_REASON.lower(), "reason must be lowercase"
    assert re.match(r"^[a-z]+(-[a-z]+)*$", HITL_REASON), (
        f"reason {HITL_REASON!r} must be kebab-lowercase (audit-schema convention)"
    )


# -- Status / metadata -------------------------------------------------------


def test_adr_is_accepted():
    """Design slice landed → ADR status must be Accepted (not Draft/Proposed),
    so downstream G3-S4..S10 can treat it as load-bearing."""
    src = ADR.read_text().lower()
    assert "status: accepted" in src or "status:** accepted" in src or "**status:** accepted" in src, (
        "ADR-0010 must be marked Accepted (downstream slices depend on it)"
    )
