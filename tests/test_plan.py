"""Tests for mentat-plan skill."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-plan/scripts"
LOG_SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-log/scripts/log.py"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def run_plan(args: list[str], env: dict | None = None):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["python3", str(SCRIPTS / "plan.py"), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


# ── resolve_plan ────────────────────────────────────────────────────────────


def test_resolve_plan_bare_slug_returns_canonical_path():
    plan_mod = load_module("plan")
    result = plan_mod.resolve_plan("my-plan")
    assert result == Path.home() / ".agents" / "plans" / "my-plan.md"


def test_resolve_plan_relative_path_with_slash():
    plan_mod = load_module("plan")
    result = plan_mod.resolve_plan("some/path.md")
    assert result.is_absolute()
    assert result.name == "path.md"


def test_resolve_plan_absolute_path_with_md_suffix():
    plan_mod = load_module("plan")
    result = plan_mod.resolve_plan("/tmp/my-plan.md")
    assert result == Path("/tmp/my-plan.md")


def test_resolve_plan_tilde_expansion():
    plan_mod = load_module("plan")
    result = plan_mod.resolve_plan("~/custom/plan.md")
    assert not str(result).startswith("~")
    assert result.is_absolute()


def test_resolve_plan_missing_file_does_not_raise():
    """Resolution is pure path arithmetic — does not stat."""
    plan_mod = load_module("plan")
    result = plan_mod.resolve_plan("nonexistent-plan-xyz")
    # Just resolves without error
    assert result.name == "nonexistent-plan-xyz.md"


# ── write ────────────────────────────────────────────────────────────────────


def test_write_canonical_path(tmp_path):
    plan_mod = load_module("plan")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    body_file = tmp_path / "body.md"
    body_file.write_text("# Test plan\n")

    plan_mod.write_plan("test-slug", body_file, plans_dir=plans_dir)
    written = plans_dir / "test-slug.md"
    assert written.exists()
    assert written.read_text() == "# Test plan\n"


# ── emit events ──────────────────────────────────────────────────────────────


def test_emits_plan_started_and_succeeded(tmp_path, monkeypatch):
    """write_plan emits plan.started then plan.succeeded via subprocess."""
    plan_mod = load_module("plan")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    body_file = tmp_path / "body.md"
    body_file.write_text("# Test plan\n")

    emitted: list[str] = []

    original_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list) and "log.py" in " ".join(str(c) for c in cmd):
            emitted.append(cmd[cmd.index("emit") + 2] if "emit" in cmd else "")
            return MagicMock(returncode=0)
        return original_run(cmd, **kwargs)

    with patch("subprocess.run", fake_run):
        plan_mod.write_plan("test-slug", body_file, plans_dir=plans_dir)

    assert any("plan.started" in e for e in emitted)
    assert any("plan.succeeded" in e for e in emitted)


# ── tasks handoff (S13) ───────────────────────────────────────────────────────


def test_suggest_tasks_references_slug():
    plan_mod = load_module("plan")
    msg = plan_mod.suggest_tasks("my-slug")
    assert "/mentat-tasks" in msg
    assert "my-slug" in msg


def test_write_plan_default_plans_dir_when_none(tmp_path):
    """write_plan with plans_dir=None uses ~/.agents/plans — covers the None branch."""
    plan_mod = load_module("plan")
    body_file = tmp_path / "body.md"
    body_file.write_text("# Plan\n")

    calls: list[str] = []
    original_emit = plan_mod._emit
    plan_mod._emit = lambda event, payload: calls.append(event)
    try:
        with patch("pathlib.Path.home", return_value=tmp_path):
            dest = plan_mod.write_plan("default-slug", body_file, plans_dir=None)
        assert dest == tmp_path / ".agents" / "plans" / "default-slug.md"
        assert "plan.succeeded" in calls
    finally:
        plan_mod._emit = original_emit


def test_write_plan_oserror_emits_failed_and_reraises(tmp_path):
    plan_mod = load_module("plan")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    nonexistent_body = tmp_path / "does_not_exist.md"
    failed_events: list[str] = []

    original_emit = plan_mod._emit

    def fake_emit(event: str, payload: dict) -> None:
        failed_events.append(event)

    plan_mod._emit = fake_emit
    try:
        import pytest as _pytest

        with _pytest.raises(OSError):
            plan_mod.write_plan("err-slug", nonexistent_body, plans_dir=plans_dir)
        assert "plan.failed" in failed_events
    finally:
        plan_mod._emit = original_emit


def test_main_no_subcommand_exits_1(tmp_path):
    result = run_plan([], env={"HOME": str(tmp_path)})
    assert result.returncode != 0


def test_main_no_subcommand_prints_help_in_process(monkeypatch, capsys):
    """main() with no subcommand prints help and exits 1 (in-process, for coverage)."""
    plan_mod = load_module("plan")
    monkeypatch.setattr("sys.argv", ["plan.py"])
    try:
        plan_mod.main()
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert exc.code == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_main_resolve_slug_prints_path(tmp_path, monkeypatch, capsys):
    """main() with resolve-slug cmd prints canonical path."""
    plan_mod = load_module("plan")
    monkeypatch.setattr("sys.argv", ["plan.py", "resolve-slug", "my-plan"])
    try:
        plan_mod.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    captured = capsys.readouterr()
    assert "my-plan.md" in captured.out


def test_main_write_calls_write_plan(tmp_path, monkeypatch, capsys):
    """main() with write cmd invokes write_plan and prints tasks suggestion."""
    plan_mod = load_module("plan")
    body_file = tmp_path / "body.md"
    body_file.write_text("# Plan\n")
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()

    original_emit = plan_mod._emit
    plan_mod._emit = lambda event, payload: None
    monkeypatch.setattr("sys.argv", ["plan.py", "write", "cli-slug", str(body_file)])
    try:
        with patch("pathlib.Path.home", return_value=tmp_path):
            try:
                plan_mod.main()
            except SystemExit as exc:
                assert exc.code == 0 or exc.code is None
        captured = capsys.readouterr()
        assert "/mentat-tasks" in captured.out
        assert "cli-slug" in captured.out
    finally:
        plan_mod._emit = original_emit


def test_write_cli_prints_tasks_suggestion(tmp_path):
    """`plan.py write` output ends with a /mentat-tasks suggestion for the slug."""
    body_file = tmp_path / "body.md"
    body_file.write_text("# Test plan\n")
    result = run_plan(
        ["write", "handoff-slug", str(body_file)],
        env={"HOME": str(tmp_path), "MENTAT_LOG_PATH": str(tmp_path / "logs")},
    )
    assert result.returncode == 0
    assert "/mentat-tasks" in result.stdout
    assert "handoff-slug" in result.stdout
