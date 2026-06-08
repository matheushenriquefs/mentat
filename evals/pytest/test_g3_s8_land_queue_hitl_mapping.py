"""G3-S8: mentat-land-queue maps HITL exit code 42 → reason: hitl-ambiguity.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S8):
  - On chunk exit code = HITL code from S3 (=42): emit `land.complete` row
    with `outcome: eject` and `reason: hitl-ambiguity`. Do NOT classify as
    `implement-fail`.
  - Verify: replay wedge session through land-queue → audit row has
    `reason: hitl-ambiguity`, worktree left for operator review.

ADR-0010 §3 (HITL audit reason): the typed `reason` field is the slot
already defined by G1-S1's audit-schema.jsonc — kebab-lowercase
`hitl-ambiguity`. ADR-0010 §G3-S8 cross-reference locks the mapping.

Contract:
  - `_classify_gate_rc <rc>` echoes a reason string:
      * 0           → ""              (continue to ff-merge)
      * 42          → "hitl-ambiguity"
      * any other   → "gate-fail"
  - HITL_EXIT constant equals 42 (drift guard against ADR-0010 renumbering).
  - mentat-land-queue sources the helper and uses _classify_gate_rc in
    the re-gate exit-code branch.
  - Docstring lists hitl-ambiguity in the valid reasons inventory.

Blocked-by: S3 (ADR-0010) — done; G1-S7 (mentat-land-queue exists) — done.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / ".agents" / "bin" / "lib" / "land-queue.sh"
LAND_QUEUE = ROOT / ".agents" / "bin" / "mentat-land-queue"
ADR_0010 = ROOT / ".agents" / "docs" / "adr" / "0010-hitl-routing.md"

HITL_EXIT = 42
HITL_REASON = "hitl-ambiguity"
GATE_FAIL_REASON = "gate-fail"


def _classify(rc: int) -> str:
    """Source lib/land-queue.sh, call _classify_gate_rc, return stdout."""
    script = f'source "{LIB}"; _classify_gate_rc "$1"'
    result = subprocess.run(
        ["bash", "-c", script, "_", str(rc)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"_classify_gate_rc {rc} failed: rc={result.returncode} "
        f"stderr={result.stderr!r}"
    )
    return result.stdout.strip()


# -- Library file exists -----------------------------------------------------


def test_lib_file_exists():
    """The sourceable helper must exist — extracted so tests can call the
    classifier without invoking the full land-queue runner."""
    assert LIB.is_file(), f"missing helper lib: {LIB}"


def test_lib_is_bash():
    """Helper must be a bash script (sourced, not executed)."""
    head = LIB.read_text().splitlines()[0]
    assert "bash" in head or head.startswith("#"), (
        f"land-queue.sh must be a shell script; first line: {head!r}"
    )


# -- Classifier contract -----------------------------------------------------


def test_classify_zero_returns_empty():
    """Exit 0 = re-gate green; no eject, no reason — empty string."""
    assert _classify(0) == ""


def test_classify_42_returns_hitl_ambiguity():
    """HITL exit code (ADR-0010 §2) → hitl-ambiguity reason (ADR-0010 §3)."""
    assert _classify(42) == HITL_REASON


def test_classify_one_returns_gate_fail():
    """Generic nonzero (1) preserves the existing gate-fail mapping — no
    regression on the most-common red-gate path."""
    assert _classify(1) == GATE_FAIL_REASON


def test_classify_two_returns_gate_fail():
    """Tool-level exit (2 = die) still classified as gate-fail at the
    land-queue boundary; land-queue does not re-route to hitl-ambiguity."""
    assert _classify(2) == GATE_FAIL_REASON


def test_classify_high_codes_return_gate_fail():
    """Sentinel codes (SIGKILL=137, SIGTERM=143, segfault=139, generic 255)
    must all bucket as gate-fail — only 42 routes to HITL."""
    for rc in (127, 137, 139, 143, 255):
        assert _classify(rc) == GATE_FAIL_REASON, (
            f"rc={rc} must map to gate-fail; got {_classify(rc)!r}"
        )


def test_classify_only_42_routes_to_hitl():
    """Drift guard: among 0..50, only 0 (empty) and 42 (hitl) escape the
    gate-fail bucket. Any future renumbering breaks this test."""
    for rc in range(50):
        out = _classify(rc)
        if rc == 0:
            assert out == "", f"rc=0 must be empty; got {out!r}"
        elif rc == 42:
            assert out == HITL_REASON, f"rc=42 must be hitl-ambiguity; got {out!r}"
        else:
            assert out == GATE_FAIL_REASON, (
                f"rc={rc} must be gate-fail (only 42 is HITL); got {out!r}"
            )


# -- HITL_EXIT constant (drift guard) ----------------------------------------


def test_hitl_exit_constant_is_42():
    """The lib must export HITL_EXIT=42 — drift guard against ADR-0010
    renumbering. Tests downstream (S9, S10) can import this constant."""
    script = f'source "{LIB}"; printf "%s" "$HITL_EXIT"'
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
    )
    assert result.returncode == 0, f"HITL_EXIT not exported: {result.stderr!r}"
    assert result.stdout == str(HITL_EXIT), (
        f"HITL_EXIT must equal {HITL_EXIT} (ADR-0010 §2); got {result.stdout!r}"
    )


def test_lib_references_adr_0010():
    """The lib must cite ADR-0010 — the canonical source for the four-tuple.
    Anyone reading the lib must be able to grep back to the contract."""
    text = LIB.read_text()
    assert re.search(r"ADR[-\s]?0010|0010-hitl-routing", text), (
        "land-queue.sh must cite ADR-0010 (canonical HITL contract)"
    )


# -- mentat-land-queue integration: sources lib + uses classifier ------------


def test_land_queue_sources_lib():
    """mentat-land-queue must source lib/land-queue.sh — otherwise the
    classifier is defined but unused, and the re-gate block still hardcodes
    gate-fail."""
    text = LAND_QUEUE.read_text()
    assert re.search(r'\.\s+"?[^"\s]*land-queue\.sh"?|source\s+"?[^"\s]*land-queue\.sh"?', text), (
        "mentat-land-queue must source lib/land-queue.sh"
    )


def test_land_queue_uses_classify_in_regate():
    """The re-gate block must call _classify_gate_rc on the spawn exit code
    — that's the whole point of S8. Hardcoded 'gate-fail' in the re-gate
    branch defeats the slice."""
    text = LAND_QUEUE.read_text()
    assert "_classify_gate_rc" in text, (
        "mentat-land-queue must invoke _classify_gate_rc on the gate exit code"
    )


def test_land_queue_records_hitl_ambiguity_reason():
    """Source-level invariant: hitl-ambiguity must appear in the land-queue
    source (either as a literal or via the lib helper) — otherwise the
    audit row can never carry the typed reason."""
    text = LAND_QUEUE.read_text()
    lib_text = LIB.read_text()
    combined = text + "\n" + lib_text
    assert HITL_REASON in combined, (
        f"mentat-land-queue or its lib must emit {HITL_REASON!r} reason"
    )


def test_land_queue_docstring_lists_hitl_ambiguity():
    """The script's leading docstring documents valid `reason` values.
    hitl-ambiguity must be one of them — operators reading the script
    must see HITL as a first-class verdict, not a hidden code path."""
    text = LAND_QUEUE.read_text()
    head = "\n".join(text.splitlines()[:25])
    assert HITL_REASON in head, (
        f"mentat-land-queue docstring (top 25 lines) must list {HITL_REASON!r} "
        f"among valid `reason` values per ADR-0010 §3"
    )


def test_land_queue_does_not_collapse_hitl_into_implement_fail():
    """ADR-0010 §3 + plan S8 verify: 'Do NOT classify as implement-fail'.
    Make sure no active code path equates 42 with implement-fail. Skip
    comment lines — the docstring enumerates both as distinct buckets,
    which is correct (the forbidden thing is mapping, not co-listing)."""
    text = LAND_QUEUE.read_text()
    for line in text.splitlines():
        stripped = line.lstrip()
        # Skip comment lines and the inventory docstring — those legitimately
        # name both buckets as separate values of the `reason` enum.
        if stripped.startswith("#"):
            continue
        if "implement-fail" in line and ("42" in line or "HITL" in line.upper()):
            assert False, (
                f"active line collapses HITL into implement-fail (forbidden "
                f"by ADR-0010 §3 + S8): {line!r}"
            )


# -- ADR-0010 drift guard ----------------------------------------------------


def test_adr_0010_names_land_queue_mapping():
    """ADR-0010 must name S8's land-queue mapping. If the ADR changes the
    reason name or exit code, this test breaks and forces the lib to follow."""
    src = ADR_0010.read_text()
    assert "mentat-land-queue" in src, "ADR-0010 must reference mentat-land-queue"
    assert HITL_REASON in src, f"ADR-0010 must define {HITL_REASON!r} reason"
    assert str(HITL_EXIT) in src, f"ADR-0010 must lock exit code {HITL_EXIT}"


def test_adr_0010_forbids_implement_fail_collapse():
    """ADR-0010 §3 must explicitly say 'not implement-fail' — that's the
    semantic content the lib enforces."""
    src = ADR_0010.read_text()
    assert "implement-fail" in src, (
        "ADR-0010 must reference implement-fail (to forbid the collapse)"
    )
