"""E2E: an orchestrate dry-run over a real plan tree, including parent-index expansion.

Drives ``run_orchestrate(..., dry_run=True)`` over real plan files on disk: it loads +
frontmatter-parses them, expands a parent index into its siblings, partitions HITL/AFK,
and prints the anchor/spawn preview — all hermetic (no worktrees, no docker, no harness
spawn). Asserts the preview names each slug in the right group and that the batch.reviewed
audit row is written. Also drives the plan-loader guards (nested index, bad blocked_by).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    log_root = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "orchrepo")
    monkeypatch.setenv("MENTAT_SESSION", "orchestrate-holding-1")
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)
    monkeypatch.chdir(tmp_path)
    return log_root


def _orch():
    return load_script(SCRIPTS / "orchestrate.py", "e2e_orch")


def _plan(plans_dir: Path, slug: str, *, cls: str = "AFK", blocked_by: str = "", siblings: str = "") -> Path:
    lines = ["---", f"id: {slug}", f"class: {cls}"]
    if blocked_by:
        lines.append(f"blocked_by: {blocked_by}")
    if siblings:
        lines.append(f"siblings: {siblings}")
    lines += ["---", f"# {slug}", "body", ""]
    p = plans_dir / f"{slug}.md"
    p.write_text("\n".join(lines))
    return p


def _batch_reviews(log_root: Path) -> list[dict]:
    out: list[dict] = []
    for f in log_root.rglob("*.jsonl"):
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("event") == "batch.reviewed":
                out.append(row)
    return out


def test_dry_run_previews_partition(tmp_path, audit_env, capsys):
    orch = _orch()
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    api = _plan(plans_dir, "api", cls="HITL")
    ui = _plan(plans_dir, "ui", cls="AFK", blocked_by="api")  # upstream HITL → anchored
    infra = _plan(plans_dir, "infra", cls="AFK")  # standalone → auto

    rc = orch.run_orchestrate("holding", [api, ui, infra], harness=None, model=None, dry_run=True)
    assert rc == 0

    out = capsys.readouterr().out
    assert "api" in out and "ui" in out, "anchored slugs previewed"
    assert "infra" in out, "auto slug previewed"
    assert "would anchor" in out and "would spawn" in out

    # A dry run still records the advisory batch review.
    assert _batch_reviews(audit_env), "dry-run must emit batch.reviewed"


def test_dry_run_expands_parent_index(tmp_path, audit_env, capsys):
    orch = _orch()
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    _plan(plans_dir, "child-a", cls="AFK")
    _plan(plans_dir, "child-b", cls="AFK")
    parent = _plan(plans_dir, "parent", cls="AFK", siblings="child-a, child-b")

    rc = orch.run_orchestrate("holding", [parent], harness=None, model=None, dry_run=True)
    assert rc == 0

    out = capsys.readouterr().out
    # The parent index expands to its siblings; the parent itself is not a chunk.
    assert "child-a" in out and "child-b" in out
    assert "parent" not in out.replace("child", "")  # parent slug not itself a chunk


def test_load_plans_rejects_nested_parent_index(tmp_path, audit_env):
    orch = _orch()
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    _plan(plans_dir, "grandchild", cls="AFK")
    _plan(plans_dir, "child", cls="AFK", siblings="grandchild")  # a sibling that is itself an index
    parent = _plan(plans_dir, "parent", cls="AFK", siblings="child")

    with pytest.raises(SystemExit):
        orch._load_plans([parent])


def test_load_plans_rejects_parent_with_blocked_by(tmp_path, audit_env):
    orch = _orch()
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    _plan(plans_dir, "sib", cls="AFK")
    _plan(plans_dir, "dep", cls="AFK")
    parent = _plan(plans_dir, "parent", cls="AFK", siblings="sib", blocked_by="dep")

    with pytest.raises(SystemExit):
        orch._load_plans([parent])


def test_load_plans_warns_on_external_dep(tmp_path, audit_env, capsys):
    orch = _orch()
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    p = _plan(plans_dir, "solo", cls="AFK", blocked_by="not-in-batch")

    plans = orch._load_plans([p])
    assert [pl.slug for pl in plans] == ["solo"]
    assert "not in batch" in capsys.readouterr().err
