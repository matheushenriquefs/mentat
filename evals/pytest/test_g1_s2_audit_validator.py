"""G1-S2: audit.sh validates + rejects non-JSON, unknown event, missing required.

Spec (plan ~/.agents/plans/mentat-architecture-revamp-g1-audit-substrate.md):
  - `mentat_audit foo bad-event '{}'` exits nonzero; no row appended to .jsonl.
  - `mentat_audit <agent> plan.complete '{"path":"x.md"}'` succeeds.
  - Non-JSON payload rejected with sidecar trail.
  - Missing-required-field rejected with sidecar trail.
  - Sidecar path = `${MENTAT_LOG_PATH}/<repo>/<session>/.stderr/${agent}-${slug}.stderr`.
  - Schema gap closure: `orchestrate.start` event exists (was emitted but unschemaed).
  - `mentat-plan.md` plan.start emit carries the `path` field (strict-per-S2-decision).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SH = ROOT / ".agents" / "bin" / "lib" / "audit.sh"
SCHEMA = ROOT / ".agents" / "bin" / "lib" / "audit-schema.jsonc"
PLAN_CMD_MD = ROOT / ".agents" / "commands" / "mentat-plan.md"


def _emit(event: str, payload: str, *, agent: str = "test-agent"):
    """Invoke `mentat_audit` in a clean MENTAT_LOG_PATH tempdir.

    Returns (returncode, stderr_str, jsonl_lines, sidecar_lines).
    """
    td = Path(tempfile.mkdtemp(prefix="mentat-s2-"))
    try:
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("MENTAT_")},
            "MENTAT_LOG_PATH": str(td),
            "MENTAT_SESSION": "1700000000-12345",
            "MENTAT_REPO": "testrepo",
            "MENTAT_SLUG": "testslug",
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        script = f"source {AUDIT_SH} && mentat_audit {agent} {event} {shlex_quote(payload)}"
        proc = subprocess.run(
            ["bash", "-c", script],
            env=env,
            capture_output=True,
            text=True,
        )
        base = td / "testrepo" / "1700000000-12345"
        jsonl = base / f"{agent}-testslug.jsonl"
        sidecar = base / ".stderr" / f"{agent}-testslug.stderr"
        return (
            proc.returncode,
            proc.stderr,
            jsonl.read_text().splitlines() if jsonl.exists() else [],
            sidecar.read_text().splitlines() if sidecar.exists() else [],
        )
    finally:
        shutil.rmtree(td, ignore_errors=True)


def shlex_quote(s: str) -> str:
    # Single-quote, escaping any embedded single quotes.
    return "'" + s.replace("'", "'\"'\"'") + "'"


# ── Schema gap closure ───────────────────────────────────────────────────────


def test_schema_strip_comments_jq_parses():
    out = subprocess.run(
        ["bash", "-c", f"sed 's|//.*$||' {SCHEMA} | jq -c '.events | keys | length'"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) > 0


def test_schema_includes_orchestrate_start():
    out = subprocess.run(
        ["bash", "-c", f"sed 's|//.*$||' {SCHEMA} | jq -e '.events[\"orchestrate.start\"].required'"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, "orchestrate.start missing from schema"


# ── Validator behavior ───────────────────────────────────────────────────────


def test_unknown_event_rejected():
    rc, _stderr, jsonl, sidecar = _emit("bad-event", "{}")
    assert rc != 0, "unknown event should exit nonzero"
    assert jsonl == [], "unknown event must not be appended to .jsonl"
    assert any("bad-event" in line for line in sidecar), f"sidecar must mention rejected event; got {sidecar!r}"


def test_non_json_payload_rejected():
    rc, _stderr, jsonl, sidecar = _emit("plan.complete", "not-json-at-all")
    assert rc != 0, "non-JSON payload should exit nonzero"
    assert jsonl == [], "non-JSON payload must not produce .jsonl row"
    assert sidecar, "sidecar must be populated on non-JSON rejection"


def test_missing_required_field_rejected():
    rc, _stderr, jsonl, sidecar = _emit("plan.complete", "{}")
    assert rc != 0, "plan.complete requires `path`; empty {} should reject"
    assert jsonl == [], "missing-required must not produce .jsonl row"
    assert any(("path" in line) or ("required" in line) for line in sidecar), (
        f"sidecar must cite missing field; got {sidecar!r}"
    )


def test_known_event_with_required_succeeds():
    rc, _stderr, jsonl, sidecar = _emit("plan.complete", '{"path":"x.md"}')
    assert rc == 0, f"valid emit must exit 0 (stderr={_stderr!r})"
    assert len(jsonl) == 1, f"valid emit must write exactly one row; got {jsonl!r}"
    row = json.loads(jsonl[0])
    assert row["event"] == "plan.complete"
    assert row["payload"] == {"path": "x.md"}
    assert row["agent"] == "test-agent"
    assert row["session"] == "1700000000-12345"
    assert sidecar == [], "valid emit must not touch sidecar"


def test_known_event_with_optional_field_succeeds():
    # land.complete: required ["slug","outcome","tip"], optional ["reason","conflicted_files","resume_cmd"]
    rc, _stderr, jsonl, _sidecar = _emit(
        "land.complete",
        '{"slug":"s","outcome":"success","tip":"abc1234","reason":"ok"}',
    )
    assert rc == 0, f"valid emit with optional field must exit 0 (stderr={_stderr!r})"
    assert len(jsonl) == 1


def test_sidecar_path_layout():
    """Sidecar must land at $base/.stderr/<agent>-<slug>.stderr per plan."""
    td = Path(tempfile.mkdtemp(prefix="mentat-s2-"))
    try:
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("MENTAT_")},
            "MENTAT_LOG_PATH": str(td),
            "MENTAT_SESSION": "1700000000-12345",
            "MENTAT_REPO": "testrepo",
            "MENTAT_SLUG": "myslug",
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        subprocess.run(
            ["bash", "-c", f"source {AUDIT_SH} && mentat_audit special-agent bad-event '{{}}'"],
            env=env,
            capture_output=True,
            text=True,
        )
        sidecar = td / "testrepo" / "1700000000-12345" / ".stderr" / "special-agent-myslug.stderr"
        assert sidecar.exists(), f"sidecar missing at expected layout: {sidecar}"
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ── Emit-site alignment (companion changes shipped with S2) ──────────────────


def test_plan_command_emit_carries_path_on_start():
    """Per S2 strict decision: plan.start emit must include `path` field."""
    content = PLAN_CMD_MD.read_text()
    matches = re.findall(
        r"mentat_audit\s+mentat-plan\s+plan\.start\s+(\S+)",
        content,
    )
    assert matches, "no plan.start emit found in mentat-plan.md"
    for payload_token in matches:
        # Accept any quoted JSON or "$var" carrying a path key
        assert "path" in payload_token, f"plan.start payload must mention `path`; got {payload_token!r}"
