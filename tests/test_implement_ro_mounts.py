"""ADR-0010 — read-only test mount integration.

run_plan() must:
  - read ~/.agents/plans/<slug>.tests.json (if present)
  - compute closed - open
  - set MENTAT_RO_MOUNTS env var to the JSON-encoded list before invoking the harness

Tests use monkeypatched HOME so the manifest lives under tmp_path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

_IMPL = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts/implement.py"


def _load():
    return load_script(_IMPL, "impl_ro")


def _write_plan(plans_dir: Path, slug: str, *, kind: str = "AFK") -> Path:
    plans_dir.mkdir(parents=True, exist_ok=True)
    p = plans_dir / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nkind: {kind}\n---\n# body\n")
    return p


def _write_manifest(plans_dir: Path, slug: str, *, closed: list[str], open_: list[str]) -> None:
    (plans_dir / f"{slug}.tests.json").write_text(json.dumps({"closed": closed, "open": open_}))


def test_run_plan_sets_ro_mounts_from_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    impl = _load()

    plans_dir = tmp_path / ".agents/plans"
    plan = _write_plan(plans_dir, "ro-plan")
    _write_manifest(
        plans_dir,
        "ro-plan",
        closed=["tests/test_one.py", "tests/test_two.py"],
        open_=["tests/test_two.py"],
    )

    harness_result = MagicMock(returncode=0, session_log=None)
    with patch.object(impl, "_invoke_harness", return_value=harness_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_emit_event"):
                rc = impl.run_plan(plan)

    assert rc == 0
    assert "MENTAT_RO_MOUNTS" in os.environ
    ro = json.loads(os.environ["MENTAT_RO_MOUNTS"])
    # closed - open = test_one.py only (test_two was marked writable)
    assert ro == ["tests/test_one.py"]


def test_run_plan_omits_ro_mounts_when_manifest_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    impl = _load()

    plans_dir = tmp_path / ".agents/plans"
    plan = _write_plan(plans_dir, "no-manifest")
    # No <slug>.tests.json written.

    harness_result = MagicMock(returncode=0, session_log=None)
    with patch.object(impl, "_invoke_harness", return_value=harness_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_emit_event"):
                rc = impl.run_plan(plan)

    assert rc == 0
    assert "MENTAT_RO_MOUNTS" not in os.environ


def test_run_plan_omits_ro_mounts_when_all_closed_are_open(tmp_path, monkeypatch):
    """All closed tests marked writable → no RO mounts → env var stays unset."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MENTAT_RO_MOUNTS", raising=False)
    impl = _load()

    plans_dir = tmp_path / ".agents/plans"
    plan = _write_plan(plans_dir, "all-open")
    _write_manifest(plans_dir, "all-open", closed=["tests/a.py"], open_=["tests/a.py"])

    harness_result = MagicMock(returncode=0, session_log=None)
    with patch.object(impl, "_invoke_harness", return_value=harness_result):
        with patch.object(impl, "_detect_self_answer", return_value=False):
            with patch.object(impl, "_emit_event"):
                rc = impl.run_plan(plan)

    assert rc == 0
    assert "MENTAT_RO_MOUNTS" not in os.environ


def test_mark_test_writable_flips_closed_to_open(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    impl = _load()

    plans_dir = tmp_path / ".agents/plans"
    plans_dir.mkdir(parents=True)
    _write_manifest(plans_dir, "flip", closed=["tests/x.py", "tests/y.py"], open_=[])

    with patch.object(impl, "_emit_event") as mock_emit:
        impl.mark_test_writable("flip", "tests/x.py")

    data = json.loads((plans_dir / "flip.tests.json").read_text())
    assert "tests/x.py" in data["open"]
    assert "tests/y.py" not in data["open"]
    # Audit event emitted
    assert mock_emit.called
    event_name = mock_emit.call_args.args[0]
    assert event_name == "test_writable_requested"


def test_mark_test_writable_refuses_unknown_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    impl = _load()

    plans_dir = tmp_path / ".agents/plans"
    plans_dir.mkdir(parents=True)
    _write_manifest(plans_dir, "flip2", closed=["tests/x.py"], open_=[])

    with patch.object(impl, "_emit_event") as mock_emit:
        impl.mark_test_writable("flip2", "tests/not-in-list.py")

    # No mutation; no audit event
    data = json.loads((plans_dir / "flip2.tests.json").read_text())
    assert data["open"] == []
    mock_emit.assert_not_called()
