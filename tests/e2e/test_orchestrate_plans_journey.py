"""E2E: the mentat-orchestrate thin wrappers over the shared lib seams.

Drives ``mentat-orchestrate/scripts/plans.py``: ``resolve_plan_ref`` delegates to
``lib.plans`` (slug → ``<slug>.md`` path), ``parse_frontmatter`` reads a real tmp
plan file and returns the frontmatter dict, and ``run_gates`` returns the fast
``("pass", "")`` on a ``None`` chunk and otherwise forwards to the real gate
engine — exercised over a tmp dir holding a single clean ``.py`` source so the
engine's real ``evaluate`` returns a genuine pass verdict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANS_PY = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/plans.py"


def test_resolve_plan_ref_maps_slug_to_md_path():
    plans = load_script(PLANS_PY, "orch_plans_resolve")
    result = plans.resolve_plan_ref("some-slug")
    assert result.name == "some-slug.md"


def test_parse_frontmatter_returns_dict_from_real_file(tmp_path: Path):
    plans = load_script(PLANS_PY, "orch_plans_parse")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("---\nslug: alpha\nstatus: open\n---\nbody\n")
    assert plans.parse_frontmatter(plan_path) == {"slug": "alpha", "status": "open"}


def test_run_gates_none_chunk_is_immediate_pass():
    plans = load_script(PLANS_PY, "orch_plans_none")
    assert plans.run_gates(None) == ("pass", "")


def test_run_gates_forwards_to_engine_and_passes_on_clean_tree(tmp_path: Path):
    plans = load_script(PLANS_PY, "orch_plans_real")
    (tmp_path / "clean.py").write_text("def f(x):\n    return x + 1\n")
    verdict, msg = plans.run_gates(tmp_path)
    assert isinstance(verdict, str)
    assert verdict == "pass"
    assert msg == ""
