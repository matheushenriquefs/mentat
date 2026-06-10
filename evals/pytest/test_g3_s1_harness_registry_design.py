"""G3-S1: ADR-0012 codifies harness-registry schema; JSONC stub seeded.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S1):
  - Design call: schema for one row per harness.
  - Required fields: name, bin, base_args, supports_afk (bool),
    disallowed_tools_arg (template), system_prompt_template.
  - Decide registry location: chosen = .agents/bin/lib/harness-registry.jsonc
    (mirrors G1-S1 audit-schema.jsonc pattern, shell + python both consume).
  - Default policy for unknown harness: refuse to spawn, exit nonzero — fail closed.
  - Verify: design doc lists every field with default-value policy.

Blocked-by: none (G1 done; G3 internally unblocked).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")


import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = ROOT / ".agents" / "docs" / "adr" / "0012-harness-registry.md"
STUB = ROOT / ".agents" / "bin" / "lib" / "harness-registry.jsonc"

REQUIRED_FIELDS = (
    "name",
    "bin",
    "base_args",
    "supports_afk",
    "disallowed_tools_arg",
    "system_prompt_template",
)


# -- ADR-0012 exists ----------------------------------------------------------


def test_adr_0012_file_exists():
    assert ADR.is_file(), f"S1: {ADR.name} must exist (new ADR for harness registry)"


def test_only_one_adr_0012():
    matches = sorted(p.name for p in ADR.parent.glob("0012-*.md"))
    assert matches == ["0012-harness-registry.md"], f"exactly one 0012-* ADR expected, got {matches}"


# -- ADR enumerates every required field --------------------------------------


def test_adr_lists_every_required_field():
    src = ADR.read_text()
    for f in REQUIRED_FIELDS:
        assert f"`{f}`" in src, f"ADR must enumerate required field `{f}` (backticked) — missing"


def test_adr_states_field_purpose_table():
    """Field list isn't enough — each field needs a one-line purpose so the
    contract is unambiguous. Test: a table or field-list section anchors the
    field names."""
    src = ADR.read_text()
    field_section_idx = src.lower().find("field")
    assert field_section_idx >= 0, "ADR must have a 'field' section heading or table"
    window = src[field_section_idx : field_section_idx + 2000]
    hits = sum(1 for f in REQUIRED_FIELDS if f"`{f}`" in window)
    assert hits == len(REQUIRED_FIELDS), (
        f"ADR field section must list all {len(REQUIRED_FIELDS)} required fields "
        f"within one section (~2000 chars of first 'field' mention); found {hits}"
    )


# -- Fail-closed default policy ----------------------------------------------


def test_adr_states_fail_closed_for_unknown_harness():
    src = ADR.read_text().lower()
    assert "fail closed" in src or "fail-closed" in src, (
        "ADR must declare fail-closed default policy for unknown harnesses"
    )


def test_adr_states_refuse_to_spawn_on_unknown():
    src = ADR.read_text().lower()
    assert "refuse to spawn" in src or "exit nonzero" in src, (
        "ADR must spell out the fail-closed behavior: refuse to spawn / exit nonzero"
    )


# -- Registry path cited consistently ----------------------------------------


def test_adr_cites_registry_jsonc_path():
    src = ADR.read_text()
    assert ".agents/bin/lib/harness-registry.jsonc" in src, (
        "ADR must cite the registry JSONC at .agents/bin/lib/harness-registry.jsonc"
    )


def test_adr_explains_location_decision():
    """Location was a HITL decision (bin/lib vs .agents/lib). ADR must record
    the rationale, not just the path."""
    src = ADR.read_text().lower()
    assert "source-of-truth" in src or "source of truth" in src or "single source" in src, (
        "ADR must articulate why bin/lib was chosen — source-of-truth rationale"
    )


# -- JSONC stub seeded --------------------------------------------------------


def test_registry_stub_exists():
    assert STUB.is_file(), f"S1: {STUB} must exist (commented JSONC stub for S2 to fill)"


def _strip_jsonc_comments(text: str) -> str:
    # Strip // line comments (naive — mirrors audit.sh convention).
    return re.sub(r"//.*$", "", text, flags=re.MULTILINE)


def test_registry_stub_parses_after_comment_strip():
    raw = STUB.read_text()
    try:
        parsed = json.loads(_strip_jsonc_comments(raw))
    except json.JSONDecodeError as e:
        raise AssertionError(f"stub must be valid JSONC (parse-after-strip): {e}")
    assert isinstance(parsed, dict), "stub root must be a JSON object"


def test_registry_stub_has_harnesses_key():
    parsed = json.loads(_strip_jsonc_comments(STUB.read_text()))
    assert "harnesses" in parsed, "stub must declare `harnesses` map (empty in S1, S2 fills 8 rows)"
    assert isinstance(parsed["harnesses"], dict), "`harnesses` must be an object"


def test_registry_stub_has_schema_metadata():
    """Stub carries field schema declaratively so consumers can validate
    rows. S2 fills rows; S1 declares the contract."""
    parsed = json.loads(_strip_jsonc_comments(STUB.read_text()))
    assert "required_fields" in parsed, "stub must declare `required_fields` list — S2 validates rows against it"
    declared = parsed["required_fields"]
    assert isinstance(declared, list), "`required_fields` must be a list"
    assert set(declared) == set(REQUIRED_FIELDS), (
        f"stub required_fields {declared!r} must equal canonical set {list(REQUIRED_FIELDS)!r}"
    )


def test_registry_stub_documents_unknown_policy():
    """Fail-closed policy must be machine-readable in the stub, not just
    prose in the ADR."""
    parsed = json.loads(_strip_jsonc_comments(STUB.read_text()))
    assert "on_unknown" in parsed, "stub must declare `on_unknown` policy field"
    policy = parsed["on_unknown"]
    assert policy in ("refuse", "fail-closed", "exit-nonzero"), (
        f"`on_unknown` must encode fail-closed semantics, got {policy!r}"
    )


# -- ADR ↔ stub alignment (no drift) -----------------------------------------


def test_adr_and_stub_field_lists_agree():
    """If the ADR's enumerated fields and the stub's required_fields drift,
    the contract is broken. Cross-check."""
    adr_src = ADR.read_text()
    stub = json.loads(_strip_jsonc_comments(STUB.read_text()))
    adr_fields = {f for f in REQUIRED_FIELDS if f"`{f}`" in adr_src}
    stub_fields = set(stub["required_fields"])
    assert adr_fields == stub_fields, (
        f"ADR field set {sorted(adr_fields)} must equal stub field set {sorted(stub_fields)}"
    )


# -- Slice-boundary marker (S1 -> S2 transition) -----------------------------


def test_stub_harnesses_map_well_formed():
    """S1 stub declared an empty `harnesses` map awaiting S2. S2 has landed
    and populated 8 rows. This test now asserts the post-S2 floor: the
    `harnesses` value is a dict (whether empty during S1 or populated post-S2)
    — never a list, string, or null. Schema contract from S1 holds."""
    parsed = json.loads(_strip_jsonc_comments(STUB.read_text()))
    assert isinstance(parsed["harnesses"], dict), (
        f"`harnesses` must be a JSON object (dict); got {type(parsed['harnesses']).__name__}"
    )


# -- ADR ties to ADR-0010 (HITL routing) -------------------------------------


def test_adr_cross_references_adr_0010():
    """G3 contract sits next to ADR-0010 (HITL routing). The registry's
    supports_afk field maps to that ADR's AFK/HITL plan classification."""
    src = ADR.read_text()
    assert "0010" in src, (
        "ADR-0012 must cross-reference ADR-0010 (HITL routing) — `supports_afk` "
        "field is consumed by the AFK fan-out path"
    )


# -- ADR ties to G3 plan slice graph ------------------------------------------


def test_adr_names_g3_dependents():
    """S2 fills rows, S4/S5/S6 consume `disallowed_tools_arg` +
    `system_prompt_template`. ADR should name these downstream consumers so
    future readers see the registry's reach."""
    src = ADR.read_text()
    # Look for G3-S2 explicitly (consumer that fills the table).
    assert re.search(r"G3-S2(?!\d)", src), "ADR must reference G3-S2 (the slice that writes the 8 rows)"
    # And at least one of the adapter slices that consumes the schema.
    assert re.search(r"G3-S[456](?!\d)", src), "ADR must reference at least one of G3-S4/S5/S6 (adapter consumers)"
