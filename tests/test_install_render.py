"""Tests for mentat-install render.py submodule."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-install/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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


def test_render_uses_color_when_tty(tmp_path, monkeypatch):
    render_mod = load_module("render")
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".agents" / "mentat").mkdir(parents=True)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    output = render_mod.render(ip, color=True)
    assert "\033[" in output
