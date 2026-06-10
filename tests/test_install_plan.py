"""Tests for mentat-install plan.py submodule."""

from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_compute_plan_clone_mode_uses_symlinks(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    clone_root = tmp_path / "clone"
    (clone_root / ".agents" / "skills").mkdir(parents=True)

    ip = plan_mod.compute_plan(home=home, clone_root=clone_root)
    assert any(a.action_type == "symlink" for a in ip.add)


def test_compute_plan_user_mode_uses_copies(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    for action in ip.add:
        assert action.action_type in ("copy", "mkdir", "file-create", "symlink")


def test_compute_plan_detects_claude_code_when_dir_exists(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    (tmp_path / ".claude").mkdir()
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    harnesses = [a.target for a in ip.add if ".claude" in str(a.target)]
    assert harnesses or any(".claude" in str(a.target) for a in ip.update)


def test_compute_plan_detects_cursor_when_dir_exists(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    (tmp_path / ".cursor").mkdir()
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    cursor_items = [a for a in ip.add + ip.update if ".cursor" in str(a.target)]
    assert cursor_items


def test_compute_plan_skips_undetected_harness(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    cursor_items = [a for a in ip.add + ip.update if ".cursor" in str(a.target)]
    claude_items = [a for a in ip.add + ip.update if ".claude" in str(a.target)]
    assert not cursor_items
    assert not claude_items


def test_compute_plan_lists_stale_paths(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    stale = tmp_path / ".agents" / "mentat"
    stale.mkdir(parents=True)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    assert any("mentat" in str(p) for p in ip.stale)


def test_compute_plan_is_pure_no_side_effects(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    before = set(tmp_path.rglob("*"))
    plan_mod.compute_plan(home=home, clone_root=None)
    after = set(tmp_path.rglob("*"))
    assert before == after
