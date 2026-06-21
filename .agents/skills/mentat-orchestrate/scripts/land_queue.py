"""Serial land-queue: rebase + gate + FF-merge or eject per chunk."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import git as _git  # noqa: E402
from lib.events import EjectReason, bind, ejected_payload  # noqa: E402
from lib.loader import load_sibling  # noqa: E402

_utils = load_sibling(__file__, "plans")

_emit_event = bind("mentat-orchestrate")


class Chunk(NamedTuple):
    slug: str
    worktree: Path


def _rebase_chunk(chunk: Chunk, holding: str) -> tuple[str | None, str | None]:
    """Rebase chunk onto holding. Returns (tip_sha, error_message)."""
    # mentat-container up modifies .devcontainer/ files in every worktree but
    # never stages them; git rebase refuses "You have unstaged changes".
    _git.discard_path(chunk.worktree, ".devcontainer/")
    return _git.rebase_ff_only(chunk.worktree, holding)


def _run_gates(chunk: Chunk) -> tuple[str, str]:
    return _utils.run_gates(chunk.worktree)


def _ff_merge(chunk: Chunk, holding: str) -> str | None:
    """FF-merge chunk HEAD onto the explicit holding branch.

    Returns None on success, ``"not-ff"`` when the merge is genuinely not
    fast-forward, or ``"git-error"`` for any git/setup failure.
    """
    return _git.ff_merge(chunk.worktree, holding)


def _teardown_container(slug: str) -> None:
    from lib import devcontainer

    ok = devcontainer.down(slug)
    _emit_event("chunk.teardown", {"slug": slug, "ok": ok})


def land(chunk: Chunk, *, holding: str) -> dict[str, object]:
    """Land one chunk. Returns verdict dict."""
    tip, err = _rebase_chunk(chunk, holding)
    if err:
        _emit_event(
            "chunk.ejected",
            ejected_payload(chunk.slug, EjectReason.REBASE_CONFLICTED, str(chunk.worktree)),
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": EjectReason.REBASE_CONFLICTED,
            "tip": None,
            "conflicted_files": [],
        }

    verdict, message = _run_gates(chunk)
    if verdict == "block":
        _emit_event(
            "chunk.ejected",
            ejected_payload(chunk.slug, EjectReason.GATE_FAILED, str(chunk.worktree)),
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": EjectReason.GATE_FAILED,
            "tip": tip,
            "findings": [message],
        }

    ff_err = _ff_merge(chunk, holding)
    if ff_err is not None:
        reason = EjectReason.NOT_FF if ff_err == "not-ff" else EjectReason.GIT_ERROR
        _emit_event(
            "chunk.ejected",
            ejected_payload(chunk.slug, reason, str(chunk.worktree)),
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": reason,
            "tip": tip,
        }

    _emit_event(
        "chunk.landed",
        {
            "slug": chunk.slug,
            "sha": tip or "",
            "holding": holding,
        },
    )
    return {
        "slug": chunk.slug,
        "status": "success",
        "tip": tip,
    }


def drain(
    chunks: list[Chunk],
    *,
    holding: str,
    on_landed: Callable[[str], None] | None = None,
    on_ejected: Callable[[str], list[str]] | None = None,
    next_ready: Callable[[list[str]], str | None] | None = None,
) -> list[dict[str, object]]:
    """Land all chunks serially.

    Without `next_ready`: iterate chunks in input order (no-dep path).

    With `next_ready`: pull the next chunk whose plan deps are wholly landed
    via `next_ready(candidates)`. Land it, call on_landed / on_ejected,
    repeat until pending empty or no chunk ready (stalled verdict).
    """
    _on_landed = on_landed or (lambda _: None)
    _on_ejected = on_ejected or (lambda _: [])

    if next_ready is None:
        results: list[dict[str, object]] = []
        for chunk in chunks:
            verdict = land(chunk, holding=holding)
            results.append(verdict)
            _teardown_container(chunk.slug)
        return results

    by_slug: dict[str, Chunk] = {c.slug: c for c in chunks}
    pending: list[str] = [c.slug for c in chunks]
    results = []

    while pending:
        ready = next_ready(pending)
        if ready is None:
            stalled_pending = list(pending)
            for slug in stalled_pending:
                _teardown_container(slug)
            results.append(
                {
                    "slug": None,
                    "status": "stalled",
                    "pending": stalled_pending,
                }
            )
            return results
        verdict = land(by_slug[ready], holding=holding)
        results.append(verdict)
        _teardown_container(ready)
        pending.remove(ready)
        if verdict.get("status") == "success":
            _on_landed(ready)
            continue

        # Eject cascade: every chunk that transitively depends on `ready`
        # is preemptively ejected — no rebase, no gate, payload-only
        # extension to chunk.ejected (ADR-0007).
        cascaded = _on_ejected(ready)
        for downstream in cascaded:
            if downstream not in pending:
                continue
            chunk = by_slug.get(downstream)
            where = str(chunk.worktree) if chunk else ""
            _emit_event(
                "chunk.ejected",
                ejected_payload(downstream, EjectReason.UPSTREAM_EJECTED, where, upstream=ready),
            )
            results.append(
                {
                    "slug": downstream,
                    "status": "eject",
                    "reason": EjectReason.UPSTREAM_EJECTED,
                    "upstream": ready,
                }
            )
            pending.remove(downstream)
            _teardown_container(downstream)

    return results
