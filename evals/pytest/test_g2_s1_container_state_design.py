"""G2-S1: container-state.sh interface design doc.

Spec (~/.agents/plans/mentat-architecture-revamp-g2-container-quartet.md S1):
  - Decide helpers + their contracts:
      * container_id_for(slug)
      * ensure_workspace_folder(ws)
      * assert_safe_directory()
      * synthesize_compose_if_absent()
      * container_slug_for_cwd()
  - Output: function signatures + invariants documented.
  - Each function has one explicit failure mode (no silent fallback).
  - Verify: design doc enumerates every invariant currently re-derived in
    the 4 scripts (workspaceFolder, safe.directory, basename "$PWD" sites).

Design decisions locked by user during S1 [HITL]:
  - Doc path: .agents/docs/container-state-design.md (free-standing, not ADR).
  - Signature convention: stdout-return + exit 0/nonzero (bash-idiomatic).

These tests lock the design-doc content. Re-running S1 (or renaming a
helper) breaks the gate.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / ".agents" / "docs" / "container-state-design.md"
BIN = ROOT / ".agents" / "bin"
CONTAINER_SCRIPTS = (
    BIN / "mentat-container-up",
    BIN / "mentat-container-run",
    BIN / "mentat-container-down",
    BIN / "mentat-container-doctor",
)

HELPERS = (
    "container_id_for",
    "ensure_workspace_folder",
    "assert_safe_directory",
    "synthesize_compose_if_absent",
    "container_slug_for_cwd",
)

INVARIANT_TERMS = (
    "workspaceFolder",
    "safe.directory",
)


# -- Doc existence + structure -----------------------------------------------


def test_design_doc_exists():
    """The free-standing design doc lives at .agents/docs/container-state-design.md
    (user choice during G2-S1 HITL — not an ADR, not a docstring header)."""
    assert DOC.is_file(), f"design doc missing: {DOC}"


def test_design_doc_titled_for_g2_s1():
    """Top H1 must name the artifact + slice — operators landing in the doc
    must see what it is and which plan slice produced it."""
    text = DOC.read_text()
    first_line = text.splitlines()[0] if text else ""
    assert first_line.startswith("# "), f"doc must start with H1; got {first_line!r}"
    assert "container-state" in first_line.lower(), (
        f"H1 must name container-state; got {first_line!r}"
    )


def test_design_doc_cites_slice():
    """Doc must reference G2-S1 — drift guard so a future slice editor sees
    where this doc came from."""
    text = DOC.read_text()
    assert "G2-S1" in text or "g2-s1" in text.lower(), (
        "design doc must cite slice G2-S1"
    )


def test_design_doc_cites_parent_plan():
    """Doc must reference the G2 plan or the index parent. Cross-anchor."""
    text = DOC.read_text()
    assert re.search(r"container-quartet|architecture-revamp", text), (
        "design doc must cite G2 (container-quartet) or parent index plan"
    )


# -- All 5 helpers documented ------------------------------------------------


def test_design_doc_lists_all_five_helpers():
    """Plan S1 names exactly 5 helpers. All must appear in the doc — missing
    one means the contract for that helper is undefined."""
    text = DOC.read_text()
    missing = [h for h in HELPERS if h not in text]
    assert not missing, (
        f"design doc must document all 5 helpers; missing: {missing}"
    )


def test_each_helper_has_a_section():
    """Each helper must have its own section header (##/### with the name)
    so signatures + failure modes are not collapsed into a single paragraph."""
    text = DOC.read_text()
    for helper in HELPERS:
        # Header line containing the helper name (any depth ##+ acceptable).
        pattern = rf"^#{{2,}}[^\n]*{re.escape(helper)}"
        assert re.search(pattern, text, re.MULTILINE), (
            f"helper {helper!r} must have its own section header (##/###)"
        )


# -- Signature convention (stdout + exit code) -------------------------------


def test_design_doc_states_signature_convention():
    """User locked stdout-return + exit 0/nonzero during S1 HITL. Doc must
    state this once, prominently — readers should not have to infer from
    individual signatures."""
    text = DOC.read_text().lower()
    has_stdout = "stdout" in text
    has_exit = "exit" in text and ("nonzero" in text or "non-zero" in text or "exit code" in text or "exit 0" in text)
    assert has_stdout and has_exit, (
        "doc must state the signature convention: values on stdout, success "
        "via exit 0 / failure via nonzero exit"
    )


# -- Failure modes (one per helper, no silent fallback) ----------------------


def test_each_helper_documents_a_failure_mode():
    """Plan S1: 'Each function has one explicit failure mode (no silent
    fallback).' Check each helper section names what triggers a nonzero
    exit. Acceptable signals: 'fail', 'error', 'exit', 'abort', 'die'."""
    text = DOC.read_text()
    # Split into per-helper windows by header.
    for helper in HELPERS:
        pattern = rf"^#{{2,}}[^\n]*{re.escape(helper)}(?P<body>(?:(?!^#{{1,2}} ).)*)"
        m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        assert m, f"could not locate {helper} section body"
        body = m.group("body").lower()
        signals = ("fail", "error", "exit", "abort", "die", "nonzero", "non-zero")
        assert any(s in body for s in signals), (
            f"{helper!r} section must document its failure mode "
            f"(expected one of {signals})"
        )


def test_design_doc_forbids_silent_fallback():
    """S1 spec: 'no silent fallback'. Doc must contain that anti-pattern
    text once — a binding constraint readers can grep for."""
    text = DOC.read_text().lower()
    assert "silent fallback" in text or "no silent" in text or "fail loud" in text, (
        "doc must explicitly forbid silent fallback (cite the S1 constraint)"
    )


# -- Invariant inventory: every site currently re-derived in 4 scripts -------


def test_design_doc_inventories_workspace_folder_invariant():
    """`workspaceFolder` is re-derived in mentat-container-up + -run today.
    Doc must name it explicitly — that's invariant #1 the lib will absorb."""
    text = DOC.read_text()
    assert "workspaceFolder" in text, (
        "doc must inventory `workspaceFolder` invariant (re-derived in "
        "container-up + container-run)"
    )


def test_design_doc_inventories_safe_directory_invariant():
    """`safe.directory` is re-derived in container-up + others. Invariant #2."""
    text = DOC.read_text()
    assert "safe.directory" in text, (
        "doc must inventory `safe.directory` invariant"
    )


def test_design_doc_inventories_slug_invariant():
    """`basename $PWD` / slug derivation is duplicated 4x with subtle
    divergence per S1 spec. Doc must name the unification target."""
    text = DOC.read_text().lower()
    assert "slug" in text or 'basename "$pwd"' in text or "basename $pwd" in text, (
        "doc must inventory the slug / basename-of-PWD invariant"
    )


def test_design_doc_invariant_count_matches_scripts():
    """Plan verify: 'design doc enumerates every invariant currently
    re-derived in the 4 scripts'. Count callable sites in scripts; doc must
    name each at least once. Allow doc to also describe NEW invariants the
    lib introduces — but no script-side invariant may be missing."""
    pattern = re.compile(r'workspaceFolder|safe\.directory|basename "\$PWD"')
    sites_per_script: dict[str, set[str]] = {}
    for script in CONTAINER_SCRIPTS:
        assert script.is_file(), f"container script missing: {script}"
        hits = set(pattern.findall(script.read_text()))
        sites_per_script[script.name] = hits
    seen_terms = set().union(*sites_per_script.values())
    doc_text = DOC.read_text()
    # Map regex matches back to the source-of-truth label that must appear.
    label_map = {
        "workspaceFolder": "workspaceFolder",
        "safe.directory": "safe.directory",
        'basename "$PWD"': "basename",  # doc may say `basename` or `$PWD`-derived slug
    }
    missing = []
    for term in seen_terms:
        label = label_map.get(term, term)
        if label not in doc_text:
            missing.append(term)
    assert not missing, (
        f"doc misses script-side invariants: {missing} "
        f"(sites per script: {sites_per_script})"
    )


# -- Helper-specific contract sanity -----------------------------------------


def test_container_id_for_signature_documented():
    """The most-called helper must show its input + output explicitly."""
    text = DOC.read_text()
    m = re.search(
        r"#{2,}[^\n]*container_id_for(?P<body>(?:(?!^#{1,2} ).)*)",
        text, re.MULTILINE | re.DOTALL,
    )
    assert m, "container_id_for section missing"
    body = m.group("body").lower()
    assert "slug" in body, "container_id_for must name `slug` input"
    assert "docker" in body or "container" in body, (
        "container_id_for must describe what it returns / looks up"
    )


def test_ensure_workspace_folder_signature_documented():
    """Workspace-folder helper must name its input + what it asserts."""
    text = DOC.read_text()
    m = re.search(
        r"#{2,}[^\n]*ensure_workspace_folder(?P<body>(?:(?!^#{1,2} ).)*)",
        text, re.MULTILINE | re.DOTALL,
    )
    assert m, "ensure_workspace_folder section missing"
    body = m.group("body").lower()
    assert "workspacefolder" in body or "workspace" in body, (
        "ensure_workspace_folder must reference the workspaceFolder concept"
    )


def test_assert_safe_directory_signature_documented():
    """Safe-directory helper must reference git's `safe.directory` config."""
    text = DOC.read_text()
    m = re.search(
        r"#{2,}[^\n]*assert_safe_directory(?P<body>(?:(?!^#{1,2} ).)*)",
        text, re.MULTILINE | re.DOTALL,
    )
    assert m, "assert_safe_directory section missing"
    body = m.group("body")
    assert "safe.directory" in body, (
        "assert_safe_directory must reference safe.directory in its body"
    )


# -- Cross-reference: doc cites S2 as consumer -------------------------------


def test_design_doc_references_s2_consumer():
    """S2 implements what S1 designs. Doc must point at S2 (or
    `lib/container-state.sh`) — operators reading the design must know
    where the impl lives."""
    text = DOC.read_text()
    assert (
        "S2" in text
        or "container-state.sh" in text
        or "lib/container-state" in text
    ), "design doc must cite S2 / container-state.sh as the implementation site"
