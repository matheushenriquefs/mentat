"""Tests for tasks/health.py — metrics ledger, coverage capture, sonnet sweep."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("sqlite_utils", reason="sqlite-utils not installed in this Python env")

ROOT = Path(__file__).resolve().parents[1]


def _load_health():
    spec = importlib.util.spec_from_file_location("health", ROOT / "tasks" / "health.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["health"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── Slice 1: metrics ledger ──────────────────────────────────────────────────


def test_record_run_stores_severity_counts(tmp_path: Path) -> None:
    health = _load_health()
    db_path = tmp_path / "quality.db"
    run_id = health.record_run(
        75.0,
        [
            {"file": "a.py", "line": 1, "severity": "HIGH", "lens": "bugs", "summary": "bad"},
            {"file": "b.py", "line": 2, "severity": "MED", "lens": "perf", "summary": "slow"},
            {"file": "c.py", "line": 3, "severity": "LOW", "lens": "style", "summary": "nit"},
        ],
        db_path=db_path,
    )
    import sqlite_utils

    db = sqlite_utils.Database(db_path)
    row = next(db["runs"].rows_where("id = ?", [run_id]))
    assert row["high"] == 1
    assert row["med"] == 1
    assert row["low"] == 1
    assert row["total"] == 3
    assert row["coverage_pct"] == 75.0


def test_trend_returns_correct_deltas(tmp_path: Path) -> None:
    health = _load_health()
    db_path = tmp_path / "quality.db"
    # Run 1: high=2, med=1, low=0, coverage=70.0
    health.record_run(
        70.0,
        [
            {"file": "a.py", "line": 1, "severity": "HIGH", "lens": "bugs", "summary": "x"},
            {"file": "b.py", "line": 2, "severity": "HIGH", "lens": "bugs", "summary": "y"},
            {"file": "c.py", "line": 3, "severity": "MED", "lens": "perf", "summary": "z"},
        ],
        db_path=db_path,
    )
    # Run 2: high=0, med=0, low=1, coverage=78.0
    health.record_run(
        78.0,
        [{"file": "d.py", "line": 4, "severity": "LOW", "lens": "style", "summary": "nit"}],
        db_path=db_path,
    )
    t = health.trend(n=2, db_path=db_path)
    assert t is not None
    assert t["coverage"] == (70.0, 78.0)
    assert t["high"] == (2, 0)
    assert t["med"] == (1, 0)
    assert t["low"] == (0, 1)


def test_trend_returns_none_for_single_run(tmp_path: Path) -> None:
    health = _load_health()
    db_path = tmp_path / "quality.db"
    health.record_run(75.0, [], db_path=db_path)
    assert health.trend(n=2, db_path=db_path) is None


# ── Slice 2: coverage capture ─────────────────────────────────────────────────


def test_coverage_pct_captured_from_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    health = _load_health()
    db_path = tmp_path / "quality.db"
    fake_cov: dict[str, Any] = {"totals": {"percent_covered": 82.5}}
    monkeypatch.setattr(health, "_run_coverage", lambda: fake_cov)
    monkeypatch.setattr(health, "_spawn_agent", lambda *a, **k: [])
    health.sweep(db_path=db_path)
    import sqlite_utils

    db = sqlite_utils.Database(db_path)
    rows = list(db["runs"].rows)
    assert len(rows) == 1
    assert rows[0]["coverage_pct"] == 82.5


# ── Slice 3: sonnet sweep + trend print ───────────────────────────────────────


def test_sweep_records_findings_and_prints_trend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    health = _load_health()
    db_path = tmp_path / "quality.db"
    # Seed a prior run so trend has two points to compare.
    health.record_run(
        70.0,
        [{"file": "x.py", "line": 1, "severity": "HIGH", "lens": "bugs", "summary": "old bug"}],
        db_path=db_path,
    )
    canned: list[dict[str, Any]] = [
        {"file": "y.py", "line": 2, "severity": "MED", "lens": "perf", "summary": "slow path"},
    ]
    monkeypatch.setattr(health, "_run_coverage", lambda: {"totals": {"percent_covered": 75.0}})
    monkeypatch.setattr(health, "_spawn_agent", lambda *a, **k: canned)
    health.sweep(db_path=db_path)
    import sqlite_utils

    db = sqlite_utils.Database(db_path)
    findings = list(db["findings"].rows)
    assert any(f["severity"] == "MED" for f in findings)
    captured = capsys.readouterr()
    assert "→" in captured.out
    assert "HIGH" in captured.out
