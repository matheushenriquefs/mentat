"""Serial land-queue: rebase + gate + FF-merge or eject per chunk."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.loader import load_sibling  # noqa: E402

_utils = load_sibling(__file__, "utils")

_AGENTS_ROOT = Path(__file__).resolve().parents[3]  # .agents/
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import EjectReason, bind, ejected_payload  # noqa: E402

_emit_event = bind("mentat-orchestrate")


class Chunk(NamedTuple):
    slug: str
    worktree: Path


def _rebase_chunk(chunk: Chunk, holding: str) -> tuple[str | None, str | None]:
    """Rebase chunk onto holding. Returns (tip_sha, error_message)."""
    result = subprocess.run(
        ["git", "rebase", holding],
        capture_output=True,
        text=True,
        cwd=str(chunk.worktree),
    )
    if result.returncode != 0:
        return None, result.stderr.strip()
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(chunk.worktree),
    )
    return sha_result.stdout.strip(), None


def _run_gates(chunk: Chunk) -> tuple[str, str]:
    return _utils.run_gates(chunk.worktree)


def _ff_merge(chunk: Chunk, holding: str) -> bool:
    """FF-merge chunk HEAD onto holding branch via merge --ff-only in main worktree.

    Advances both the branch pointer and the main worktree's working tree.
    Returns False if the merge is not fast-forward or the main worktree is dirty.
    """
    sha_r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(chunk.worktree),
    )
    if sha_r.returncode != 0:
        return False
    sha = sha_r.stdout.strip()

    # Locate the main worktree — always the first entry in porcelain output
    wt_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(chunk.worktree),
    )
    if wt_list.returncode != 0:
        return False

    main_wt: Path | None = None
    for line in wt_list.stdout.splitlines():
        if line.startswith("worktree "):
            main_wt = Path(line[len("worktree ") :])
            break

    if main_wt is None:
        return False

    result = subprocess.run(
        ["git", "merge", "--ff-only", sha],
        capture_output=True,
        cwd=str(main_wt),
    )
    return result.returncode == 0


def _teardown_container(slug: str) -> None:
    from lib import devcontainer

    ok = devcontainer.down(slug)
    _emit_event("chunk.teardown", {"slug": slug, "ok": ok})


def land(chunk: Chunk, *, holding: str) -> dict:
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

    merged = _ff_merge(chunk, holding)
    if not merged:
        _emit_event(
            "chunk.ejected",
            ejected_payload(chunk.slug, EjectReason.NOT_FF, str(chunk.worktree)),
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": EjectReason.NOT_FF,
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
    on_landed=None,
    on_ejected=None,
    next_ready=None,
) -> list[dict]:
    """Land all chunks serially.

    Without `next_ready`: iterate chunks in input order (legacy / no-dep path).

    With `next_ready`: pull the next chunk whose plan deps are wholly landed
    via `next_ready(candidates)`. Land it, call on_landed / on_ejected,
    repeat until pending empty or no chunk ready (stalled verdict).
    """
    _on_landed = on_landed or (lambda _: None)
    _on_ejected = on_ejected or (lambda _: [])

    if next_ready is None:
        results: list[dict] = []
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
            results.append(
                {
                    "slug": None,
                    "status": "stalled",
                    "pending": list(pending),
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
