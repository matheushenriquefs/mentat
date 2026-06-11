"""Serial land-queue: rebase + gate + FF-merge or eject per chunk."""

from __future__ import annotations

import importlib.util as _ilu
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


def _load_sibling(name: str):
    here = Path(__file__).parent
    key = f"{here.parent.name}.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, here / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_utils = _load_sibling("utils")


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
    """FF-merge chunk HEAD onto holding branch via update-ref."""
    sha_r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(chunk.worktree),
    )
    if sha_r.returncode != 0:
        return False
    sha = sha_r.stdout.strip()

    # Verify holding is an ancestor of sha (fast-forward is possible)
    anc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", holding, sha],
        capture_output=True,
        cwd=str(chunk.worktree),
    )
    if anc.returncode != 0:
        return False

    result = subprocess.run(
        ["git", "update-ref", f"refs/heads/{holding}", sha],
        capture_output=True,
        cwd=str(chunk.worktree),
    )
    return result.returncode == 0


def _emit_event(event: str, payload: dict) -> None:
    _utils.emit_event(event, payload)


def land(chunk: Chunk, *, holding: str) -> dict:
    """Land one chunk. Returns verdict dict."""
    tip, err = _rebase_chunk(chunk, holding)
    if err:
        _emit_event(
            "chunk.ejected",
            {
                "slug": chunk.slug,
                "reason": "rebase-conflicted",
                "where": str(chunk.worktree),
            },
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": "rebase-conflicted",
            "tip": None,
            "conflicted_files": [],
        }

    verdict, message = _run_gates(chunk)
    if verdict == "block":
        _emit_event(
            "chunk.ejected",
            {
                "slug": chunk.slug,
                "reason": "gate-failed",
                "where": str(chunk.worktree),
            },
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": "gate-failed",
            "tip": tip,
            "findings": [message],
        }

    merged = _ff_merge(chunk, holding)
    if not merged:
        _emit_event(
            "chunk.ejected",
            {
                "slug": chunk.slug,
                "reason": "not-ff",
                "where": str(chunk.worktree),
            },
        )
        return {
            "slug": chunk.slug,
            "status": "eject",
            "reason": "not-ff",
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


def drain(chunks: list[Chunk], *, holding: str, scheduler=None) -> list[dict]:
    """Land all chunks serially.

    Without `scheduler`: legacy behavior — iterate chunks in input order
    and land each one. Independent AFK plans with no cross-deps stay on
    this path (no scheduler passed) so the pre-slice-2 contract holds.

    With `scheduler`: pull the next chunk whose plan deps are wholly
    landed via `scheduler.next_ready`. Land it, mark landed/ejected,
    repeat until pending is empty or no chunk is ready (cycle / missing
    upstream → stalled verdict carries `pending` list).
    """
    if scheduler is None:
        results: list[dict] = []
        for chunk in chunks:
            results.append(land(chunk, holding=holding))
        return results

    by_slug: dict[str, Chunk] = {c.slug: c for c in chunks}
    pending: list[str] = [c.slug for c in chunks]
    results = []

    while pending:
        ready = scheduler.next_ready(pending)
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
        pending.remove(ready)
        if verdict.get("status") == "success":
            scheduler.mark_landed(ready)
            continue

        # Eject cascade: every chunk that transitively depends on `ready`
        # is preemptively ejected — no rebase, no gate, payload-only
        # extension to chunk.ejected (ADR-0007).
        cascaded = scheduler.mark_ejected(ready)
        for downstream in cascaded:
            if downstream not in pending:
                continue
            chunk = by_slug.get(downstream)
            where = str(chunk.worktree) if chunk else ""
            _emit_event(
                "chunk.ejected",
                {
                    "slug": downstream,
                    "reason": "upstream_ejected",
                    "upstream": ready,
                    "where": where,
                },
            )
            results.append(
                {
                    "slug": downstream,
                    "status": "eject",
                    "reason": "upstream_ejected",
                    "upstream": ready,
                }
            )
            pending.remove(downstream)

    return results
