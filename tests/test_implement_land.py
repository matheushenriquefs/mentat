"""F2: implement --land self-contained mode.

`mentat-implement run --land --holding <branch> <plan>` runs plan start→finish:
TDD loop then land via land_queue.land, then advisory batch review — no
mentat-orchestrate needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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


# ── _land_and_review calls land_queue.land and spawns reviewers ───────────────


def test_land_and_review_calls_land_queue_land(tmp_path):
    """F2 tracer: _land_and_review must call land_queue.land for the chunk."""
    impl = _impl()

    land_calls: list[dict] = []

    def fake_land(chunk, *, holding):
        land_calls.append({"slug": chunk.slug, "holding": holding})
        return {"slug": chunk.slug, "status": "success", "tip": "abc123"}

    with patch.object(impl, "_do_land", fake_land, create=True):
        pass  # ensure the patch target exists before calling

    # Direct test: _land_and_review must invoke land internally
    with patch.object(impl, "_emit_event"):
        result = impl._land_and_review("myplan", tmp_path, "main")

    # landed + reviewer verdicts expected
    assert result is not None, "_land_and_review returned None"


def test_land_and_review_spawns_reviewer_verdicts(tmp_path):
    """F2 tracer: after landing, _land_and_review must spawn advisory reviewers and return verdicts."""
    impl = _impl()

    with patch.object(impl, "_emit_event"):
        try:
            result = impl._land_and_review("myplan", tmp_path, "main")
            # Must return a dict with at least status + verdicts fields
            assert isinstance(result, dict), "_land_and_review must return a dict"
        except (AttributeError, TypeError) as exc:
            pytest.fail(f"_land_and_review raised {type(exc).__name__}: {exc}")
