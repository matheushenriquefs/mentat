"""E2E: mentat-container CLI journey — in-process seams, no docker/devcontainer.

Drives ``container.py`` through its pure helpers, the runtime opt-out branches,
the devcontainer.json synth/rewrite logic, the up/run/down commands, every
doctor section, ``build_parser`` and ``main`` dispatch. Every seam that would
spawn a subprocess, call docker, or invoke the devcontainer CLI is
monkeypatched — the tests exercise only the in-process-reachable lines.

Two subprocess strategies are used:
  * a fake ``CompletedProcess`` (``_cp`` → ``SimpleNamespace``) for the fields read,
  * an argv-branching ``Recorder`` that returns different fakes based on argv[0]/[1]
    (docker vs git vs devcontainer vs uname vs bash).

Functions doing lazy ``from lib.config import ...`` / ``from lib import devcontainer``
are patched on the real ``lib`` module (imported in-test and setattr'd).
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from lib import config as lib_config
from lib import devcontainer as lib_devcontainer

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_PY = REPO_ROOT / ".agents/skills/mentat-container/scripts/container.py"


@pytest.fixture
def cc():
    """Fresh container module. monkeypatch.setattr auto-restores globals."""
    return load_script(CONTAINER_PY, "container_cli")


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> types.SimpleNamespace:
    """A stand-in for subprocess.CompletedProcess (only the fields we read)."""
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class Recorder:
    """Captures every argv it is called with and replays a scripted result.

    ``responder`` receives the argv and returns a fake CompletedProcess, or
    raises to simulate a missing/hung binary.
    """

    def __init__(self, responder) -> None:
        self.responder = responder
        self.calls: list[dict] = []

    def __call__(self, cmd, *args, **kwargs):  # noqa: D401 - subprocess.run shim
        self.calls.append({"cmd": cmd, "args": args, "kwargs": kwargs})
        return self.responder(cmd)


class _Popper:
    """Stateful callable returning list-scripted values across successive calls."""

    def __init__(self, values) -> None:
        self._values = list(values)

    def __call__(self, *a, **k):
        return self._values.pop(0)


# ── _host_runtime ───────────────────────────────────────────────────────────────


def test_host_runtime_true_when_config_says_host(cc, monkeypatch):
    monkeypatch.setattr(lib_config, "read_config", lambda: {"runtime": "host"})
    assert cc._host_runtime() is True


def test_host_runtime_false_for_docker(cc, monkeypatch):
    monkeypatch.setattr(lib_config, "read_config", lambda: {"runtime": "docker"})
    assert cc._host_runtime() is False


def test_host_runtime_false_when_unset(cc, monkeypatch):
    monkeypatch.setattr(lib_config, "read_config", lambda: {})
    assert cc._host_runtime() is False


def test_host_runtime_false_for_container(cc, monkeypatch):
    monkeypatch.setattr(lib_config, "read_config", lambda: {"runtime": "container"})
    assert cc._host_runtime() is False


# ── _warn_host_runtime_once ─────────────────────────────────────────────────────


def test_warn_host_runtime_once_first_warns_then_silent(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    cc._warn_host_runtime_once("slug-a")
    err1 = capsys.readouterr().err
    assert "FORFEITED" in err1
    # marker now exists → second call is silent
    marker = tmp_path / ".mentat" / ".host-runtime-warned" / "slug-a"
    assert marker.exists()
    cc._warn_host_runtime_once("slug-a")
    assert capsys.readouterr().err == ""


def test_warn_host_runtime_once_swallows_mkdir_oserror(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))

    def _boom(self, *a, **k):
        raise OSError("no perms")

    monkeypatch.setattr(cc.Path, "mkdir", _boom)
    # Must not raise even though marker creation fails.
    cc._warn_host_runtime_once("slug-b")
    assert "FORFEITED" in capsys.readouterr().err


# ── _run_on_host ────────────────────────────────────────────────────────────────


def test_run_on_host_uses_bash_lc_and_returns_rc(cc, monkeypatch, tmp_path):
    rec = Recorder(lambda cmd: _cp(7))
    monkeypatch.setattr(cc.subprocess, "run", rec)
    assert cc._run_on_host("make", tmp_path) == 7
    assert rec.calls[0]["cmd"] == ["bash", "-lc", "make"]
    assert rec.calls[0]["kwargs"]["cwd"] == str(tmp_path)


# ── _git_root ───────────────────────────────────────────────────────────────────


def test_git_root_returns_path_on_success(cc, monkeypatch):
    monkeypatch.setattr(cc.subprocess, "run", Recorder(lambda cmd: _cp(0, "/repo/root\n")))
    assert cc._git_root() == Path("/repo/root")


def test_git_root_raises_argparse_exit_on_failure(cc, monkeypatch, capsys):
    monkeypatch.setattr(cc.subprocess, "run", Recorder(lambda cmd: _cp(128, "")))
    with pytest.raises(SystemExit) as exc:
        cc._git_root()
    assert exc.value.code == cc.EX_ARGPARSE
    assert "must run from inside a git worktree" in capsys.readouterr().err


# ── _git_mount_for_worktree ─────────────────────────────────────────────────────


def test_git_mount_for_worktree_returns_bind_string(cc, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /main/.git/worktrees/x\n")
    mount = cc._git_mount_for_worktree(wt)
    # main_git = parent.parent of "/main/.git/worktrees/x" == "/main/.git"
    assert mount == "source=/main/.git,target=/main/.git,type=bind"


def test_git_mount_for_worktree_none_when_git_is_dir(cc, tmp_path):
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    assert cc._git_mount_for_worktree(wt) is None


def test_git_mount_for_worktree_none_when_git_absent(cc, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    assert cc._git_mount_for_worktree(wt) is None


def test_git_mount_for_worktree_none_when_not_gitdir_pointer(cc, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("something else\n")
    assert cc._git_mount_for_worktree(wt) is None


# ── _main_repo_root_for_wt ──────────────────────────────────────────────────────


def test_main_repo_root_for_wt_returns_grandparent_of_gitdir(cc, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /main/.git/worktrees/x\n")
    # parent.parent.parent of "/main/.git/worktrees/x" == "/main"
    assert cc._main_repo_root_for_wt(wt) == Path("/main")


def test_main_repo_root_for_wt_none_when_absent(cc, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    assert cc._main_repo_root_for_wt(wt) is None


def test_main_repo_root_for_wt_none_when_not_gitdir(cc, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("nope\n")
    assert cc._main_repo_root_for_wt(wt) is None


# ── _atomic_write ───────────────────────────────────────────────────────────────


def test_atomic_write_writes_text_and_leaves_no_tmp(cc, tmp_path):
    target = tmp_path / "out.json"
    cc._atomic_write(target, "hello")
    assert target.read_text() == "hello"
    assert not (tmp_path / "out.json.tmp").exists()


# ── _ensure_devcontainer_json ───────────────────────────────────────────────────


def _dcj_path(wt: Path) -> Path:
    return wt / ".devcontainer" / "devcontainer.json"


def test_ensure_dcj_correct_existing_is_left_untouched(cc, tmp_path):
    wt = tmp_path / "myslug"
    dcj = _dcj_path(wt)
    dcj.parent.mkdir(parents=True)
    dcj.write_text('{\n  "workspaceFolder": "/workspaces/myslug"\n}\n')
    before = dcj.read_text()
    cc._ensure_devcontainer_json(wt, "myslug")
    # ws matches and no git mount → early return, file unchanged.
    assert dcj.read_text() == before


def test_ensure_dcj_wrong_workspace_folder_is_rewritten(cc, tmp_path):
    wt = tmp_path / "newslug"
    dcj = _dcj_path(wt)
    dcj.parent.mkdir(parents=True)
    dcj.write_text(
        "{\n"
        '  "name": "mentat",\n'
        '  "workspaceFolder": "/workspaces/mentat",\n'
        '  "workspaceMount": "source=/a,target=/workspaces/mentat,type=bind",\n'
        '  "postCreateCommand": "cd /workspaces/mentat && setup",\n'
        '  "onCreateCommand": "init /workspaces/mentat"\n'
        "}\n"
    )
    cc._ensure_devcontainer_json(wt, "newslug")
    import json

    data = json.loads(dcj.read_text())
    assert data["name"] == "newslug"
    assert data["workspaceFolder"] == "/workspaces/newslug"
    assert data["workspaceMount"] == "source=/a,target=/workspaces/newslug,type=bind"
    assert data["postCreateCommand"] == "cd /workspaces/newslug && setup"
    assert data["onCreateCommand"] == "init /workspaces/newslug"


def test_ensure_dcj_appends_missing_git_mount(cc, tmp_path):
    wt = tmp_path / "myslug"
    dcj = _dcj_path(wt)
    dcj.parent.mkdir(parents=True)
    # ws is already correct; only the git mount is missing.
    dcj.write_text('{\n  "workspaceFolder": "/workspaces/myslug",\n  "mounts": []\n}\n')
    (wt / ".git").write_text("gitdir: /main/.git/worktrees/x\n")
    cc._ensure_devcontainer_json(wt, "myslug")
    import json

    data = json.loads(dcj.read_text())
    assert "source=/main/.git,target=/main/.git,type=bind" in data["mounts"]


def test_ensure_dcj_synthesizes_when_absent(cc, monkeypatch, tmp_path):
    wt = tmp_path / "myslug"
    wt.mkdir()
    synth = SimpleNamespace(
        devcontainer_json='{"name":"x"}',
        extra_files={"docker-compose.yml": "services: {}\n"},
    )
    monkeypatch.setattr(cc.compose_render, "synth_spec", lambda w: synth)
    cc._ensure_devcontainer_json(wt, "myslug")
    dcj = _dcj_path(wt)
    assert dcj.read_text() == '{"name":"x"}'
    assert (dcj.parent / "docker-compose.yml").read_text() == "services: {}\n"


def test_ensure_dcj_synthesizes_and_merges_git_mount(cc, monkeypatch, tmp_path):
    wt = tmp_path / "myslug"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /main/.git/worktrees/x\n")
    synth = SimpleNamespace(devcontainer_json='{"name":"x"}', extra_files={})
    monkeypatch.setattr(cc.compose_render, "synth_spec", lambda w: synth)
    cc._ensure_devcontainer_json(wt, "myslug")
    import json

    data = json.loads(_dcj_path(wt).read_text())
    assert data["mounts"] == ["source=/main/.git,target=/main/.git,type=bind"]


def test_ensure_dcj_synth_valueerror_exits(cc, monkeypatch, tmp_path, capsys):
    wt = tmp_path / "myslug"
    wt.mkdir()

    def _boom(w):
        raise ValueError("no template found")

    monkeypatch.setattr(cc.compose_render, "synth_spec", _boom)
    with pytest.raises(SystemExit) as exc:
        cc._ensure_devcontainer_json(wt, "myslug")
    assert exc.value.code == 1
    assert "no template found" in capsys.readouterr().err


# ── _ensure_safe_directory ──────────────────────────────────────────────────────


def test_ensure_safe_directory_runs_git_config(cc, monkeypatch):
    monkeypatch.setattr(cc.utils, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    rec = Recorder(lambda cmd: _cp(0))
    monkeypatch.setattr(cc.subprocess, "run", rec)
    cc._ensure_safe_directory("/workspaces/x", "cid")
    argv = rec.calls[0]["cmd"]
    assert argv[:3] == ["docker", "exec", "cid"]
    assert "safe.directory" in argv and argv[-1] == "/workspaces/x"


def test_ensure_safe_directory_suppresses_timeout(cc, monkeypatch):
    monkeypatch.setattr(cc, "_docker", lambda: "docker")

    def _boom(cmd):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=30)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(_boom))
    # Suppressed — no raise.
    cc._ensure_safe_directory("/workspaces/x", "cid")


# ── cmd_up ──────────────────────────────────────────────────────────────────────


def test_cmd_up_host_runtime_warns_and_returns_zero(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: True)
    warned = []
    monkeypatch.setattr(cc, "_warn_host_runtime_once", lambda slug: warned.append(slug))
    assert cc.cmd_up(tmp_path / "slug") == 0
    assert warned == ["slug"]


def test_cmd_up_already_running_ensures_safe_dir(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: "cid")
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    ensured = []
    monkeypatch.setattr(cc, "_ensure_safe_directory", lambda ws, cid: ensured.append((ws, cid)))
    assert cc.cmd_up(tmp_path / "slug") == 0
    assert ensured == [("/ws", "cid")]


def test_cmd_up_restart_stopped_container(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", _Popper([None, "cid2"]))
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_safe_directory", lambda ws, cid: None)

    def responder(cmd):
        if cmd[1] == "ps":
            return _cp(0, "stopcid\n")
        if cmd[1] == "start":
            return _cp(0)
        raise AssertionError(cmd)

    rec = Recorder(responder)
    monkeypatch.setattr(cc.subprocess, "run", rec)
    assert cc.cmd_up(tmp_path / "slug") == 0
    start = [c["cmd"] for c in rec.calls if c["cmd"][1] == "start"]
    assert start == [["docker", "start", "stopcid"]]


def test_cmd_up_docker_ps_timeout_is_unavailable(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")

    def _boom(cmd):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=30)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(_boom))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_UNAVAILABLE
    assert "docker ps timed out" in capsys.readouterr().err


def test_cmd_up_docker_start_timeout_is_unavailable(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")

    def responder(cmd):
        if cmd[1] == "ps":
            return _cp(0, "stopcid\n")
        if cmd[1] == "start":
            raise subprocess.TimeoutExpired(cmd="docker", timeout=30)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_UNAVAILABLE
    assert "docker start timed out" in capsys.readouterr().err


def test_cmd_up_docker_start_nonzero_is_failure(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")

    def responder(cmd):
        if cmd[1] == "ps":
            return _cp(0, "stopcid\n")
        if cmd[1] == "start":
            return _cp(1, "", "already gone")
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_FAILURE
    assert "docker start failed" in capsys.readouterr().err


def test_cmd_up_start_ok_but_no_container_is_failure(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    # both container_id_for lookups return None → post-start check fails.
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")

    def responder(cmd):
        if cmd[1] == "ps":
            return _cp(0, "stopcid\n")
        if cmd[1] == "start":
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_FAILURE
    assert "no usable container found" in capsys.readouterr().err


def test_cmd_up_cold_start_success(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", _Popper([None, "cid"]))
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_devcontainer_json", lambda wt, slug: None)
    monkeypatch.setattr(cc, "_main_repo_root_for_wt", lambda wt: None)
    monkeypatch.setattr(cc, "_ensure_safe_directory", lambda ws, cid: None)

    def responder(cmd):
        if cmd[0] == "docker" and cmd[1] == "ps":
            return _cp(0, "")  # no stopped container
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            assert "--remote-env" in cmd  # git_dir present
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == 0


def test_cmd_up_cold_start_devcontainer_missing_is_failure(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_devcontainer_json", lambda wt, slug: None)
    monkeypatch.setattr(cc, "_main_repo_root_for_wt", lambda wt: None)

    def responder(cmd):
        if cmd[0] == "docker" and cmd[1] == "ps":
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            raise FileNotFoundError
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_FAILURE
    assert "devcontainer CLI not on PATH" in capsys.readouterr().err


def test_cmd_up_cold_start_devcontainer_timeout_is_unavailable(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_devcontainer_json", lambda wt, slug: None)
    monkeypatch.setattr(cc, "_main_repo_root_for_wt", lambda wt: None)

    def responder(cmd):
        if cmd[0] == "docker" and cmd[1] == "ps":
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            raise subprocess.TimeoutExpired(cmd="devcontainer", timeout=900)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_UNAVAILABLE
    assert "devcontainer up timed out" in capsys.readouterr().err


def test_cmd_up_cold_start_devcontainer_nonzero_is_failure(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_devcontainer_json", lambda wt, slug: None)
    monkeypatch.setattr(cc, "_main_repo_root_for_wt", lambda wt: None)

    def responder(cmd):
        if cmd[0] == "docker" and cmd[1] == "ps":
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            return _cp(1)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == cc.EX_FAILURE


def test_cmd_up_cold_start_git_timeout_omits_remote_env(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", _Popper([None, "cid"]))
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_devcontainer_json", lambda wt, slug: None)
    monkeypatch.setattr(cc, "_main_repo_root_for_wt", lambda wt: None)
    monkeypatch.setattr(cc, "_ensure_safe_directory", lambda ws, cid: None)

    def responder(cmd):
        if cmd[0] == "docker" and cmd[1] == "ps":
            return _cp(0, "")
        if cmd[0] == "git":
            raise subprocess.TimeoutExpired(cmd="git", timeout=30)
        if cmd[0] == "devcontainer":
            assert "--remote-env" not in cmd  # git_dir "" → no remote-env
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(tmp_path / "slug") == 0


def test_cmd_up_cold_start_symlinks_and_env_from_repo_root(cc, monkeypatch, tmp_path):
    """Exercise the repo-root symlink + .env copy block with a real tmp repo."""
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", _Popper([None, "cid"]))
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc, "_ensure_devcontainer_json", lambda wt, slug: None)
    monkeypatch.setattr(cc, "_ensure_safe_directory", lambda ws, cid: None)

    repo_root = tmp_path / "main"
    (repo_root / "vendor").mkdir(parents=True)
    (repo_root / ".env").write_text("SECRET=1\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(cc, "_main_repo_root_for_wt", lambda w: repo_root)

    def responder(cmd):
        if cmd[0] == "docker" and cmd[1] == "ps":
            return _cp(0, "")
        if cmd[0] == "git":
            return _cp(0, ".git\n")
        if cmd[0] == "devcontainer":
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    assert cc.cmd_up(wt) == 0
    assert (wt / "vendor").is_symlink()
    assert (wt / ".env").read_text() == "SECRET=1\n"


# ── cmd_run ─────────────────────────────────────────────────────────────────────


def test_cmd_run_host_runtime_runs_on_host(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: True)
    monkeypatch.setattr(cc, "_warn_host_runtime_once", lambda slug: None)
    called = []
    monkeypatch.setattr(cc, "_run_on_host", lambda command, wt: called.append((command, wt)) or 3)
    assert cc.cmd_run(tmp_path / "slug", "pytest") == 3
    assert called == [("pytest", tmp_path / "slug")]


def test_cmd_run_daemon_down_is_unavailable(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    sentinel = object()
    monkeypatch.setattr(cc.utils, "DAEMON_DOWN", sentinel)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: sentinel)
    assert cc.cmd_run(tmp_path / "slug", "ls") == cc.EX_UNAVAILABLE
    assert "daemon not reachable" in capsys.readouterr().err


def test_cmd_run_container_not_running_is_unavailable(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)
    assert cc.cmd_run(tmp_path / "slug", "ls") == cc.EX_UNAVAILABLE
    assert "container not running" in capsys.readouterr().err


def test_cmd_run_execs_in_container(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: "cid")
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    rec = Recorder(lambda cmd: _cp(0))
    monkeypatch.setattr(cc.subprocess, "run", rec)
    assert cc.cmd_run(tmp_path / "slug", "echo hi") == 0
    argv = rec.calls[0]["cmd"]
    assert argv[:2] == ["docker", "exec"]
    assert "cid" in argv and argv[-2] == "-lc"
    assert "echo hi" in argv[-1]


# ── cmd_down ────────────────────────────────────────────────────────────────────


def test_cmd_down_host_runtime_returns_zero(cc, monkeypatch):
    monkeypatch.setattr(cc, "_host_runtime", lambda: True)
    assert cc.cmd_down(slug="s") == 0


def test_cmd_down_true_when_devcontainer_down_ok(cc, monkeypatch):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(lib_devcontainer, "down", lambda slug: True)
    assert cc.cmd_down(slug="s") == cc.EX_OK


def test_cmd_down_failure_when_devcontainer_down_false(cc, monkeypatch):
    monkeypatch.setattr(cc, "_host_runtime", lambda: False)
    monkeypatch.setattr(lib_devcontainer, "down", lambda slug: False)
    assert cc.cmd_down(slug="s") == cc.EX_FAILURE


# ── _doctor_section_host ─────────────────────────────────────────────────────────


def test_doctor_section_host_prints_and_returns_empty(cc, capsys):
    w, a = cc._doctor_section_host("arm64", "darwin 25.1.0")
    assert (w, a) == ([], [])
    out = capsys.readouterr().out
    assert "[host]" in out and "arm64" in out and "darwin 25.1.0" in out


# ── _doctor_section_container ────────────────────────────────────────────────────


def test_doctor_section_container_daemon_down_warns(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_docker", lambda: "docker")

    def _boom(cmd):
        raise FileNotFoundError

    monkeypatch.setattr(cc.subprocess, "run", Recorder(_boom))
    w, a = cc._doctor_section_container(tmp_path / "slug", "arm64")
    assert w == ["docker daemon not running"]
    assert "not running" in capsys.readouterr().out


def test_doctor_section_container_emulation_warns(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: "cid")
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")

    def responder(cmd):
        if cmd[1] == "info":
            return _cp(0)
        if cmd[1] == "inspect":
            return _cp(0, "linux/amd64\n")
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    w, a = cc._doctor_section_container(tmp_path / "slug", "arm64")
    assert w == ["arch emulation"]
    assert "qemu" in capsys.readouterr().out


def test_doctor_section_container_no_emulation(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: "cid")
    monkeypatch.setattr(cc.utils, "resolve_workspace_folder", lambda wt: "/ws")

    def responder(cmd):
        if cmd[1] == "info":
            return _cp(0)
        if cmd[1] == "inspect":
            return _cp(0, "linux/arm64\n")
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    w, a = cc._doctor_section_container(tmp_path / "slug", "arm64")
    assert w == []
    assert "none" in capsys.readouterr().out


def test_doctor_section_container_no_container_warns(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc, "_docker", lambda: "docker")
    monkeypatch.setattr(cc.utils, "container_id_for", lambda slug: None)

    def responder(cmd):
        if cmd[1] == "info":
            return _cp(0)
        raise AssertionError(cmd)

    monkeypatch.setattr(cc.subprocess, "run", Recorder(responder))
    w, a = cc._doctor_section_container(tmp_path / "myslug", "arm64")
    assert w == ["container not running (slug=myslug)"]
    assert "no container for slug=myslug" in capsys.readouterr().out


# ── _doctor_section_harness ──────────────────────────────────────────────────────


def test_doctor_section_harness_detects_claude_and_cursor(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    claude = tmp_path / ".claude"
    (claude / "agents").mkdir(parents=True)
    (claude / "agents" / "mentat-a").write_text("x")
    (claude / "skills").mkdir()
    (claude / "skills" / "mentat-b").write_text("x")
    (tmp_path / ".cursor").mkdir()
    cc._doctor_section_harness()
    out = capsys.readouterr().out
    assert "detected at" in out
    assert "1 mentat-* subagents linked" in out
    assert "1 mentat-* skills linked" in out
    assert ".cursor" in out


def test_doctor_section_harness_not_detected(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    cc._doctor_section_harness()
    out = capsys.readouterr().out
    assert "claude-code" in out and "not detected" in out


# ── _doctor_section_companions ───────────────────────────────────────────────────


def test_doctor_section_companions_present(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".claude/skills/diagnose").mkdir(parents=True)
    (tmp_path / ".claude/skills/diagnose/SKILL.md").write_text("x")
    (tmp_path / ".claude/plugins/marketplaces/caveman").mkdir(parents=True)
    w, a = cc._doctor_section_companions()
    assert a == []
    out = capsys.readouterr().out
    assert out.count("present") == 2


def test_doctor_section_companions_missing_advises(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    w, a = cc._doctor_section_companions()
    assert a == ["companion(s) missing"]
    assert "missing" in capsys.readouterr().out


# ── _doctor_section_mentat_state ─────────────────────────────────────────────────


def test_doctor_section_mentat_state_ok_with_logs_and_repo(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".mentat" / "logs" / "sess-1").mkdir(parents=True)
    monkeypatch.setattr(lib_config, "config_status", lambda d: ("ok", None))
    monkeypatch.setattr(cc.subprocess, "run", Recorder(lambda cmd: _cp(0, "/repo\n")))
    w, a = cc._doctor_section_mentat_state(tmp_path / "slug")
    assert w == []
    out = capsys.readouterr().out
    assert "present" in out
    assert "1 sessions" in out
    assert "config (repo)" in out


def test_doctor_section_mentat_state_warn_no_repo_no_logs(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(lib_config, "config_status", lambda d: ("warn-status", "warnmsg"))
    monkeypatch.setattr(cc.subprocess, "run", Recorder(lambda cmd: _cp(128, "")))
    w, a = cc._doctor_section_mentat_state(tmp_path / "slug")
    # global warn recorded; repo branch skipped (rc != 0).
    assert w == ["warnmsg"]
    out = capsys.readouterr().out
    assert "absent" in out  # ~/.mentat absent
    assert "logs dir" in out


# ── _doctor_section_tests ────────────────────────────────────────────────────────


def test_doctor_section_tests_counts_valid_manifest(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    plans = tmp_path / ".agents" / "plans"
    plans.mkdir(parents=True)
    (plans / "p.tests.json").write_text('{"closed": ["a", "b", "c"], "open": ["c"]}')
    cc._doctor_section_tests()
    out = capsys.readouterr().out
    # closed minus open (a, b) → 2 ro-mounted, 1 open.
    assert "2 ro-mounted, 1 open" in out


def test_doctor_section_tests_parse_error(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    plans = tmp_path / ".agents" / "plans"
    plans.mkdir(parents=True)
    (plans / "bad.tests.json").write_text("{not json")
    cc._doctor_section_tests()
    assert "manifest parse error" in capsys.readouterr().out


def test_doctor_section_tests_no_manifests(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".agents" / "plans").mkdir(parents=True)
    cc._doctor_section_tests()
    assert "no test manifests" in capsys.readouterr().out


def test_doctor_section_tests_no_plans_dir(cc, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: tmp_path))
    cc._doctor_section_tests()
    assert "no plans dir" in capsys.readouterr().out


# ── cmd_doctor ───────────────────────────────────────────────────────────────────


def _stub_sections(cc, monkeypatch, *, container_warn=False):
    monkeypatch.setattr(cc, "_doctor_section_host", lambda arch, os: ([], []))
    monkeypatch.setattr(
        cc,
        "_doctor_section_container",
        lambda wt, arch: (["w1"], []) if container_warn else ([], []),
    )
    monkeypatch.setattr(cc, "_doctor_section_harness", lambda: ([], []))
    monkeypatch.setattr(cc, "_doctor_section_companions", lambda: ([], ["a1"]))
    monkeypatch.setattr(cc, "_doctor_section_mentat_state", lambda wt: ([], []))
    monkeypatch.setattr(cc, "_doctor_section_tests", lambda: ([], []))


def test_cmd_doctor_ok_when_no_warnings(cc, monkeypatch, tmp_path, capsys):
    _stub_sections(cc, monkeypatch, container_warn=False)
    monkeypatch.setattr(cc.subprocess, "run", Recorder(lambda cmd: _cp(0, "arm64\n")))
    assert cc.cmd_doctor(tmp_path) == cc.EX_OK
    out = capsys.readouterr().out
    assert "0 warnings" in out and "1 advisory" in out


def test_cmd_doctor_failure_when_warnings(cc, monkeypatch, tmp_path, capsys):
    _stub_sections(cc, monkeypatch, container_warn=True)
    monkeypatch.setattr(cc.subprocess, "run", Recorder(lambda cmd: _cp(0, "arm64\n")))
    assert cc.cmd_doctor(tmp_path) == cc.EX_FAILURE
    assert "1 warning (w1)" in capsys.readouterr().out


def test_cmd_doctor_uname_missing_uses_unknown_arch(cc, monkeypatch, tmp_path):
    captured = {}
    _stub_sections(cc, monkeypatch, container_warn=False)

    def _cont(wt, arch):
        captured["arch"] = arch
        return ([], [])

    monkeypatch.setattr(cc, "_doctor_section_container", _cont)

    def _boom(cmd):
        raise FileNotFoundError

    monkeypatch.setattr(cc.subprocess, "run", Recorder(_boom))
    cc.cmd_doctor(tmp_path)
    assert captured["arch"] == "unknown"


# ── build_parser ─────────────────────────────────────────────────────────────────


def test_build_parser_up_namespace(cc):
    args = cc.build_parser().parse_args(["up"])
    assert args.cmd == "up"


def test_build_parser_run_namespace(cc):
    args = cc.build_parser().parse_args(["run", "echo", "hi"])
    assert args.cmd == "run"
    assert args.command == ["echo", "hi"]


def test_build_parser_down_namespace_with_slug(cc):
    args = cc.build_parser().parse_args(["down", "--slug", "x"])
    assert args.cmd == "down"
    assert args.slug == "x"


def test_build_parser_down_namespace_default_slug(cc):
    args = cc.build_parser().parse_args(["down"])
    assert args.slug is None


def test_build_parser_doctor_namespace(cc):
    args = cc.build_parser().parse_args(["doctor"])
    assert args.cmd == "doctor"


def test_build_parser_requires_subcommand(cc):
    with pytest.raises(SystemExit):
        cc.build_parser().parse_args([])


# ── main dispatch ────────────────────────────────────────────────────────────────


def test_main_up_dispatches(cc, monkeypatch, tmp_path):
    root = tmp_path / "repo"
    monkeypatch.setattr(cc, "_git_root", lambda: root)
    monkeypatch.setattr(cc, "cmd_up", lambda wt: 0)
    monkeypatch.setattr(cc.sys, "argv", ["c", "up"])
    with pytest.raises(SystemExit) as exc:
        cc.main()
    assert exc.value.code == 0


def test_main_run_joins_command_with_spaces(cc, monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(cc, "_git_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(cc, "cmd_run", lambda wt, command: captured.update(command=command) or 5)
    monkeypatch.setattr(cc.sys, "argv", ["c", "run", "echo", "a", "b"])
    with pytest.raises(SystemExit) as exc:
        cc.main()
    assert exc.value.code == 5
    assert captured["command"] == "echo a b"


def test_main_down_defaults_slug_to_git_root_name(cc, monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(cc, "_git_root", lambda: tmp_path / "my-repo")
    monkeypatch.setattr(cc, "cmd_down", lambda *, slug: captured.update(slug=slug) or 0)
    monkeypatch.setattr(cc.sys, "argv", ["c", "down"])
    with pytest.raises(SystemExit) as exc:
        cc.main()
    assert exc.value.code == 0
    assert captured["slug"] == "my-repo"


def test_main_down_uses_explicit_slug(cc, monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(cc, "_git_root", lambda: tmp_path / "my-repo")
    monkeypatch.setattr(cc, "cmd_down", lambda *, slug: captured.update(slug=slug) or 0)
    monkeypatch.setattr(cc.sys, "argv", ["c", "down", "--slug", "chosen"])
    with pytest.raises(SystemExit):
        cc.main()
    assert captured["slug"] == "chosen"


def test_main_doctor_dispatches(cc, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "cmd_doctor", lambda wt: 1)
    monkeypatch.setattr(cc.Path, "cwd", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(cc.sys, "argv", ["c", "doctor"])
    with pytest.raises(SystemExit) as exc:
        cc.main()
    assert exc.value.code == 1
