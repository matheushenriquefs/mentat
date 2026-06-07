"""G1-S3: audit_schema.py loads .agents/bin/lib/audit-schema.jsonc at runtime.

Spec (plan ~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - Strip duplicated schema constants from audit_schema.py.
  - Load .agents/bin/lib/audit-schema.jsonc (strip `//` comments + json.loads).
  - Expose `known_events()`, `required_fields(event)`, `validate_row(row)`.
  - CLI: `python -m audit_schema validate <file>` reports zero crashes on
    real `~/.agents/mentat/logs/**/*.jsonl` corpus.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCHEMA_PY = ROOT / ".agents" / "lib" / "audit_schema.py"
AUDIT_SCHEMA_JSONC = ROOT / ".agents" / "bin" / "lib" / "audit-schema.jsonc"

sys.path.insert(0, str(ROOT / ".agents" / "lib"))


@pytest.fixture(autouse=True)
def _reload_schema_module():
    # Force fresh import each test so cached _SCHEMA is rebuilt.
    sys.modules.pop("audit_schema", None)
    yield
    sys.modules.pop("audit_schema", None)


# ── JSONC source-of-truth ─────────────────────────────────────────────────────

def test_audit_schema_py_no_hardcoded_verb_map():
    """S3: hand-maintained _VERB_MAP must vanish; dispatch sourced from JSONC."""
    src = AUDIT_SCHEMA_PY.read_text()
    assert "_VERB_MAP" not in src, "hardcoded _VERB_MAP must be removed (S3)"


def test_audit_schema_py_references_jsonc():
    src = AUDIT_SCHEMA_PY.read_text()
    assert "audit-schema.jsonc" in src, "audit_schema.py must load audit-schema.jsonc"


def test_known_events_matches_jsonc_keys():
    import audit_schema
    raw = AUDIT_SCHEMA_JSONC.read_text()
    stripped = re.sub(r"//[^\n]*", "", raw)
    expected = set(json.loads(stripped)["events"].keys())
    assert audit_schema.known_events() == expected


def test_required_fields_plan_start():
    import audit_schema
    assert audit_schema.required_fields("plan.start") == ["path"]


def test_required_fields_unknown_event_empty():
    import audit_schema
    assert audit_schema.required_fields("nope.never") == []


# ── validate_row contract ────────────────────────────────────────────────────

def _envelope(event: str, payload: dict | None) -> dict:
    return {
        "ts": "2026-06-07T12:00:00Z",
        "agent": "test-agent",
        "session": "1700000000-12345",
        "event": event,
        "payload": payload,
    }


def test_validate_row_clean_pass():
    import audit_schema
    errs = audit_schema.validate_row(_envelope("plan.complete", {"path": "x.md"}))
    assert errs == [], f"clean row must validate; got {errs!r}"


def test_validate_row_unknown_event():
    import audit_schema
    errs = audit_schema.validate_row(_envelope("ghost.event", {}))
    assert errs and "unknown-event" in errs[0]


def test_validate_row_missing_required():
    import audit_schema
    errs = audit_schema.validate_row(_envelope("plan.complete", {}))
    assert errs and "missing-required" in errs[0]
    assert "path" in errs[0]


def test_validate_row_envelope_broken():
    import audit_schema
    # Missing `session` field.
    errs = audit_schema.validate_row({
        "ts": "2026-06-07T12:00:00Z",
        "agent": "x",
        "event": "plan.start",
        "payload": {"path": "x.md"},
    })
    assert errs and "envelope" in errs[0]


# ── Backward-compat: named pydantic classes still present (P7) ───────────────

def test_named_models_preserved():
    import audit_schema
    assert hasattr(audit_schema, "AuditEnvelope")
    assert hasattr(audit_schema, "ChunkResultPayload")
    assert hasattr(audit_schema, "ReviewVerdictPayload")
    assert hasattr(audit_schema, "dispatch_payload")


def test_dispatch_payload_land_complete():
    import audit_schema
    model = audit_schema.dispatch_payload(
        "land.complete",
        {"slug": "s1", "outcome": "success", "tip": "abc1234"},
    )
    assert model is not None
    assert model.slug == "s1"


def test_dispatch_payload_unknown_returns_none():
    import audit_schema
    assert audit_schema.dispatch_payload("nope.never", {}) is None


# ── CLI: python audit_schema.py validate <files> ─────────────────────────────

def _write_jsonl(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(AUDIT_SCHEMA_PY), *args],
        capture_output=True,
        text=True,
    )


def test_cli_validate_clean_file_exits_zero(tmp_path):
    f = _write_jsonl(tmp_path, "clean.jsonl", [
        _envelope("plan.start", {"path": "p.md"}),
        _envelope("plan.complete", {"path": "p.md"}),
    ])
    proc = _run_cli("validate", str(f))
    assert proc.returncode == 0, f"clean file must exit 0; stderr={proc.stderr!r}"


def test_cli_validate_dirty_file_exits_nonzero(tmp_path):
    f = _write_jsonl(tmp_path, "dirty.jsonl", [
        _envelope("plan.complete", {}),  # missing required `path`
    ])
    proc = _run_cli("validate", str(f))
    assert proc.returncode != 0, "dirty file must exit nonzero"
    assert "missing-required" in proc.stdout


def test_cli_validate_non_json_line(tmp_path):
    f = tmp_path / "garbled.jsonl"
    f.write_text("not-json-at-all\n")
    proc = _run_cli("validate", str(f))
    assert proc.returncode != 0
    assert "not-json" in proc.stdout or "json" in proc.stdout.lower()


# ── Corpus smoke: real ~/.agents/mentat/logs rows do not crash ───────────────

def test_corpus_validation_does_not_crash():
    """Plan verify: `python -m audit_schema validate ~/.agents/mentat/logs/<recent>`
    reports zero crashes (warnings on legacy rows OK — exit code may be nonzero)."""
    log_root = Path.home() / ".agents" / "mentat" / "logs"
    if not log_root.exists():
        pytest.skip(f"no corpus at {log_root}")
    files = sorted(log_root.rglob("*.jsonl"))[-5:]
    if not files:
        pytest.skip("no .jsonl files in corpus")
    proc = subprocess.run(
        [sys.executable, str(AUDIT_SCHEMA_PY), "validate", *map(str, files)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Crash = python traceback. Non-zero exit from missing-required is fine.
    assert "Traceback" not in proc.stderr, f"corpus validation crashed: {proc.stderr}"
