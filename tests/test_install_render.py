"""Tests for mentat-install render.py submodule."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-install/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _fake_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_render_sections_present(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    output = render_mod.render(ip, color=False)
    assert "Added" in output or "Stale" in output or "Skipped" in output or "Warned" in output


def test_render_plain_when_no_color(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    output = render_mod.render(ip, color=False)
    assert "\033[" not in output


def test_render_no_color_flag_overrides_tty(tmp_path, monkeypatch):
    render_mod = load_module("render")
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    with patch("sys.stdout.isatty", return_value=True):
        output = render_mod.render(ip, color=False)
    assert "\033[" not in output


def _plan(plan_mod, **kw):
    base = dict(add=[], update=[], stale=[], conflicts=[], missing_companions=[], skipped=[])
    base.update(kw)
    return plan_mod.InstallPlan(**base)


def test_render_color_none_defaults_to_isatty(tmp_path):
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    ip = _plan(plan_mod, add=[plan_mod.Action("mkdir", None, tmp_path / "x")])
    output = render_mod.render(ip)  # color=None → line 20 isatty() path
    assert "Added:" in output


def test_render_all_sections_present(tmp_path):
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    A = plan_mod.Action
    ip = _plan(
        plan_mod,
        update=[A("symlink", tmp_path / "s", tmp_path / "u")],
        conflicts=[tmp_path / "c"],
        stale=[tmp_path / "st"],
        missing_companions=["comp"],
        skipped=[A("symlink", None, tmp_path / f"sk{i}" / "leaf") for i in range(5)],
    )
    output = render_mod.render(ip, color=False)
    assert "Updated:" in output
    assert "Conflicts" in output
    assert "Stale" in output
    assert "Missing companion" in output
    assert "Skipped" in output
    assert "and 2 more" in output


def test_render_skipped_three_or_fewer(tmp_path):
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    A = plan_mod.Action
    ip = _plan(plan_mod, skipped=[A("symlink", None, tmp_path / "a" / "x"), A("symlink", None, tmp_path / "b" / "y")])
    output = render_mod.render(ip, color=False)
    assert "Skipped" in output
    assert "more" not in output


def test_render_empty_plan_says_nothing_to_install():
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    output = render_mod.render(_plan(plan_mod), color=False)
    assert "Nothing to install." in output


def test_render_color_applies_ansi_to_all_sections(tmp_path):
    plan_mod = load_module("plan")
    render_mod = load_module("render")
    A = plan_mod.Action
    ip = _plan(
        plan_mod,
        add=[A("mkdir", None, tmp_path / "a")],
        update=[A("symlink", tmp_path / "s", tmp_path / "u")],
        conflicts=[tmp_path / "c"],
        stale=[tmp_path / "st"],
        missing_companions=["comp"],
    )
    output = render_mod.render(ip, color=True)
    assert "\033[" in output


def test_render_uses_color_when_tty(tmp_path, monkeypatch):
    render_mod = load_module("render")
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".agents" / "mentat").mkdir(parents=True)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    output = render_mod.render(ip, color=True)
    assert "\033[" in output
