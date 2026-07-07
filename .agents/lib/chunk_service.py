"""Single lifecycle owner for chunk spawn, persist, and terminal transitions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lib import devcontainer
from lib.chunk import chunk_slug, holding_branch
from lib.events import StatusReason
from lib.plan_slices import parse_slices
from lib.store import (
    Chunk,
    ChunkDAO,
    ChunkStatus,
    Slice,
    SliceDAO,
    SliceKind,
    connect,
    iso_now,
    make_slice_id,
)
from typing import cast


class ChunkService:
    """Sole writer for chunk + slice rows on spawn and land."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._slices = SliceDAO(conn)
        self._chunks = ChunkDAO(conn)

    @classmethod
    def open(cls) -> ChunkService:
        return cls(connect())

    def create(
        self,
        *,
        chunk_id: str,
        plan_slug: str,
        plan_path: Path,
        agent_id: str,
        worktree: Path,
    ) -> Chunk:
        """Persist slice rows for the plan and insert the chunk row."""
        existing = self._chunks.get_by_id(chunk_id)
        if existing is not None:
            return existing
        from lib.store import Agent, AgentDAO

        agents = AgentDAO(self._conn)
        if agents.get_by_id(agent_id) is None:
            agents.insert(
                Agent(
                    id=agent_id,
                    supervisor_id=None,
                    resumed_from_id=None,
                    forked_from_id=None,
                    harness="unknown",
                    pid=None,
                    status="running",
                    status_reason=None,
                    started_at=iso_now(),
                    ended_at=None,
                )
            )
        slices = parse_slices(plan_path)
        if not slices:
            plan_kind: SliceKind = "AFK"
            if plan_path.is_file():
                from lib.support import frontmatter as _fm

                fm, _ = _fm.parse(plan_path.read_text())
                plan_kind = cast("SliceKind", fm.get("kind", "AFK"))
            slices = [(plan_slug, plan_kind)]
        for key, kind in slices:
            self._slices.upsert(
                Slice(
                    id=make_slice_id(plan_slug, key),
                    plan_slug=plan_slug,
                    key=key,
                    kind=cast("SliceKind", kind),
                )
            )
        primary_key = slices[0][0]
        row = Chunk(
            id=chunk_id,
            slice_id=make_slice_id(plan_slug, primary_key),
            agent_id=agent_id,
            attempt=1,
            container_id=None,
            worktree_path=str(worktree),
            status="running",
            status_reason=None,
            started_at=iso_now(),
            ended_at=None,
            slug=plan_slug,
        )
        self._chunks.insert(row)
        return row

    def mark_landed(self, chunk_id: str) -> Chunk | None:
        return self._chunks.update_status(chunk_id, status="landed", ended_at=iso_now())

    def mark_ejected(self, chunk_id: str, *, reason: StatusReason) -> Chunk | None:
        return self._chunks.update_status(
            chunk_id,
            status="ejected",
            status_reason=reason,
            ended_at=iso_now(),
        )

    def teardown_resources(self, chunk: Chunk) -> bool:
        """Remove worktree, holding branch, and container for a landed chunk."""
        from lib import git as _git
        from lib import worktrees as _worktrees
        from lib.git import repo_root

        wt = chunk.worktree
        root = repo_root(wt)
        if root is None:
            return False
        branch = holding_branch(chunk_slug(chunk.id, chunk.slug))
        ok_wt = _worktrees.teardown(wt)
        ok_branch = _git.delete_branch(root, branch)
        ok_container = devcontainer.down(chunk_slug(chunk.id, chunk.slug))
        return ok_wt and ok_branch and ok_container

    def list_landed_reclaimable(self, holding: str, repo_root: Path) -> list[Chunk]:
        """Chunks whose worktree commit is an ancestor of holding."""
        from lib import git as _git

        out: list[Chunk] = []
        for row in self._chunks.list_with_worktree():
            wt = row.worktree
            if not wt.is_dir():
                continue
            tip = _git.rev_parse_head(wt)
            if tip is None:
                continue
            if _git.is_ancestor(tip, holding, cwd=repo_root):
                out.append(row)
        return out
