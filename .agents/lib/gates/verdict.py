"""Reviewer verdict domain model — a typed, validated parse of reviewer JSON.

Structured-output borrow (mentat-owned, harness-agnostic): a reviewer emits JSON
matching this shape and the gate parser validates it into frozen dataclasses,
instead of regex-scraping free-text output. Any harness that emits the JSON works —
there is no dependency on a specific harness tool. This kills a parse-fragility
class: the score gate reads typed fields, not shapes it guessed at.

`surviving_mutants` is advisory (ADR-0016): it rides on the verdict as `file:line`
strings but never contributes to the pass/block decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

Severity = Literal["low", "medium", "high"]
_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high"})
_CLEAN_VETO = "clean"


class VerdictError(ValueError):
    """Raised when reviewer JSON does not validate into a ReviewVerdict."""


@dataclass(frozen=True)
class Finding:
    """One reviewer finding — a concrete gap at a source location."""

    file: str
    line: int
    reason: str
    severity: Severity = "medium"


@dataclass(frozen=True)
class ReviewVerdict:
    """A validated reviewer verdict.

    `veto` retains the raw signal: `None` or the exact string ``"clean"`` are the
    only safe values (fail-closed — any other value is a tripped veto). `veto_clean`
    encodes that policy so callers do not re-derive it.
    """

    reviewer: str
    asserts_plan: float
    veto: str | None
    findings: tuple[Finding, ...] = ()
    surviving_mutants: tuple[str, ...] = ()

    @property
    def veto_clean(self) -> bool:
        """True only when the veto is absent or the exact string ``"clean"``."""
        return self.veto is None or self.veto == _CLEAN_VETO

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ReviewVerdict:
        """Validate a reviewer's raw JSON dict into a ReviewVerdict.

        Fail-loud: a malformed field raises VerdictError rather than silently
        coercing to a passing value. A tripped veto is a valid parse (it blocks
        downstream), so a non-string veto is kept as its ``str`` form, not rejected.
        """
        reviewer = str(raw.get("reviewer", ""))
        asserts_plan = _coerce_score(raw.get("asserts_plan", 0.0))
        veto = _coerce_veto(raw.get("veto"))
        findings = _coerce_findings(raw.get("findings"))
        surviving_mutants = _coerce_str_tuple(raw.get("surviving_mutants"), key="surviving_mutants")
        return cls(
            reviewer=reviewer,
            asserts_plan=asserts_plan,
            veto=veto,
            findings=findings,
            surviving_mutants=surviving_mutants,
        )


def _coerce_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise VerdictError(f"asserts_plan must be a number, got {value!r}") from exc


def _coerce_veto(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # A truthy non-string veto is still a tripped veto — keep it as its str form so
    # veto_clean rejects it, rather than dropping the signal.
    return str(value)


def _coerce_findings(value: Any) -> tuple[Finding, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise VerdictError(f"findings must be a list, got {type(value).__name__}")
    items = cast(list[Any], value)
    return tuple(_coerce_finding(item) for item in items)


def _coerce_finding(item: Any) -> Finding:
    if not isinstance(item, dict):
        raise VerdictError(f"finding must be an object, got {type(item).__name__}")
    data = cast(dict[str, Any], item)
    severity = str(data.get("severity", "medium"))
    if severity not in _SEVERITIES:
        raise VerdictError(f"finding severity must be one of {sorted(_SEVERITIES)}, got {severity!r}")
    return Finding(
        file=str(data.get("file", "")),
        line=int(data.get("line", 0)),
        reason=str(data.get("reason", "")),
        severity=cast(Severity, severity),  # membership checked above
    )


def _coerce_str_tuple(value: Any, *, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise VerdictError(f"{key} must be a list, got {type(value).__name__}")
    items = cast(list[Any], value)
    return tuple(str(item) for item in items)


__all__ = ["Finding", "ReviewVerdict", "Severity", "VerdictError"]
