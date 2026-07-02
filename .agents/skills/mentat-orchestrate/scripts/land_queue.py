"""Serial land-queue: rebase + gate + FF-merge or eject per chunk."""

from __future__ import annotations

import concurrent.futures
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


def _speculative_land_enabled() -> bool:
    """Config flag ``speculative_land`` (default False).

    OFF ships by default; serial rebase-per-chunk stays the safe path. ON opts
    an independent batch into speculative-parallel gating (see ``_drain_speculative``).
    """
    return bool(_utils.read_config().get("speculative_land", False))


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


def _drain_serial(chunks: list[Chunk], *, holding: str) -> list[dict[str, object]]:
    """Land chunks one-by-one in input order (rebase → gate → FF-merge each).

    The safe path: every chunk is rebased onto the live holding tip and gated
    against it, so a red chunk ejects with its real reason and never blocks a
    sibling. Also the fallback target when a speculative wave collides.
    """
    results: list[dict[str, object]] = []
    for chunk in chunks:
        verdict = land(chunk, holding=holding)
        results.append(verdict)
        _teardown_container(chunk.slug)
    return results


def _speculative_gate(chunk: Chunk, holding: str) -> tuple[Chunk, bool]:
    """Rebase chunk onto holding + run gates (no merge). Returns (chunk, passed).

    A rebase conflict or a blocking gate verdict counts as not-passed; the caller
    abandons speculation and re-drains serially so the failure ejects cleanly.
    """
    _tip, err = _rebase_chunk(chunk, holding)
    if err is not None:
        return (chunk, False)
    verdict, _message = _run_gates(chunk)
    return (chunk, verdict != "block")


def _drain_speculative(chunks: list[Chunk], *, holding: str) -> list[dict[str, object]]:
    """Speculative-parallel land (bors batch / Zuul speculative).

    Assume the whole batch lands: gate every chunk *concurrently* against the
    current holding tip. This is sound only for an independent batch — the
    ``next_ready is None`` path, which carries no cross-chunk deps — so a chunk's
    gate result never depends on a sibling's changes.

    If every candidate passes, FF-merge serially, re-rebasing each onto the
    advancing tip (the merge is cheap; the gate was the expensive part, already
    paid in parallel). Any gate or merge failure abandons the optimistic path and
    falls back to a serial re-drain of the not-yet-landed chunks, so ejects land
    with their real reasons. Serial stays the safe path; this only cuts the O(N)
    gate latency for large independent batches.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(chunks)) as ex:
        futures = [ex.submit(_speculative_gate, chunk, holding) for chunk in chunks]
        gated = [f.result() for f in futures]

    if any(not passed for _chunk, passed in gated):
        return _drain_serial(chunks, holding=holding)

    results: list[dict[str, object]] = []
    for i, chunk in enumerate(chunks):
        tip, err = _rebase_chunk(chunk, holding)
        ff_err = _ff_merge(chunk, holding) if err is None else None
        if err is not None or ff_err is not None:
            # Speculative merge collided with the advancing tip — re-drain this
            # chunk and everything after it serially for correct ejects.
            results.extend(_drain_serial(chunks[i:], holding=holding))
            return results
        _emit_event(
            "chunk.landed",
            {"slug": chunk.slug, "sha": tip or "", "holding": holding},
        )
        results.append({"slug": chunk.slug, "status": "success", "tip": tip})
        _teardown_container(chunk.slug)
    return results


def drain(
    chunks: list[Chunk],
    *,
    holding: str,
    on_landed: Callable[[str], None] | None = None,
    on_ejected: Callable[[str], list[str]] | None = None,
    next_ready: Callable[[list[str]], str | None] | None = None,
    speculative: bool | None = None,
) -> list[dict[str, object]]:
    """Land all chunks serially.

    Without `next_ready`: iterate chunks in input order (no-dep path). When the
    `speculative_land` config flag is on (or `speculative=True` is forced), this
    independent batch is gated in parallel and FF-merged (see
    `_drain_speculative`); serial stays the safe fallback.

    With `next_ready`: pull the next chunk whose plan deps are wholly landed
    via `next_ready(candidates)`. Land it, call on_landed / on_ejected,
    repeat until pending empty or no chunk ready (stalled verdict). Speculation
    never applies here — a live dep graph forbids the "assume 1..N-1 land"
    optimism.
    """
    _on_landed = on_landed or (lambda _: None)
    _on_ejected = on_ejected or (lambda _: [])

    if next_ready is None:
        if speculative is None:
            speculative = _speculative_land_enabled()
        if speculative and chunks:
            return _drain_speculative(chunks, holding=holding)
        return _drain_serial(chunks, holding=holding)

    by_slug: dict[str, Chunk] = {c.slug: c for c in chunks}
    pending: list[str] = [c.slug for c in chunks]
    results: list[dict[str, object]] = []

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
