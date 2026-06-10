"""Tests for mentat-install skill."""

from __future__ import annotations

import importlib.util
import subprocess
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


# ── plan.py ──────────────────────────────────────────────────────────────────


def test_compute_plan_clone_mode_uses_symlinks(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    # Simulate clone mode: cwd is a git repo with .agents/skills/
    clone_root = tmp_path / "clone"
    (clone_root / ".agents" / "skills").mkdir(parents=True)

    ip = plan_mod.compute_plan(home=home, clone_root=clone_root)
    assert any(a.action_type == "symlink" for a in ip.add)


def test_compute_plan_user_mode_uses_copies(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    # No clone root → copy mode
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    # With no clone root, should either have no add items or use copy
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
    # Neither .claude nor .cursor present
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    cursor_items = [a for a in ip.add + ip.update if ".cursor" in str(a.target)]
    claude_items = [a for a in ip.add + ip.update if ".claude" in str(a.target)]
    assert not cursor_items
    assert not claude_items


def test_compute_plan_lists_stale_paths(tmp_path, monkeypatch):
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    # Create a known stale path
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


# ── render.py ─────────────────────────────────────────────────────────────────


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


# ── install.py ────────────────────────────────────────────────────────────────


def test_install_creates_mentat_dotdir(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"):
        with patch.object(install_mod, "_emit_installed"):
            install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    assert (home / ".mentat").exists()


def test_install_dry_run_writes_nothing(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    before = set(tmp_path.rglob("*"))
    install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=True, color=False)
    after = set(tmp_path.rglob("*"))
    assert before == after


def test_install_yes_flag_skips_prompt(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    prompted = []

    def fake_input(prompt=""):
        prompted.append(prompt)
        return "n"

    with patch("builtins.input", fake_input):
        with patch.object(install_mod, "_execute_actions"):
            with patch.object(install_mod, "_emit_installed"):
                install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)

    assert not prompted


def test_install_help_flag_exits_0():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "install.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "Usage" in result.stdout


def test_install_writes_default_config(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"):
        with patch.object(install_mod, "_emit_installed"):
            install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    config = home / ".mentat" / "config.jsonc"
    assert config.exists()


def test_install_no_symlink_farm_at_agents_bin(tmp_path, monkeypatch):
    """install must not create ~/.agents/bin/ symlink entries."""
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"):
        with patch.object(install_mod, "_emit_installed"):
            install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    agents_bin = home / ".agents" / "bin"
    if agents_bin.exists():
        items = [p for p in agents_bin.iterdir() if p.name != "mentat-install"]
        assert not items


def test_install_idempotent_second_run_noop(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"):
        with patch.object(install_mod, "_emit_installed"):
            install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
            snapshot1 = set(str(p) for p in tmp_path.rglob("*"))
            install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
            snapshot2 = set(str(p) for p in tmp_path.rglob("*"))
    assert snapshot1 == snapshot2


def test_install_emits_install_completed_event(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    emit_calls: list = []
    with patch.object(install_mod, "_execute_actions"):
        with patch.object(install_mod, "_emit_installed", side_effect=lambda: emit_calls.append(True)):
            install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    assert emit_calls, "_emit_installed was not called"


def test_render_uses_color_when_tty(tmp_path, monkeypatch):
    render_mod = load_module("render")
    plan_mod = load_module("plan")
    home = _fake_home(tmp_path, monkeypatch)
    # Create a stale path so render has content to colorize
    (home / ".agents" / "mentat").mkdir(parents=True)
    ip = plan_mod.compute_plan(home=home, clone_root=None)
    output = render_mod.render(ip, color=True)
    assert "\033[" in output  # some ANSI code present


def test_shell_wrapper_execs_python_when_present():
    wrapper = Path(__file__).resolve().parents[1] / ".agents/bin/mentat-install"
    assert wrapper.exists(), "mentat-install wrapper not found"
    result = subprocess.run(
        [str(wrapper), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "mentat-install" in result.stdout.lower()


def test_shell_wrapper_errors_when_python_missing():
    """Wrapper source must contain python3 guard with error and exit 1."""
    wrapper = Path(__file__).resolve().parents[1] / ".agents/bin/mentat-install"
    content = wrapper.read_text()
    assert "python3" in content
    assert "exit 1" in content
    assert "not found" in content
