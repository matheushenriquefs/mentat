"""Canonical pydantic schema for mentat audit JSONL events (ADR-0009).

Schema source: .agents/bin/lib/audit-schema.jsonc — single source-of-truth
shared with bash (audit.sh). Add new verbs there, not here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

# ── JSONC loader ──────────────────────────────────────────────────────────────

_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_jsonc(text: str) -> str:
    # Mirrors `sed 's|//.*$||'` in audit.sh. Audit-schema.jsonc uses no `//`
    # inside string literals (documented in its header).
    return _COMMENT_RE.sub("", text)


def _schema_path() -> Path:
    here = Path(__file__).resolve()
    # .agents/lib/audit_schema.py → ../bin/lib/audit-schema.jsonc
    candidate = here.parent.parent / "bin" / "lib" / "audit-schema.jsonc"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"audit-schema.jsonc not found at {candidate}")


_SCHEMA: dict[str, Any] | None = None


def load_schema(force: bool = False) -> dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None or force:
        _SCHEMA = json.loads(_strip_jsonc(_schema_path().read_text()))
    return _SCHEMA


def known_events() -> set[str]:
    return set(load_schema().get("events", {}).keys())


def required_fields(event: str) -> list[str]:
    ev = load_schema().get("events", {}).get(event)
    return list(ev.get("required", [])) if ev else []


# ── Envelope + named payload models (kept for callers + P7 grep tests) ───────

class AuditEnvelope(BaseModel):
    ts: str
    agent: str
    session: str
    event: str
    payload: dict | None = None


class ChunkResultPayload(BaseModel):
    slug: str
    outcome: Literal["success", "eject"]
    tip: str | None = None
    reason: str | None = None
    conflicted_files: list[str] | None = None
    resume_cmd: str | None = None


class ReviewVerdictPayload(BaseModel):
    reviewer: str
    score: float
    veto: bool
    findings: list[str]


class ReviewFinalPayload(ReviewVerdictPayload):
    """End-of-queue composite verdict emitted by mentat-orchestrate."""
    base: str | None = None
    tip: str | None = None
    stdout: str | None = None
    stderr_path: str | None = None


# Verb → named-model lookup, built from JSONC. Only events with a hand-written
# model class get pydantic dispatch; others fall through to envelope-level
# required-field check (validate_row).
_NAMED_MODELS: dict[str, type[BaseModel]] = {
    "land.complete": ChunkResultPayload,
    "review.final":  ReviewFinalPayload,
}


def dispatch_payload(event: str, payload: dict | None) -> BaseModel | None:
    """Validate payload against named pydantic model when one exists.

    Returns None for verbs not covered by a hand-written class — caller falls
    back to `validate_row` for JSONC-driven required-field check.
    """
    model = _NAMED_MODELS.get(event)
    if model is None or payload is None:
        return None
    return model(**payload)


# ── Schema-driven row validation ──────────────────────────────────────────────

def validate_row(row: dict[str, Any]) -> list[str]:
    """Return list of validation issues for one envelope row. Empty = OK."""
    errors: list[str] = []
    try:
        env = AuditEnvelope(**row)
    except ValidationError as e:
        errors.append(f"envelope: {e.errors()[0]['msg']}")
        return errors
    if env.event not in known_events():
        errors.append(f"unknown-event:{env.event}")
        return errors
    payload = env.payload if isinstance(env.payload, dict) else {}
    missing = [k for k in required_fields(env.event) if k not in payload]
    if missing:
        errors.append(f"missing-required:{env.event}:{','.join(missing)}")
    return errors


# ── CLI: validate JSONL files ─────────────────────────────────────────────────

def _validate_file(path: Path, max_samples: int = 5) -> tuple[int, int, list[str]]:
    seen = bad = 0
    samples: list[str] = []
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            seen += 1
            try:
                row = json.loads(s)
            except json.JSONDecodeError as e:
                bad += 1
                if len(samples) < max_samples:
                    samples.append(f"{path}:{lineno}: not-json: {e.msg}")
                continue
            errs = validate_row(row)
            if errs:
                bad += 1
                if len(samples) < max_samples:
                    samples.append(f"{path}:{lineno}: {errs[0]}")
    return seen, bad, samples


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="audit_schema")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate JSONL audit log files")
    v.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.cmd != "validate":
        parser.error(f"unknown command: {args.cmd}")
        return 2
    total_seen = total_bad = 0
    for p in args.files:
        if not p.exists():
            print(f"{p}: missing", file=sys.stderr)
            continue
        seen, bad, samples = _validate_file(p)
        total_seen += seen
        total_bad += bad
        for s in samples:
            print(s)
    print(f"summary: {total_bad}/{total_seen} rows with validation errors")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
