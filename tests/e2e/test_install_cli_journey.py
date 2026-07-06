"""E2E: drive the mentat-install CLI orchestrator.

Exercises ``.agents/skills/mentat-install/scripts/install.py`` — the action
executor, ``do_install`` / ``do_repo_install`` flows, the argument parser, and
``main`` dispatch — end to end. The module holds its sibling helpers as module
attributes (``_plan``, ``_render``, ``_utils``, ``_companions``, ``_path_setup``,
``_emit_installed_fn``); tests monkeypatch those seams with recorders so no real
install, real bash/jq, or real git-required path ever runs. Real ``tmp_path``
dirs back the repo-install filesystem writes.

Loaded via ``load_script`` (the module is a free-standing bin-layer script that
imports its siblings by path), mirroring ``test_install_interactive_journey.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_PY = REPO_ROOT / ".agents/skills/mentat-install/scripts/install.py"


def _load(key: str):
    return load_script(INSTALL_PY, key)


class _Recorder:
    """Records calls; returns a canned value."""

    def __init__(self, ret=None):
        self.calls: list[tuple[tuple, dict]] = []
        self._ret = ret

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._ret

    @property
    def called(self) -> bool:
        return bool(self.calls)


def _fake_utils():
    return SimpleNamespace(
        safe_mkdir=_Recorder(),
        write_default_config=_Recorder(),
        safe_symlink=_Recorder(),
        safe_copy=_Recorder(),
    )


def _action(action_type: str, *, source=None, target=None):
    return SimpleNamespace(action_type=action_type, source=source, target=target)


def _plan(*, add=None, update=None, conflicts=None):
    return SimpleNamespace(add=add or [], update=update or [], conflicts=conflicts or [])


# ── _emit_installed ──────────────────────────────────────────────────────────


def test_emit_installed_no_longer_emits():
    install_cli = _load("install_emit")
    assert not hasattr(install_cli, "_emit_installed")


# ── _execute_actions ─────────────────────────────────────────────────────────


def test_execute_actions_drives_each_add_seam():
    install_cli = _load("install_exec_add")
    utils = _fake_utils()
    install_cli._utils = utils

    ip = _plan(
        add=[
            _action("mkdir", target=Path("/tmp/d")),
            _action("file-create", target=Path("/tmp/f")),
            _action("symlink", source=Path("/src/l"), target=Path("/tmp/l")),
            _action("copy", source=Path("/src/c"), target=Path("/tmp/c")),
        ]
    )
    ok = install_cli._execute_actions(ip, dry_run=True)
    assert ok is True
    # Each seam invoked once, forwarding dry_run.
    assert utils.safe_mkdir.calls[0][1]["dry_run"] is True
    assert utils.write_default_config.calls[0][1]["dry_run"] is True
    assert utils.safe_symlink.calls[0][1]["dry_run"] is True
    assert utils.safe_copy.calls[0][1]["dry_run"] is True


def test_execute_actions_skips_symlink_without_source():
    install_cli = _load("install_exec_symlink_nosrc")
    utils = _fake_utils()
    install_cli._utils = utils
    ip = _plan(add=[_action("symlink", source=None, target=Path("/tmp/l"))])
    ok = install_cli._execute_actions(ip, dry_run=False)
    # The `and action.source` guard falls through → no symlink call, ok stays True.
    assert ok is True
    assert not utils.safe_symlink.called


def test_execute_actions_copy_without_source_warns_and_flags(capsys):
    install_cli = _load("install_exec_copy_nosrc")
    utils = _fake_utils()
    install_cli._utils = utils
    ip = _plan(add=[_action("copy", source=None, target=Path("/tmp/c"))])
    ok = install_cli._execute_actions(ip, dry_run=False)
    assert ok is False
    assert not utils.safe_copy.called
    assert "skipping copy" in capsys.readouterr().err


def test_execute_actions_update_symlink_invoked():
    install_cli = _load("install_exec_update")
    utils = _fake_utils()
    install_cli._utils = utils
    ip = _plan(update=[_action("symlink", source=Path("/src/u"), target=Path("/tmp/u"))])
    ok = install_cli._execute_actions(ip, dry_run=True)
    assert ok is True
    assert utils.safe_symlink.calls[0][1]["dry_run"] is True


# ── do_install ───────────────────────────────────────────────────────────────


def _wire_install(install_cli, *, ip, execute_ok=True):
    """Wire the compute_plan/render/companions/path_setup seams for do_install."""
    install_cli._plan = SimpleNamespace(compute_plan=_Recorder(ret=ip), InstallPlan=object)
    install_cli._render = SimpleNamespace(render=_Recorder(ret="RENDERED\n"))
    install_cli._companions = SimpleNamespace(install_all=_Recorder())
    install_cli._path_setup = SimpleNamespace(setup_path=_Recorder())
    install_cli._emit_installed_fn = _Recorder()
    install_cli._utils = _fake_utils()
    # Deterministic execute result.
    install_cli._execute_actions = _Recorder(ret=execute_ok)
    return install_cli


def test_do_install_dry_run_makes_no_changes(tmp_path: Path, capsys):
    install_cli = _load("install_dry")
    _wire_install(install_cli, ip=_plan())
    rc = install_cli.do_install(home=tmp_path, dry_run=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "RENDERED" in out
    assert "[dry-run] no changes made." in out
    # No side-effect seams beyond compute_plan/render.
    assert not install_cli._companions.install_all.called
    assert not install_cli._path_setup.setup_path.called
    assert not install_cli._execute_actions.called


def test_do_install_aborts_on_conflicts(tmp_path: Path, capsys):
    install_cli = _load("install_conflict")
    _wire_install(install_cli, ip=_plan(conflicts=["/tmp/x"]))
    rc = install_cli.do_install(home=tmp_path, yes=True)
    assert rc == install_cli.EX_DATAERR
    assert "Aborted: real file/dir" in capsys.readouterr().err


def test_do_install_non_tty_proceeds_without_prompt(tmp_path: Path, monkeypatch):
    install_cli = _load("install_notty")
    _wire_install(install_cli, ip=_plan())
    monkeypatch.setattr(install_cli.sys.stdin, "isatty", lambda: False)
    rc = install_cli.do_install(home=tmp_path, yes=False)
    assert rc == 0
    assert install_cli._companions.install_all.called
    assert install_cli._path_setup.setup_path.called
    assert install_cli._execute_actions.called
    # ~/.mentat scaffolding writes.
    assert install_cli._utils.safe_mkdir.called
    assert install_cli._utils.write_default_config.called


def test_do_install_tty_user_declines(tmp_path: Path, monkeypatch, capsys):
    install_cli = _load("install_decline")
    _wire_install(install_cli, ip=_plan())
    monkeypatch.setattr(install_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    rc = install_cli.do_install(home=tmp_path, yes=False)
    assert rc == 1
    assert "Aborted." in capsys.readouterr().out
    assert not install_cli._companions.install_all.called


def test_do_install_tty_user_accepts(tmp_path: Path, monkeypatch):
    install_cli = _load("install_accept")
    _wire_install(install_cli, ip=_plan())
    monkeypatch.setattr(install_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    rc = install_cli.do_install(home=tmp_path, yes=False)
    assert rc == 0
    assert install_cli._companions.install_all.called


def test_do_install_skip_companions(tmp_path: Path, monkeypatch):
    install_cli = _load("install_skipcomp")
    _wire_install(install_cli, ip=_plan())
    monkeypatch.setattr(install_cli.sys.stdin, "isatty", lambda: False)
    rc = install_cli.do_install(home=tmp_path, yes=True, skip_companions=True)
    assert rc == 0
    assert not install_cli._companions.install_all.called
    assert install_cli._path_setup.setup_path.called


def test_do_install_warns_when_execute_returns_false(tmp_path: Path, monkeypatch, capsys):
    install_cli = _load("install_warn")
    _wire_install(install_cli, ip=_plan(), execute_ok=False)
    monkeypatch.setattr(install_cli.sys.stdin, "isatty", lambda: False)
    rc = install_cli.do_install(home=tmp_path, yes=True)
    assert rc == 1
    assert "completed with warnings" in capsys.readouterr().err


def test_do_install_home_defaults_to_path_home(tmp_path: Path, monkeypatch):
    install_cli = _load("install_defaulthome")
    _wire_install(install_cli, ip=_plan())
    monkeypatch.setattr(install_cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(install_cli.Path, "home", classmethod(lambda cls: tmp_path))
    rc = install_cli.do_install(yes=True)  # home=None → Path.home()
    assert rc == 0
    # compute_plan received the defaulted home.
    _, kwargs = install_cli._plan.compute_plan.calls[0]
    assert kwargs["home"] == tmp_path


# ── do_repo_install ──────────────────────────────────────────────────────────


def test_repo_install_not_in_git_repo(monkeypatch, capsys):
    install_cli = _load("repo_nogit")
    monkeypatch.setattr(
        install_cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="fatal"),
    )
    rc = install_cli.do_repo_install(repo_path=None)
    assert rc == 1
    assert "not inside a git repo" in capsys.readouterr().err


def test_repo_install_uses_git_toplevel(tmp_path: Path, monkeypatch):
    install_cli = _load("repo_git_toplevel")
    monkeypatch.setattr(
        install_cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr=""),
    )
    rc = install_cli.do_repo_install(repo_path=None)
    assert rc == 0
    assert (tmp_path / ".mentat" / "config.toml").exists()


def test_repo_install_skips_when_config_exists(tmp_path: Path, capsys):
    install_cli = _load("repo_exists")
    cfg = tmp_path / ".mentat" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("# pre-existing\n")
    rc = install_cli.do_repo_install(repo_path=tmp_path)
    assert rc == 0
    assert "already exists" in capsys.readouterr().out
    # Not overwritten.
    assert cfg.read_text() == "# pre-existing\n"


def test_repo_install_creates_gitignore_when_absent(tmp_path: Path):
    install_cli = _load("repo_gi_absent")
    rc = install_cli.do_repo_install(repo_path=tmp_path)
    assert rc == 0
    gi = tmp_path / ".gitignore"
    assert gi.exists()
    assert ".mentat/" in gi.read_text()


def test_repo_install_appends_to_gitignore_missing_entry(tmp_path: Path):
    install_cli = _load("repo_gi_append")
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n")
    rc = install_cli.do_repo_install(repo_path=tmp_path)
    assert rc == 0
    body = gi.read_text()
    assert "node_modules/" in body
    assert ".mentat/" in body


def test_repo_install_leaves_gitignore_with_entry_unchanged(tmp_path: Path):
    install_cli = _load("repo_gi_present")
    gi = tmp_path / ".gitignore"
    original = "node_modules/\n.mentat/\n"
    gi.write_text(original)
    rc = install_cli.do_repo_install(repo_path=tmp_path)
    assert rc == 0
    assert gi.read_text() == original


# ── build_parser ─────────────────────────────────────────────────────────────


def test_build_parser_all_flags():
    install_cli = _load("parser_flags")
    args = install_cli.build_parser().parse_args(["--dry-run", "--yes", "--no-color", "--skip-companions"])
    assert args.dry_run is True
    assert args.yes is True
    assert args.no_color is True
    assert args.skip_companions is True
    assert args.repo is None


def test_build_parser_repo_const_empty():
    install_cli = _load("parser_repo_const")
    args = install_cli.build_parser().parse_args(["--repo"])
    assert args.repo == ""


def test_build_parser_repo_with_path():
    install_cli = _load("parser_repo_path")
    args = install_cli.build_parser().parse_args(["--repo", "/some/path"])
    assert args.repo == "/some/path"


# ── main ─────────────────────────────────────────────────────────────────────


def test_main_repo_with_path_calls_repo_install(monkeypatch):
    install_cli = _load("main_repo_path")
    rec = _Recorder(ret=0)
    install_cli.do_repo_install = rec
    monkeypatch.setattr(install_cli.sys, "argv", ["mentat-install", "--repo", "/x/y"])
    with pytest.raises(SystemExit) as ei:
        install_cli.main()
    assert ei.value.code == 0
    _, kwargs = rec.calls[0]
    assert kwargs["repo_path"] == Path("/x/y").resolve()


def test_main_repo_alone_passes_none(monkeypatch):
    install_cli = _load("main_repo_none")
    rec = _Recorder(ret=0)
    install_cli.do_repo_install = rec
    monkeypatch.setattr(install_cli.sys, "argv", ["mentat-install", "--repo"])
    with pytest.raises(SystemExit) as ei:
        install_cli.main()
    assert ei.value.code == 0
    _, kwargs = rec.calls[0]
    assert kwargs["repo_path"] is None


def test_main_no_color_passes_color_false(tmp_path: Path, monkeypatch):
    install_cli = _load("main_nocolor")
    rec = _Recorder(ret=0)
    install_cli.do_install = rec
    # cwd without .agents/skills → clone_root stays None.
    monkeypatch.setattr(install_cli.Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(install_cli.sys, "argv", ["mentat-install", "--no-color"])
    with pytest.raises(SystemExit) as ei:
        install_cli.main()
    assert ei.value.code == 0
    _, kwargs = rec.calls[0]
    assert kwargs["color"] is False
    assert kwargs["clone_root"] is None


def test_main_default_color_none_and_clone_root_set(tmp_path: Path, monkeypatch):
    install_cli = _load("main_default")
    rec = _Recorder(ret=0)
    install_cli.do_install = rec
    # cwd WITH .agents/skills → clone_root becomes cwd.
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    monkeypatch.setattr(install_cli.Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(install_cli.sys, "argv", ["mentat-install", "--yes", "--dry-run", "--skip-companions"])
    with pytest.raises(SystemExit) as ei:
        install_cli.main()
    assert ei.value.code == 0
    _, kwargs = rec.calls[0]
    assert kwargs["color"] is None
    assert kwargs["yes"] is True
    assert kwargs["dry_run"] is True
    assert kwargs["skip_companions"] is True
    assert kwargs["clone_root"] == tmp_path
