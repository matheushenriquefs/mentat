"""Tests for mentat-install skill."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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


def test_execute_actions_symlink_without_source_is_skipped(tmp_path):
    install_mod = load_module("install")
    ip = install_mod._plan.InstallPlan(
        add=[install_mod._plan.Action("symlink", None, tmp_path / "a")],
        update=[install_mod._plan.Action("symlink", None, tmp_path / "u")],
        stale=[],
        conflicts=[],
        missing_companions=[],
        skipped=[],
    )
    ok = install_mod._execute_actions(ip, dry_run=False)
    assert ok is True
    assert not (tmp_path / "a").exists()
    assert not (tmp_path / "u").exists()


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


# ── _emit_installed body ───────────────────────────────────────────────────────


def test_emit_installed_calls_bound_emit_fn(monkeypatch):
    install_mod = load_module("install")
    calls: list = []
    monkeypatch.setattr(install_mod, "_emit_installed_fn", lambda event, payload: calls.append((event, payload)))
    install_mod._emit_installed()
    assert calls == [("plan.started", {"path": "install"})]


# ── do_install: home=None, interactive prompt, skip_companions ─────────────────


def test_do_install_home_none_falls_back_to_home(tmp_path, monkeypatch):
    install_mod = load_module("install")
    monkeypatch.setattr(install_mod.Path, "home", lambda: tmp_path)
    with (
        patch.object(install_mod, "_execute_actions"),
        patch.object(install_mod, "_emit_installed"),
        patch.object(install_mod._companions, "install_all"),
        patch.object(install_mod._path_setup, "setup_path"),
    ):
        rc = install_mod.do_install(home=None, clone_root=None, yes=True, dry_run=False, color=False)
    assert rc == 0
    assert (tmp_path / ".mentat").exists()


def _empty_plan(install_mod):
    return install_mod._plan.InstallPlan(add=[], update=[], stale=[], conflicts=[], missing_companions=[], skipped=[])


def test_do_install_interactive_decline_aborts(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with (
        patch.object(install_mod._plan, "compute_plan", return_value=_empty_plan(install_mod)),
        patch.object(install_mod._render, "render", return_value=""),
        patch("builtins.input", lambda prompt="": "n"),
    ):
        rc = install_mod.do_install(home=home, clone_root=None, yes=False, dry_run=False, color=False)
    assert rc == 1


def test_do_install_interactive_accept_and_skip_companions(tmp_path, monkeypatch):
    install_mod = load_module("install")
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    companion_calls: list = []
    with (
        patch.object(install_mod._plan, "compute_plan", return_value=_empty_plan(install_mod)),
        patch.object(install_mod._render, "render", return_value=""),
        patch.object(install_mod, "_execute_actions", return_value=True),
        patch.object(install_mod._companions, "install_all", side_effect=lambda **k: companion_calls.append(k)),
        patch.object(install_mod._path_setup, "setup_path"),
        patch.object(install_mod, "_emit_installed"),
        patch("builtins.input", lambda prompt="": "yes"),
    ):
        rc = install_mod.do_install(
            home=home, clone_root=None, yes=False, dry_run=False, color=False, skip_companions=True
        )
    assert rc == 0
    assert companion_calls == []  # skip_companions=True → install_all not called


# ── do_repo_install: git toplevel + existing gitignore append ──────────────────


def test_do_repo_install_uses_git_toplevel_when_repo_path_none(tmp_path, monkeypatch):
    install_mod = load_module("install")

    class R:
        returncode = 0
        stdout = str(tmp_path) + "\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    rc = install_mod.do_repo_install(repo_path=None)
    assert rc == 0
    assert (tmp_path / ".mentat" / "config.toml").exists()


def test_do_repo_install_appends_to_existing_gitignore(tmp_path):
    install_mod = load_module("install")
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n")
    rc = install_mod.do_repo_install(repo_path=tmp_path)
    assert rc == 0
    content = gi.read_text()
    assert ".mentat/" in content
    assert "node_modules/" in content


# ── build_parser + main entrypoint ─────────────────────────────────────────────


def test_build_parser_defaults():
    install_mod = load_module("install")
    args = install_mod.build_parser().parse_args([])
    assert args.dry_run is False
    assert args.yes is False
    assert args.no_color is False
    assert args.skip_companions is False
    assert args.repo is None


def test_build_parser_repo_flag_variants():
    install_mod = load_module("install")
    parser = install_mod.build_parser()
    assert parser.parse_args(["--repo"]).repo == ""
    assert parser.parse_args(["--repo", "/x"]).repo == "/x"


def test_main_repo_with_path(monkeypatch):
    install_mod = load_module("install")
    seen: dict = {}
    monkeypatch.setattr(install_mod, "do_repo_install", lambda *, repo_path: seen.__setitem__("p", repo_path) or 0)
    monkeypatch.setattr(sys, "argv", ["mentat-install", "--repo", "/tmp/somerepo"])
    with pytest.raises(SystemExit) as e:
        install_mod.main()
    assert e.value.code == 0
    assert seen["p"] == Path("/tmp/somerepo").resolve()


def test_main_repo_without_path_defaults_none(monkeypatch):
    install_mod = load_module("install")
    seen: dict = {}
    monkeypatch.setattr(install_mod, "do_repo_install", lambda *, repo_path: seen.__setitem__("p", repo_path) or 0)
    monkeypatch.setattr(sys, "argv", ["mentat-install", "--repo"])
    with pytest.raises(SystemExit):
        install_mod.main()
    assert seen["p"] is None


def test_main_install_detects_clone_root(monkeypatch, tmp_path):
    install_mod = load_module("install")
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    captured: dict = {}
    monkeypatch.setattr(install_mod, "do_install", lambda **kw: captured.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["mentat-install", "--yes", "--no-color"])
    with pytest.raises(SystemExit) as e:
        install_mod.main()
    assert e.value.code == 0
    assert captured["clone_root"] == tmp_path
    assert captured["color"] is False
    assert captured["yes"] is True


def test_main_install_no_clone_root(monkeypatch, tmp_path):
    install_mod = load_module("install")
    monkeypatch.chdir(tmp_path)
    captured: dict = {}
    monkeypatch.setattr(install_mod, "do_install", lambda **kw: captured.update(kw) or 0)
    monkeypatch.setattr(sys, "argv", ["mentat-install"])
    with pytest.raises(SystemExit):
        install_mod.main()
    assert captured["clone_root"] is None
    assert captured["color"] is None


# ── filesystem.py dry-run + edge branches ──────────────────────────────────────


def test_safe_symlink_dry_run_noop(tmp_path):
    utils = load_module("filesystem")
    src = tmp_path / "s"
    src.mkdir()
    tgt = tmp_path / "t"
    utils.safe_symlink(src, tgt, dry_run=True)
    assert not tgt.exists()


def test_safe_symlink_replaces_existing_symlink(tmp_path):
    utils = load_module("filesystem")
    src = tmp_path / "s"
    src.mkdir()
    other = tmp_path / "o"
    other.mkdir()
    tgt = tmp_path / "t"
    tgt.symlink_to(other)
    utils.safe_symlink(src, tgt)
    assert tgt.resolve() == src.resolve()


def test_safe_symlink_refuses_real_file_at_target(tmp_path):
    utils = load_module("filesystem")
    src = tmp_path / "s"
    src.mkdir()
    tgt = tmp_path / "t"
    tgt.write_text("real")  # real file → conflict, no silent overwrite
    with pytest.raises(utils.InstallConflict):
        utils.safe_symlink(src, tgt)


def test_safe_copy_dry_run_noop(tmp_path):
    utils = load_module("filesystem")
    src = tmp_path / "s"
    src.mkdir()
    tgt = tmp_path / "t"
    utils.safe_copy(src, tgt, dry_run=True)
    assert not tgt.exists()


def test_safe_copy_missing_source_raises(tmp_path):
    utils = load_module("filesystem")
    with pytest.raises(FileNotFoundError):
        utils.safe_copy(tmp_path / "nope", tmp_path / "t")


def test_safe_mkdir_dry_run_noop(tmp_path):
    utils = load_module("filesystem")
    tgt = tmp_path / "d"
    utils.safe_mkdir(tgt, dry_run=True)
    assert not tgt.exists()


def test_write_default_config_dry_run_noop(tmp_path):
    utils = load_module("filesystem")
    tgt = tmp_path / "c.toml"
    utils.write_default_config(tgt, dry_run=True)
    assert not tgt.exists()
