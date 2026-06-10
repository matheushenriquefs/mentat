"""End-to-end smoke test (mocked harness — no real claude-code required)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fixture_batch(tmp_path: Path):
    """Create a tiny fixture batch: one AFK plan + one HITL plan."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    log_dir = tmp_path / "logs" / "fixture-repo" / "smoke-session"
    log_dir.mkdir(parents=True)

    afk_plan = plans_dir / "afk-slice.md"
    afk_plan.write_text("---\nid: afk-slice\nclass: AFK\n---\n# AFK plan\n")

    hitl_plan = plans_dir / "hitl-slice.md"
    hitl_plan.write_text("---\nid: hitl-slice\nclass: HITL\n---\n# HITL plan\n")

    return {
        "plans_dir": plans_dir,
        "log_dir": log_dir,
        "afk_plan": afk_plan,
        "hitl_plan": hitl_plan,
    }


# ── Smoke: routing partitions correctly ──────────────────────────────────────


def test_smoke_routing_partitions_afk_and_hitl(fixture_batch):
    routing = load_module_from(REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/routing.py", "routing")
    plans = [
        routing.Plan(slug="afk-slice", class_="AFK", blocked_by=[], path=fixture_batch["afk_plan"]),
        routing.Plan(slug="hitl-slice", class_="HITL", blocked_by=[], path=fixture_batch["hitl_plan"]),
    ]
    anchored, auto = routing.partition(plans)
    assert any(p.slug == "hitl-slice" for p in anchored)
    assert any(p.slug == "afk-slice" for p in auto)


# ── Smoke: land queue emits both event types ─────────────────────────────────


def test_smoke_land_queue_emits_all_event_types(fixture_batch):
    lq = load_module_from(REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/land_queue.py", "land_queue")

    emitted_events: list[str] = []

    def fake_emit(event: str, payload: dict) -> None:
        emitted_events.append(event)

    with patch.object(lq, "_emit_event", side_effect=fake_emit):
        with patch.object(lq, "_rebase_chunk", return_value=("sha-1", None)):
            with patch.object(lq, "_run_gates", return_value=("pass", "")):
                with patch.object(lq, "_ff_merge", return_value=True):
                    chunk = lq.Chunk(slug="afk-slice", worktree=fixture_batch["afk_plan"].parent)
                    result = lq.land(chunk, holding="main")

    assert result["status"] == "success"
    assert "chunk.landed" in emitted_events


# ── Smoke: doctor produces clean verdict ─────────────────────────────────────


def test_smoke_doctor_produces_clean_verdict(fixture_batch, tmp_path):
    doctor = load_module_from(REPO_ROOT / ".agents/skills/mentat-session/scripts/doctor.py", "doctor")

    session_dir = fixture_batch["log_dir"]
    log_file = session_dir / "mentat-orchestrate-chunk.jsonl"
    log_file.write_text(
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-orchestrate",
                "session": "smoke-session",
                "event": "chunk.landed",
                "payload": {"slug": "afk-slice", "sha": "abc123", "holding": "main"},
            }
        )
        + "\n"
    )

    verdict = doctor.build_verdict(session_dir)
    assert "chunk.landed" in verdict or "landed" in verdict.lower()
    assert "## Verdict" in verdict
    assert "## Regression" in verdict


# ── Smoke: all 9 event types are in EVENT_CATALOG ────────────────────────────


def test_smoke_all_9_event_types_in_catalog():
    log_mod = load_module_from(REPO_ROOT / ".agents/skills/mentat-log/scripts/log.py", "log")
    catalog = log_mod.EVENT_CATALOG
    expected = {
        "plan.started",
        "plan.succeeded",
        "plan.failed",
        "chunk.spawned",
        "chunk.landed",
        "chunk.ejected",
        "gate.evaluated",
        "review.submitted",
        "batch.reviewed",
    }
    assert set(catalog.keys()) == expected


# ── Smoke: mentat-install --help exits 0 ─────────────────────────────────────


def test_smoke_install_help_exits_0():
    import subprocess

    result = subprocess.run(
        ["python3", str(REPO_ROOT / ".agents/skills/mentat-install/scripts/install.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


# ── Smoke: no legacy shell files ─────────────────────────────────────────────


def test_smoke_shell_era_closed():
    """Verify no *.sh files remain in .agents/bin/."""
    bin_dir = REPO_ROOT / ".agents/bin"
    sh_files = list(bin_dir.rglob("*.sh"))
    assert not sh_files, f"shell-era *.sh files still present: {sh_files}"


def test_smoke_only_install_wrapper_remains():
    bin_dir = REPO_ROOT / ".agents/bin"
    mentat_bins = [f for f in bin_dir.iterdir() if f.name.startswith("mentat-") and f.is_file()]
    assert len(mentat_bins) == 1
    assert mentat_bins[0].name == "mentat-install"


# ── Smoke: Python skills count ───────────────────────────────────────────────


def test_smoke_python_skill_count():
    skills_dir = REPO_ROOT / ".agents/skills"
    py_scripts = [f for f in skills_dir.rglob("*.py") if f.name != "__init__.py"]
    assert len(py_scripts) >= 25, f"expected ≥25 Python scripts, found {len(py_scripts)}"
