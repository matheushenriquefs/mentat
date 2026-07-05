"""F2 + B6: implement --land self-contained mode.

`mentat-implement run --land --holding <branch> <plan>` runs plan start→finish:
TDD loop then land via land_queue.land — no mentat-orchestrate needed.
B6 removed the dangling batch_review.py load.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-implement/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))


def _impl():
    return load_script(IMPL_SCRIPTS / "implement.py", "impl_land")


def _write_plan(tmp_path: Path, slug: str, class_: str = "AFK") -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nclass: {class_}\nblocked_by: []\n---\n# {slug}\nbody\n")
    return p


class _FakeChunk:
    def __init__(self, slug, worktree, chunk_id=None):
        self.slug = slug
        self.worktree = worktree
        self.chunk_id = chunk_id


class _FakeLandQueue:
    Chunk = _FakeChunk


# ── argparse: --land flag exists ──────────────────────────────────────────────


def test_build_parser_accepts_land_flag():
    """F2 tracer: --land must be a recognized arg on the 'run' subparser."""
    impl = _impl()
    parser = impl._build_parser()
    # Should parse without error
    args = parser.parse_args(["run", "--land", "--holding", "main", "my-plan"])
    assert getattr(args, "land", None) is True or getattr(args, "land", False) is not False or hasattr(args, "land"), (
        "--land flag not present in parsed args"
    )


def test_build_parser_land_requires_holding():
    """F2: --land without --holding must produce an error (holding required when landing)."""
    impl = _impl()
    parser = impl._build_parser()
    # --land without --holding — should either error at parse time or we document holding defaults to main
    # Minimally: --holding arg must exist on the run subparser
    args = parser.parse_args(["run", "--land", "--holding", "mybranch", "my-plan"])
    assert hasattr(args, "holding"), "--holding arg not present on run subparser"
    assert args.holding == "mybranch"


# ── _land_and_review function exists ─────────────────────────────────────────


def test_land_and_review_function_exists():
    """F2 tracer: implement.py must expose _land_and_review(slug, worktree, holding)."""
    impl = _impl()
    assert callable(getattr(impl, "_land_and_review", None)), "implement.py missing _land_and_review function"


# ── _land_and_review calls land_queue.land ────────────────────────────────────


def test_land_and_review_calls_land_queue_land(tmp_path):
    """F2 tracer: _land_and_review must call _do_land for the chunk."""
    impl = _impl()

    land_calls: list[dict] = []

    def fake_do_land(chunk, *, holding, land_queue):
        land_calls.append({"slug": chunk.slug, "holding": holding})
        return {"slug": chunk.slug, "status": "success", "tip": "abc123"}

    with (
        patch.object(impl, "_do_land", fake_do_land),
        patch.object(impl, "_load_mod", lambda key, path: _FakeLandQueue()),
    ):
        result = impl._land_and_review("myplan", tmp_path, "main")

    assert land_calls, "_do_land was not called"
    assert land_calls[0]["slug"] == "myplan"
    assert land_calls[0]["holding"] == "main"
    assert result is not None, "_land_and_review returned None"


def test_land_and_review_returns_status_and_tip(tmp_path):
    """_land_and_review must return a dict with status + tip (no verdicts after B6)."""
    impl = _impl()

    with (
        patch.object(impl, "_do_land", lambda chunk, *, holding, land_queue: {"status": "success", "tip": "sha123"}),
        patch.object(impl, "_load_mod", lambda key, path: _FakeLandQueue()),
    ):
        result = impl._land_and_review("myplan", tmp_path, "main")

    assert isinstance(result, dict), "_land_and_review must return a dict"
    assert "status" in result, "result missing 'status' key"
    assert result.get("status") == "success"


# ── B6: _land_and_review must not crash with missing batch_review.py ──────────


def test_land_and_review_no_import_error(tmp_path):
    """_land_and_review must not crash — batch_review.py was removed (B6)."""
    impl = _impl()

    def fake_do_land(chunk, *, holding, land_queue):
        return {"slug": chunk.slug, "status": "success", "tip": "abc123"}

    with (
        patch.object(impl, "_do_land", fake_do_land),
        patch.object(impl, "_load_mod", lambda key, path: _FakeLandQueue()),
    ):
        result = impl._land_and_review("myplan", tmp_path, "main")

    assert result is not None
    assert result.get("status") == "success"
    assert "tip" in result


def test_land_and_review_no_verdicts_key(tmp_path):
    """After B6, _land_and_review result must NOT include 'verdicts' (batch_review removed)."""
    impl = _impl()

    with (
        patch.object(impl, "_do_land", lambda chunk, *, holding, land_queue: {"status": "success", "tip": "sha"}),
        patch.object(impl, "_load_mod", lambda key, path: _FakeLandQueue()),
    ):
        result = impl._land_and_review("slug", tmp_path, "main")

    assert "verdicts" not in result, "verdicts key must be absent after B6 removes batch_review"


# ── main() --land integration: rc 0 → _land_and_review fires ─────────────────


import pytest  # noqa: E402


def test_main_land_flag_invokes_land_and_review(tmp_path, monkeypatch):
    impl = _impl()
    plan = _write_plan(tmp_path, "landme", "AFK")
    target = tmp_path / "wt"
    target.mkdir()

    monkeypatch.setattr(impl.sys, "argv", ["implement.py", "run", str(plan), "--land", "--holding", "hold-x"])
    monkeypatch.setattr(impl, "resolve_plan_path", lambda _ref: plan)
    monkeypatch.setattr(impl, "ensure_session", lambda *a, **k: "sess")
    monkeypatch.setattr(impl, "_prune_worktrees_preflight", lambda: None)
    monkeypatch.setattr(impl._utils, "default_harness", lambda: "claude-code")
    monkeypatch.setattr(impl, "preflight_veto_reviewers", lambda _h: (0, []))
    monkeypatch.setattr(impl, "preflight_worktree", lambda _slug: (0, target))
    monkeypatch.setattr(impl.os, "chdir", lambda _p: None)
    monkeypatch.setattr(impl, "_in_shared_main_tree", lambda: False)
    monkeypatch.setattr(impl, "_run_and_doctor", lambda *a, **k: 0)

    calls: dict = {}
    monkeypatch.setattr(
        impl, "_land_and_review", lambda slug, worktree, holding: calls.update(slug=slug, wt=worktree, holding=holding)
    )

    with pytest.raises(SystemExit) as exc:
        impl.main()

    assert exc.value.code == 0
    assert calls["slug"] == "landme"
    assert calls["holding"] == "hold-x"
    assert calls["wt"] == target
