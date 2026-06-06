"""Canonical pydantic schema for mentat audit JSONL events (ADR-0009)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AuditEnvelope(BaseModel):
    ts: str
    agent: str
    session: str
    event: str
    payload: dict | None = None


class ChunkResultPayload(BaseModel):
    slug: str
    outcome: Literal["success", "error"]
    tip: str | None = None
    reason: str | None = None


class ReviewVerdictPayload(BaseModel):
    reviewer: str
    score: float
    veto: bool
    findings: list[str]


class ReviewFinalPayload(ReviewVerdictPayload):
    """End-of-queue composite verdict emitted by mentat-orchestrate."""
    base: str | None = None
    tip: str | None = None


class SyncCompletePayload(BaseModel):
    upstreams: list[str]
    changed: int


class PreflightPayload(BaseModel):
    slices: list[dict]  # [{id, status: "DONE"|"MISSING", predicate}]


class RenameDonePayload(BaseModel):
    old: str
    new: str


class StaleRefSweepPayload(BaseModel):
    terms: list[str]
    hits: int


class ReviewDismissPayload(BaseModel):
    reviewer: str
    score: float
    reason: str  # must enumerate refuted findings


_VERB_MAP: dict[str, type[BaseModel]] = {
    "land.complete": ChunkResultPayload,
    "review.final": ReviewFinalPayload,
    "sync.complete": SyncCompletePayload,
    "implement.preflight": PreflightPayload,
    "rename.complete": RenameDonePayload,
    "staleref.sweep": StaleRefSweepPayload,
    "review.dismiss": ReviewDismissPayload,
}


def dispatch_payload(event: str, payload: dict | None) -> BaseModel | None:
    """Validate payload against its event-verb model. Returns None for unknown verbs."""
    model = _VERB_MAP.get(event)
    if model is None or payload is None:
        return None
    return model(**payload)
