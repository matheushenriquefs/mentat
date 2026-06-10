"""G3-S7: .agents/commands/mentat-implement.md references the ADR-0010 contract.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S7):
  - Replace prose-only AFK description with reference to the S3/ADR-0010
    contract: env var name, HITL exit code, audit reason. Prose stays — but
    it's now linked, not load-bearing.
  - Verify: `grep -A 3 'AFK' mentat-implement.md` shows the
    `MENTAT_INTERACTIVE` env reference and HITL exit code, no contradiction
    with `harness-registry.jsonc`.

Contract source — ADR-0010 four-tuple:
  - signal env: MENTAT_INTERACTIVE=0 (opt-in)
  - HITL exit code: 42
  - audit reason: hitl-ambiguity (kebab-lowercase)
  - system-prompt clause (verbatim, in registry under
    harnesses.claude-code.system_prompt_template)

The doc must reference all four anchors. Drift guard: any future change to
ADR-0010 / registry that renames a field breaks this test, forcing the doc
to follow.

Blocked-by: S3 (ADR-0010) — done.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")


import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / ".agents" / "commands" / "mentat-implement.md"
REGISTRY = ROOT / ".agents" / "bin" / "lib" / "harness-registry.jsonc"
ADR_0010 = ROOT / ".agents" / "docs" / "adr" / "0010-hitl-routing.md"

CLAUSE = (
    "AFK mode: do not ask the user questions. On ambiguity, exit nonzero with a HITL audit reason instead of guessing."
)
HITL_EXIT = "42"
HITL_REASON = "hitl-ambiguity"
SIGNAL_ENV = "MENTAT_INTERACTIVE"


def _doc_text() -> str:
    return DOC.read_text()


def _load_registry() -> dict:
    raw = REGISTRY.read_text()
    return json.loads(re.sub(r"//.*$", "", raw, flags=re.MULTILINE))


# -- File exists --------------------------------------------------------------


def test_doc_file_exists():
    """mentat-implement.md must exist — it's the slash-command body for /mentat-implement."""
    assert DOC.is_file(), f"missing doc: {DOC}"


# -- Four-tuple references (ADR-0010 contract) -------------------------------


def test_doc_references_mentat_interactive_env():
    """The signal half of the four-tuple: env var name must appear in prose."""
    text = _doc_text()
    assert SIGNAL_ENV in text, (
        f"mentat-implement.md must reference {SIGNAL_ENV} env var (ADR-0010 signal); "
        f"S7 verify line: `grep -A 3 'AFK' mentat-implement.md` must show it."
    )


def test_doc_references_hitl_exit_code_42():
    """The exit-code half of the four-tuple: literal `42` must appear."""
    text = _doc_text()
    assert HITL_EXIT in text, (
        f"mentat-implement.md must reference exit code {HITL_EXIT} (ADR-0010 HITL code); "
        f"drift guard: future renumbering breaks contract."
    )


def test_doc_references_hitl_ambiguity_reason():
    """The audit-reason half of the four-tuple: kebab-lowercase token verbatim."""
    text = _doc_text()
    assert HITL_REASON in text, (
        f"mentat-implement.md must reference audit reason {HITL_REASON!r} "
        f"(ADR-0010 §3); kebab-lowercase per audit-schema convention."
    )


def test_doc_references_adr_0010():
    """The doc must point at the canonical source of truth, not restate it."""
    text = _doc_text()
    # Accept "ADR-0010" or "0010-hitl-routing" — either form anchors back to the source.
    assert re.search(r"ADR[-\s]?0010|0010-hitl-routing", text), (
        "mentat-implement.md must cite ADR-0010 — S7 says 'prose stays "
        "but it's now linked, not load-bearing'. Cite the source."
    )


# -- S7 verify line literal --------------------------------------------------


def test_grep_dash_a_3_afk_shows_signal_and_exit():
    """S7 verify line (literal): `grep -A 3 'AFK' mentat-implement.md`
    must show MENTAT_INTERACTIVE env reference AND HITL exit code 42.

    The verify line in the plan is a contract: any AFK paragraph in the doc
    must, within the same `grep -A 3` window, surface both anchors.
    """
    result = subprocess.run(
        ["grep", "-A", "3", "AFK", str(DOC)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "grep -A 3 'AFK' returned no match — doc has no AFK paragraph at all; S7 requires AFK be referenced by name."
    )
    out = result.stdout
    assert SIGNAL_ENV in out, f"grep -A 3 'AFK' output must include {SIGNAL_ENV}; got:\n{out}"
    assert HITL_EXIT in out, f"grep -A 3 'AFK' output must include exit code {HITL_EXIT}; got:\n{out}"


# -- Registry consistency (no-contradiction clause from S7) ------------------


def test_doc_clause_matches_registry_byte_for_byte():
    """If the doc quotes the system-prompt clause, it must match the
    registry verbatim. S7 verify line: 'no contradiction with
    harness-registry.jsonc'. The registry is the source of truth."""
    text = _doc_text()
    registry = _load_registry()
    registry_clause = registry["harnesses"]["claude-code"]["system_prompt_template"]
    # If the doc reproduces the clause prose at all, the registry version
    # must appear verbatim. If the doc only links to ADR-0010 without
    # restating the clause, this test is vacuously OK (nothing to mismatch).
    if "AFK mode:" in text:
        assert registry_clause in text, (
            f"doc restates 'AFK mode:' prose but text drifted from registry; "
            f"expected verbatim substring:\n{registry_clause!r}\n"
            f"doc text contains 'AFK mode:' at position {text.find('AFK mode:')}"
        )


def test_doc_does_not_contradict_registry_exit_code():
    """Drift guard: doc must not declare any HITL-related exit code other
    than 42. We scan for `exit code N` or `code N` adjacent to AFK/HITL
    paragraphs and ensure no other integer creeps in as the HITL number."""
    text = _doc_text()
    # Find any "exit code N" or "exit N" patterns near AFK/HITL keywords.
    # Strict check: every appearance of `exit code <num>` in an AFK/HITL
    # context must be 42.
    for match in re.finditer(r"exit(?:\s+code)?\s+(\d+)", text):
        num = match.group(1)
        window_start = max(0, match.start() - 60)
        window_end = min(len(text), match.end() + 60)
        window = text[window_start:window_end]
        if re.search(r"AFK|HITL|hitl-ambiguity|MENTAT_INTERACTIVE", window):
            assert num == HITL_EXIT, (
                f"doc declares 'exit {num}' near AFK/HITL context but ADR-0010 "
                f"locks HITL exit code at {HITL_EXIT}; mismatch:\n{window!r}"
            )


def test_doc_signal_value_is_zero():
    """ADR-0010 §1: 'AFK is opt-in via explicit =0'. If the doc names a
    value alongside MENTAT_INTERACTIVE, it must be 0 (not 1 / true / yes)."""
    text = _doc_text()
    # Find any `MENTAT_INTERACTIVE=<val>` patterns.
    for match in re.finditer(r"MENTAT_INTERACTIVE\s*=\s*(\S+?)\b", text):
        val = match.group(1).rstrip("`'\".,;)")
        assert val == "0", (
            f"doc names MENTAT_INTERACTIVE={val} but ADR-0010 specifies =0 "
            f"as the AFK signal; non-zero (or unset) = interactive default."
        )


# -- Contract back-reference (drift guard) -----------------------------------


def test_adr_0010_is_canonical_source():
    """Drift guard: ADR-0010 must contain all four anchors the doc references.
    If ADR-0010 changes, this test breaks and forces the doc to follow."""
    src = ADR_0010.read_text()
    assert SIGNAL_ENV in src, f"ADR-0010 must define {SIGNAL_ENV} signal"
    assert HITL_EXIT in src, f"ADR-0010 must define exit code {HITL_EXIT}"
    assert HITL_REASON in src, f"ADR-0010 must define audit reason {HITL_REASON}"
    assert CLAUSE in src, "ADR-0010 must contain the system-prompt clause verbatim"


def test_registry_claude_code_supports_afk():
    """S7 verify pre-condition: registry must claim claude-code supports AFK,
    or the doc reference is hollow. Re-asserts G3-S2's contract."""
    registry = _load_registry()
    assert registry["harnesses"]["claude-code"]["supports_afk"] is True, (
        "registry claude-code row must claim supports_afk: true (G3-S2)"
    )


def test_registry_cursor_supports_afk():
    """S7 verify pre-condition: cursor adapter (G3-S6) also claims AFK
    support; the doc's reference must hold for both AFK adapters."""
    registry = _load_registry()
    assert registry["harnesses"]["cursor"]["supports_afk"] is True, (
        "registry cursor row must claim supports_afk: true (G3-S6)"
    )
