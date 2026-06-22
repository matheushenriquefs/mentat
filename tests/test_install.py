"""Tests for mentat-install skill."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-install/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _fake_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


# ── install.py ────────────────────────────────────────────────────────────────


def test_install_creates_mentat_dotdir(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"), patch.object(install_mod, "_emit_installed"):
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

    with (
        patch("builtins.input", fake_input),
        patch.object(install_mod, "_execute_actions"),
        patch.object(install_mod, "_emit_installed"),
    ):
        install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)

    assert not prompted


def test_install_help_flag_exits_0():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "install.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "Usage" in result.stdout


def test_install_writes_default_config(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"), patch.object(install_mod, "_emit_installed"):
        install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    config = home / ".mentat" / "config.toml"
    assert config.exists()
    assert "harness" in config.read_text()


def test_install_no_symlink_farm_at_agents_bin(tmp_path, monkeypatch):
    """install must not create ~/.agents/bin/ symlink entries."""
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"), patch.object(install_mod, "_emit_installed"):
        install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    agents_bin = home / ".agents" / "bin"
    if agents_bin.exists():
        items = [p for p in agents_bin.iterdir() if p.name != "mentat-install"]
        assert not items


def test_install_idempotent_second_run_noop(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    with patch.object(install_mod, "_execute_actions"), patch.object(install_mod, "_emit_installed"):
        install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
        snapshot1 = set(str(p) for p in tmp_path.rglob("*"))
        install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
        snapshot2 = set(str(p) for p in tmp_path.rglob("*"))
    assert snapshot1 == snapshot2


def test_install_emits_install_completed_event(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    emit_calls: list = []
    with (
        patch.object(install_mod, "_execute_actions"),
        patch.object(install_mod, "_emit_installed", side_effect=lambda: emit_calls.append(True)),
    ):
        install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False, color=False)
    assert emit_calls, "_emit_installed was not called"


def test_shell_wrapper_execs_python_when_present():
    wrapper = Path(__file__).resolve().parents[1] / ".agents/bin/mentat-install"
    assert wrapper.exists(), "mentat-install wrapper not found"
    result = subprocess.run(
        [str(wrapper), "--help"],
        capture_output=True,
        text=True,
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


# ── utils.py ──────────────────────────────────────────────────────────────────


# ── _execute_actions branch coverage ──────────────────────────────────────────


def test_execute_actions_mkdir(tmp_path):
    install_mod = load_module("install")
    target = tmp_path / "newdir"
    ip = install_mod._plan.InstallPlan(
        add=[install_mod._plan.Action("mkdir", None, target)],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is True
    assert target.exists()


def test_execute_actions_file_create(tmp_path):
    install_mod = load_module("install")
    target = tmp_path / "config.toml"
    ip = install_mod._plan.InstallPlan(
        add=[install_mod._plan.Action("file-create", None, target)],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is True
    assert target.exists()


def test_execute_actions_symlink(tmp_path):
    install_mod = load_module("install")
    source = tmp_path / "src"
    source.mkdir()
    target = tmp_path / "link"
    ip = install_mod._plan.InstallPlan(
        add=[install_mod._plan.Action("symlink", source, target)],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is True
    assert target.is_symlink()


def test_execute_actions_copy_no_source_warns_and_returns_false(tmp_path, capsys):
    install_mod = load_module("install")
    target = tmp_path / "dst"
    ip = install_mod._plan.InstallPlan(
        add=[install_mod._plan.Action("copy", None, target)],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is False
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()


def test_execute_actions_copy_with_source(tmp_path):
    install_mod = load_module("install")
    source = tmp_path / "src_dir"
    source.mkdir()
    (source / "file.txt").write_text("data")
    target = tmp_path / "dst_dir"
    ip = install_mod._plan.InstallPlan(
        add=[install_mod._plan.Action("copy", source, target)],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is True
    assert (target / "file.txt").read_text() == "data"


def test_execute_actions_update_symlink(tmp_path):
    install_mod = load_module("install")
    source = tmp_path / "src"
    source.mkdir()
    target = tmp_path / "link"
    ip = install_mod._plan.InstallPlan(
        add=[],
        update=[install_mod._plan.Action("symlink", source, target)],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is True
    assert target.is_symlink()


# ── do_install edge cases ──────────────────────────────────────────────────────


def test_do_install_conflicts_returns_dataerr(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    fake_ip = install_mod._plan.InstallPlan(
        add=[],
        update=[],
        stale=[],
        conflicts=[tmp_path / "conflict"],
        missing_companions=[],
        skipped=[],
    )
    with (
        patch.object(install_mod._plan, "compute_plan", return_value=fake_ip),
        patch.object(install_mod._render, "render", return_value=""),
    ):
        rc = install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False)
    assert rc == 65  # EX_DATAERR


def test_do_install_partial_failure_warns_and_returns_1(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    fake_ip = install_mod._plan.InstallPlan(
        add=[],
        update=[],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    with (
        patch.object(install_mod._plan, "compute_plan", return_value=fake_ip),
        patch.object(install_mod._render, "render", return_value=""),
        patch.object(install_mod, "_execute_actions", return_value=False),
        patch.object(install_mod._companions, "install_all"),
        patch.object(install_mod._path_setup, "setup_path"),
        patch.object(install_mod, "_emit_installed"),
    ):
        rc = install_mod.do_install(home=home, clone_root=None, yes=True, dry_run=False)
    assert rc == 1


# ── do_repo_install edge cases ────────────────────────────────────────────────


def test_do_repo_install_not_in_git_repo_returns_1():
    install_mod = load_module("install")

    def fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = ""
            stderr = "not a git repo"

        return R()

    with patch("subprocess.run", fake_run):
        rc = install_mod.do_repo_install(repo_path=None)
    assert rc == 1


def test_safe_symlink_recovers_from_broken_parent_symlink(tmp_path):
    """Parent path being a broken symlink must not crash mkdir."""
    utils = load_module("filesystem")
    source = tmp_path / "src"
    source.mkdir()
    missing = tmp_path / "missing_target"
    parent = tmp_path / "claude_agents"
    parent.symlink_to(missing)  # broken: points at non-existent dir
    target = parent / "leaf"

    utils.safe_symlink(source, target)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()
