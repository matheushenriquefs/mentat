"""Tests for mentat-plan skill."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-plan/scripts"
LOG_SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-log/scripts/log.py"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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
