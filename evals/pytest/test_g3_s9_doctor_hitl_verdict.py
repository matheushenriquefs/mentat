"""G3-S9: mentat-doctor distinguishes reason:hitl-ambiguity in verdict output.

Spec (~/.agents/plans/mentat-architecture-revamp-g3-harness-afk.md S9):
  - Doctor's verdict logic: `reason: hitl-ambiguity` → suspect "ambiguous
    plan, AFK chunk needed a design call". Different output section than
    `implement-fail`.
  - Verify: doctor invoked on a HITL-tagged session produces output naming
    the suspect, not the generic placeholder.

ADR-0010 §3 + §G3-S9 cross-reference: the typed `reason` field flows from
G3-S8 land.complete audit row into doctor's diagnosis. Doctor names the
suspect — the human operator reading the diagnosis must see "design call
needed" not "<describe expected outcome>".

Contract:
  - When any chunk audit row has `payload.reason == "hitl-ambiguity"`, doctor's
    output includes:
      * a distinct verdict section (header containing "HITL" or "hitl-ambiguity")
      * the suspect phrase ("ambiguous plan" / "design call")
      * a back-reference to ADR-0010
      * explicit guidance that this is NOT implement-fail
  - When no such row is present, doctor's output MUST NOT include the HITL
    suspect (no false positives — operators must not chase ghosts).
  - Drift guard: ADR-0010 §G3-S9 must continue to name the doctor mapping.

Blocked-by: S3 (ADR-0010) — done; S8 (land-queue emits the row) — done.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")


import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCTOR = ROOT / ".agents" / "bin" / "mentat-doctor"
ADR_0010 = ROOT / ".agents" / "docs" / "adr" / "0010-hitl-routing.md"

HITL_REASON = "hitl-ambiguity"
SUSPECT_PHRASES = ["ambiguous plan", "design call"]


# -- Fixture helpers ---------------------------------------------------------


def _write_chunk_jsonl(path: Path, rows: list[dict]) -> None:
    """Write a chunk audit JSONL file (one JSON object per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _make_row(
    *,
    agent: str = "mentat-land-queue",
    event: str = "land.complete",
    session: str = "test-session",
    payload: dict | None = None,
) -> dict:
    return {
        "ts": "2026-06-07T00:00:00Z",
        "agent": agent,
        "session": session,
        "event": event,
        "payload": payload or {},
    }


def _run_doctor(home: Path, log_path: Path, repo: str, session: str, slug: str) -> tuple[str, Path]:
    """Invoke mentat-doctor with the given env; return (stdout, diagnosis path)."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["MENTAT_LOG_PATH"] = str(log_path)
    env["MENTAT_REPO"] = repo
    env["MENTAT_SESSION"] = session
    # Disable docker query — test env has no container with the slug label.
    env["PATH"] = env.get("PATH", "")
    result = subprocess.run(
        [str(DOCTOR), slug],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"mentat-doctor exited {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Doctor's last stdout line is "mentat-doctor: diagnosis written to <path>".
    m = re.search(r"diagnosis written to (.+)$", result.stdout.strip())
    assert m, f"could not parse diagnosis path from stdout: {result.stdout!r}"
    diag = Path(m.group(1))
    assert diag.is_file(), f"diagnosis file missing: {diag}"
    return result.stdout, diag


@pytest.fixture
def env_with_hitl_row(tmp_path: Path):
    """Spin up a fake log tree with a single chunk jsonl containing one
    hitl-ambiguity row. Yield (home, log_path, repo, session, slug, diag_text_fn)."""
    home = tmp_path / "home"
    home.mkdir()
    log_path = tmp_path / "logs"
    repo = "test-repo"
    session = f"test-session-{int(time.time() * 1000)}"
    slug = "chunk-hitl"
    chunk_log = log_path / repo / session / f"{slug}.jsonl"
    _write_chunk_jsonl(
        chunk_log,
        [
            _make_row(
                event="land.complete",
                session=session,
                payload={"slug": slug, "outcome": "eject", "tip": "abc1234", "reason": HITL_REASON},
            ),
        ],
    )
    return home, log_path, repo, session, slug


@pytest.fixture
def env_with_implement_fail_row(tmp_path: Path):
    """Same fixture shape, but with a non-HITL eject (generic gate-fail)."""
    home = tmp_path / "home"
    home.mkdir()
    log_path = tmp_path / "logs"
    repo = "test-repo"
    session = f"test-session-{int(time.time() * 1000)}"
    slug = "chunk-gate-fail"
    chunk_log = log_path / repo / session / f"{slug}.jsonl"
    _write_chunk_jsonl(
        chunk_log,
        [
            _make_row(
                event="land.complete",
                session=session,
                payload={"slug": slug, "outcome": "eject", "tip": "def5678", "reason": "gate-fail"},
            ),
        ],
    )
    return home, log_path, repo, session, slug


# -- HITL path: doctor names the suspect -------------------------------------


def test_doctor_emits_hitl_section_for_hitl_chunk(env_with_hitl_row):
    """When chunk audit carries reason:hitl-ambiguity, doctor must emit a
    section whose header surfaces HITL — not a generic placeholder."""
    home, log_path, repo, session, slug = env_with_hitl_row
    _, diag = _run_doctor(home, log_path, repo, session, slug)
    text = diag.read_text()
    # Header heuristic: a markdown section header line containing HITL/hitl.
    has_header = any(
        line.startswith("#") and ("HITL" in line or "hitl-ambiguity" in line) for line in text.splitlines()
    )
    assert has_header, (
        f"diagnosis must include a HITL section header (line starting with # "
        f"containing 'HITL' or 'hitl-ambiguity'); got:\n{text}"
    )


def test_doctor_names_suspect_for_hitl_chunk(env_with_hitl_row):
    """S9 verify: doctor must name the suspect — 'ambiguous plan, AFK chunk
    needed a design call' (or that semantic pair, lowercase-tolerant)."""
    home, log_path, repo, session, slug = env_with_hitl_row
    _, diag = _run_doctor(home, log_path, repo, session, slug)
    text = diag.read_text().lower()
    for phrase in SUSPECT_PHRASES:
        assert phrase in text, f"diagnosis must name HITL suspect phrase {phrase!r}; got:\n{text}"


def test_doctor_cites_adr_0010_for_hitl_chunk(env_with_hitl_row):
    """The HITL section must back-reference ADR-0010 (canonical source)."""
    home, log_path, repo, session, slug = env_with_hitl_row
    _, diag = _run_doctor(home, log_path, repo, session, slug)
    text = diag.read_text()
    assert re.search(r"ADR[-\s]?0010|0010-hitl-routing", text), (
        f"diagnosis must cite ADR-0010 in HITL section; got:\n{text}"
    )


def test_doctor_distinguishes_hitl_from_implement_fail(env_with_hitl_row):
    """S9 spec: 'different output section than implement-fail'. The diagnosis
    must say this is NOT implement-fail — operators must not collapse them."""
    home, log_path, repo, session, slug = env_with_hitl_row
    _, diag = _run_doctor(home, log_path, repo, session, slug)
    text = diag.read_text().lower()
    # The diagnosis must contain prose explicitly excluding implement-fail
    # for HITL chunks (i.e. "not implement-fail", "not a implement-fail",
    # "≠ implement-fail" etc).
    assert re.search(r"not\s+(an?\s+)?implement-fail|≠\s*implement-fail|distinct\s+from\s+implement-fail", text), (
        f"diagnosis must state HITL is NOT implement-fail; got:\n{text}"
    )


def test_doctor_reads_payload_reason_field(env_with_hitl_row):
    """Drift guard: doctor must inspect `payload.reason` (not top-level
    `reason`). The audit schema (G1-S3) nests verdict fields under payload."""
    # Constructive test: the fixture writes payload.reason. If the test for
    # naming-the-suspect passes, doctor must have walked payload.reason.
    # This test is the explicit assertion of that contract via fixture shape.
    home, log_path, repo, session, slug = env_with_hitl_row
    _, diag = _run_doctor(home, log_path, repo, session, slug)
    text = diag.read_text()
    # Sanity: the chunk log itself nests reason under payload (no top-level).
    chunk_log = log_path / repo / session / f"{slug}.jsonl"
    raw = chunk_log.read_text()
    assert '"reason":"hitl-ambiguity"' in raw or '"reason": "hitl-ambiguity"' in raw, (
        "fixture must nest reason under payload — otherwise the test is vacuous"
    )
    assert HITL_REASON in text, f"diagnosis must surface payload.reason value {HITL_REASON!r}; got:\n{text}"


# -- Non-HITL path: no false positives ---------------------------------------


def test_doctor_omits_hitl_suspect_for_non_hitl_chunk(env_with_implement_fail_row):
    """Negative: a chunk with reason:gate-fail must NOT receive the HITL
    suspect phrasing — that would mislead the operator."""
    home, log_path, repo, session, slug = env_with_implement_fail_row
    _, diag = _run_doctor(home, log_path, repo, session, slug)
    text = diag.read_text().lower()
    # The suspect noun phrase ("ambiguous plan ... design call") must be
    # absent when no hitl-ambiguity row exists.
    assert "ambiguous plan" not in text, f"non-HITL diagnosis must NOT name HITL suspect 'ambiguous plan'; got:\n{text}"
    assert "design call" not in text, f"non-HITL diagnosis must NOT mention 'design call'; got:\n{text}"


def test_doctor_omits_hitl_section_when_no_chunk_log(tmp_path: Path):
    """Edge: empty session (no chunk jsonl exists). Doctor must fall back to
    MENTAT_SESSION env path and exit cleanly — no HITL suspect injected."""
    home = tmp_path / "home"
    home.mkdir()
    log_path = tmp_path / "logs"
    repo = "test-repo"
    session = "empty-session"
    slug = "ghost-slug"
    # Create the session dir but no chunk file → doctor uses env fallback.
    (log_path / repo / session).mkdir(parents=True)
    home_env, _, _, _, _ = home, log_path, repo, session, slug
    env = os.environ.copy()
    env["HOME"] = str(home_env)
    env["MENTAT_LOG_PATH"] = str(log_path)
    env["MENTAT_REPO"] = repo
    env["MENTAT_SESSION"] = session
    result = subprocess.run(
        [str(DOCTOR), slug],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    # Doctor exits 0 because env-fallback found the session dir.
    assert result.returncode == 0, f"unexpected rc={result.returncode}: stderr={result.stderr!r}"
    m = re.search(r"diagnosis written to (.+)$", result.stdout.strip())
    assert m, f"no diagnosis path: {result.stdout!r}"
    text = Path(m.group(1)).read_text().lower()
    assert "ambiguous plan" not in text, "ghost slug (no chunk jsonl) must not summon HITL suspect"


# -- Source-level invariants -------------------------------------------------


def test_doctor_source_references_hitl_ambiguity():
    """Source-level invariant: mentat-doctor must reference hitl-ambiguity
    literal — otherwise the runtime detection path can never fire."""
    text = DOCTOR.read_text()
    assert HITL_REASON in text, f"mentat-doctor must reference {HITL_REASON!r} literal (ADR-0010 §3)"


def test_doctor_source_references_adr_0010():
    """Source citation: doctor source must point at ADR-0010 — the canonical
    contract definition. Allows future maintainers to grep back."""
    text = DOCTOR.read_text()
    assert re.search(r"ADR[-\s]?0010|0010-hitl-routing|G3-S9", text), (
        "mentat-doctor must cite ADR-0010 (canonical HITL contract) or G3-S9"
    )


def test_doctor_source_names_suspect_phrase():
    """Source-level invariant: the suspect phrase must appear in the doctor
    source — that's how it ends up in the diagnosis output. Drift guard
    against output template rewrites that drop the suspect."""
    text = DOCTOR.read_text().lower()
    for phrase in SUSPECT_PHRASES:
        assert phrase in text, f"mentat-doctor source must contain HITL suspect phrase {phrase!r}"


# -- ADR-0010 drift guard ----------------------------------------------------


def test_adr_0010_names_doctor_mapping():
    """ADR-0010 must name S9's doctor distinction — if the ADR renames the
    reason or drops the doctor reference, this test forces the doctor to follow."""
    src = ADR_0010.read_text()
    assert "mentat-doctor" in src, "ADR-0010 must reference mentat-doctor"
    assert HITL_REASON in src, f"ADR-0010 must define {HITL_REASON!r} reason"
    # The G3-S9 line in ADR-0010 specifically names the doctor mapping.
    assert "G3-S9" in src, "ADR-0010 must cross-reference G3-S9 (doctor distinguishes HITL verdict)"
