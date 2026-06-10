"""G1-S12: ADR-0009 codifies audit envelope contract; file renamed.

Spec (~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md S12):
  - Rename: 0009-audit-log-format.md -> 0009-audit-envelope.md.
  - Amend ADR body with envelope contract paragraph:
      "All audit writes route through `audit.sh::mentat_audit`. Subprocess
       stderr lands in `<base>/.stderr/<agent>-<slug>.stderr` — never in
       `.jsonl`. Schema lives in `.agents/bin/lib/audit-schema.jsonc`
       (single source-of-truth, consumed by bash + python)."
  - Cross-reference S1 (schema path), S2 (emit fn), S4 (sidecar path).
  - Verify: `grep -r 'append.*\\.jsonl' .agents/bin/` returns only `audit.sh`.

Blocked-by: S2, S3, S4 (all done).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")


import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / ".agents" / "docs" / "adr"
OLD_ADR = ADR_DIR / "0009-audit-log-format.md"
NEW_ADR = ADR_DIR / "0009-audit-envelope.md"


# -- File rename --------------------------------------------------------------


def test_new_adr_file_exists():
    assert NEW_ADR.is_file(), f"S12: {NEW_ADR.name} must exist (renamed from 0009-audit-log-format.md)"


def test_old_adr_file_absent():
    assert not OLD_ADR.exists(), f"S12: {OLD_ADR.name} must be removed after git mv"


def test_only_one_adr_0009():
    matches = sorted(p.name for p in ADR_DIR.glob("0009-*.md"))
    assert matches == ["0009-audit-envelope.md"], f"exactly one 0009-* ADR expected, got {matches}"


# -- Envelope contract paragraph ---------------------------------------------


def test_adr_routes_writes_through_mentat_audit():
    src = NEW_ADR.read_text()
    assert "audit.sh::mentat_audit" in src or "`mentat_audit`" in src, (
        "ADR must state all audit writes route through audit.sh::mentat_audit"
    )


def test_adr_states_writes_route_phrase():
    src = NEW_ADR.read_text().lower()
    assert "route through" in src, "ADR must contain the 'route through' contract phrase"


def test_adr_documents_stderr_sidecar_path():
    src = NEW_ADR.read_text()
    assert (
        "<base>/.stderr/<agent>-<slug>.stderr" in src
        or ".stderr/${agent}-${slug}.stderr" in src
        or ".stderr/<agent>-<slug>.stderr" in src
    ), "ADR must document stderr sidecar path pattern"


def test_adr_states_stderr_never_in_jsonl():
    src = NEW_ADR.read_text().lower()
    assert "never in `.jsonl`" in src or "never in .jsonl" in src, (
        "ADR must explicitly state stderr never lands in .jsonl"
    )


def test_adr_cites_schema_jsonc_path():
    src = NEW_ADR.read_text()
    assert ".agents/bin/lib/audit-schema.jsonc" in src, (
        "ADR must cite the schema JSONC at .agents/bin/lib/audit-schema.jsonc"
    )


def test_adr_states_schema_is_source_of_truth():
    src = NEW_ADR.read_text().lower()
    assert "source-of-truth" in src or "source of truth" in src, "ADR must declare schema as single source-of-truth"


def test_adr_states_bash_and_python_both_consume():
    """Schema source-of-truth claim must bind bash + python within one sentence,
    not just mention both languages somewhere in the doc."""
    src = NEW_ADR.read_text().lower()
    sot_idx = src.find("source-of-truth")
    if sot_idx < 0:
        sot_idx = src.find("source of truth")
    assert sot_idx >= 0, "no source-of-truth phrase to anchor the bash/python claim"
    window = src[max(0, sot_idx - 200) : sot_idx + 400]
    assert "bash" in window and "python" in window, (
        "ADR must state schema source-of-truth is consumed by bash + python "
        "within ~200 chars of the source-of-truth claim"
    )


# -- Cross-references to S1/S2/S4 --------------------------------------------
#
# Each cross-ref must bind the slice id to its responsibility (schema / emit
# fn / sidecar) so bare "Blocked-by: S2, S3, S4" cannot satisfy the assertion.


import re as _re


# Word-boundary regex for a single slice id (G1-S1 not G1-S12, and not the
# S1–S4 range form). Looks for the canonical `G1-S<n>` cross-ref form used in
# the ADR's dedicated cross-ref bullets.
def _slice_line(slice_id: str) -> str:
    pat = _re.compile(rf"G1-{_re.escape(slice_id)}(?!\d)")
    for line in NEW_ADR.read_text().splitlines():
        if pat.search(line):
            return line
    return ""


def test_adr_cross_references_s1_schema():
    line = _slice_line("S1")
    assert line, "ADR must cross-reference G1-S1 (schema source-of-truth)"
    assert any(k in line.lower() for k in ("schema", "source-of-truth", "jsonc")), (
        f"S1 cross-ref must bind to schema/source-of-truth context, got: {line!r}"
    )


def test_adr_cross_references_s2_emit_fn():
    line = _slice_line("S2")
    assert line, "ADR must cross-reference G1-S2 (mentat_audit emit fn)"
    assert any(k in line for k in ("mentat_audit", "emit", "audit.sh")), (
        f"S2 cross-ref must bind to mentat_audit / emit fn / audit.sh context, got: {line!r}"
    )


def test_adr_cross_references_s4_sidecar():
    line = _slice_line("S4")
    assert line, "ADR must cross-reference G1-S4 (stderr sidecar)"
    assert any(k in line.lower() for k in ("sidecar", ".stderr", "stderr")), (
        f"S4 cross-ref must bind to stderr sidecar context, got: {line!r}"
    )


# -- Stale-ref sweep ---------------------------------------------------------


def test_no_stale_old_adr_filename_refs():
    result = subprocess.run(
        [
            "grep",
            "-rln",
            "--include=*",
            "--exclude-dir=.git",
            "--exclude-dir=.pytest_cache",
            "--exclude-dir=__pycache__",
            "--exclude-dir=evals",
            "--exclude-dir=.claude",
            "--exclude-dir=.mentat",
            "0009-audit-log-format",
            str(ROOT),
        ],
        capture_output=True,
        text=True,
    )
    hits = [line for line in result.stdout.splitlines() if line]
    assert hits == [], f"stale '0009-audit-log-format' references remain: {hits}"


# -- jsonl-write invariant (per S12 verify clause) ---------------------------


# Bins that legitimately write `.jsonl` files outside of audit-row emission:
#   - mentat-fan-out: writes per-chunk *harness output* (normalized via
#     harness_<name>_normalize) to `$LOGDIR/$slug.jsonl` — a separate stream
#     from audit rows. The audit row for that chunk lives in
#     `<base>/mentat-fan-out-<slug>.jsonl` and is emitted via mentat_audit.
#   - mentat-land-queue: writes container-run / gate stdout+stderr to a
#     per-chunk log file (also named *.jsonl historically) — same separate
#     stream. Both predate S12 and are tracked separately from the audit-row
#     envelope this ADR codifies.
# Strict invariant after S12: any *new* `>>` to a `.jsonl` path under
# .agents/bin/ must go through `mentat_audit` (i.e. `>> "$f"` inside
# `audit.sh::mentat_audit`). The test enumerates every `>>...jsonl` writer
# under .agents/bin/ and asserts the set equals the allowlist.

ALLOWED_JSONL_WRITERS = {
    ".agents/bin/lib/audit.sh",  # the audit row writer (this ADR's contract)
    ".agents/bin/mentat-fan-out",  # harness output stream (separate concern)
    ".agents/bin/mentat-land-queue",  # per-chunk log stream (separate concern)
}


def test_jsonl_write_set_matches_allowlist():
    """Enumerate every `>>...jsonl` writer under .agents/bin/ and assert the
    set equals the audit-envelope allowlist. Catches: a new bin starts
    appending to `.jsonl` without routing through `mentat_audit`."""
    import re

    bin_dir = ROOT / ".agents" / "bin"
    pat = re.compile(r">>\s*[\"']?[^\s\"'|]*(?:\.jsonl|\$\{?(?:f|logf|stderr_path)\b)")
    writers: set[str] = set()
    for p in bin_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in (".jsonc", ".json", ".md", ".pyc"):
            continue
        try:
            text = p.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if pat.search(line):
                # Track the candidate writer; skip if line redirects to a
                # known non-jsonl sidecar like $stderr_path or $WT/.env.
                if "stderr_path" in line or "/.env" in line or "$sidecar" in line:
                    continue
                # Must actually involve a .jsonl path (literal or via $f/$logf)
                if ".jsonl" in line or "$f" in line or "$logf" in line or "${f}" in line or "${logf}" in line:
                    writers.add(str(p.relative_to(ROOT)))
                break
    extra = writers - ALLOWED_JSONL_WRITERS
    missing = ALLOWED_JSONL_WRITERS - writers
    assert not extra, (
        f"new .jsonl writer(s) found under .agents/bin/ that must route through mentat_audit: {sorted(extra)}"
    )
    assert not missing, f"expected allowlisted writer(s) missing — refactor or update allowlist: {sorted(missing)}"


def test_audit_sh_is_sole_audit_row_writer():
    """audit.sh::mentat_audit is the only function that appends to the audit
    row file (`<base>/<agent>-<slug>.jsonl`). Verified by string match on the
    exact redirect form used inside `mentat_audit`."""
    audit_sh = (ROOT / ".agents" / "bin" / "lib" / "audit.sh").read_text()
    assert '>> "$f"' in audit_sh, 'audit.sh::mentat_audit must contain the canonical `>> "$f"` audit-row append'
    # And no other bin contains that exact pattern (audit-row writer alias)
    bin_dir = ROOT / ".agents" / "bin"
    other_hits = []
    for p in bin_dir.rglob("*"):
        if not p.is_file() or p.suffix in (".jsonc", ".json", ".md", ".pyc"):
            continue
        if p.name == "audit.sh":
            continue
        try:
            if '>> "$f"' in p.read_text():
                other_hits.append(str(p.relative_to(ROOT)))
        except (UnicodeDecodeError, PermissionError):
            pass
    assert other_hits == [], f'non-audit.sh writers found using `>> "$f"`: {other_hits}'
