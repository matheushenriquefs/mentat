"""Chunk identity: mint, derive, and bind plan slugs to per-run chunk ids."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

HOLDING_PREFIX = "mentat"
CHUNK_LABEL = "mentat_chunk"

_plan_chunk_ids: dict[str, str] = {}


def make_chunk_id() -> str:
    return uuid.uuid7().hex


def chunk_slug(chunk_id: str, slug: str) -> str:
    return f"{chunk_id}/{slug}"


def parse_chunk_slug(value: str) -> tuple[str, str]:
    chunk_id, sep, slug = value.partition("/")
    if not sep or not chunk_id or not slug:
        raise ValueError(f"invalid chunk_slug: {value!r}")
    return chunk_id, slug


def holding_branch(chunk_slug_value: str) -> str:
    return f"{HOLDING_PREFIX}/{chunk_slug_value}"


def worktree_rel_parts(chunk_slug_value: str) -> tuple[str, str]:
    return parse_chunk_slug(chunk_slug_value)


def worktree_path(repo_root: Path, chunk_slug_value: str) -> Path:
    chunk_id, slug = parse_chunk_slug(chunk_slug_value)
    return repo_root / ".mentat" / "worktrees" / chunk_id / slug


def chunk_slug_from_worktree(worktree: Path, repo_root: Path) -> str:
    root = (repo_root / ".mentat" / "worktrees").resolve()
    rel = worktree.resolve().relative_to(root)
    if len(rel.parts) != 2:
        raise ValueError(f"worktree {worktree} is not under chunk-keyed layout")
    return f"{rel.parts[0]}/{rel.parts[1]}"


def bind_plan_chunk(plan_slug: str, chunk_id: str) -> None:
    _plan_chunk_ids[plan_slug] = chunk_id


def clear_plan_chunks() -> None:
    _plan_chunk_ids.clear()


def chunk_id_for_plan(plan_slug: str) -> str:
    bound = _plan_chunk_ids.get(plan_slug)
    if bound:
        return bound
    env = os.environ.get("MENTAT_CHUNK_ID", "").strip()
    if env:
        return env
    raise LookupError(f"no chunk_id bound for plan {plan_slug!r}")


def override_config_dir(repo_root: Path, chunk_slug_value: str) -> Path:
    chunk_id, slug = parse_chunk_slug(chunk_slug_value)
    return repo_root / ".mentat" / "config" / chunk_id / slug
